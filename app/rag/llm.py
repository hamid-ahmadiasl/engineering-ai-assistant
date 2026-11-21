"""OpenAI-compatible chat client. Groq, Gemini, OpenAI, Azure, and Ollama share it."""

from __future__ import annotations

import json
import logging
import re

import httpx

from app.config import get_settings

log = logging.getLogger("engineering_assistant.llm")

# Groq retired llama-3.3-70b-versatile on 2026-08-16 for free and developer tiers.
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
TIMEOUT_SECONDS = 60.0
ANSWER_MAX_TOKENS = 2048
_JSON_OBJECT_PRESETS = {"groq", "openai", "gemini"}
_SECRET = re.compile(r"(Bearer\s+)\S+|gsk_[A-Za-z0-9]+|sk-[A-Za-z0-9]+")


def redact(text: str, secret: str = "") -> str:
    """Drop credentials before a log line or an admin error string."""
    cleaned = text or ""
    if secret:
        cleaned = cleaned.replace(secret, "[redacted]")
    return _SECRET.sub(lambda match: (match.group(1) or "") + "[redacted]", cleaned)


def public_snippet(text: str, limit: int = 400) -> str:
    secret = get_settings().llm_api_key
    return redact(text or "", secret)[:limit]


def complete(system: str, user: str, *, json_mode: bool = False, max_tokens: int = ANSWER_MAX_TOKENS) -> str | None:
    text, _error = complete_detailed(system, user, json_mode=json_mode, max_tokens=max_tokens)
    return text


def complete_detailed(
    system: str,
    user: str,
    *,
    json_mode: bool = False,
    max_tokens: int = ANSWER_MAX_TOKENS,
) -> tuple[str | None, str | None]:
    """Return (content, error). The error is safe to show to an administrator."""
    settings = get_settings()
    if not settings.llm_configured:
        return None, "LLM is not configured"
    url = f"{settings.llm_base_url}/chat/completions"
    payload: dict = {
        "model": settings.llm_model,
        "temperature": 0.1,
        "max_completion_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode and settings.llm_preset in _JSON_OBJECT_PRESETS:
        payload["response_format"] = {"type": "json_object"}
    if settings.llm_model.startswith("openai/gpt-oss"):
        # Reasoning tokens share this budget. Low effort keeps the JSON in content.
        payload["reasoning_effort"] = "low"
        payload["reasoning_format"] = "hidden"
    headers = {"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"}
    secret = settings.llm_api_key
    response: httpx.Response | None = None
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            response = client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            snippet = redact(response.text[:400], secret)
            log.warning("LLM HTTP %s: %s", response.status_code, snippet)
            return None, f"HTTP {response.status_code}: {snippet}"
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            snippet = redact(response.text[:400], secret)
            log.warning("LLM response was not JSON (%s). body=%s", exc, snippet)
            return None, f"invalid JSON: {snippet}"
        message = (data.get("choices") or [{}])[0].get("message") or {}
        content = _message_text(message)
        if not content.strip():
            snippet = redact(response.text[:400], secret)
            log.warning("LLM returned empty content. HTTP %s: %s", response.status_code, snippet)
            return None, f"empty content: {snippet}"
        return content, None
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
        body = ""
        status = ""
        if response is not None:
            status = f" HTTP {response.status_code}"
            body = redact(response.text[:400], secret)
        detail = redact(str(exc), secret)
        log.warning("LLM call failed:%s %s: %s body=%s", status, type(exc).__name__, detail, body)
        error = f"{type(exc).__name__}: {detail}"
        if body:
            error = f"{error} body={body}"
        return None, error


def _message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or part.get("content") or ""))
            else:
                parts.append(str(part))
        content = "".join(parts)
    return str(content or "")


def llm_check() -> dict:
    """One tiny completion an administrator can read without opening the host logs."""
    settings = get_settings()
    result = {
        "ok": False,
        "model": settings.llm_model,
        "base_url": settings.llm_base_url,
        "error": None,
        "sample": None,
    }
    text, error = complete_detailed(
        'Reply with a JSON object {"ok": true, "sample": "pong"}.',
        "ping",
        json_mode=True,
        max_tokens=256,
    )
    if error or not text:
        result["error"] = error or "empty completion"
        return result
    result["ok"] = True
    result["sample"] = public_snippet(text, 500)
    return result
