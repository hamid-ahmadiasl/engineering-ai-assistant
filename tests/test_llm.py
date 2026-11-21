"""Groq request shape, JSON cleanup, and the admin probe."""

import json
import logging

from app.db import session_scope
from app.rag.answer import _parse_llm, _valid_blocks
from app.rag.llm import complete_detailed
from app.seed.bootstrap import seed_demo
from tests.conftest import login_admin

SECRET = "gsk_test_secret_value"


def _groq_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.setenv("LLM_PRESET", "groq")
    monkeypatch.setenv("GROQ_API_KEY", SECRET)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)


class _Client:
    def __init__(self, timeout=None, **_kwargs):
        self.timeout = timeout
        _Client.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, url, headers, json):
        _Client.captured = {"url": url, "json": json, "headers": headers, "timeout": self.timeout}
        return _Client.response


def test_parse_strips_fences_and_leading_text():
    fenced = """Here is the answer:
```json
{"blocks":[{"kind":"ai_interpretation","text":"kept","citation_ids":["C1"]}]}
```
"""
    parsed = _parse_llm(fenced)
    assert parsed["blocks"][0]["text"] == "kept"
    leading = 'Note {not json}\n{"blocks":[{"kind":"ai_interpretation","text":"also","citation_ids":[]}]}\nThanks'
    assert _parse_llm(leading)["blocks"][0]["text"] == "also"


def test_valid_blocks_keep_lenient_citations():
    known = {"C1", "C2"}
    blocks = _valid_blocks(
        {
            "blocks": [
                {
                    "kind": "explicit_requirement",
                    "text": "Shell design pressure is 18 barg.",
                    "citation_ids": ["[c1]", "C99", "C1"],
                },
                {"kind": "explicit_requirement", "text": "No source id was given."},
                {"text": "A bare conclusion."},
            ]
        },
        known,
    )
    assert blocks[0]["citation_ids"] == ["C1"]
    assert blocks[0]["kind"] == "explicit_requirement"
    assert blocks[1]["kind"] == "ai_interpretation"
    assert blocks[1]["citation_ids"] == []
    assert blocks[2]["kind"] == "ai_interpretation"


def test_retired_groq_model_is_replaced(monkeypatch):
    _groq_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "llama-3.3-70b-versatile")

    class Response:
        status_code = 200
        text = "{}"

        def json(self):
            return {"choices": [{"message": {"content": '{"sample": "pong"}'}}]}

    _Client.response = Response()
    _Client.captured = {}
    monkeypatch.setattr("app.rag.llm.httpx.Client", _Client)
    text, error = complete_detailed("Return JSON", "ping", json_mode=True)
    assert error is None and text
    assert _Client.captured["json"]["model"] == "openai/gpt-oss-120b"


def test_groq_request_uses_json_mode_and_a_live_model(monkeypatch):
    _groq_env(monkeypatch)

    class Response:
        status_code = 200
        text = '{"choices":[{"message":{"content":"{\\"sample\\":\\"pong\\"}"}}]}'

        def json(self):
            return {"choices": [{"message": {"content": '{"sample": "pong"}'}}]}

    _Client.response = Response()
    _Client.captured = {}
    monkeypatch.setattr("app.rag.llm.httpx.Client", _Client)
    text, error = complete_detailed("Return JSON", "ping", json_mode=True, max_tokens=256)
    assert error is None
    assert text == '{"sample": "pong"}'
    sent = _Client.captured
    assert sent["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert sent["json"]["model"] == "openai/gpt-oss-120b"
    assert sent["json"]["response_format"] == {"type": "json_object"}
    assert sent["json"]["max_completion_tokens"] == 256
    assert sent["json"]["reasoning_effort"] == "low"
    assert sent["timeout"] >= 30
    assert SECRET in sent["headers"]["Authorization"]


def test_groq_http_error_is_logged_without_the_key(monkeypatch, caplog):
    _groq_env(monkeypatch)

    class Response:
        status_code = 400
        text = f"model llama-3.3-70b-versatile has been decommissioned {SECRET}"

        def json(self):
            raise AssertionError("error bodies are not parsed")

    _Client.response = Response()
    monkeypatch.setattr("app.rag.llm.httpx.Client", _Client)
    with caplog.at_level(logging.WARNING, logger="engineering_assistant.llm"):
        text, error = complete_detailed("Return JSON", "ping", json_mode=True)
    assert text is None
    assert "400" in error
    assert "decommissioned" in error
    assert SECRET not in error
    assert SECRET not in caplog.text
    assert "400" in caplog.text


def test_llm_check_is_admin_only(client):
    registered = client.post(
        "/api/auth/register",
        json={"email": "reader@example.com", "password": "password1"},
    )
    assert registered.status_code == 200, registered.text
    denied = client.get(
        "/api/admin/llm-check",
        headers={"Authorization": f"Bearer {registered.json()['token']}"},
    )
    assert denied.status_code == 403


def test_admin_llm_check_returns_the_sample(client, monkeypatch):
    _groq_env(monkeypatch)

    class Response:
        status_code = 200
        text = "{}"

        def json(self):
            return {"choices": [{"message": {"content": '{"ok": true, "sample": "pong"}'}}]}

    _Client.response = Response()
    monkeypatch.setattr("app.rag.llm.httpx.Client", _Client)
    admin = login_admin(client)
    response = client.get("/api/admin/llm-check", headers=admin)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["base_url"] == "https://api.groq.com/openai/v1"
    assert body["error"] is None
    assert "pong" in body["sample"]
    assert SECRET not in json.dumps(body)


def test_fenced_persian_completion_becomes_blocks(client, monkeypatch):
    with session_scope() as db:
        seed_demo(db)

    def fake_complete(system, user, **kwargs):
        assert kwargs.get("json_mode") is True
        question = json.loads(user)["question"]
        if "فشار" in question:
            return """```json
{"blocks":[{"kind":"explicit_requirement","text":"فشار طراحی سمت پوسته 18 barg است.","citation_ids":["[c1]"]}],"limitations":[]}
```"""
        return json.dumps(
            {
                "blocks": [
                    {
                        "kind": "explicit_requirement",
                        "text": "The shell-side design pressure is 18 barg.",
                        "citation_ids": ["C1"],
                    }
                ],
                "limitations": [],
            }
        )

    monkeypatch.setattr("app.rag.answer.complete", fake_complete)
    admin = login_admin(client)
    project = next(
        item for item in client.get("/api/projects", headers=admin).json()["projects"] if item["code"] == "HX-2201"
    )
    persian = client.post(
        "/api/chat",
        headers=admin,
        json={
            "project_id": project["id"],
            "message": "فشار طراحی سمت پوسته HX-2201 را بگو",
            "mode": "qa",
        },
    )
    assert persian.status_code == 200, persian.text
    fa = persian.json()
    assert fa["generator"] == "llm"
    assert fa["answer_language"] == "fa"
    assert fa["blocks"][0]["citation_ids"] == ["C1"]
    assert "فشار" in fa["blocks"][0]["text"]
    assert "18 barg" in fa["blocks"][0]["text"]

    def english_for_persian(*_args, **_kwargs):
        return json.dumps(
            {
                "blocks": [
                    {
                        "kind": "explicit_requirement",
                        "text": "The shell-side design pressure is 18 barg.",
                        "citation_ids": ["C1"],
                    }
                ],
                "limitations": [],
            }
        )

    monkeypatch.setattr("app.rag.answer.complete", english_for_persian)
    framed = client.post(
        "/api/chat",
        headers=admin,
        json={
            "project_id": project["id"],
            "message": "فشار طراحی سمت پوسته HX-2201 چقدر است؟",
            "mode": "qa",
        },
    )
    assert framed.status_code == 200, framed.text
    body = framed.json()
    assert body["generator"] == "llm"
    assert body["answer_language"] == "fa"
    assert any("\u0600" <= ch <= "\u06ff" for ch in body["blocks"][0]["text"])
    assert "18 barg" in body["blocks"][0]["text"]
