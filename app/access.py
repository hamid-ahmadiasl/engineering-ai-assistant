"""Project membership and demo-mode limits."""

from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document, Membership, Project, RateHit, User, utcnow


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get("eai_session")


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "local"


def rate_limit(db: Session, bucket: str, limit: int, *, hours: int = 1) -> None:
    if limit <= 0:
        return
    cutoff = utcnow() - timedelta(hours=hours)
    count = db.scalar(
        select(func.count()).select_from(RateHit).where(RateHit.bucket == bucket, RateHit.created_at >= cutoff)
    )
    if count and count >= limit:
        raise HTTPException(
            status_code=429,
            detail="Too many requests from this session. Wait a while and try again.",
        )
    db.add(RateHit(bucket=bucket, created_at=utcnow()))


def get_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


def membership(db: Session, project: Project, user: User) -> Membership | None:
    return db.scalar(
        select(Membership).where(Membership.project_id == project.id, Membership.user_id == user.id)
    )


def assert_read(db: Session, project: Project, user: User) -> None:
    if project.visibility == "public_demo":
        return
    if user.role == "admin":
        return
    if membership(db, project, user) is None:
        raise HTTPException(status_code=403, detail="You do not have access to that project.")


def assert_owner(db: Session, project: Project, user: User) -> None:
    if user.role == "admin":
        return
    row = membership(db, project, user)
    if row is None or row.role != "owner":
        raise HTTPException(status_code=403, detail="Only the project owner can change or delete it.")


def assert_write(db: Session, project: Project, user: User) -> None:
    if user.is_anonymous or user.plan == "trial":
        raise HTTPException(
            status_code=403,
            detail="The trial can read the demo project. Uploads and edits need a signed-in account.",
        )
    if user.role == "admin":
        return
    row = membership(db, project, user)
    if row is None or row.role not in {"owner", "editor"}:
        raise HTTPException(status_code=403, detail="You do not have write access to that project.")


def assert_upload_allowed(db: Session, user: User, size_bytes: int) -> None:
    settings = get_settings()
    if user.is_anonymous or user.plan == "trial":
        raise HTTPException(
            status_code=403,
            detail="Uploads are turned off for the anonymous trial. Sign in with an account that has project access.",
        )
    limit_mb = settings.max_upload_mb(user.plan)
    if size_bytes > limit_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"That file is larger than the {limit_mb} MB limit for the {user.plan} plan.")
    cap = settings.uploads_per_day(user.plan)
    if settings.demo_mode:
        cutoff = utcnow() - timedelta(days=1)
        count = db.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.uploaded_by == user.id, Document.created_at >= cutoff)
        )
        if count and count >= cap:
            raise HTTPException(
                status_code=429,
                detail=f"Upload limit reached ({cap} documents in 24 hours on the {user.plan} plan).",
            )


def visible_projects(db: Session, user: User) -> list[Project]:
    projects = list(db.scalars(select(Project).order_by(Project.name)))
    if user.role == "admin":
        return projects
    member_ids = set(
        db.scalars(select(Membership.project_id).where(Membership.user_id == user.id))
    )
    return [p for p in projects if p.visibility == "public_demo" or p.id in member_ids]
