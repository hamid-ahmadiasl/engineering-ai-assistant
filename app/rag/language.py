"""Cross-language retrieval. Persian questions are rewritten into English search text."""

from __future__ import annotations

import logging
import re

from app.config import get_settings
from app.textnorm import is_persian, normalize_persian

log = logging.getLogger("engineering_assistant.language")

# Longest phrases first. Latin tokens already in the question are kept as well.
_PHRASES: tuple[tuple[str, str], ...] = (
    ("فشار طراحی سمت پوسته", "shell-side design pressure"),
    ("فشار طراحی طرف پوسته", "shell-side design pressure"),
    ("فشار طراحی پوسته", "shell design pressure"),
    ("فشار طراحی سمت لوله", "tube-side design pressure"),
    ("فشار طراحی طرف لوله", "tube-side design pressure"),
    ("فشار طراحی لوله", "tube design pressure"),
    ("اضافه ضخامت خوردگی", "corrosion allowance"),
    ("ضخامت مجاز خوردگی", "corrosion allowance"),
    ("مجاز خوردگی", "corrosion allowance"),
    ("خوردگی", "corrosion allowance"),
    ("حداقل دمای طراحی فلز", "minimum design metal temperature MDMT"),
    ("دمای طراحی", "design temperature"),
    ("پیشنهاد فروشنده", "vendor offer"),
    ("پیشنهاد وندور", "vendor offer"),
    ("کدام سند", "which document"),
    ("کدام مدرک", "which document"),
    ("حاکم است", "governs"),
    ("مشخصات فنی", "project specification"),
    ("مشخصات پروژه", "project specification"),
    ("برگه داده", "datasheet"),
    ("دیتاشیت", "datasheet"),
    ("فروشنده", "vendor"),
    ("وندور", "vendor"),
    ("مشخصات", "specification"),
    ("ویرایش استاندارد", "code edition"),
    ("نسخه استاندارد", "code edition"),
    ("عیب‌یابی", "troubleshooting"),
    ("عیب یابی", "troubleshooting"),
    ("نشتی", "leak weep gasket"),
    ("نشت", "leak"),
    ("لرزش", "vibration"),
    ("گرفتگی", "fouling pressure drop"),
    ("واشر", "gasket"),
    ("مقایسه", "compare"),
    ("تعارض", "conflict"),
    ("انحراف", "deviation"),
    ("حاکم", "governs"),
    ("مبدل حرارتی", "heat exchanger"),
    ("مبدل", "heat exchanger"),
    ("سمت پوسته", "shell side"),
    ("سمت لوله", "tube side"),
    ("پوشش کانال", "channel cover"),
    ("سیکل حرارتی", "thermal cycle"),
    ("چرخه حرارتی", "thermal cycle"),
)

_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9./-]{1,}")


def glossary_rewrite(question: str) -> str:
    """Deterministic Persian-to-English query expansion. Works with no API key."""
    text = normalize_persian(question)
    added: list[str] = []
    for phrase, english in _PHRASES:
        if phrase in text:
            added.append(english)
    latin = " ".join(_LATIN.findall(question))
    return " ".join(part for part in (latin, " ".join(added)) if part).strip()


def llm_rewrite(question: str) -> str | None:
    settings = get_settings()
    if settings.query_translation not in {"llm", "both"} or not settings.llm_configured:
        return None
    from app.rag.llm import complete

    raw = complete(
        "Rewrite the user's engineering question as a short English search query. "
        "Keep tag numbers, standard names (ASME, API, TEMA, ASTM, ISO, EN), units, and numeric values unchanged. "
        "Return only the English query, with no explanation.",
        question,
    )
    if not raw:
        return None
    line = raw.strip().splitlines()[0].strip().strip('"')
    return line[:500] if line else None


def retrieval_text(question: str) -> str:
    """Text actually sent to lexical and vector search.

    Persian questions keep their original wording (for Persian uploads) and gain an
    English rewrite so the English corpus can be found. QUERY_TRANSLATION selects
    glossary, llm, both, or off.
    """
    normalized = normalize_persian(question)
    if not is_persian(question):
        return normalized
    mode = get_settings().query_translation
    if mode == "off":
        return normalized
    parts = [normalized]
    if mode in {"glossary", "both"}:
        gloss = glossary_rewrite(question)
        if gloss:
            parts.append(gloss)
    if mode in {"llm", "both"}:
        try:
            rewritten = llm_rewrite(question)
        except Exception as exc:
            log.warning("Query rewrite failed: %s", exc)
            rewritten = None
        if rewritten:
            parts.append(rewritten)
        elif mode == "llm":
            gloss = glossary_rewrite(question)
            if gloss:
                parts.append(gloss)
    return "\n".join(parts)
