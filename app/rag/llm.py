"""OpenAI-compatible chat client. Groq, Gemini, OpenAI, Azure, and Ollama share it."""

from __future__ import annotations

import json
import logging

import httpx

from app.config import get_settings

log = logging.getLogger("engineering_assistant.llm")


def complete(system: str, user: str) -> str | None:
    settings = get_settings()
    if not settings.llm_configured:
        return None
    url = f"{settings.llm_base_url}/chat/completions"
    payload = {
        "model": settings.llm_model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    headers = {"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            log.warning("LLM HTTP %s: %s", response.status_code, response.text[:400])
            return None
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as exc:
        log.warning("LLM call failed: %s", exc)
        return None
