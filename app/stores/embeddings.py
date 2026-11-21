"""Pluggable embeddings. fastembed on CPU, with a deterministic hash fallback."""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

log = logging.getLogger("engineering_assistant.embeddings")

DIM = 384
_TOKEN = re.compile(r"[a-z0-9]+")
_fallback_logged = False


def hash_embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    tokens = _TOKEN.findall(text.lower())
    if not tokens:
        tokens = ["empty"]
    for tok in tokens:
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "little") % DIM
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[bucket] += sign
        # A second feature from the next bytes helps short engineering tokens.
        bucket2 = int.from_bytes(digest[5:9], "little") % DIM
        vec[bucket2] += 0.5 * sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


@lru_cache(maxsize=1)
def _fastembed_model(model_name: str):
    from fastembed import TextEmbedding

    cache = Path(os.getenv("FASTEMBED_CACHE_PATH", "")) if os.getenv("FASTEMBED_CACHE_PATH") else get_settings().data_dir / "models"
    cache.mkdir(parents=True, exist_ok=True)
    return TextEmbedding(model_name=model_name, cache_dir=str(cache))


def _e5_prefix(kind: str) -> str:
    settings = get_settings()
    if settings.embedding_provider == "hash":
        return ""
    if "e5" not in settings.embedding_model.lower():
        return ""
    return "query: " if kind == "query" else "passage: "


def embed_texts(texts: list[str], *, kind: str = "passage") -> list[list[float]]:
    if not texts:
        return []
    settings = get_settings()
    provider = settings.embedding_provider
    prepared = [f"{_e5_prefix(kind)}{text}" if text else text for text in texts]
    if provider == "hash":
        return [hash_embed(t) for t in prepared]
    try:
        model = _fastembed_model(settings.embedding_model)
        return [list(map(float, vec)) for vec in model.embed(prepared)]
    except Exception:
        global _fallback_logged
        if not _fallback_logged:
            log.warning(
                "fastembed model %s is unavailable; using hash embeddings",
                settings.embedding_model,
            )
            _fallback_logged = True
        # A missing or oversized model must not take the demo down.
        # The health endpoint reports hash-fallback after this path.
        return [hash_embed(t) for t in texts]


def embedding_backend() -> str:
    if get_settings().embedding_provider == "hash":
        return "hash"
    try:
        _fastembed_model(get_settings().embedding_model)
        return "fastembed"
    except Exception:
        return "hash-fallback"


def clear_embed_cache() -> None:
    global _fallback_logged
    _fallback_logged = False
    _fastembed_model.cache_clear()
