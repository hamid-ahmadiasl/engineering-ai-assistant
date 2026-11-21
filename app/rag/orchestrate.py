"""Route a question to the global store, one project store, and the precedence rules."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk, Claim, Project
from app.rag.answer import answer_from_evidence
from app.rag.language import retrieval_text
from app.rag.precedence import (
    DEFAULT_ROLE_ORDER,
    compare_claims,
    filter_parameters,
    named_conflicts,
    separate_project_notes,
)
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


def _role_order(project: Project) -> list[str]:
    order = list(DEFAULT_ROLE_ORDER)
    if not project.precedence_json:
        return order
    try:
        raw = json.loads(project.precedence_json).get("roles") or []
    except json.JSONDecodeError:
        return order
    chosen = [role for role in raw if role in DEFAULT_ROLE_ORDER]
    for role in DEFAULT_ROLE_ORDER:
        if role not in chosen:
            chosen.append(role)
    return chosen or order


def _project_conflicts(db: Session, project: Project, message: str, query: str, resolved: str, document_ids: list[str] | None):
    claims = list(db.scalars(select(Claim).where(Claim.project_id == project.id)))
    if document_ids:
        allowed_docs = set(document_ids)
        claims = [claim for claim in claims if claim.document_id in allowed_docs]
    rules = ""
    if project.precedence_json:
        try:
            rules = json.loads(project.precedence_json).get("summary", "")
        except json.JSONDecodeError:
            rules = ""
    found = compare_claims(claims, rules, _role_order(project))
    searchable = f"{message}\n{query}"
    named = named_conflicts(searchable, found)
    broad = resolved == "compare" or any(
        word in searchable.lower() for word in ("compare", "conflict", "deviation", "governs", "مقایسه", "حاکم")
    )
    if broad:
        chosen = named or filter_parameters(message, found)
    else:
        chosen = [item for item in named if item.status != "aligned"] or named
    cards = []
    if chosen:
        cards = [item.as_dict() for item in chosen if item.status != "aligned"]
        if broad and not cards:
            cards = [item.as_dict() for item in chosen]
        for card in cards:
            card["project_id"] = project.id
            card["project_code"] = project.code
    return chosen, cards


def run_query(
    db: Session,
    *,
    project: Project | None,
    message: str,
    mode: str | None,
    document_ids: list[str] | None = None,
    projects: list[Project] | None = None,
    include_global: bool | None = None,
    include_personal: bool = False,
    owner_id: str | None = None,
    folder_documents: dict[str, set[str]] | None = None,
) -> dict:
    resolved = classify(message, mode)
    selected = projects if projects is not None else ([project] if project else [])
    if include_global is None:
        include_global = True
    query = retrieval_text(message)
    if resolved == "troubleshoot":
        query = query + " troubleshooting considerations limitations operating window leak gasket"
    chunks = retrieve(
        db,
        query,
        selected[0].id if selected else None,
        k=8,
        document_ids=document_ids,
        project_ids=[item.id for item in selected],
        include_global=include_global,
        include_personal=include_personal,
        owner_id=owner_id if include_personal else None,
        folder_documents=folder_documents,
    )

    conflicts: list[dict] = []
    grouped: list[tuple[str, list]] = []
    if resolved in {"compare", "qa", "troubleshoot"}:
        for item in selected:
            chosen, cards = _project_conflicts(db, item, message, query, resolved, document_ids)
            grouped.append((item.code, chosen))
            conflicts.extend(cards)
            if chosen:
                pairs = [(obs.document, obs.clause) for conflict in chosen for obs in conflict.observed]
                extra = _chunks_for_clauses(db, item.id, pairs)
                if folder_documents and item.id in folder_documents:
                    extra = [chunk for chunk in extra if chunk.document_id in folder_documents[item.id]]
                if document_ids:
                    allowed_docs = set(document_ids)
                    extra = [chunk for chunk in extra if chunk.document_id in allowed_docs]
                have = {chunk.id for chunk in chunks}
                for chunk in extra:
                    if chunk.id not in have:
                        chunks.insert(0, chunk)
                        have.add(chunk.id)
        chunks = chunks[:12]
        conflicts.extend(separate_project_notes(grouped))

    result = answer_from_evidence(resolved, message, chunks, conflicts)
    codes = {item.id: item.code for item in selected}
    for citation in result.get("citations") or []:
        if citation.get("store") == "personal":
            citation["store_label"] = "General Codes and STD"
        elif citation.get("store") == "global":
            citation["store_label"] = "Demo notes"
        else:
            citation["store_label"] = codes.get(citation.get("project_id") or "", citation.get("store") or "")
    result["project_id"] = selected[0].id if len(selected) == 1 else None
    result["project_code"] = selected[0].code if len(selected) == 1 else None
    result["project_ids"] = [item.id for item in selected]
    result["include_global"] = include_global
    return result
