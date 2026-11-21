"""Normalize Persian and Arabic-script text for indexing and search."""

from __future__ import annotations

import re

# Arabic yeh/kaf and their Persian counterparts. Presentation forms are folded too.
_CHAR_MAP = str.maketrans(
    {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ة": "ه",
        "ؤ": "و",
        "إ": "ا",
        "أ": "ا",
        "آ": "آ",
        "\u200c": " ",  # ZWNJ
        "\u200d": "",  # ZWJ
        "\u200e": "",
        "\u200f": "",
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
    }
)

_ARABIC = re.compile(r"[\u0600-\u06FF]")
_SPACE = re.compile(r"\s+")


def normalize_persian(text: str) -> str:
    """Fold Arabic yeh/kaf into Persian, turn ZWNJ into a space, and use Western digits.

    Excerpts shown to the engineer are normalized the same way, so digits stay Western
    whether the source file used Persian or Arabic numerals.
    """
    if not text:
        return ""
    folded = text.translate(_CHAR_MAP)
    lines = [_SPACE.sub(" ", line).strip() for line in folded.splitlines()]
    return "\n".join(line for line in lines if line or True).strip()


def is_persian(text: str) -> bool:
    """True when the question is Persian or mixed Persian with Latin technical terms."""
    if not text:
        return False
    letters = _ARABIC.findall(text)
    return len(letters) >= 2


def answer_language(text: str) -> str:
    return "fa" if is_persian(text) else "en"
