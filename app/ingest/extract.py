"""Extract text and tables from PDF and Excel. OCR is optional."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ExtractedPage:
    page: str
    text: str
    tables: list[str] = field(default_factory=list)

    @property
    def combined(self) -> str:
        parts = [self.text.strip()] if self.text.strip() else []
        parts.extend(self.tables)
        return "\n".join(parts).strip()


def _render_table(rows: list[list]) -> str:
    lines = []
    for row in rows:
        cells = ["" if c is None else str(c).strip() for c in row]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def _ocr_image(image) -> str:
    from app.config import get_settings

    if not get_settings().ocr_enabled:
        return ""
    if shutil.which("tesseract") is None:
        return ""
    try:
        import pytesseract
    except ImportError:
        return ""
    try:
        return pytesseract.image_to_string(image) or ""
    except Exception:
        return ""


def extract_pdf(path: Path) -> tuple[list[ExtractedPage], str]:
    import pdfplumber

    warning = ""
    pages: list[ExtractedPage] = []
    with pdfplumber.open(str(path)) as pdf:
        if not pdf.pages:
            return [], "The PDF has no pages."
        for index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            tables = []
            try:
                extracted = page.extract_tables() or []
            except Exception:
                extracted = []
            for table in extracted:
                rendered = _render_table(table)
                if rendered:
                    tables.append(rendered)
            if len(text.strip()) < 25 and not tables:
                ocr_text = ""
                try:
                    image = page.to_image(resolution=120).original
                    ocr_text = _ocr_image(image)
                except Exception:
                    ocr_text = ""
                if ocr_text.strip():
                    text = ocr_text
                elif not warning:
                    warning = "A page had almost no extractable text. Enable OCR_ENABLED and install tesseract for scans."
            pages.append(ExtractedPage(page=str(index), text=text, tables=tables))
    if not any(p.combined for p in pages):
        warning = warning or "No text or tables were extracted."
    return pages, warning


def extract_xlsx(path: Path) -> tuple[list[ExtractedPage], str]:
    import openpyxl

    workbook = openpyxl.load_workbook(path, data_only=True)
    pages: list[ExtractedPage] = []
    for sheet in workbook.worksheets:
        for r_idx, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            cells = ["" if v is None else str(v).strip() for v in row]
            if not any(cells):
                continue
            pages.append(
                ExtractedPage(
                    page=f"{sheet.title}!{r_idx}",
                    text=" | ".join(cells),
                )
            )
    if not pages:
        return [], "The workbook has no cell values."
    return pages, ""


def extract_text_file(path: Path) -> tuple[list[ExtractedPage], str]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    pages = []
    # Split on form-feed if present, otherwise one page.
    parts = raw.split("\f") if "\f" in raw else [raw]
    for index, part in enumerate(parts, start=1):
        if part.strip():
            pages.append(ExtractedPage(page=str(index), text=part))
    if not pages:
        return [], "The file is empty."
    return pages, ""


def extract_image(path: Path) -> tuple[list[ExtractedPage], str]:
    from app.config import get_settings

    if not get_settings().ocr_enabled or shutil.which("tesseract") is None:
        return [], "Image stored. OCR is off, so no text was indexed. Set OCR_ENABLED=true and install tesseract."
    try:
        from PIL import Image
    except ImportError:
        return [], "Image stored. Install pillow and tesseract to index it."
    text = _ocr_image(Image.open(path))
    if not text.strip():
        return [], "OCR found no text in the image."
    return [ExtractedPage(page="1", text=text)], ""


def extract_file(path: Path) -> tuple[list[ExtractedPage], str]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf(path)
    if suffix in {".xlsx", ".xlsm"}:
        return extract_xlsx(path)
    if suffix in {".txt", ".md", ".csv"}:
        return extract_text_file(path)
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}:
        return extract_image(path)
    raise ValueError(f"Unsupported file type '{suffix}'. Use PDF, Excel, text, or an image.")
