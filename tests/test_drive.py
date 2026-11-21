"""Per-user Google Drive storage, with a fake Drive client."""

from urllib.parse import parse_qs, unquote, urlparse

from sqlalchemy import select

from app.db import session_scope
from app.models import Chunk, User
from app.seed.bootstrap import bootstrap_admin
from tests.conftest import login_admin


class FakeDrive:
    created: list = []
    deleted: list = []
    missing: set = set()

    def __init__(self, token: str):
        self.token = token

    def put_in_folders(self, folders, filename, data, mime):
        file_id = f"drive-{len(FakeDrive.created) + 1}"
        FakeDrive.created.append({"id": file_id, "folders": folders, "filename": filename, "data": data, "token": self.token})
        return file_id

    def delete(self, file_id: str) -> None:
        FakeDrive.deleted.append(file_id)

    def exists(self, file_id: str) -> bool:
        return file_id not in FakeDrive.missing


def _reset_fake():
    FakeDrive.created = []
    FakeDrive.deleted = []
    FakeDrive.missing = set()


def _google(monkeypatch):
    _reset_fake()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://engineering-ai-assistant-i9fb.onrender.com")
    monkeypatch.setenv("ALLOW_LOCAL_UPLOADS", "false")
    monkeypatch.setattr("app.drive.client_for_token", lambda token: FakeDrive(token))
    monkeypatch.setattr("app.drive.exchange_code", lambda code: "refresh-token-1")
    monkeypatch.setattr("app.drive.revoke_token", lambda token: None)


def _project(client, headers):
    response = client.post(
        "/api/projects",
        headers=headers,
        json={"name": "Drive job", "code": "DRV-1", "description": ""},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _upload(client, headers, project_id, name, text, **fields):
    response = client.post(
        f"/api/projects/{project_id}/documents",
        headers=headers,
        files={"file": (name, text.encode(), "text/plain")},
        data=fields,
    )
    return response


def test_upload_is_blocked_until_drive_is_connected(client, monkeypatch):
    _google(monkeypatch)
    admin = login_admin(client)
    project = _project(client, admin)
    denied = _upload(client, admin, project["id"], "note.txt", "A note about design pressure.\n", title="Note", doc_type="upload")
    assert denied.status_code == 409
    assert "Google Drive" in denied.json()["detail"]


def test_upload_lands_in_the_users_drive_folder(client, monkeypatch):
    _google(monkeypatch)
    admin = login_admin(client)
    project = _project(client, admin)
    connect = client.get("/api/drive/connect", headers=admin)
    assert connect.status_code == 200, connect.text
    url = connect.json()["url"]
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "https://www.googleapis.com/auth/drive.file" in unquote(url)
    state = parse_qs(urlparse(url).query)["state"][0]
    callback = client.get(f"/api/drive/callback?code=abc&state={state}", follow_redirects=False)
    assert callback.status_code in {302, 307}
    assert callback.headers["location"].endswith("/?drive=connected")

    uploaded = _upload(
        client,
        admin,
        project["id"],
        "ASME-VIII.txt",
        "UG-99 The joint shall be examined.\n",
        doc_type="standard",
        standard_name="ASME VIII",
        edition="2023",
        part="Div. 1",
    )
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert body["storage"] == "gdrive"
    assert body["drive_file_id"] == "drive-1"
    assert FakeDrive.created[0]["folders"] == ["Engineering AI Assistant", "DRV-1", "Codes & Standards"]
    assert b"UG-99" in FakeDrive.created[0]["data"]

    listed = client.get(f"/api/projects/{project['id']}/documents", headers=admin).json()["documents"]
    assert listed[0]["status"] == "ready"
    FakeDrive.missing.add("drive-1")
    missing = client.get(f"/api/projects/{project['id']}/documents", headers=admin).json()["documents"][0]
    assert missing["status"] == "source_missing"
    with session_scope() as db:
        chunk = db.scalar(select(Chunk).where(Chunk.document_id == body["id"]))
        assert chunk is not None
        assert "UG-99" in chunk.text

    removed = client.delete(f"/api/projects/{project['id']}/documents/{body['id']}", headers=admin)
    assert removed.status_code == 200, removed.text
    assert "drive-1" in FakeDrive.deleted
    with session_scope() as db:
        assert db.scalar(select(Chunk).where(Chunk.document_id == body["id"])) is None


def test_disconnect_revokes_and_blocks_the_next_upload(client, monkeypatch):
    _google(monkeypatch)
    admin = login_admin(client)
    project = _project(client, admin)
    state = parse_qs(urlparse(client.get("/api/drive/connect", headers=admin).json()["url"]).query)["state"][0]
    client.get(f"/api/drive/callback?code=abc&state={state}", follow_redirects=False)
    gone = client.post("/api/drive/disconnect", headers=admin)
    assert gone.status_code == 200
    assert gone.json()["connected"] is False
    denied = _upload(client, admin, project["id"], "note.txt", "Design pressure is 10 barg.\n", title="Note")
    assert denied.status_code == 409


def test_local_fallback_is_marked_temporary(client, monkeypatch):
    _google(monkeypatch)
    monkeypatch.setenv("ALLOW_LOCAL_UPLOADS", "true")
    admin = login_admin(client)
    project = _project(client, admin)
    uploaded = _upload(client, admin, project["id"], "note.txt", "Design pressure is 10 barg.\n", title="Local note", doc_type="project_spec")
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["storage"] == "temporary"
    assert uploaded.json()["drive_file_id"] == ""
    assert FakeDrive.created == []


def test_vector_index_rebuilds_from_database_chunks(client, tmp_path):
    admin = login_admin(client)
    project = _project(client, admin)
    uploaded = _upload(
        client,
        admin,
        project["id"],
        "note.txt",
        "REBUILD-SENTINEL shell design pressure shall be 19 barg.\n",
        title="Rebuild note",
        doc_type="project_spec",
    )
    assert uploaded.status_code == 200, uploaded.text
    import shutil

    from chromadb.api.shared_system_client import SharedSystemClient

    from app.stores.rebuild import rebuild_vector_index
    from app.stores.vector_store import reset_store

    reset_store()
    SharedSystemClient.clear_system_cache()
    shutil.rmtree(tmp_path / "stores", ignore_errors=True)
    (tmp_path / "stores").mkdir()
    assert rebuild_vector_index() > 0
    from app.rag.retrieve import vector_search

    with session_scope() as db:
        hits = vector_search("REBUILD-SENTINEL", scope="project", project_id=project["id"], k=4, db=db)
    assert any("REBUILD-SENTINEL" in hit.text for hit in hits)


def test_changed_admin_password_replaces_the_stored_hash(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "rotated-pass-1")
    with session_scope() as db:
        bootstrap_admin(db)
    old = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "test-admin-pass"})
    assert old.status_code == 401
    new = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "rotated-pass-1"})
    assert new.status_code == 200, new.text
    with session_scope() as db:
        user = db.scalar(select(User).where(User.email == "admin@example.com"))
        assert user.password_hash
        assert "rotated-pass-1" not in user.password_hash
