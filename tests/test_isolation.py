"""A query against one project cannot see another project's store."""

from sqlalchemy import select

from app.db import session_scope
from app.models import Project
from app.rag.retrieve import retrieve
from tests.conftest import auth_header, login_admin


def _register(client, email: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password1"},
    )
    assert response.status_code == 200, response.text
    return auth_header(response.json()["token"])


def test_project_stores_stay_isolated(client, tmp_path):
    admin = login_admin(client)
    alice = _register(client, "alice@example.com")
    bob = _register(client, "bob@example.com")

    project_a = client.post(
        "/api/projects",
        headers=alice,
        json={"name": "Alice exchanger", "code": "ALICE-1", "description": ""},
    ).json()
    project_b = client.post(
        "/api/projects",
        headers=bob,
        json={"name": "Bob exchanger", "code": "BOB-1", "description": ""},
    ).json()

    def upload(headers, project_id, name, text):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        with path.open("rb") as handle:
            response = client.post(
                f"/api/projects/{project_id}/documents",
                headers=headers,
                files={"file": (name, handle, "text/plain")},
                data={"title": name, "doc_type": "project_spec", "revision": "A"},
            )
        assert response.status_code == 200, response.text

    upload(alice, project_a["id"], "alice.txt", "4.2 Design pressure\n\nAlice shell design pressure shall be 11 barg.\n")
    upload(
        bob,
        project_b["id"],
        "bob.txt",
        "2 Sentinel\n\nPROJECT-B-SENTINEL-7741 is private to Bob and the shell design pressure shall be 42 barg.\n",
    )

    denied = client.get(f"/api/projects/{project_b['id']}/documents", headers=alice)
    assert denied.status_code == 403

    listed = client.get("/api/projects", headers=alice).json()["projects"]
    assert all(project["id"] != project_b["id"] for project in listed)

    answer = client.post(
        "/api/chat",
        headers=alice,
        json={
            "project_id": project_a["id"],
            "message": "What is PROJECT-B-SENTINEL-7741 and the shell design pressure?",
            "mode": "qa",
        },
    )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    joined = " ".join(block["text"] for block in body["blocks"])
    excerpts = " ".join(citation["excerpt"] for citation in body["citations"])
    sources = " ".join(citation["source_document"] for citation in body["citations"])
    assert "PROJECT-B-SENTINEL-7741" not in excerpts
    assert "bob.txt" not in sources
    assert "42 barg" not in excerpts
    assert "11 barg" in joined or "11 barg" in excerpts

    with session_scope() as db:
        project = db.get(Project, project_a["id"])
        hits = retrieve(db, "PROJECT-B-SENTINEL-7741 shell design pressure", project.id, k=8)
        assert hits
        assert all(chunk.project_id == project.id or chunk.scope == "global" for chunk in hits)
        assert all("PROJECT-B-SENTINEL-7741" not in chunk.text for chunk in hits)
        bob_project = db.scalar(select(Project).where(Project.code == "BOB-1"))
        bob_hits = retrieve(db, "PROJECT-B-SENTINEL-7741", bob_project.id, k=4)
        assert any("PROJECT-B-SENTINEL-7741" in chunk.text for chunk in bob_hits)

    # An administrator can open both projects, and a question on Alice's project
    # still does not retrieve Bob's store.
    admin_answer = client.post(
        "/api/chat",
        headers=admin,
        json={
            "project_id": project_a["id"],
            "message": "Repeat PROJECT-B-SENTINEL-7741 if it is in this project.",
            "mode": "qa",
        },
    )
    assert admin_answer.status_code == 200
    admin_excerpts = " ".join(citation["excerpt"] for citation in admin_answer.json()["citations"])
    assert "PROJECT-B-SENTINEL-7741" not in admin_excerpts
