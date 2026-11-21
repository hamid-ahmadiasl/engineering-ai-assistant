"""Project folders filter retrieval and stay at most two levels deep."""

from tests.conftest import login_admin


def _project(client, headers):
    response = client.post(
        "/api/projects",
        headers=headers,
        json={"name": "Folder job", "code": "FLD-1", "description": ""},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _folder(client, headers, project_id, name, parent_id=None):
    response = client.post(
        f"/api/projects/{project_id}/folders",
        headers=headers,
        json={"name": name, "parent_id": parent_id},
    )
    return response


def _upload(client, headers, project_id, name, text, folder_id=""):
    return client.post(
        f"/api/projects/{project_id}/documents",
        headers=headers,
        files={"file": (name, text.encode(), "text/plain")},
        data={"title": name, "doc_type": "project_spec", "revision": "A", "folder_id": folder_id},
    )


def test_folder_filter_limits_retrieval_and_nesting(client):
    admin = login_admin(client)
    project = _project(client, admin)
    parent = _folder(client, admin, project["id"], "E-101")
    assert parent.status_code == 200, parent.text
    child = _folder(client, admin, project["id"], "Datasheets", parent.json()["id"])
    assert child.status_code == 200, child.text
    third = _folder(client, admin, project["id"], "Datasheets", child.json()["id"])
    assert third.status_code == 200, third.text
    too_deep = _folder(client, admin, project["id"], "Too deep", third.json()["id"])
    assert too_deep.status_code == 400

    inside = _upload(client, admin, project["id"], "inside.txt", "FOLDER-INSIDE design pressure is 8 barg.\n", parent.json()["id"])
    outside = _upload(client, admin, project["id"], "outside.txt", "FOLDER-OUTSIDE design pressure is 9 barg.\n", "")
    assert inside.status_code == 200, inside.text
    assert outside.status_code == 200, outside.text
    assert inside.json()["folder_id"] == parent.json()["id"]

    moved = client.patch(
        f"/api/projects/{project['id']}/documents/{outside.json()['id']}",
        headers=admin,
        json={"folder_id": child.json()["id"]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["folder_id"] == child.json()["id"]

    answer = client.post(
        "/api/chat",
        headers=admin,
        json={
            "message": "What design pressures are listed?",
            "mode": "qa",
            "scopes": {
                "global": False,
                "project_ids": [project["id"]],
                "folders": {project["id"]: [parent.json()["id"]]},
            },
        },
    )
    assert answer.status_code == 200, answer.text
    blob = " ".join(item["excerpt"] for item in answer.json()["citations"])
    assert "FOLDER-INSIDE" in blob
    assert "FOLDER-OUTSIDE" in blob  # child folder is included with its parent

    only_child = client.post(
        "/api/chat",
        headers=admin,
        json={
            "message": "What design pressures are listed?",
            "mode": "qa",
            "scopes": {
                "global": False,
                "project_ids": [project["id"]],
                "folders": {project["id"]: [child.json()["id"]]},
            },
        },
    )
    child_blob = " ".join(item["excerpt"] for item in only_child.json()["citations"])
    assert "FOLDER-OUTSIDE" in child_blob
    assert "FOLDER-INSIDE" not in child_blob

    empty = _folder(client, admin, project["id"], "Empty")
    removed = client.delete(f"/api/folders/{empty.json()['id']}", headers=admin)
    assert removed.status_code == 200, removed.text
    busy = client.delete(f"/api/folders/{parent.json()['id']}", headers=admin)
    assert busy.status_code == 409
    forced = client.delete(f"/api/folders/{parent.json()['id']}?force=true", headers=admin)
    assert forced.status_code == 200, forced.text
