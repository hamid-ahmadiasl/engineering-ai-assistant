"""Create the demo global corpus and the two sample projects."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest.pipeline import ingest_path
from app.models import Document, Membership, Project, User
from app.seed.content import PRECEDENCE, global_notes, project_b_documents, project_hx_documents


def _write_pdf(path: Path, text: str) -> None:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    # Core fonts are Latin-1. Keep the demo text ASCII.
    safe = text.encode("latin-1", "replace").decode("latin-1")
    for block in safe.split("\n"):
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 6, block if block else " ", new_x="LMARGIN", new_y="NEXT")
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))


def _write_xlsx(path: Path, rows: list[tuple]) -> None:
    import openpyxl

    book = openpyxl.Workbook()
    default = book.active
    book.remove(default)
    sheets: dict = {}
    for sheet_name, values in rows:
        if sheet_name not in sheets:
            sheets[sheet_name] = book.create_sheet(sheet_name)
        sheets[sheet_name].append(list(values))
    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)


def _materialise(root: Path, doc: dict) -> Path:
    path = root / doc["filename"]
    if doc.get("render") == "xlsx":
        _write_xlsx(path, doc["rows"])
    elif doc.get("render") == "pdf":
        _write_pdf(path, doc["text"])
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(doc["text"], encoding="utf-8")
    return path


def _meta(doc: dict) -> dict:
    return {
        "title": doc["title"],
        "doc_type": doc["doc_type"],
        "revision": doc["revision"],
        "edition": doc.get("edition") or "",
        "hierarchy_level": doc["hierarchy_level"],
        "corpus_label": doc["corpus_label"],
        "statement_class_default": doc["statement_class_default"],
        "sections": doc.get("sections") or {},
        "claims": doc.get("claims") or [],
        "external_id": doc["external_id"],
    }


def _already(db: Session, external_id: str) -> bool:
    return db.scalar(select(Document).where(Document.external_id == external_id)) is not None


def _project(db: Session, *, code: str, name: str, description: str, visibility: str) -> Project:
    existing = db.scalar(select(Project).where(Project.code == code))
    if existing:
        return existing
    project = Project(
        id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"engineering-ai-assistant:{code}")),
        code=code,
        name=name,
        description=description,
        visibility=visibility,
        precedence_json=json.dumps(PRECEDENCE),
    )
    db.add(project)
    db.flush()
    return project


def _owner(db: Session, project: Project) -> None:
    admin = db.scalar(select(User).where(User.role == "admin"))
    if admin is None:
        return
    project.owner_id = admin.id
    member = db.scalar(
        select(Membership).where(Membership.project_id == project.id, Membership.user_id == admin.id)
    )
    if member is None:
        db.add(Membership(project_id=project.id, user_id=admin.id, role="owner"))


def seed_demo(db: Session, data_dir: Path | None = None) -> None:
    from app.config import get_settings

    root = (data_dir or get_settings().data_dir) / "seed-src"
    hx = _project(
        db,
        code="HX-2201",
        name="HX-2201 crude preheat",
        description="Fictional shell-and-tube exchanger used to demonstrate citations, conflicts, and precedence.",
        visibility="public_demo",
    )
    isolated = _project(
        db,
        code="HX-900",
        name="HX-900 amine condenser",
        description="Private sample project. Its documents must not appear in HX-2201 answers.",
        visibility="private",
    )
    _owner(db, hx)
    _owner(db, isolated)

    for doc in global_notes():
        if _already(db, doc["external_id"]):
            continue
        path = _materialise(root / "global", doc)
        ingest_path(
            db,
            path,
            scope="global",
            project_id=None,
            uploaded_by=None,
            meta=_meta(doc),
            external_id=doc["external_id"],
        )
    for doc in project_hx_documents():
        if _already(db, doc["external_id"]):
            continue
        path = _materialise(root / "HX-2201", doc)
        ingest_path(
            db,
            path,
            scope="project",
            project_id=hx.id,
            uploaded_by=None,
            meta=_meta(doc),
            external_id=doc["external_id"],
        )
    for doc in project_b_documents():
        if _already(db, doc["external_id"]):
            continue
        path = _materialise(root / "HX-900", doc)
        ingest_path(
            db,
            path,
            scope="project",
            project_id=isolated.id,
            uploaded_by=None,
            meta=_meta(doc),
            external_id=doc["external_id"],
        )
    db.flush()


def bootstrap_admin(db: Session) -> None:
    from app.auth import new_user
    from app.config import get_settings

    settings = get_settings()
    if not settings.admin_email or not settings.admin_password:
        return
    existing = db.scalar(select(User).where(User.email == settings.admin_email))
    if existing:
        if existing.role != "admin":
            existing.role = "admin"
            existing.plan = "admin"
        return
    user = new_user(
        email=settings.admin_email,
        password=settings.admin_password,
        role="admin",
        plan="admin",
    )
    db.add(user)
    db.flush()
    for project in db.scalars(select(Project)):
        _owner(db, project)
