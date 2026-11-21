"""Split extracted pages into cited sections."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.ingest.extract import ExtractedPage

HEADING = re.compile(r"^(?P<num>\d+(?:\.\d+)*)\s+(?P<title>[A-Z][^\n]{2,100})$")


@dataclass
class SectionChunk:
    text: str
    page: str
    clause: str
    section: str
    statement_class: str


def chunk_pages(pages: list[ExtractedPage], meta: dict, *, per_row: bool = False) -> list[SectionChunk]:
    default_class = meta.get("statement_class_default") or "informative"
    default_clause = meta.get("default_clause") or ""
    sections_meta = meta.get("sections") or {}
    if per_row:
        chunks: list[SectionChunk] = []
        for page in pages:
            text = page.combined
            if not text:
                continue
            clause = default_clause
            statement = default_class
            # "Parameter | value" rows can carry an explicit class in the sidecar by clause name.
            first = text.split("|", 1)[0].strip()
            row_meta = sections_meta.get(first) or sections_meta.get(first.lower()) or {}
            if row_meta:
                statement = row_meta.get("statement_class", statement)
                clause = row_meta.get("clause", first)
            else:
                clause = first[:80] or default_clause or page.page
            chunks.append(
                SectionChunk(
                    text=text,
                    page=page.page,
                    clause=str(clause),
                    section=first[:180],
                    statement_class=statement,
                )
            )
        return chunks

    current: dict | None = None
    found: list[SectionChunk] = []

    def flush() -> None:
        nonlocal current
        if current and current["text"].strip():
            found.append(
                SectionChunk(
                    text=current["text"].strip(),
                    page=current["page"],
                    clause=current["clause"],
                    section=current["section"],
                    statement_class=current["statement_class"],
                )
            )
        current = None

    for page in pages:
        body = page.combined
        if not body:
            continue
        for line in body.splitlines():
            stripped = line.strip()
            match = HEADING.match(stripped)
            if match:
                flush()
                num = match.group("num")
                sec = sections_meta.get(num, {})
                current = {
                    "text": stripped,
                    "page": page.page,
                    "clause": num,
                    "section": match.group("title").strip(),
                    "statement_class": sec.get("statement_class", default_class),
                }
            else:
                if current is None:
                    current = {
                        "text": "",
                        "page": page.page,
                        "clause": default_clause or "0",
                        "section": meta.get("title") or "Document",
                        "statement_class": default_class,
                    }
                current["text"] += ("\n" if current["text"] else "") + stripped
    flush()
    return found
