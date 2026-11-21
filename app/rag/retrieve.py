"""Hybrid retrieval. Lexical search and vectors stay inside one store, then fuse."""

from __future__ import annotations

import re

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.models import Chunk
from app.stores.vector_store import get_store, scope_key

_TOKEN = re.compile(r"[A-Za-z0-9\u0600-\u06FF][A-Za-z0-9\u0600-\u06FF.\-]{1,}")
_STOP = {
    "what", "which", "does", "this", "that", "with", "from", "have", "your",
    "about", "into", "should", "would", "could", "there", "their", "project",
    "please", "explain", "compare", "across", "where", "when", "will",
    "برای", "است", "این", "آن", "که", "را", "از", "به", "با", "در", "یک", "های", "می",
}


def _tokens(query: str) -> list[str]:
    found = []
    for raw in _TOKEN.findall(query):
        if raw.lower() in _STOP:
            continue
        if raw.lower() not in {t.lower() for t in found}:
            found.append(raw)
    return found[:12]


def lexical_search(
    db: Session,
    query: str,
    *,
    scope: str,
    project_id: str | None,
    k: int,
    owner_id: str | None = None,
) -> list[Chunk]:
    tokens = _tokens(query)
    if not tokens:
        return []
    if scope == "personal":
        return _like_search(db, tokens, scope=scope, project_id=None, k=k, owner_id=owner_id)
    dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
    if dialect == "sqlite":
        and_hits = (
            _fts(db, tokens[:6], scope=scope, project_id=project_id, k=k, operator="AND")
            if len(tokens) > 1
            else []
        )
        or_hits = _fts(db, tokens, scope=scope, project_id=project_id, k=k, operator="OR")
        if or_hits is None:
            return _like_search(db, tokens, scope=scope, project_id=project_id, k=k)
        return _dedupe((and_hits or []) + or_hits)[:k]
    return _like_search(db, tokens, scope=scope, project_id=project_id, k=k)


def _dedupe(chunks: list[Chunk]) -> list[Chunk]:
    seen = set()
    ordered = []
    for chunk in chunks:
        if chunk.id in seen:
            continue
        seen.add(chunk.id)
        ordered.append(chunk)
    return ordered


def _fts(db: Session, tokens: list[str], *, scope: str, project_id: str | None, k: int, operator: str) -> list[Chunk] | None:
    match = f" {operator} ".join(f'"{tok}"' for tok in tokens)
    sql = text(
        """
        SELECT chunks.pk AS pk
        FROM chunks_fts
        JOIN chunks ON chunks.pk = chunks_fts.rowid
        WHERE chunks_fts MATCH :match
          AND chunks.scope = :scope
          AND (:project_id IS NULL OR chunks.project_id = :project_id)
        ORDER BY rank
        LIMIT :k
        """
    )
    try:
        with db.begin_nested():
            rows = db.execute(
                sql,
                {"match": match, "scope": scope, "project_id": project_id, "k": k},
            ).fetchall()
    except Exception:
        return None
    pks = [row.pk for row in rows]
    if not pks:
        return []
    chunks = list(db.scalars(select(Chunk).where(Chunk.pk.in_(pks))))
    order = {pk: index for index, pk in enumerate(pks)}
    chunks.sort(key=lambda chunk: order.get(chunk.pk, 999))
    return chunks


def _like_search(
    db: Session,
    tokens: list[str],
    *,
    scope: str,
    project_id: str | None,
    k: int,
    owner_id: str | None = None,
) -> list[Chunk]:
    stmt = select(Chunk).where(Chunk.scope == scope)
    if scope == "personal":
        stmt = stmt.where(Chunk.owner_id == owner_id)
    elif project_id is not None:
        stmt = stmt.where(Chunk.project_id == project_id)
    else:
        stmt = stmt.where(Chunk.project_id.is_(None))
    clauses = [Chunk.text.ilike(f"%{tok}%") for tok in tokens]
    stmt = stmt.where(or_(*clauses)).limit(max(k * 5, 20))
    rows = list(db.scalars(stmt))

    def score(chunk: Chunk) -> int:
        haystack = f"{chunk.text} {chunk.title} {chunk.clause}".lower()
        return sum(tok.lower() in haystack for tok in tokens)

    rows.sort(key=score, reverse=True)
    return rows[:k]


def vector_search(
    query: str,
    *,
    scope: str,
    project_id: str | None,
    k: int,
    db: Session,
    owner_id: str | None = None,
) -> list[Chunk]:
    hits = get_store().query(scope_key(scope, project_id, owner_id), query, k)
    if not hits:
        return []
    ids = [hit["id"] for hit in hits]
    chunks = list(db.scalars(select(Chunk).where(Chunk.id.in_(ids))))
    # Defend the boundary even if a store was mis-filed.
    if scope == "global":
        chunks = [c for c in chunks if c.scope == "global" and not c.project_id]
    elif scope == "personal":
        chunks = [c for c in chunks if c.scope == "personal" and c.owner_id == owner_id]
    else:
        chunks = [c for c in chunks if c.project_id == project_id]
    order = {cid: index for index, cid in enumerate(ids)}
    chunks.sort(key=lambda chunk: order.get(chunk.id, 999))
    return chunks


def reciprocal_rank_fusion(rankings: list[list[Chunk]], k: int = 8, rrf_k: int = 60) -> list[Chunk]:
    scores: dict[str, float] = {}
    chosen: dict[str, Chunk] = {}
    for ranking in rankings:
        for index, chunk in enumerate(ranking):
            scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (rrf_k + index + 1)
            chosen[chunk.id] = chunk
    ordered = sorted(scores, key=lambda cid: scores[cid], reverse=True)
    return [chosen[cid] for cid in ordered[:k]]


def retrieve(
    db: Session,
    query: str,
    project_id: str | None,
    k: int = 8,
    document_ids: list[str] | None = None,
    project_ids: list[str] | None = None,
    include_global: bool = True,
    owner_id: str | None = None,
) -> list[Chunk]:
    rankings: list[list[Chunk]] = []
    if include_global:
        rankings.append(lexical_search(db, query, scope="global", project_id=None, k=k))
        rankings.append(vector_search(query, scope="global", project_id=None, k=k, db=db))
        if owner_id:
            rankings.append(lexical_search(db, query, scope="personal", project_id=None, k=k, owner_id=owner_id))
            rankings.append(vector_search(query, scope="personal", project_id=None, k=k, db=db, owner_id=owner_id))
    selected = project_ids if project_ids is not None else ([project_id] if project_id else [])
    for pid in selected:
        rankings.append(lexical_search(db, query, scope="project", project_id=pid, k=k))
        rankings.append(vector_search(query, scope="project", project_id=pid, k=k, db=db))
    fused = reciprocal_rank_fusion(rankings, k=k)
    if not document_ids:
        return fused
    allowed = {doc_id for doc_id in document_ids if doc_id}
    picked = [chunk for chunk in fused if chunk.document_id in allowed]
    have = {chunk.id for chunk in picked}
    if len(picked) < k:
        extra = list(db.scalars(select(Chunk).where(Chunk.document_id.in_(allowed)).limit(k * 4)))
        for chunk in extra:
            if chunk.id in have:
                continue
            picked.append(chunk)
            have.add(chunk.id)
            if len(picked) >= k:
                break
    return picked[:k]
