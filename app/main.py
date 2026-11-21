"""HTTP API and the chat UI."""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from app.locale import localize_detail
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import __version__
from app.access import (
    assert_read,
    assert_upload_allowed,
    assert_write,
    bearer_token,
    client_ip,
    get_project,
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


class ChatIn(BaseModel):
    message: str = Field(min_length=2, max_length=4000)
    project_id: str | None = None
    mode: str | None = "auto"
    conversation_id: str | None = None


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
        "credits": quota_detail(user),
        "created_at": user.created_at.isoformat() + "Z",
    }


def _public_project(project: Project) -> dict:
    return {
        "id": project.id,
        "code": project.code,
        "name": project.name,
        "description": project.description,
        "visibility": project.visibility,
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
    return {"projects": [_public_project(p) for p in visible_projects(db, user)]}


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
    return _public_project(project)


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
    docs = db.scalars(select(Document).where(Document.project_id == project.id).order_by(Document.title)).all()
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
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = get_project(db, project_id)
    assert_write(db, project, user)
    rate_limit(db, f"upload:{user.id}", 30, hours=1)
    dest = get_settings().data_dir / "uploads" / project.id / uuid.uuid4().hex
    path = _save_upload(file, dest)
    assert_upload_allowed(db, user, path.stat().st_size)
    try:
        document = ingest_path(
            db,
            path,
            scope="project",
            project_id=project.id,
            uploaded_by=user.id,
            meta={
                "title": title or path.stem,
                "doc_type": doc_type or "upload",
                "revision": revision,
                "edition": edition,
                "hierarchy_level": {"project_spec": 2, "datasheet": 3, "vendor": 5, "requisition": 2}.get(doc_type, 4),
                "statement_class_default": "explicit_requirement" if doc_type == "project_spec" else "informative",
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    delete_document(db, document)
    return {"ok": True}


@app.get("/api/kb/documents")
def kb_documents(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    docs = db.scalars(select(Document).where(Document.scope == "global").order_by(Document.title)).all()
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
    dest = get_settings().data_dir / "uploads" / "global" / uuid.uuid4().hex
    path = _save_upload(file, dest)
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
    return _public_document(document)


@app.post("/api/chat")
def chat(body: ChatIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    if settings.demo_mode:
        rate_limit(db, f"chat:{user.id}", settings.demo_chat_per_hour, hours=1)
    project = None
    if body.project_id:
        project = get_project(db, body.project_id)
        assert_read(db, project, user)
    elif user.is_anonymous:
        project = db.scalar(select(Project).where(Project.code == "HX-2201"))
    charge_or_http(db, user, settings.credit_cost_per_query, "chat", body.message[:240])
    result = run_query(db, project=project, message=body.message.strip(), mode=body.mode)
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
