"""User-owned library tree: Drive mirror, no demo notes for signed-in users, role folders."""

from urllib.parse import parse_qs, urlparse

from app.seed.bootstrap import seed_demo
from app.db import session_scope
from tests.conftest import login_admin
from tests.test_drive import FakeDrive, _google, _upload


def _connect(client, headers):
    url = client.get("/api/drive/connect", headers=headers).json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    client.get(f"/api/drive/callback?code=abc&state={state}", follow_redirects=False)


def test_role_folders_are_mirrored_and_moves_follow(client, monkeypatch):
    _google(monkeypatch)
    admin = login_admin(client)
    _connect(client, admin)
    created = client.post(
        "/api/projects",
        headers=admin,
        json={
            "name": "Preheat",
            "code": "0001",
            "roles": ["owner", "vendor", "consultant", "third_party"],
            "custom_folders": ["Site"],
        },
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    folders = client.get(f"/api/projects/{project_id}/folders", headers=admin).json()["folders"]
    by_name = {item["name"]: item for item in folders}
    assert by_name["Owner"]["role"] == "owner"
    assert by_name["Vendor"]["role"] == "vendor"
    assert by_name["Site"]["role"] == ""
    assert "EAIA/0001 - Preheat/Owner" in FakeDrive.paths
    assert "EAIA/0001 - Preheat/Third Party" in FakeDrive.paths

    owner = by_name["Owner"]["id"]
    pump = client.post(
        f"/api/projects/{project_id}/folders",
        headers=admin,
        json={"name": "Pump vendor", "parent_id": by_name["Vendor"]["id"]},
    )
    assert pump.status_code == 200, pump.text
    sheets = client.post(
        f"/api/projects/{project_id}/folders",
        headers=admin,
        json={"name": "Datasheets", "parent_id": pump.json()["id"]},
    )
    assert sheets.status_code == 200, sheets.text
    assert "EAIA/0001 - Preheat/Vendor/Pump vendor/Datasheets" in FakeDrive.paths

    uploaded = _upload(
        client,
        admin,
        project_id,
        "offer.txt",
        "Vendor design pressure is 14 barg.\n",
        title="Offer",
        doc_type="upload",
    )
    assert uploaded.status_code == 200, uploaded.text
    assert FakeDrive.created[-1]["folders"] == ["EAIA", "0001 - Preheat"]
    moved = client.patch(
        f"/api/projects/{project_id}/documents/{uploaded.json()['id']}",
        headers=admin,
        json={"folder_id": sheets.json()["id"]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["folder_id"] == sheets.json()["id"]
    assert FakeDrive.moved[-1]["folders"] == ["EAIA", "0001 - Preheat", "Vendor", "Pump vendor", "Datasheets"]

    renamed = client.patch(f"/api/folders/{owner}", headers=admin, json={"name": "Company"})
    assert renamed.status_code == 200, renamed.text
    assert FakeDrive.renamed[-1]["name"] == "Company"


def test_signed_in_search_skips_demo_notes(client):
    with session_scope() as db:
        seed_demo(db)
    admin = login_admin(client)
    signed = client.post(
        "/api/chat",
        headers=admin,
        json={
            "message": "The channel cover is weeping after a thermal cycle. What should I consider, including the MDMT?",
            "mode": "troubleshoot",
            "scopes": {"global": True, "project_ids": []},
        },
    )
    assert signed.status_code == 200, signed.text
    signed_docs = " ".join(item["source_document"] for item in signed.json()["citations"])
    assert "Demo knowledge" not in signed_docs

    trial = client.post("/api/auth/trial")
    assert trial.status_code == 200, trial.text
    anonymous = client.post(
        "/api/chat",
        headers={"Authorization": f"Bearer {trial.json()['token']}"},
        json={
            "message": "The channel cover is weeping after a thermal cycle. What should I consider, including the MDMT?",
            "mode": "troubleshoot",
        },
    )
    assert anonymous.status_code == 200, anonymous.text
    anon_docs = " ".join(item["source_document"] for item in anonymous.json()["citations"])
    assert "Demo knowledge" in anon_docs
