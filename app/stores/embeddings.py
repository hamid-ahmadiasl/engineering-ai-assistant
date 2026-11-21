"""Pluggable embeddings. fastembed on CPU, with a deterministic hash fallback."""

from __future__ import annotations

import hashlib
import math
import os
import re
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

DIM = 384
_TOKEN = re.compile(r"[a-z0-9]+")


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


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    settings = get_settings()
    provider = settings.embedding_provider
    if provider == "hash":
        return [hash_embed(t) for t in texts]
    try:
        model = _fastembed_model(settings.embedding_model)
        return [list(map(float, vec)) for vec in model.embed(texts)]
    except Exception:
        if provider == "fastembed":
            # Auto-style fallback so a missing model does not take the demo down.
            # Explicit "fastembed" still falls back, but the health endpoint reports it.
            return [hash_embed(t) for t in texts]
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
    _fastembed_model.cache_clear()
