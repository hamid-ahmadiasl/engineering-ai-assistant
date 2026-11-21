"""Password hashing, sessions, and access-code redemption."""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta

import bcrypt
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AccessCode, CodeRedemption, SessionToken, User, utcnow

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_password(password: str) -> str:
    rounds = max(4, min(get_settings().bcrypt_rounds, 14))
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=rounds))
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_session(db: Session, user: User, days: int = 14) -> str:
    token = secrets.token_urlsafe(32)
    db.add(
        SessionToken(
            token_hash=_token_hash(token),
            user_id=user.id,
            created_at=utcnow(),
            expires_at=utcnow() + timedelta(days=days),
        )
    )
    return token


def user_from_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    row = db.scalar(select(SessionToken).where(SessionToken.token_hash == _token_hash(token)))
    if row is None or row.expires_at < utcnow():
        return None
    user = db.get(User, row.user_id)
    if user is None or user.disabled:
        return None
    return user


def require_user(db: Session, token: str | None) -> User:
    user = user_from_token(db, token)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return user


def require_admin(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required.")


def validate_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    return email


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Use a password of at least 8 characters.")


def new_user(
    *,
    email: str,
    password: str,
    role: str = "user",
    plan: str = "free",
    balance: int | None = None,
    anonymous: bool = False,
) -> User:
    settings = get_settings()
    now = utcnow()
    if anonymous:
        period_end = now + timedelta(days=1)
        plan_name = "trial"
        start_balance = settings.trial_credits if balance is None else balance
    else:
        period_end = _add_month(now)
        plan_name = plan
        start_balance = settings.allowance(plan_name) if balance is None else balance
    return User(
        id=str(uuid.uuid4()),
        email=email,
        password_hash="" if anonymous else hash_password(password),
        role=role,
        plan=plan_name,
        credit_balance=start_balance,
        period_start=now,
        period_end=period_end,
        is_anonymous=anonymous,
        created_at=now,
    )


def _add_month(dt: datetime) -> datetime:
    month = dt.month + 1
    year = dt.year
    if month > 12:
        month = 1
        year += 1
    # clamp day
    import calendar

    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def add_month(dt: datetime) -> datetime:
    return _add_month(dt)


class CodeError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def load_code(db: Session, raw: str) -> AccessCode:
    code = db.scalar(select(AccessCode).where(AccessCode.code == raw.strip().upper()))
    if code is None:
        raise CodeError("That access code is not valid.")
    if code.revoked:
        raise CodeError("That access code has been revoked.")
    if code.expires_at is not None and code.expires_at < utcnow():
        raise CodeError("That access code has expired.")
    if code.uses >= code.max_uses:
        raise CodeError("That access code has already been used.")
    return code


def redeem_code(db: Session, user: User, raw: str, *, for_signup: bool = False) -> AccessCode:
    code = load_code(db, raw)
    if for_signup and not code.grants_signup:
        raise CodeError("That code does not grant registration.")
    already = db.scalar(
        select(CodeRedemption).where(
            CodeRedemption.code_id == code.id, CodeRedemption.user_id == user.id
        )
    )
    if already is not None:
        raise CodeError("This account has already redeemed that code.")
    if code.plan:
        user.plan = code.plan
    user.credit_balance += max(0, code.credit_amount)
    code.uses += 1
    db.add(CodeRedemption(code_id=code.id, user_id=user.id, created_at=utcnow()))
    db.add(user)
    db.add(code)
    return code
