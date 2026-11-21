"""Project codes stay in that project's store, and @-mentions limit retrieval."""

from sqlalchemy import select

from app.db import session_scope
from app.models import Chunk
from tests.conftest import auth_header, login_admin


def _register(client, email: str) -> dict[str, str]:
    response = client.post("/api/auth/register", json={"email": email, "password": "password1"})
    assert response.status_code == 200, response.text
    return auth_header(response.json()["token"])


def _project(client, headers, code: str) -> dict:
    response = client.post(
        "/api/projects",
        headers=headers,
        json={"name": code, "code": code, "description": ""},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _upload(client, headers, project_id, name: str, text: str, **fields) -> dict:
    from pathlib import Path
    import tempfile

    handle_path = Path(tempfile.mkdtemp()) / name
    handle_path.write_text(text, encoding="utf-8")
    with handle_path.open("rb") as handle:
        response = client.post(
            f"/api/projects/{project_id}/documents",
            headers=headers,
            files={"file": (name, handle, "text/plain")},
            data=fields,
        )
    assert response.status_code == 200, response.text
    return response.json()


def test_standard_is_stored_on_the_project_not_the_global_kb(client):
    admin = login_admin(client)
    project = _project(client, admin, "STD-1")
    other = _project(client, admin, "STD-2")
    uploaded = _upload(
        client,
        admin,
        project["id"],
        "ASME-VIII-2023.txt",
        "UG-27 The minimum required thickness shall be 12 mm.\n",
        doc_type="standard",
        standard_name="ASME VIII",
        edition="2023",
        part="Div. 1",
    )
    assert uploaded["doc_type"] == "standard"
    assert uploaded["title"] == "ASME VIII"
    assert uploaded["edition"] == "2023"
    assert uploaded["revision"] == "Div. 1"
    assert uploaded["scope"] == "project"
    assert uploaded["project_id"] == project["id"]

    global_ids = {doc["id"] for doc in client.get("/api/kb/documents", headers=admin).json()["documents"]}
    assert uploaded["id"] not in global_ids
    other_ids = {
        doc["id"]
        for doc in client.get(f"/api/projects/{other['id']}/documents", headers=admin).json()["documents"]
    }
    assert uploaded["id"] not in other_ids

    with session_scope() as db:
        chunk = db.scalar(select(Chunk).where(Chunk.document_id == uploaded["id"]))
        assert chunk is not None
        assert chunk.scope == "project"
        assert chunk.project_id == project["id"]
        assert chunk.doc_type == "standard"
        assert chunk.edition == "2023"
        assert chunk.statement_class == "code_requirement"

    answer = client.post(
        "/api/chat",
        headers=admin,
        json={"project_id": project["id"], "message": "What minimum thickness does UG-27 require?", "mode": "qa"},
    )
    assert answer.status_code == 200, answer.text
    citations = answer.json()["citations"]
    matched = [item for item in citations if item["source_document"] == "ASME VIII"]
    assert matched
    assert matched[0]["edition"] == "2023"
    assert matched[0]["statement_class"] == "code_requirement"


def test_document_ids_restrict_the_answer_to_those_files(client):
    admin = login_admin(client)
    project = _project(client, admin, "MENT-1")
    first = _upload(
        client,
        admin,
        project["id"],
        "spec.txt",
        "4.2 Design pressure\n\nALPHA-SPEC-ONLY shell design pressure shall be 11 barg.\n",
        title="Project specification",
        doc_type="project_spec",
        revision="A",
    )
    second = _upload(
        client,
        admin,
        project["id"],
        "vendor.txt",
        "Offer\n\nBETA-VENDOR-ONLY shell design pressure shall be 42 barg.\n",
        title="Vendor offer",
        doc_type="vendor",
        revision="A",
    )
    answer = client.post(
        "/api/chat",
        headers=admin,
        json={
            "project_id": project["id"],
            "message": "What is the shell design pressure?",
            "mode": "qa",
            "document_ids": [first["id"]],
        },
    )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    blob = " ".join(item["excerpt"] for item in body["citations"]) + " " + " ".join(
        block["text"] for block in body["blocks"]
    )
    assert "ALPHA-SPEC-ONLY" in blob or "11 barg" in blob
    assert "BETA-VENDOR-ONLY" not in blob
    assert all(item["source_document"] != "Vendor offer" for item in body["citations"])
    assert second["id"] not in {item.get("document_id") for item in body["citations"]}


def test_document_ids_must_belong_to_a_readable_store(client):
    alice = _register(client, "alice-std@example.com")
    bob = _register(client, "bob-std@example.com")
    project_a = _project(client, alice, "ALICE-STD")
    project_b = _project(client, bob, "BOB-STD")
    secret = _upload(
        client,
        bob,
        project_b["id"],
        "secret.txt",
        "PRIVATE-BOB-FILE shell design pressure shall be 7 barg.\n",
        title="Bob specification",
        doc_type="project_spec",
        revision="A",
    )
    denied = client.post(
        "/api/chat",
        headers=alice,
        json={
            "project_id": project_a["id"],
            "message": "What is the shell design pressure?",
            "mode": "qa",
            "document_ids": [secret["id"]],
        },
    )
    assert denied.status_code == 403
