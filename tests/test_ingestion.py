"""PDF and Excel ingestion keep text, tables, page, and revision metadata."""

from pathlib import Path

from fpdf import FPDF
from openpyxl import Workbook

from tests.conftest import login_admin


def _pdf(path: Path) -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(0, 8, "4.2 Design pressure", new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(0, 8, "The shell-side design pressure shall be 21 barg.", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    with pdf.table(width=160) as table:
        header = table.row()
        header.cell("Parameter")
        header.cell("Value")
        row = table.row()
        row.cell("Corrosion allowance")
        row.cell("3.0 mm")
    pdf.output(str(path))


def _xlsx(path: Path) -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "Process Data"
    sheet.append(["Parameter", "Shell", "Unit"])
    sheet.append(["Shell design pressure", "16", "barg"])
    book.save(path)


def test_pdf_and_excel_ingest_with_trace_metadata(client, tmp_path):
    admin = login_admin(client)
    created = client.post(
        "/api/projects",
        headers=admin,
        json={"name": "Ingest trial", "code": "INGEST-1", "description": ""},
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]

    pdf_path = tmp_path / "note.pdf"
    xlsx_path = tmp_path / "sheet.xlsx"
    _pdf(pdf_path)
    _xlsx(xlsx_path)

    with pdf_path.open("rb") as handle:
        pdf_response = client.post(
            f"/api/projects/{project_id}/documents",
            headers=admin,
            files={"file": ("note.pdf", handle, "application/pdf")},
            data={"title": "Ingested specification", "doc_type": "project_spec", "revision": "C"},
        )
    assert pdf_response.status_code == 200, pdf_response.text
    assert pdf_response.json()["revision"] == "C"
    assert pdf_response.json()["status"] == "ready"

    with xlsx_path.open("rb") as handle:
        xlsx_response = client.post(
            f"/api/projects/{project_id}/documents",
            headers=admin,
            files={"file": ("sheet.xlsx", handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"title": "Ingested datasheet", "doc_type": "datasheet", "revision": "B"},
        )
    assert xlsx_response.status_code == 200, xlsx_response.text

    from sqlalchemy import select

    from app.db import session_scope
    from app.models import Chunk

    with session_scope() as db:
        chunks = list(db.scalars(select(Chunk).where(Chunk.project_id == project_id)))
    blob = "\n".join(chunk.text for chunk in chunks)
    assert "21 barg" in blob
    assert "3.0 mm" in blob
    assert "16" in blob and "barg" in blob
    pdf_chunks = [chunk for chunk in chunks if chunk.filename == "note.pdf"]
    assert pdf_chunks
    assert any(chunk.clause == "4.2" for chunk in pdf_chunks)
    assert all(chunk.revision == "C" for chunk in pdf_chunks)
    assert all(chunk.page for chunk in pdf_chunks)
    excel_chunks = [chunk for chunk in chunks if chunk.filename == "sheet.xlsx"]
    assert any(chunk.page.startswith("Process Data!") for chunk in excel_chunks)
    assert all(chunk.revision == "B" for chunk in excel_chunks)
