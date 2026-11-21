"""Credits: deduction, monthly reset, access codes, and a hard stop at zero."""

from datetime import timedelta

from sqlalchemy import select

from app.db import session_scope
from app.models import User, utcnow
from tests.conftest import auth_header, login_admin


def _user(client, email="engineer@example.com"):
    response = client.post("/api/auth/register", json={"email": email, "password": "password1"})
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload["user"], auth_header(payload["token"])


def test_query_deducts_one_credit(client):
    user, headers = _user(client)
    before = user["credits"]["balance"]
    response = client.post(
        "/api/chat",
        headers=headers,
        json={"message": "What is a corrosion allowance?", "mode": "qa"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["credits"]["balance"] == before - 1


def test_monthly_reset_restores_the_plan_allowance(client):
    user, headers = _user(client, "reset@example.com")
    with session_scope() as db:
        row = db.scalar(select(User).where(User.email == "reset@example.com"))
        row.credit_balance = 0
        row.period_end = utcnow() - timedelta(days=1)
    response = client.get("/api/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["credits"]["balance"] == 30
    assert response.json()["plan"] == "free"


def test_access_code_adds_credits_once(client):
    _, headers = _user(client, "coded@example.com")
    admin = login_admin(client)
    created = client.post(
        "/api/admin/codes",
        headers=admin,
        json={"credit_amount": 12, "max_uses": 1, "note": "lab", "grants_signup": True},
    )
    assert created.status_code == 200, created.text
    code = created.json()["code"]
    before = client.get("/api/me", headers=headers).json()["credits"]["balance"]
    redeemed = client.post("/api/account/redeem", headers=headers, json={"code": code})
    assert redeemed.status_code == 200, redeemed.text
    assert redeemed.json()["user"]["credits"]["balance"] == before + 12
    again = client.post("/api/account/redeem", headers=headers, json={"code": code})
    assert again.status_code == 400
    outsider = client.post("/api/auth/register", json={"email": "other@example.com", "password": "password1"})
    other_headers = auth_header(outsider.json()["token"])
    blocked = client.post("/api/account/redeem", headers=other_headers, json={"code": code})
    assert blocked.status_code == 400


def test_exhausted_quota_blocks_the_query(client):
    user, headers = _user(client, "empty@example.com")
    admin = login_admin(client)
    cleared = client.post(
        f"/api/admin/users/{user['id']}/credits",
        headers=admin,
        json={"amount": 0, "mode": "set"},
    )
    assert cleared.status_code == 200
    response = client.post(
        "/api/chat",
        headers=headers,
        json={"message": "What is the design pressure?", "mode": "qa"},
    )
    assert response.status_code == 402
    detail = response.json()["detail"]
    assert detail["code"] == "quota_exhausted"
    assert "used up" in detail["message"].lower() or "credits" in detail["message"].lower()
    me = client.get("/api/me", headers=headers).json()
    assert me["credits"]["balance"] == 0


def test_demo_registration_requires_a_code(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_ALLOW_REGISTRATION", "false")
    blocked = client.post(
        "/api/auth/register",
        json={"email": "public@example.com", "password": "password1"},
    )
    assert blocked.status_code == 403
    admin = login_admin(client)
    code = client.post(
        "/api/admin/codes",
        headers=admin,
        json={"credit_amount": 5, "max_uses": 1, "plan": "free"},
    ).json()["code"]
    opened = client.post(
        "/api/auth/register",
        json={"email": "public@example.com", "password": "password1", "code": code},
    )
    assert opened.status_code == 200, opened.text
    assert opened.json()["user"]["credits"]["balance"] >= 30
