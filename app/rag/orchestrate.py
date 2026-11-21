"""Route a question to the global store, one project store, and the precedence rules."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk, Claim, Project
from app.rag.answer import answer_from_evidence
from app.rag.language import retrieval_text
from app.rag.precedence import compare_claims, filter_parameters, named_conflicts
from app.rag.retrieve import retrieve

TROUBLE_WORDS = (
    "troubleshoot", "leak", "weep", "fouling", "vibration", "failure", "failed",
    "pressure drop", "root cause", "problem", "unusual", "noise", "tube leak",
    "gasket", "why is", "what should i check",
    "نشت", "نشتی", "لرزش", "گرفتگی", "عیب", "واشر",
)
COMPARE_WORDS = (
    "compare", "conflict", "deviation", "versus", " vs ", "difference",
    "which governs", "which document", "vendor offer", "does the vendor",
    "مقایسه", "تعارض", "انحراف", "حاکم", "فروشنده",
)


def classify(message: str, requested: str | None) -> str:
    if requested in {"qa", "compare", "troubleshoot"}:
        return requested
    text = f" {message.lower()} "
    if any(word in text for word in COMPARE_WORDS):
        return "compare"
    if any(word in text for word in TROUBLE_WORDS):
        return "troubleshoot"
    return "qa"


def _chunks_for_clauses(db: Session, project_id: str, pairs: list[tuple[str, str]]) -> list[Chunk]:
    found: list[Chunk] = []
    seen = set()
    for title, clause in pairs:
        stmt = select(Chunk).where(Chunk.project_id == project_id, Chunk.title == title)
        if clause:
            stmt = stmt.where(Chunk.clause == clause)
        for chunk in db.scalars(stmt.limit(2)):
            if chunk.id not in seen:
                seen.add(chunk.id)
                found.append(chunk)
    return found


def run_query(
    db: Session,
    *,
    project: Project | None,
    message: str,
    mode: str | None,
    document_ids: list[str] | None = None,
) -> dict:
    resolved = classify(message, mode)
    project_id = project.id if project else None
    query = retrieval_text(message)
    if resolved == "troubleshoot":
        query = query + " troubleshooting considerations limitations operating window leak gasket"
    chunks = retrieve(db, query, project_id, k=8, document_ids=document_ids)

    conflicts: list[dict] = []
    if project is not None and resolved in {"compare", "qa", "troubleshoot"}:
        claims = list(db.scalars(select(Claim).where(Claim.project_id == project.id)))
        if document_ids:
            allowed_docs = set(document_ids)
            claims = [claim for claim in claims if claim.document_id in allowed_docs]
        rules = ""
        if project.precedence_json:
            try:
                payload = json.loads(project.precedence_json)
                rules = payload.get("summary", "")
            except json.JSONDecodeError:
                rules = ""
        found = compare_claims(claims, rules)
        searchable = f"{message}\n{query}"
        named = named_conflicts(searchable, found)
        broad = resolved == "compare" or any(
            word in searchable.lower() for word in ("compare", "conflict", "deviation", "governs", "مقایسه", "حاکم")
        )
        if broad:
            chosen = named or filter_parameters(message, found)
        else:
            chosen = [item for item in named if item.status != "aligned"] or named
        if chosen:
            conflicts = [item.as_dict() for item in chosen if item.status != "aligned"]
            if broad and not conflicts:
                conflicts = [item.as_dict() for item in chosen]
            pairs = [(obs.document, obs.clause) for item in chosen for obs in item.observed]
            extra = _chunks_for_clauses(db, project.id, pairs)
            if document_ids:
                allowed_docs = set(document_ids)
                extra = [chunk for chunk in extra if chunk.document_id in allowed_docs]
            have = {c.id for c in chunks}
            for chunk in extra:
                if chunk.id not in have:
                    chunks.insert(0, chunk)
                    have.add(chunk.id)
            chunks = chunks[:12]

    result = answer_from_evidence(resolved, message, chunks, conflicts)
    result["project_id"] = project_id
    result["project_code"] = project.code if project else None
    return result
