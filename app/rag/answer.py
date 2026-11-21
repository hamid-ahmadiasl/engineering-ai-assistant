"""Turn retrieved evidence into labeled blocks. The LLM is optional."""

from __future__ import annotations

import json
import re

from app.rag.citations import STATEMENT_LABELS, format_citation
from app.rag.llm import complete

DISCLAIMER = (
    "Decision support only. A qualified engineer reviews every statement before it is used. "
    "This assistant does not approve deviations, choose a design, or replace the licensed code."
)

SYSTEM = """You are the Engineering AI Assistant, a decision-support tool for mechanical and process engineers.
You answer only from the evidence pack. You do not invent clause numbers, editions, or values.
Return JSON with this shape:
{"blocks":[{"kind":"explicit_requirement|engineering_recommendation|ai_interpretation","text":"...","citation_ids":["C1"]}],
 "limitations":["..."]}
Rules:
- explicit_requirement blocks may only restate a source whose statement_class is explicit_requirement.
- engineering_recommendation blocks restate sources marked engineering_recommendation.
- Everything you conclude, compare, or warn about is ai_interpretation, and it must cite the sources used.
- Vendor offers and informative demo notes are not requirements. Quote them only inside ai_interpretation.
- Never say that the most restrictive value wins.
- If the evidence is missing, say so in limitations and do not guess.
- The demo knowledge notes are not the text of ASME, API, TEMA, ASTM, ISO, or EN.
"""


def _block_for_source(statement_class: str) -> str | None:
    if statement_class == "explicit_requirement":
        return "explicit_requirement"
    if statement_class == "engineering_recommendation":
        return "engineering_recommendation"
    return None


def _parse_llm(raw: str) -> dict | None:
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data.get("blocks"), list):
        return None
    return data


def _valid_blocks(data: dict, known_ids: set[str]) -> list[dict]:
    blocks = []
    for block in data.get("blocks", []):
        kind = block.get("kind")
        text = (block.get("text") or "").strip()
        if kind not in STATEMENT_LABELS or kind == "informative" or not text:
            continue
        cites = [cid for cid in block.get("citation_ids") or [] if cid in known_ids]
        if kind != "ai_interpretation" and not cites:
            kind = "ai_interpretation"
        blocks.append({"kind": kind, "text": text, "citation_ids": cites})
    return blocks


def extractive_answer(mode: str, question: str, chunks: list, conflicts: list[dict]) -> dict:
    citations = []
    id_by_chunk = {}
    for index, chunk in enumerate(chunks, start=1):
        cid = f"C{index}"
        id_by_chunk[chunk.id] = cid
        citations.append(format_citation(chunk, cid))

    blocks: list[dict] = []
    limitations: list[str] = []

    if mode == "troubleshoot":
        blocks.append(
            {
                "kind": "ai_interpretation",
                "text": (
                    "This is a troubleshooting brief, not a diagnosis. The notes below are considerations "
                    "to take back to the equipment history, the operating window, and the project requirements."
                ),
                "citation_ids": [],
            }
        )

    used = set()
    for chunk, citation in zip(chunks, citations):
        kind = _block_for_source(chunk.statement_class)
        if kind is None:
            continue
        if len([b for b in blocks if b["kind"] == kind]) >= 4:
            continue
        blocks.append(
            {
                "kind": kind,
                "text": citation["excerpt"],
                "citation_ids": [citation["citation_id"]],
            }
        )
        used.add(chunk.id)

    if conflicts:
        for conflict in conflicts:
            if conflict["status"] == "aligned":
                continue
            gov = conflict.get("governing") or {}
            cite_ids = []
            for citation in citations:
                if citation["source_document"] == gov.get("document") and (
                    not gov.get("clause") or citation["clause"] == gov.get("clause")
                ):
                    cite_ids.append(citation["citation_id"])
                    break
            for item in conflict.get("observed") or []:
                for citation in citations:
                    if citation["source_document"] == item.get("document") and citation["citation_id"] not in cite_ids:
                        if item.get("clause") and citation["clause"] != item.get("clause"):
                            continue
                        cite_ids.append(citation["citation_id"])
                        break
            blocks.append(
                {
                    "kind": "ai_interpretation",
                    "text": f"{conflict['label']}: {conflict['why']} {conflict['implication']}",
                    "citation_ids": cite_ids,
                }
            )

    informative = [c for c in citations if c["statement_class"] in {"informative", "vendor_offer"}]
    if informative and mode != "compare":
        shown = informative[:3]
        blocks.append(
            {
                "kind": "ai_interpretation",
                "text": (
                    "The following passages are source statements. Informative demo notes and vendor offers "
                    "are not project requirements: "
                    + " ".join(f"{c['citation_id']} {c['source_document']} — {c['excerpt']}" for c in shown)
                ),
                "citation_ids": [c["citation_id"] for c in shown],
            }
        )

    if not blocks:
        blocks.append(
            {
                "kind": "ai_interpretation",
                "text": (
                    "No passage in the global knowledge notes or the selected project documents answers this. "
                    "Nothing was inferred beyond that gap."
                ),
                "citation_ids": [],
            }
        )
        limitations.append("Retrieval returned no supporting excerpt.")

    if not any(c["statement_class"] == "explicit_requirement" for c in citations):
        limitations.append("No explicit requirement was retrieved for this question. Do not treat the answer as a code rule.")
    limitations.append("Demo knowledge notes are original explanations. They are not a licensed standard.")
    limitations.append(DISCLAIMER)
    if mode == "troubleshoot":
        limitations.append(
            "Options are considerations only. They omit site history, inspection results, and any calculation the licensed code requires."
        )

    return {
        "mode": mode,
        "disclaimer": DISCLAIMER,
        "blocks": blocks,
        "citations": citations,
        "conflicts": conflicts,
        "limitations": limitations,
        "generator": "extractive",
    }


def answer_from_evidence(mode: str, question: str, chunks: list, conflicts: list[dict]) -> dict:
    base = extractive_answer(mode, question, chunks, conflicts)
    citations = base["citations"]
    known = {c["citation_id"] for c in citations}
    evidence = []
    for citation in citations:
        evidence.append(
            {
                "id": citation["citation_id"],
                "document": citation["source_document"],
                "file": citation["source_file"],
                "clause": citation["clause"],
                "page": citation["page"],
                "revision": citation["revision"],
                "edition": citation["edition"],
                "statement_class": citation["statement_class"],
                "doc_type": citation["doc_type"],
                "excerpt": citation["excerpt"],
            }
        )
    user = json.dumps(
        {
            "question": question,
            "mode": mode,
            "conflicts": conflicts,
            "evidence": evidence,
        },
        ensure_ascii=False,
    )
    raw = complete(SYSTEM, user)
    if not raw:
        return base
    parsed = _parse_llm(raw)
    if not parsed:
        return base
    blocks = _valid_blocks(parsed, known)
    if not blocks:
        return base
    limitations = [str(item) for item in parsed.get("limitations") or [] if str(item).strip()]
    limitations.append("Demo knowledge notes are original explanations. They are not a licensed standard.")
    if DISCLAIMER not in limitations:
        limitations.append(DISCLAIMER)
    return {
        "mode": mode,
        "disclaimer": DISCLAIMER,
        "blocks": blocks,
        "citations": citations,
        "conflicts": conflicts,
        "limitations": limitations,
        "generator": "llm",
    }
