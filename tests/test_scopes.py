"""Multi-scope chat, project permissions, and the personal general library."""

from app.rag.precedence import Conflict, Observed, separate_project_notes
from tests.conftest import auth_header, login_admin


def _register(client, email: str) -> dict[str, str]:
    response = client.post("/api/auth/register", json={"email": email, "password": "password1"})
    assert response.status_code == 200, response.text
    return auth_header(response.json()["token"])


def _project(client, headers, code: str) -> dict:
    response = client.post(
        "/api/projects",
        headers=headers,
        json={"name": code, "code": code, "description": "A job", "equipment": "exchanger"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _upload(client, headers, project_id: str, name: str, text: str) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/documents",
        headers=headers,
        files={"file": (name, text.encode(), "text/plain")},
        data={"title": name, "doc_type": "project_spec", "revision": "A"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_trial_cannot_create_a_project_and_owner_can(client):
    trial = client.post("/api/auth/trial")
    assert trial.status_code == 200, trial.text
    denied = client.post(
        "/api/projects",
        headers=auth_header(trial.json()["token"]),
        json={"name": "Trial job", "code": "TRIAL-1", "description": ""},
    )
    assert denied.status_code == 403
    user = _register(client, "owner-scope@example.com")
    created = _project(client, user, "OWN-1")
    assert created["role"] == "owner"
    assert created["equipment"] == "exchanger"
    renamed = client.patch(
        f"/api/projects/{created['id']}",
        headers=user,
        json={"name": "Renamed job"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Renamed job"
    outsider = _register(client, "outsider-scope@example.com")
    blocked = client.delete(f"/api/projects/{created['id']}", headers=outsider)
    assert blocked.status_code == 403
    removed = client.delete(f"/api/projects/{created['id']}", headers=user)
    assert removed.status_code == 200, removed.text


def test_chat_searches_every_selected_project(client):
    admin = login_admin(client)
    first = _project(client, admin, "SC-A")
    second = _project(client, admin, "SC-B")
    _upload(client, admin, first["id"], "a.txt", "ALPHA-SCOPE-ONLY design pressure is 11 barg.\n")
    _upload(client, admin, second["id"], "b.txt", "BETA-SCOPE-ONLY design pressure is 22 barg.\n")
    answer = client.post(
        "/api/chat",
        headers=admin,
        json={
            "message": "What design pressures are listed?",
            "mode": "qa",
            "scopes": {"global": False, "project_ids": [first["id"], second["id"]]},
        },
    )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    blob = " ".join(item["excerpt"] for item in body["citations"])
    assert "ALPHA-SCOPE-ONLY" in blob
    assert "BETA-SCOPE-ONLY" in blob
    labels = {item["store_label"] for item in body["citations"]}
    assert "SC-A" in labels
    assert "SC-B" in labels


def test_personal_library_is_not_visible_to_another_user(client):
    alice = _register(client, "alice-lib@example.com")
    bob = _register(client, "bob-lib@example.com")
    uploaded = client.post(
        "/api/library/documents",
        headers=alice,
        files={"file": ("mine.txt", b"ALICE-PRIVATE-LIBRARY design pressure is 5 barg.\n", "text/plain")},
        data={"title": "Alice notes"},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["scope"] == "personal"
    bob_list = client.get("/api/library/documents", headers=bob).json()["documents"]
    assert all(doc["id"] != uploaded.json()["id"] for doc in bob_list)
    answer = client.post(
        "/api/chat",
        headers=bob,
        json={"message": "What is ALICE-PRIVATE-LIBRARY?", "mode": "qa", "scopes": {"global": True, "project_ids": []}},
    )
    assert answer.status_code == 200, answer.text
    blob = " ".join(item["excerpt"] for item in answer.json()["citations"])
    assert "ALICE-PRIVATE-LIBRARY" not in blob
    own = client.post(
        "/api/chat",
        headers=alice,
        json={"message": "What is ALICE-PRIVATE-LIBRARY?", "mode": "qa", "scopes": {"global": True, "project_ids": []}},
    )
    assert own.status_code == 200, own.text
    own_blob = " ".join(item["excerpt"] for item in own.json()["citations"])
    assert "ALICE-PRIVATE-LIBRARY" in own_blob
    assert any(item["store_label"] == "General Codes and STD" for item in own.json()["citations"])


def test_cross_project_values_are_not_one_conflict():
    def observed(value: str) -> Observed:
        return Observed(
            value=value,
            document="Spec",
            filename="spec.txt",
            doc_type="project_spec",
            revision="A",
            edition="",
            clause="1",
            page="1",
            statement_class="explicit_requirement",
            role="governing",
        )

    left = Conflict(
        parameter="shell_design_pressure",
        label="Shell-side design pressure",
        status="aligned",
        governing=observed("11 barg"),
    )
    right = Conflict(
        parameter="shell_design_pressure",
        label="Shell-side design pressure",
        status="aligned",
        governing=observed("22 barg"),
    )
    notes = separate_project_notes([("SC-A", [left]), ("SC-B", [right])])
    assert len(notes) == 1
    assert notes[0]["status"] == "separate"
    assert notes[0]["why"] == "These values come from different projects, not a conflict."
