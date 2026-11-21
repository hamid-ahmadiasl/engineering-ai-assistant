"""Rebuild the vector index from chunk text already stored in the database."""

from __future__ import annotations

import logging
import os
import threading

from sqlalchemy import func, select

log = logging.getLogger("engineering_assistant.rebuild")


def index_is_missing() -> bool:
    from app.config import get_settings

    root = get_settings().data_dir / "stores"
    if not root.exists():
        return True
    return not any(path.is_file() for path in root.rglob("*"))


def rebuild_vector_index() -> int:
    """Embed stored chunk text again. The hash embedder stays small enough for 512 MB."""
    from app.db import session_scope
    from app.models import Chunk
    from app.stores.embeddings import embed_texts
    from app.stores.vector_store import get_store, scope_key

    with session_scope() as db:
        chunks = list(db.scalars(select(Chunk)))
    if not chunks:
        return 0
    grouped: dict[str, list] = {}
    for chunk in chunks:
        grouped.setdefault(scope_key(chunk.scope, chunk.project_id), []).append(chunk)
    store = get_store()
    written = 0
    for key, rows in grouped.items():
        for start in range(0, len(rows), 16):
            batch = rows[start : start + 16]
            vectors = embed_texts([row.text for row in batch])
            store.upsert(
                key,
                ids=[row.id for row in batch],
                texts=[row.text for row in batch],
                embeddings=vectors,
                metadatas=[
                    {
                        "document_id": row.document_id,
                        "project_id": row.project_id or "",
                        "scope": row.scope,
                        "clause": row.clause,
                        "page": row.page,
                        "title": row.title,
                        "filename": row.filename,
                        "revision": row.revision,
                        "edition": row.edition,
                        "statement_class": row.statement_class,
                        "doc_type": row.doc_type,
                    }
                    for row in batch
                ],
            )
            written += len(batch)
    log.info("Rebuilt %s vector rows from the database", written)
    return written


def schedule_vector_rebuild() -> None:
    if os.getenv("REBUILD_VECTORS", "true").strip().lower() in {"0", "false", "no", "off"}:
        return
    threading.Thread(target=_rebuild_if_needed, name="vector-rebuild", daemon=True).start()


def _rebuild_if_needed() -> None:
    from app.db import session_scope
    from app.models import Chunk

    try:
        if not index_is_missing():
            return
        with session_scope() as db:
            count = db.scalar(select(func.count()).select_from(Chunk)) or 0
        if not count:
            return
        log.info("Vector index is missing; rebuilding %s chunks in the background", count)
        rebuild_vector_index()
    except Exception:
        log.exception("Vector rebuild failed")
