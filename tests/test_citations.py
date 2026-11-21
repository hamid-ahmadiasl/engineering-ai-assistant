"""Citations carry document, clause, page, revision, and a statement class."""

from app.db import session_scope
from app.rag.citations import REQUIRED_FIELDS, format_citation
from app.seed.bootstrap import seed_demo
from tests.conftest import login_admin


def test_format_citation_fields():
    class Chunk:
        id = "chunk-1"
        title = "SP-2201 Project specification for HX-2201"
        filename = "SP-2201.pdf"
        clause = "4.2"
        section = "Design pressure"
        page = "1"
        revision = "C"
        edition = ""
        text = "The shell-side design pressure shall be 18 barg."
        statement_class = "explicit_requirement"
        doc_type = "project_spec"
        scope = "project"
        project_id = "p1"
        corpus_label = "DEMO PROJECT"
        document_id = "d1"

    citation = format_citation(Chunk(), "C1")
    for field in REQUIRED_FIELDS:
        assert field in citation
    assert citation["trace_complete"] is True
    assert citation["source_document"].startswith("SP-2201")
    assert citation["clause"] == "4.2"
    assert citation["page"] == "1"
    assert citation["revision"] == "C"
    assert "18 barg" in citation["excerpt"]
    line = f"{citation['source_document']} clause {citation['clause']} page {citation['page']} revision {citation['revision']}"
    assert "SP-2201" in line and "4.2" in line and "revision C" in line


def test_demo_answer_cites_the_specification(client):
    with session_scope() as db:
        seed_demo(db)
    admin = login_admin(client)
    projects = client.get("/api/projects", headers=admin).json()["projects"]
    project = next(item for item in projects if item["code"] == "HX-2201")
    response = client.post(
        "/api/chat",
        headers=admin,
        json={
            "project_id": project["id"],
            "message": "What shell-side design pressure is required for HX-2201?",
            "mode": "qa",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["disclaimer"]
    assert any(block["kind"] == "explicit_requirement" for block in body["blocks"])
    assert any(block["kind"] == "ai_interpretation" for block in body["blocks"])
    matched = [
        citation
        for citation in body["citations"]
        if "SP-2201" in citation["source_document"] and citation["clause"] == "4.2"
    ]
    assert matched, body["citations"]
    citation = matched[0]
    assert citation["revision"] == "C"
    assert citation["page"]
    assert citation["source_file"] == "SP-2201.pdf"
    assert "18 barg" in citation["excerpt"]
    assert citation["statement_class"] == "explicit_requirement"
    assert citation["trace_complete"] is True
