"""Turn retrieved evidence into labeled blocks. The LLM is optional."""

from __future__ import annotations

import json
import re

from app.rag.citations import STATEMENT_LABELS, format_citation
from app.rag.llm import complete
from app.textnorm import answer_language

DISCLAIMER = (
    "Decision support only. A qualified engineer reviews every statement before it is used. "
    "This assistant does not approve deviations, choose a design, or replace the licensed code."
)

DISCLAIMER_FA = (
    "فقط پشتیبان تصمیم است. یک مهندس واجد شرایط باید هر جمله را پیش از استفاده بررسی کند. "
    "این دستیار انحراف را تأیید نمی‌کند، طرح را انتخاب نمی‌کند، و جایگزین استاندارد دارای مجوز نمی‌شود."
)

FA_LABELS = {
    "explicit_requirement": "الزام صریح",
    "engineering_recommendation": "توصیه مهندسی",
    "ai_interpretation": "تفسیر هوش مصنوعی",
    "informative": "منبع اطلاع‌رسانی",
    "vendor_offer": "پیشنهاد فروشنده",
}

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
- Write block text and limitations in the same language as the question. A Persian question gets a Persian answer.
- Do not translate document titles, file names, clause or section identifiers, revision letters, units, or numeric values.
  Keep them exactly as written in the evidence, including Latin names such as ASME, TEMA, and barg.
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
        "answer_language": "en",
        "disclaimer": DISCLAIMER,
        "blocks": blocks,
        "citations": citations,
        "conflicts": conflicts,
        "limitations": limitations,
        "generator": "extractive",
    }


def _persian_conflicts(conflicts: list[dict]) -> str:
    lines = [
        "این مقایسه یک تصمیم طراحی نیست. مقدار سخت‌گیرانه‌تر یا سهل‌گیرانه‌تر به‌خودی‌خود برنده نمی‌شود."
    ]
    for conflict in conflicts:
        if conflict.get("status") == "aligned":
            continue
        gov = conflict.get("governing") or {}
        label = conflict.get("label_fa") or conflict.get("label")
        lines.append(
            f"{label}: سند حاکم {gov.get('document', '')}، "
            f"ویرایش {gov.get('revision') or '—'}، بند {gov.get('clause') or '—'}، "
            f"مقدار {gov.get('value', '')}."
        )
        for item in conflict.get("observed") or []:
            if item.get("role") == "governing":
                continue
            lines.append(
                f"{item.get('document', '')} ویرایش {item.get('revision') or '—'} "
                f"مقدار {item.get('value', '')} را آورده است."
            )
    return " ".join(lines)


def to_persian(result: dict) -> dict:
    """Frame an extractive answer in Persian. Source identifiers and values stay as stored."""
    result["answer_language"] = "fa"
    result["disclaimer"] = DISCLAIMER_FA
    conflict_used = False
    blocks = []
    for block in result["blocks"]:
        cites = [
            citation
            for citation in result["citations"]
            if citation["citation_id"] in (block.get("citation_ids") or [])
        ]
        if block["kind"] in {"explicit_requirement", "engineering_recommendation"} and cites:
            citation = cites[0]
            revision = citation["revision"] or citation["edition"] or "—"
            lead = (
                f"{FA_LABELS[block['kind']]} در {citation['source_document']}، "
                f"بند {citation['clause'] or citation['section']}، صفحه {citation['page']}، "
                f"ویرایش {revision}: "
            )
            text = lead + block["text"]
        elif block["kind"] == "ai_interpretation" and result.get("conflicts") and not conflict_used:
            text = _persian_conflicts(result["conflicts"])
            conflict_used = True
        else:
            text = "برداشت دستیار از متن منبع، بدون ترجمه اعداد و شناسه‌ها: " + block["text"]
        blocks.append({**block, "text": text})
    result["blocks"] = blocks
    limitations = [
        "یادداشت‌های نمایشی متن استاندارد دارای مجوز نیستند.",
        DISCLAIMER_FA,
    ]
    if result.get("mode") == "troubleshoot":
        limitations.append("گزینه‌ها فقط ملاحظه‌اند و جایگزین محاسبه استاندارد دارای مجوز نمی‌شوند.")
    result["limitations"] = limitations
    for citation in result["citations"]:
        citation["statement_label"] = FA_LABELS.get(citation["statement_class"], citation["statement_class"])
    return result


def answer_from_evidence(mode: str, question: str, chunks: list, conflicts: list[dict]) -> dict:
    lang = answer_language(question)
    base = extractive_answer(mode, question, chunks, conflicts)
    if lang == "fa":
        base = to_persian(base)
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
    disclaimer = DISCLAIMER_FA if lang == "fa" else DISCLAIMER
    note = (
        "یادداشت‌های نمایشی متن استاندارد دارای مجوز نیستند."
        if lang == "fa"
        else "Demo knowledge notes are original explanations. They are not a licensed standard."
    )
    limitations.append(note)
    if disclaimer not in limitations:
        limitations.append(disclaimer)
    labels = FA_LABELS if lang == "fa" else STATEMENT_LABELS
    for citation in citations:
        citation["statement_label"] = labels.get(citation["statement_class"], citation["statement_class"])
    return {
        "mode": mode,
        "answer_language": lang,
        "disclaimer": disclaimer,
        "blocks": blocks,
        "citations": citations,
        "conflicts": conflicts,
        "limitations": limitations,
        "generator": "llm",
    }
