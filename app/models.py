"""Persistence models for accounts, credits, documents, and chat."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(20), default="user")
    plan: Mapped[str] = mapped_column(String(20), default="free")
    credit_balance: Mapped[int] = mapped_column(Integer, default=0)
    period_start: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    period_end: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SessionToken(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class AccessCode(Base):
    __tablename__ = "access_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    credit_amount: Mapped[int] = mapped_column(Integer, default=0)
    plan: Mapped[str | None] = mapped_column(String(20), nullable=True)
    grants_signup: Mapped[bool] = mapped_column(Boolean, default=True)
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CodeRedemption(Base):
    __tablename__ = "code_redemptions"
    __table_args__ = (UniqueConstraint("code_id", "user_id", name="uq_code_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code_id: Mapped[str] = mapped_column(ForeignKey("access_codes.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    visibility: Mapped[str] = mapped_column(String(20), default="private")
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    precedence_json: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="viewer")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    scope: Mapped[str] = mapped_column(String(20), index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(300))
    stored_path: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(String(300))
    doc_type: Mapped[str] = mapped_column(String(40))
    revision: Mapped[str] = mapped_column(String(40), default="")
    edition: Mapped[str] = mapped_column(String(80), default="")
    hierarchy_level: Mapped[int] = mapped_column(Integer, default=5)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    corpus_label: Mapped[str] = mapped_column(String(200), default="")
    uploaded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="ready")
    warning: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Chunk(Base):
    __tablename__ = "chunks"

    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    scope: Mapped[str] = mapped_column(String(20), index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[str] = mapped_column(String(40), default="")
    clause: Mapped[str] = mapped_column(String(80), default="")
    section: Mapped[str] = mapped_column(String(200), default="")
    revision: Mapped[str] = mapped_column(String(40), default="")
    edition: Mapped[str] = mapped_column(String(80), default="")
    statement_class: Mapped[str] = mapped_column(String(40), default="informative")
    doc_type: Mapped[str] = mapped_column(String(40), default="")
    title: Mapped[str] = mapped_column(String(300), default="")
    filename: Mapped[str] = mapped_column(String(300), default="")
    corpus_label: Mapped[str] = mapped_column(String(200), default="")


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    scope: Mapped[str] = mapped_column(String(20), default="project")
    parameter: Mapped[str] = mapped_column(String(80), index=True)
    value: Mapped[str] = mapped_column(String(120))
    unit: Mapped[str] = mapped_column(String(40), default="")
    side: Mapped[str] = mapped_column(String(40), default="")
    clause: Mapped[str] = mapped_column(String(80), default="")
    page: Mapped[str] = mapped_column(String(40), default="")
    statement_class: Mapped[str] = mapped_column(String(40), default="informative")
    doc_type: Mapped[str] = mapped_column(String(40), default="")
    title: Mapped[str] = mapped_column(String(300), default="")
    revision: Mapped[str] = mapped_column(String(40), default="")
    edition: Mapped[str] = mapped_column(String(80), default="")
    hierarchy_level: Mapped[int] = mapped_column(Integer, default=5)
    filename: Mapped[str] = mapped_column(String(300), default="")


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    credits: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RateHit(Base):
    __tablename__ = "rate_hits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bucket: Mapped[str] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
