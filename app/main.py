"""HTTP API and the chat UI."""

from __future__ import annotations

import json
import logging
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from app.locale import localize_detail
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import __version__
from app.access import (
    assert_owner,
    assert_read,
    assert_upload_allowed,
    assert_write,
    bearer_token,
    client_ip,
    get_project,
    membership,
    rate_limit,
    visible_projects,
)
from app.auth import (
    CodeError,
    issue_session,
    new_user,
    redeem_code,
    require_admin,
    require_user,
    user_from_token,
    validate_email,
    validate_password,
    verify_password,
)
from app.config import get_settings
from app.credits import charge_or_http, ensure_period, quota_detail, reset_balance, set_plan, top_up
from app.db import get_db, init_db, session_scope
from app.ingest.pipeline import ALLOWED_SUFFIXES, delete_document, ingest_path
from app.models import AccessCode, Conversation, Document, Membership, Message, Project, UsageEvent, User, utcnow
from app.rag.llm import llm_check
from app.rag.orchestrate import run_query
from app.seed.bootstrap import bootstrap_admin, seed_demo
from app.stores.embeddings import embedding_backend

log = logging.getLogger("engineering_assistant")
STATIC = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    init_db()
    with session_scope() as db:
        bootstrap_admin(db)
        if settings.seed_on_startup:
            seed_demo(db)
            bootstrap_admin(db)
    log.info(
        "ready demo_mode=%s llm=%s embed=%s stripe=%s",
        settings.demo_mode,
        "configured" if settings.llm_configured else "extractive",
        embedding_backend(),
        settings.stripe_enabled,
    )
    from app.stores.rebuild import schedule_vector_rebuild

    schedule_vector_rebuild()
    yield


app = FastAPI(title="Engineering AI Assistant", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.exception_handler(HTTPException)
async def localized_errors(request: Request, exc: HTTPException) -> JSONResponse:
    raw = request.headers.get("x-lang") or request.headers.get("accept-language") or ""
    lang = "fa" if raw.lower().startswith("fa") else "en"
    return JSONResponse(status_code=exc.status_code, content={"detail": localize_detail(exc.detail, lang)})


def db_session(db: Session = Depends(get_db)) -> Session:
    return db


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = require_user(db, bearer_token(request))
    ensure_period(user)
    return user


class RegisterIn(BaseModel):
    email: str
    password: str
    code: str | None = None


class LoginIn(BaseModel):
    email: str
    password: str


class RedeemIn(BaseModel):
    code: str


class PasswordIn(BaseModel):
    password: str


class ProjectIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    code: str = Field(min_length=2, max_length=80)
    description: str = ""
    equipment: str = ""


class ProjectPatch(BaseModel):
    name: str | None = None
    code: str | None = None
    description: str | None = None
    equipment: str | None = None


class ScopesIn(BaseModel):
    model_config = {"populate_by_name": True}
    include_global: bool = Field(default=True, alias="global")
    project_ids: list[str] = []


class ChatIn(BaseModel):
    message: str = Field(min_length=2, max_length=4000)
    project_id: str | None = None
    mode: str | None = "auto"
    conversation_id: str | None = None
    document_ids: list[str] | None = None
    scopes: ScopesIn | None = None


class CodeIn(BaseModel):
    credit_amount: int = 0
    plan: str | None = None
    max_uses: int = 1
    expires_in_days: int | None = None
    note: str = ""
    grants_signup: bool = True


class CreditIn(BaseModel):
    amount: int
    mode: str = "topup"


class PlanIn(BaseModel):
    plan: str


def _public_user(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "plan": user.plan,
        "is_anonymous": user.is_anonymous,
        "drive_connected": bool(getattr(user, "drive_refresh_token", "") or ""),
        "credits": quota_detail(user),
        "created_at": user.created_at.isoformat() + "Z",
    }


def _public_project(project: Project, role: str | None = None) -> dict:
    return {
        "id": project.id,
        "code": project.code,
        "name": project.name,
        "description": project.description,
        "equipment": getattr(project, "equipment", "") or "",
        "visibility": project.visibility,
        "role": role,
        "precedence": json.loads(project.precedence_json) if project.precedence_json else None,
    }


def _public_document(doc: Document) -> dict:
    return {
        "id": doc.id,
        "title": doc.title,
        "filename": doc.filename,
        "doc_type": doc.doc_type,
        "revision": doc.revision,
        "edition": doc.edition,
        "scope": doc.scope,
        "project_id": doc.project_id,
        "page_count": doc.page_count,
        "corpus_label": doc.corpus_label,
        "status": doc.status,
        "storage": getattr(doc, "storage", "") or "",
        "drive_file_id": getattr(doc, "drive_file_id", "") or "",
        "warning": doc.warning,
        "created_at": doc.created_at.isoformat() + "Z",
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "demo_mode": settings.demo_mode,
        "llm_preset": settings.llm_preset,
        "llm_model": settings.llm_model,
        "llm_configured": settings.llm_configured,
        "embedding": embedding_backend(),
        "stripe_enabled": settings.stripe_enabled,
        "database": "postgres" if settings.database_url.startswith("postgresql") else "sqlite",
    }


@app.post("/api/auth/register")
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    rate_limit(db, f"register:{client_ip(request)}", 8, hours=1)
    email = validate_email(body.email)
    validate_password(body.password)
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with that email already exists.")
    needs_code = settings.demo_mode and not settings.demo_allow_registration
    if needs_code and not (body.code or "").strip():
        raise HTTPException(
            status_code=403,
            detail="Registration on the public demo requires an access code. Use the limited trial, or ask an administrator for a code.",
        )
    user = new_user(email=email, password=body.password, plan="free")
    db.add(user)
    db.flush()
    if (body.code or "").strip():
        try:
            redeem_code(db, user, body.code or "", for_signup=True)
        except CodeError as exc:
            raise HTTPException(status_code=400, detail=exc.message) from exc
    token = issue_session(db, user)
    return {"token": token, "user": _public_user(user)}


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)) -> dict:
    rate_limit(db, f"login:{client_ip(request)}", 20, hours=1)
    email = validate_email(body.email)
    user = db.scalar(select(User).where(User.email == email))
    if user is None or user.is_anonymous or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is not valid.")
    if user.disabled:
        raise HTTPException(status_code=403, detail="This account is disabled.")
    ensure_period(user)
    token = issue_session(db, user)
    return {"token": token, "user": _public_user(user)}


@app.post("/api/auth/trial")
def trial(request: Request, db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    if settings.demo_mode and not settings.demo_trial_enabled:
        raise HTTPException(status_code=403, detail="The anonymous trial is turned off.")
    rate_limit(db, f"trial:{client_ip(request)}", settings.max_trials_per_ip_per_day, hours=24)
    email = f"trial-{uuid.uuid4().hex[:12]}@trial.local"
    user = new_user(email=email, password="", anonymous=True)
    db.add(user)
    db.flush()
    token = issue_session(db, user, days=2)
    return {"token": token, "user": _public_user(user)}


@app.post("/api/auth/logout")
def logout() -> dict:
    return {"ok": True}


@app.get("/api/me")
def me(user: User = Depends(current_user)) -> dict:
    return _public_user(user)


@app.post("/api/me/password")
def change_password(body: PasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if user.is_anonymous:
        raise HTTPException(status_code=400, detail="Trial sessions do not have a password.")
    validate_password(body.password)
    from app.auth import hash_password

    user.password_hash = hash_password(body.password)
    db.add(user)
    return {"ok": True}


@app.post("/api/account/redeem")
def redeem(body: RedeemIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if user.is_anonymous:
        raise HTTPException(status_code=400, detail="Sign up before redeeming a code. The trial cannot hold a code.")
    try:
        code = redeem_code(db, user, body.code, for_signup=False)
    except CodeError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return {"ok": True, "added": code.credit_amount, "plan": user.plan, "user": _public_user(user)}


@app.get("/api/projects")
def list_projects(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    rows = []
    for project in visible_projects(db, user):
        if user.role == "admin":
            role = "admin"
        elif project.visibility == "public_demo" and membership(db, project, user) is None:
            role = "viewer"
        else:
            row = membership(db, project, user)
            role = row.role if row else "viewer"
        rows.append(_public_project(project, role))
    return {"projects": rows}


@app.post("/api/projects")
def create_project(body: ProjectIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    if user.is_anonymous or user.plan == "trial":
        raise HTTPException(status_code=403, detail="The trial uses the prepared demo project. Create an account to open your own.")
    code = body.code.strip().upper()
    if db.scalar(select(Project).where(Project.code == code)):
        raise HTTPException(status_code=409, detail="A project with that code already exists.")
    if settings.demo_mode and user.role != "admin":
        owned = db.scalar(
            select(func.count()).select_from(Membership).where(Membership.user_id == user.id, Membership.role == "owner")
        )
        if owned and owned >= 2:
            raise HTTPException(status_code=429, detail="The public demo allows two projects per account.")
    project = Project(
        id=str(uuid.uuid4()),
        code=code,
        name=body.name.strip(),
        description=body.description.strip(),
        equipment=(body.equipment or "").strip(),
        visibility="private",
        owner_id=user.id,
        precedence_json=json.dumps(
            {
                "summary": "Mechanical requirements follow the project specification. Process conditions follow the latest datasheet. Vendor offers do not govern.",
                "order": [
                    "Project specification, latest revision, for mechanical requirements",
                    "Datasheet, latest revision, for process conditions",
                    "Code editions named by the specification",
                    "Vendor documents as offers until a deviation is approved",
                ],
            }
        ),
    )
    db.add(project)
    db.flush()
    db.add(Membership(project_id=project.id, user_id=user.id, role="owner"))
    db.flush()
    return _public_project(project, "owner")


@app.patch("/api/projects/{project_id}")
def update_project(
    project_id: str,
    body: ProjectPatch,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = get_project(db, project_id)
    assert_owner(db, project, user)
    if body.code is not None:
        code = body.code.strip().upper()
        if code != project.code and db.scalar(select(Project).where(Project.code == code)):
            raise HTTPException(status_code=409, detail="A project with that code already exists.")
        project.code = code
    if body.name is not None:
        if len(body.name.strip()) < 2:
            raise HTTPException(status_code=400, detail="Enter a project name of at least 2 characters.")
        project.name = body.name.strip()
    if body.description is not None:
        project.description = body.description.strip()
    if body.equipment is not None:
        project.equipment = body.equipment.strip()
    return _public_project(project, "owner" if user.role != "admin" else "admin")


@app.delete("/api/projects/{project_id}")
def remove_project(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    project = get_project(db, project_id)
    assert_owner(db, project, user)
    docs = list(db.scalars(select(Document).where(Document.project_id == project.id)))
    for document in docs:
        _remove_drive_file(db, document)
        delete_document(db, document)
    for row in db.scalars(select(Membership).where(Membership.project_id == project.id)):
        db.delete(row)
    db.delete(project)
    return {"ok": True}


_YEAR = re.compile(r"(?:19|20)\d{2}")


def _upload_meta(
    *,
    filename: str,
    title: str,
    doc_type: str,
    revision: str,
    edition: str,
    standard_name: str = "",
    part: str = "",
) -> dict:
    """Project files stay project documents. Codes are a separate doc_type in the same store."""
    if (doc_type or "").strip().lower() != "standard":
        kind = doc_type or "upload"
        return {
            "title": title or Path(filename).stem,
            "doc_type": kind,
            "revision": revision,
            "edition": edition,
            "hierarchy_level": {"project_spec": 2, "datasheet": 3, "vendor": 5, "requisition": 2}.get(kind, 4),
            "statement_class_default": "explicit_requirement" if kind == "project_spec" else "informative",
        }
    stem = Path(filename).stem.replace("_", " ").replace("-", " ")
    name = (standard_name or title or stem).strip()
    year = (edition or "").strip()
    if not year:
        found = _YEAR.search(f"{name} {stem}")
        year = found.group(0) if found else ""
    division = (part or "").strip()
    return {
        "title": name,
        "doc_type": "standard",
        "revision": division,
        "edition": year,
        "hierarchy_level": 4,
        "statement_class_default": "code_requirement",
        "corpus_label": "Project code or standard. The citation edition is the one loaded for this project.",
    }


def _mentioned_documents(db: Session, user: User, project: Project | None, document_ids: list[str] | None) -> list[str] | None:
    """Keep only ids the caller can read. Global notes are readable; other projects are checked."""
    if not document_ids:
        return None
    unique: list[str] = []
    for raw in document_ids:
        doc_id = (raw or "").strip()
        if doc_id and doc_id not in unique:
            unique.append(doc_id)
    if not unique:
        return None
    docs = list(db.scalars(select(Document).where(Document.id.in_(unique))))
    found = {doc.id: doc for doc in docs}
    if any(doc_id not in found for doc_id in unique):
        raise HTTPException(status_code=404, detail="A mentioned document was not found.")
    for doc in docs:
        if doc.scope == "personal":
            if doc.uploaded_by != user.id and user.role != "admin":
                raise HTTPException(status_code=403, detail="You do not have access to that project.")
            continue
        if doc.scope == "global" or not doc.project_id:
            continue
        owner = project if project is not None and project.id == doc.project_id else get_project(db, doc.project_id)
        assert_read(db, owner, user)
    return unique


def _mark_missing_sources(db: Session, docs: list[Document]) -> None:
    from app.drive import DriveError, client_for_token, decrypt_token

    owners: dict[str, list[Document]] = {}
    for doc in docs:
        if doc.drive_file_id and doc.status != "source_missing" and doc.uploaded_by:
            owners.setdefault(doc.uploaded_by, []).append(doc)
    for owner_id, owned in owners.items():
        owner = db.get(User, owner_id)
        token = decrypt_token(owner.drive_refresh_token or "") if owner else ""
        if not token:
            continue
        client = client_for_token(token)
        for doc in owned[:20]:
            try:
                present = client.exists(doc.drive_file_id)
            except DriveError:
                continue
            if not present:
                doc.status = "source_missing"


def _original_bytes(upload: UploadFile) -> tuple[str, bytes]:
    name = Path(upload.filename or "upload").name
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="Upload a PDF, Excel workbook, text file, or image.")
    data = upload.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="That file is empty.")
    return name, data


def _keep_original(
    user: User,
    *,
    project: Project | None,
    filename: str,
    data: bytes,
    doc_type: str,
    scope: str,
) -> tuple[Path, dict]:
    """Save the original in the uploader's Drive, or on local disk when Drive is off."""
    from app.drive import (
        GLOBAL_FOLDER,
        ROOT_FOLDER,
        DriveError,
        client_for_token,
        decrypt_token,
        section_folder,
        write_local_copy,
    )

    settings = get_settings()
    bucket = project.id if project is not None else "global"

    def local(kind: str) -> tuple[Path, dict]:
        path = write_local_copy(data, filename, settings.data_dir / "uploads" / bucket / uuid.uuid4().hex)
        return path, {"storage": kind, "drive_file_id": "", "stored_path": str(path)}

    if scope == "personal":
        folders = [ROOT_FOLDER, "General library"]
    elif project is None:
        folders = [ROOT_FOLDER, GLOBAL_FOLDER]
    else:
        folders = [ROOT_FOLDER, project.code, section_folder(doc_type, scope)]
    if not settings.google_configured:
        return local("")
    token = decrypt_token(user.drive_refresh_token or "")
    if not token:
        if settings.allow_local_uploads:
            return local("temporary")
        raise HTTPException(status_code=409, detail="Connect Google Drive before uploading files.")
    try:
        file_id = client_for_token(token).put_in_folders(folders, filename, data, "application/octet-stream")
    except DriveError as exc:
        log.warning("Drive upload failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="Google Drive rejected the upload. Connect Drive again and retry.",
        ) from exc
    path = write_local_copy(data, filename, settings.data_dir / "tmp" / uuid.uuid4().hex)
    return path, {"storage": "gdrive", "drive_file_id": file_id, "stored_path": ""}


def _apply_storage(document: Document, info: dict) -> None:
    document.storage = info["storage"]
    document.drive_file_id = info["drive_file_id"]
    if info["storage"] == "gdrive":
        document.stored_path = ""


def _remove_drive_file(db: Session, document: Document) -> None:
    from app.drive import DriveError, client_for_token, decrypt_token

    if not document.drive_file_id or not document.uploaded_by:
        return
    owner = db.get(User, document.uploaded_by)
    token = decrypt_token(owner.drive_refresh_token or "") if owner else ""
    if not token:
        return
    try:
        client_for_token(token).delete(document.drive_file_id)
    except DriveError as exc:
        log.warning("Drive delete failed: %s", exc)


def _save_upload(upload: UploadFile, dest_dir: Path) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="Upload a PDF, Excel workbook, text file, or image.")
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(upload.filename or "upload").name
    target = dest_dir / safe_name
    with target.open("wb") as handle:
        shutil.copyfileobj(upload.file, handle)
    return target


@app.get("/api/projects/{project_id}/documents")
def project_documents(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    project = get_project(db, project_id)
    assert_read(db, project, user)
    docs = list(db.scalars(select(Document).where(Document.project_id == project.id).order_by(Document.title)))
    _mark_missing_sources(db, docs)
    return {"documents": [_public_document(doc) for doc in docs]}


@app.post("/api/projects/{project_id}/documents")
async def upload_project_document(
    project_id: str,
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(""),
    doc_type: str = Form("upload"),
    revision: str = Form(""),
    edition: str = Form(""),
    standard_name: str = Form(""),
    part: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = get_project(db, project_id)
    assert_write(db, project, user)
    rate_limit(db, f"upload:{user.id}", 30, hours=1)
    filename, data = _original_bytes(file)
    assert_upload_allowed(db, user, len(data))
    path, stored = _keep_original(
        user,
        project=project,
        filename=filename,
        data=data,
        doc_type=doc_type,
        scope="project",
    )
    try:
        document = ingest_path(
            db,
            path,
            scope="project",
            project_id=project.id,
            uploaded_by=user.id,
            meta=_upload_meta(
                filename=path.name,
                title=title,
                doc_type=doc_type,
                revision=revision,
                edition=edition,
                standard_name=standard_name,
                part=part,
            ),
        )
    except ValueError as exc:
        if stored.get("drive_file_id"):
            document_stub = Document(drive_file_id=stored["drive_file_id"], uploaded_by=user.id)
            _remove_drive_file(db, document_stub)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _apply_storage(document, stored)
    return _public_document(document)


@app.delete("/api/projects/{project_id}/documents/{document_id}")
def remove_document(
    project_id: str,
    document_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = get_project(db, project_id)
    assert_write(db, project, user)
    document = db.get(Document, document_id)
    if document is None or document.project_id != project.id:
        raise HTTPException(status_code=404, detail="Document not found.")
    _remove_drive_file(db, document)
    delete_document(db, document)
    return {"ok": True}


@app.get("/api/kb/documents")
def kb_documents(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    docs = list(db.scalars(select(Document).where(Document.scope == "global").order_by(Document.title)))
    _mark_missing_sources(db, docs)
    return {"documents": [_public_document(doc) for doc in docs]}


@app.post("/api/kb/documents")
async def upload_kb_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    doc_type: str = Form("standard_note"),
    revision: str = Form(""),
    edition: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_admin(user)
    filename, data = _original_bytes(file)
    assert_upload_allowed(db, user, len(data))
    path, stored = _keep_original(
        user,
        project=None,
        filename=filename,
        data=data,
        doc_type=doc_type,
        scope="global",
    )
    document = ingest_path(
        db,
        path,
        scope="global",
        project_id=None,
        uploaded_by=user.id,
        meta={
            "title": title or path.stem,
            "doc_type": doc_type,
            "revision": revision,
            "edition": edition,
            "hierarchy_level": 6,
            "corpus_label": "User-loaded document. Confirm the licence before relying on it.",
            "statement_class_default": "informative",
        },
    )
    _apply_storage(document, stored)
    return _public_document(document)


def _chat_scopes(db: Session, user: User, body: ChatIn) -> tuple[bool, list[Project]]:
    if body.scopes is not None:
        projects = []
        for project_id in body.scopes.project_ids:
            project = get_project(db, project_id)
            assert_read(db, project, user)
            if project.id not in {item.id for item in projects}:
                projects.append(project)
        include_global = body.scopes.include_global
        if not include_global and not projects:
            raise HTTPException(status_code=400, detail="Select at least one knowledge scope.")
        return include_global, projects
    if body.project_id:
        project = get_project(db, body.project_id)
        assert_read(db, project, user)
        return True, [project]
    if user.is_anonymous:
        demo = db.scalar(select(Project).where(Project.code == "HX-2201"))
        return True, [demo] if demo else []
    return True, []


@app.get("/api/library/documents")
def library_documents(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if user.is_anonymous:
        return {"documents": []}
    docs = list(
        db.scalars(
            select(Document)
            .where(Document.scope == "personal", Document.uploaded_by == user.id)
            .order_by(Document.title)
        )
    )
    _mark_missing_sources(db, docs)
    return {"documents": [_public_document(doc) for doc in docs]}


@app.post("/api/library/documents")
async def upload_library_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    doc_type: str = Form("reference"),
    revision: str = Form(""),
    edition: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    if user.is_anonymous or user.plan == "trial":
        raise HTTPException(status_code=403, detail="The trial can read the demo project. Uploads and edits need a signed-in account.")
    rate_limit(db, f"upload:{user.id}", 30, hours=1)
    filename, data = _original_bytes(file)
    assert_upload_allowed(db, user, len(data))
    path, stored = _keep_original(user, project=None, filename=filename, data=data, doc_type=doc_type, scope="personal")
    document = ingest_path(
        db,
        path,
        scope="personal",
        project_id=None,
        uploaded_by=user.id,
        meta={
            "title": title or path.stem,
            "doc_type": doc_type or "reference",
            "revision": revision,
            "edition": edition,
            "hierarchy_level": 6,
            "owner_id": user.id,
            "corpus_label": "Personal general library. Visible only to you.",
            "statement_class_default": "informative",
        },
    )
    _apply_storage(document, stored)
    return _public_document(document)


@app.delete("/api/library/documents/{document_id}")
def remove_library_document(document_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    document = db.get(Document, document_id)
    if document is None or document.scope != "personal":
        raise HTTPException(status_code=404, detail="Document not found.")
    if document.uploaded_by != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="You do not have access to that project.")
    _remove_drive_file(db, document)
    delete_document(db, document)
    return {"ok": True}


@app.post("/api/chat")
def chat(body: ChatIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    if settings.demo_mode:
        rate_limit(db, f"chat:{user.id}", settings.demo_chat_per_hour, hours=1)
    include_global, projects = _chat_scopes(db, user, body)
    project = projects[0] if len(projects) == 1 else None
    charge_or_http(db, user, settings.credit_cost_per_query, "chat", body.message[:240])
    mentioned = _mentioned_documents(db, user, project, body.document_ids)
    result = run_query(
        db,
        project=project,
        projects=projects,
        include_global=include_global,
        owner_id=None if user.is_anonymous else user.id,
        message=body.message.strip(),
        mode=body.mode,
        document_ids=mentioned,
    )
    conversation = None
    if body.conversation_id:
        conversation = db.get(Conversation, body.conversation_id)
        if conversation is None or conversation.user_id != user.id:
            raise HTTPException(status_code=404, detail="Conversation not found.")
    if conversation is None:
        conversation = Conversation(
            id=str(uuid.uuid4()),
            project_id=project.id if project else None,
            user_id=user.id,
            title=body.message.strip()[:80],
            created_at=utcnow(),
        )
        db.add(conversation)
        db.flush()
    db.add(
        Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation.id,
            role="user",
            content_json=json.dumps({"text": body.message.strip()}),
            created_at=utcnow(),
        )
    )
    db.add(
        Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation.id,
            role="assistant",
            content_json=json.dumps(result),
            created_at=utcnow(),
        )
    )
    result["conversation_id"] = conversation.id
    result["credits"] = quota_detail(user)
    return result


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    messages = db.scalars(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)
    ).all()
    return {
        "id": conversation.id,
        "title": conversation.title,
        "project_id": conversation.project_id,
        "messages": [
            {"id": msg.id, "role": msg.role, "content": json.loads(msg.content_json)} for msg in messages
        ],
    }


@app.get("/api/drive/status")
def drive_status(user: User = Depends(current_user)) -> dict:
    settings = get_settings()
    return {
        "connected": bool(user.drive_refresh_token),
        "required": settings.google_configured and not settings.allow_local_uploads,
        "temporary_uploads": settings.allow_local_uploads,
        "available": settings.google_configured,
    }


@app.get("/api/drive/connect")
def drive_connect(user: User = Depends(current_user)) -> dict:
    if user.is_anonymous:
        raise HTTPException(status_code=403, detail="Sign in before connecting Google Drive.")
    from app.drive import DriveError, authorization_url

    try:
        url = authorization_url(user.id)
    except DriveError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"url": url}


@app.get("/api/drive/callback")
def drive_callback(code: str = "", state: str = "", db: Session = Depends(get_db)) -> RedirectResponse:
    from app.drive import DriveError, encrypt_token, exchange_code, read_state

    settings = get_settings()
    try:
        user_id = read_state(state)
        refresh = exchange_code(code)
    except DriveError:
        return RedirectResponse(f"{settings.public_base_url}/?drive=error")
    user = db.get(User, user_id)
    if user is None:
        return RedirectResponse(f"{settings.public_base_url}/?drive=error")
    user.drive_refresh_token = encrypt_token(refresh)
    return RedirectResponse(f"{settings.public_base_url}/?drive=connected")


@app.post("/api/drive/disconnect")
def drive_disconnect(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    from app.drive import decrypt_token, revoke_token

    token = decrypt_token(user.drive_refresh_token or "")
    revoke_token(token)
    user.drive_refresh_token = ""
    db.add(user)
    return {"connected": False}


@app.get("/api/admin/llm-check")
def admin_llm_check(user: User = Depends(current_user)) -> dict:
    require_admin(user)
    return llm_check()


@app.get("/api/admin/users")
def admin_users(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_admin(user)
    rows = db.scalars(select(User).order_by(User.created_at.desc())).all()
    return {"users": [_public_user(row) for row in rows]}


@app.post("/api/admin/users/{user_id}/credits")
def admin_credits(
    user_id: str,
    body: CreditIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_admin(user)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if body.mode == "reset":
        reset_balance(target)
    elif body.mode == "set":
        target.credit_balance = max(0, body.amount)
    else:
        top_up(target, body.amount)
    db.add(
        UsageEvent(
            user_id=target.id,
            kind=f"admin_{body.mode}",
            credits=body.amount,
            detail=f"by {user.email}",
            created_at=utcnow(),
        )
    )
    return _public_user(target)


@app.post("/api/admin/users/{user_id}/plan")
def admin_plan(
    user_id: str,
    body: PlanIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_admin(user)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    set_plan(target, body.plan)
    return _public_user(target)


@app.get("/api/admin/codes")
def admin_list_codes(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_admin(user)
    rows = db.scalars(select(AccessCode).order_by(AccessCode.created_at.desc())).all()
    return {"codes": [_public_code(row) for row in rows]}


def _public_code(code: AccessCode) -> dict:
    return {
        "id": code.id,
        "code": code.code,
        "credit_amount": code.credit_amount,
        "plan": code.plan,
        "grants_signup": code.grants_signup,
        "max_uses": code.max_uses,
        "uses": code.uses,
        "expires_at": code.expires_at.isoformat() + "Z" if code.expires_at else None,
        "revoked": code.revoked,
        "note": code.note,
        "created_at": code.created_at.isoformat() + "Z",
    }


@app.post("/api/admin/codes")
def admin_create_code(body: CodeIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_admin(user)
    if body.plan and body.plan not in {"free", "pro"}:
        raise HTTPException(status_code=400, detail="A code can assign the free or pro plan.")
    if body.credit_amount < 0 or body.max_uses < 1:
        raise HTTPException(status_code=400, detail="Credits cannot be negative, and a code needs at least one use.")
    from datetime import timedelta

    expires = utcnow() + timedelta(days=body.expires_in_days) if body.expires_in_days else None
    code = AccessCode(
        id=str(uuid.uuid4()),
        code=uuid.uuid4().hex[:10].upper(),
        credit_amount=body.credit_amount,
        plan=body.plan,
        grants_signup=body.grants_signup,
        max_uses=body.max_uses,
        expires_at=expires,
        note=body.note[:300],
        created_by=user.id,
        created_at=utcnow(),
    )
    db.add(code)
    db.flush()
    return _public_code(code)


@app.post("/api/admin/codes/{code_id}/revoke")
def admin_revoke(code_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_admin(user)
    code = db.get(AccessCode, code_id)
    if code is None:
        raise HTTPException(status_code=404, detail="Code not found.")
    code.revoked = True
    return _public_code(code)


@app.get("/api/admin/usage")
def admin_usage(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_admin(user)
    rows = db.execute(
        select(UsageEvent.kind, func.count(), func.sum(UsageEvent.credits)).group_by(UsageEvent.kind)
    ).all()
    return {
        "totals": [{"kind": kind, "events": count, "credits": int(credits or 0)} for kind, count, credits in rows]
    }


@app.get("/api/billing/status")
def billing_status(user: User = Depends(current_user)) -> dict:
    settings = get_settings()
    return {"enabled": settings.stripe_enabled, "plan": user.plan}


@app.post("/api/billing/checkout")
def billing_checkout(user: User = Depends(current_user)) -> dict:
    settings = get_settings()
    if not settings.stripe_enabled:
        raise HTTPException(status_code=404, detail="Card billing is not enabled on this server.")
    if user.is_anonymous:
        raise HTTPException(status_code=400, detail="Create an account before starting a subscription.")
    import stripe

    stripe.api_key = settings.stripe_secret_key
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": settings.stripe_price_pro, "quantity": 1}],
        success_url=settings.stripe_success_url,
        cancel_url=settings.stripe_cancel_url,
        customer_email=user.email,
        client_reference_id=user.id,
        metadata={"user_id": user.id},
        subscription_data={"metadata": {"user_id": user.id}},
    )
    return {"url": session.url}


@app.post("/api/billing/webhook")
async def billing_webhook(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    settings = get_settings()
    if not settings.stripe_enabled:
        raise HTTPException(status_code=404, detail="Card billing is not enabled on this server.")
    import stripe

    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload, request.headers.get("stripe-signature", ""), settings.stripe_webhook_secret
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Webhook signature could not be verified.") from exc
    kind = event["type"]
    data = event["data"]["object"]
    if kind == "checkout.session.completed":
        _apply_pro(db, data.get("client_reference_id") or (data.get("metadata") or {}).get("user_id"), data.get("customer"), data.get("subscription"))
    elif kind == "invoice.paid":
        sub_id = data.get("subscription")
        _refill_subscription(db, sub_id)
    elif kind == "customer.subscription.deleted":
        _downgrade_subscription(db, data.get("id"))
    return JSONResponse({"received": True})


def _apply_pro(db: Session, user_id: str | None, customer_id: str | None, subscription_id: str | None) -> None:
    if not user_id:
        return
    target = db.get(User, user_id)
    if target is None:
        return
    target.plan = "pro"
    target.stripe_customer_id = customer_id
    target.stripe_subscription_id = subscription_id
    reset_balance(target)


def _refill_subscription(db: Session, subscription_id: str | None) -> None:
    if not subscription_id:
        return
    target = db.scalar(select(User).where(User.stripe_subscription_id == subscription_id))
    if target is None:
        return
    target.plan = "pro"
    reset_balance(target)


def _downgrade_subscription(db: Session, subscription_id: str | None) -> None:
    if not subscription_id:
        return
    target = db.scalar(select(User).where(User.stripe_subscription_id == subscription_id))
    if target is None:
        return
    target.plan = "free"
    target.stripe_subscription_id = None
