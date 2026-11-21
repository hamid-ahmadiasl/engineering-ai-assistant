"""Ingest a file into the SQL metadata store and the scope's vector store."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest.chunking import chunk_pages
from app.ingest.extract import extract_file
from app.models import Chunk, Claim, Document
from app.stores.embeddings import embed_texts
from app.stores.vector_store import get_store, scope_key

ALLOWED_SUFFIXES = {".pdf", ".xlsx", ".xlsm", ".txt", ".md", ".csv", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}


def load_sidecar(path: Path) -> dict:
    sidecar = path.with_suffix(path.suffix + ".meta.json")
    if not sidecar.exists():
        alt = path.with_suffix(".meta.json")
        sidecar = alt if alt.exists() else sidecar
    if sidecar.exists():
        return json.loads(sidecar.read_text(encoding="utf-8"))
    return {}


def ingest_path(
    db: Session,
    path: Path,
    *,
    scope: str,
    project_id: str | None,
    uploaded_by: str | None,
    meta: dict | None = None,
    external_id: str | None = None,
) -> Document:
    meta = dict(meta or {})
    file_meta = load_sidecar(path)
    # Explicit meta wins over the sidecar, sidecar fills gaps.
    merged = {**file_meta, **{k: v for k, v in meta.items() if v not in (None, "")}}
    if "sections" not in merged and "sections" in file_meta:
        merged["sections"] = file_meta["sections"]
    if "claims" not in merged and "claims" in file_meta:
        merged["claims"] = file_meta["claims"]

    suffix = path.suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"Unsupported file type '{suffix}'.")

    pages, warning = extract_file(path)
    per_row = suffix in {".xlsx", ".xlsm", ".csv"} or merged.get("chunk_mode") == "row"
    sections = chunk_pages(pages, merged, per_row=per_row)

    doc_id = str(uuid.uuid4())
    title = merged.get("title") or path.stem
    document = Document(
        id=doc_id,
        external_id=external_id or merged.get("external_id"),
        scope=scope,
        project_id=project_id,
        filename=path.name,
        stored_path=str(path),
        title=title,
        doc_type=merged.get("doc_type") or "upload",
        revision=str(merged.get("revision") or ""),
        edition=str(merged.get("edition") or ""),
        hierarchy_level=int(merged.get("hierarchy_level") or 5),
        page_count=len({p.page.split("!")[0] for p in pages}) if pages else 0,
        corpus_label=merged.get("corpus_label") or "",
        uploaded_by=uploaded_by,
        status="ready" if sections else "no_text",
        warning=warning,
    )
    db.add(document)
    db.flush()

    chunk_rows: list[Chunk] = []
    for section in sections:
        chunk_rows.append(
            Chunk(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                scope=scope,
                project_id=project_id,
                text=section.text,
                page=section.page,
                clause=section.clause,
                section=section.section,
                revision=document.revision,
                edition=document.edition,
                statement_class=section.statement_class,
                doc_type=document.doc_type,
                title=document.title,
                filename=document.filename,
                corpus_label=document.corpus_label,
            )
        )
    db.add_all(chunk_rows)
    db.flush()

    for claim in merged.get("claims") or []:
        db.add(
            Claim(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                project_id=project_id,
                scope=scope,
                parameter=claim["parameter"],
                value=str(claim["value"]),
                unit=str(claim.get("unit") or ""),
                side=str(claim.get("side") or ""),
                clause=str(claim.get("clause") or ""),
                page=str(claim.get("page") or _page_for_clause(chunk_rows, claim.get("clause"))),
                statement_class=claim.get("statement_class") or document.doc_type,
                doc_type=document.doc_type,
                title=document.title,
                revision=document.revision,
                edition=document.edition,
                hierarchy_level=document.hierarchy_level,
                filename=document.filename,
            )
        )

    if chunk_rows:
        key = scope_key(scope, project_id)
        embeddings = embed_texts([c.text for c in chunk_rows])
        get_store().upsert(
            key,
            ids=[c.id for c in chunk_rows],
            texts=[c.text for c in chunk_rows],
            embeddings=embeddings,
            metadatas=[
                {
                    "document_id": c.document_id,
                    "project_id": c.project_id or "",
                    "scope": c.scope,
                    "clause": c.clause,
                    "page": c.page,
                    "title": c.title,
                    "filename": c.filename,
                    "revision": c.revision,
                    "edition": c.edition,
                    "statement_class": c.statement_class,
                    "doc_type": c.doc_type,
                }
                for c in chunk_rows
            ],
        )
    return document


def _page_for_clause(chunks: list[Chunk], clause: str | None) -> str:
    if not clause:
        return chunks[0].page if chunks else ""
    for chunk in chunks:
        if chunk.clause == clause:
            return chunk.page
    return chunks[0].page if chunks else ""


def delete_document(db: Session, document: Document) -> None:
    chunks = list(db.scalars(select(Chunk).where(Chunk.document_id == document.id)))
    ids = [c.id for c in chunks]
    if ids:
        get_store().delete_ids(scope_key(document.scope, document.project_id), ids)
    for chunk in chunks:
        db.delete(chunk)
    for claim in db.scalars(select(Claim).where(Claim.document_id == document.id)):
        db.delete(claim)
    db.delete(document)
