"""Isolated app per test. Embeddings stay on the offline hash so tests need no model download."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["EMBEDDING_PROVIDER"] = "hash"
os.environ["LLM_PROVIDER"] = "none"
os.environ["ANONYMIZED_TELEMETRY"] = "FALSE"
os.environ["BCRYPT_ROUNDS"] = "4"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("LLM_PROVIDER", "none")
    monkeypatch.setenv("SEED_ON_STARTUP", "false")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("DEMO_ALLOW_REGISTRATION", "true")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-pass")
    monkeypatch.setenv("BCRYPT_ROUNDS", "4")
    monkeypatch.setenv("FREE_MONTHLY_CREDITS", "30")
    monkeypatch.setenv("PRO_MONTHLY_CREDITS", "400")
    monkeypatch.setenv("CREDIT_COST_PER_QUERY", "1")
    monkeypatch.setenv("TRIAL_CREDITS", "5")
    monkeypatch.setenv("DEMO_CHAT_PER_HOUR", "100")

    from app.db import reset_engine
    from app.stores.vector_store import reset_store

    reset_engine()
    reset_store()
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
    reset_engine()
    reset_store()


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login_admin(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "test-admin-pass"},
    )
    assert response.status_code == 200, response.text
    return auth_header(response.json()["token"])
