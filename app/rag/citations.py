"""Citation objects. Every answer points at a document, clause, page, and revision."""

from __future__ import annotations

REQUIRED_FIELDS = (
    "citation_id",
    "source_document",
    "source_file",
    "clause",
    "page",
    "revision",
    "edition",
    "excerpt",
    "statement_class",
    "doc_type",
    "store",
)

STATEMENT_LABELS = {
    "explicit_requirement": "Explicit requirement",
    "code_requirement": "Code / standard requirement",
    "engineering_recommendation": "Engineering recommendation",
    "ai_interpretation": "AI interpretation",
    "informative": "Informative source",
    "vendor_offer": "Vendor offer",
}


def excerpt(text: str, limit: int = 480) -> str:
    clean = " ".join((text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def format_citation(chunk, citation_id: str) -> dict:
    """Build a traceable citation. Missing trace fields stay visible as empty strings."""
    revision = getattr(chunk, "revision", "") or ""
    edition = getattr(chunk, "edition", "") or ""
    clause = getattr(chunk, "clause", "") or ""
    page = getattr(chunk, "page", "") or ""
    payload = {
        "citation_id": citation_id,
        "chunk_id": getattr(chunk, "id", ""),
        "source_document": getattr(chunk, "title", "") or "",
        "source_file": getattr(chunk, "filename", "") or "",
        "clause": clause,
        "section": getattr(chunk, "section", "") or "",
        "page": page,
        "revision": revision,
        "edition": edition,
        "excerpt": excerpt(getattr(chunk, "text", "") or ""),
        "statement_class": getattr(chunk, "statement_class", "") or "informative",
        "statement_label": STATEMENT_LABELS.get(
            getattr(chunk, "statement_class", ""), getattr(chunk, "statement_class", "")
        ),
        "doc_type": getattr(chunk, "doc_type", "") or "",
        "folder_role": getattr(chunk, "folder_role", "") or "",
        "store": getattr(chunk, "scope", "") or "",
        "project_id": getattr(chunk, "project_id", "") or "",
        "corpus_label": getattr(chunk, "corpus_label", "") or "",
        "document_id": getattr(chunk, "document_id", "") or "",
    }
    missing = [name for name in ("source_document", "source_file", "page", "excerpt") if not payload[name]]
    if not payload["revision"] and not payload["edition"]:
        missing.append("revision_or_edition")
    if not payload["clause"] and not payload["section"]:
        missing.append("clause_or_section")
    payload["trace_complete"] = not missing
    payload["trace_missing"] = missing
    return payload


def citation_line(citation: dict) -> str:
    rev = citation.get("revision") or "—"
    edition = citation.get("edition") or "—"
    return (
        f"{citation['citation_id']} {citation['source_document']} "
        f"({citation['source_file']}), clause {citation['clause'] or citation['section']}, "
        f"page {citation['page']}, revision {rev}, edition {edition}"
    )
