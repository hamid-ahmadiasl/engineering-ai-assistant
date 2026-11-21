"""Monthly credit quotas. A query spends credits; the balance resets with the plan period."""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth import add_month
from app.config import get_settings
from app.models import UsageEvent, User, utcnow


class QuotaError(Exception):
    def __init__(self, message: str, *, balance: int, plan: str, reset_at: datetime):
        self.message = message
        self.balance = balance
        self.plan = plan
        self.reset_at = reset_at
        super().__init__(message)


def ensure_period(user: User, now: datetime | None = None) -> bool:
    """Restore the plan allowance when the monthly period has elapsed.

    Anonymous trial balances do not refresh.
    """
    if user.is_anonymous or user.plan == "trial":
        return False
    now = now or utcnow()
    if user.period_end > now:
        return False
    settings = get_settings()
    user.credit_balance = settings.allowance(user.plan)
    user.period_start = now
    end = user.period_end
    # Jump forward until the new window contains `now` (skipped months do not stack).
    if end < now - _year():
        end = now
    while end <= now:
        end = add_month(end)
    user.period_end = end
    return True


def _year():
    from datetime import timedelta

    return timedelta(days=400)


def quota_detail(user: User) -> dict:
    return {
        "balance": user.credit_balance,
        "plan": user.plan,
        "reset_at": user.period_end.isoformat() + "Z",
        "cost_per_query": get_settings().credit_cost_per_query,
        "allowance": get_settings().allowance(user.plan) if user.plan != "trial" else user.credit_balance,
    }


def charge(db: Session, user: User, cost: int, kind: str, detail: str = "") -> None:
    ensure_period(user)
    if cost <= 0:
        return
    if user.credit_balance < cost:
        settings = get_settings()
        allowance = settings.allowance(user.plan)
        if user.is_anonymous:
            message = (
                f"The trial includes {settings.trial_credits} questions and they have been used. "
                "Create an account with an access code, or sign in, to continue."
            )
        else:
            message = (
                f"Monthly credits are used up. The {user.plan} plan includes {allowance} credits "
                f"each month. The balance resets on {user.period_end.date().isoformat()}. "
                "An administrator can top up credits or change the plan."
            )
        raise QuotaError(message, balance=user.credit_balance, plan=user.plan, reset_at=user.period_end)
    user.credit_balance -= cost
    db.add(
        UsageEvent(
            user_id=user.id,
            kind=kind,
            credits=cost,
            detail=detail[:500],
            created_at=utcnow(),
        )
    )


def charge_or_http(db: Session, user: User, cost: int, kind: str, detail: str = "") -> None:
    try:
        charge(db, user, cost, kind, detail)
    except QuotaError as exc:
        db.commit()
        raise HTTPException(
            status_code=402,
            detail={
                "code": "quota_exhausted",
                "message": exc.message,
                "balance": exc.balance,
                "plan": exc.plan,
                "reset_at": exc.reset_at.isoformat() + "Z",
            },
        ) from exc


def top_up(user: User, amount: int) -> None:
    user.credit_balance = max(0, user.credit_balance + amount)


def reset_balance(user: User) -> None:
    settings = get_settings()
    now = utcnow()
    user.credit_balance = settings.allowance(user.plan)
    user.period_start = now
    user.period_end = add_month(now)


def set_plan(user: User, plan: str) -> None:
    if plan not in {"free", "pro", "admin", "trial"}:
        raise HTTPException(status_code=400, detail="Unknown plan.")
    user.plan = plan
    if plan == "admin":
        user.role = "admin"
