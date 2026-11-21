"""Persian questions find the English source, and the answer follows the question language."""

import json

from app.db import session_scope
from app.rag.retrieve import lexical_search
from app.seed.bootstrap import seed_demo
from app.textnorm import normalize_persian
from tests.conftest import login_admin


def test_arabic_letters_and_zwnj_fold_to_persian():
    raw = "طراحي\u200cكاف مي\u200cشود ۱۲ barg"
    folded = normalize_persian(raw)
    assert "طراحی" in folded
    assert "کاف" in folded
    assert "\u200c" not in folded
    assert "12 barg" in folded
    assert "۱۲" not in folded


def test_uploaded_persian_text_is_searchable_after_normalization(client, tmp_path):
    admin = login_admin(client)
    project = client.post(
        "/api/projects",
        headers=admin,
        json={"name": "Persian upload", "code": "FA-1", "description": ""},
    ).json()
    # Arabic kaf and yeh, plus a ZWNJ, standing in for a scanned specification note.
    body = "۴.۲ فشار طراحي\n\nفشار طراحي سمت پوسته بايد ۱۸ barg باشد. كاف مي\u200cشود.\n"
    path = tmp_path / "note-fa.txt"
    path.write_text(body, encoding="utf-8")
    with path.open("rb") as handle:
        uploaded = client.post(
            f"/api/projects/{project['id']}/documents",
            headers=admin,
            files={"file": ("note-fa.txt", handle, "text/plain")},
            data={"title": "یادداشت فارسی", "doc_type": "project_spec", "revision": "A"},
        )
    assert uploaded.status_code == 200, uploaded.text
    with session_scope() as db:
        hits = lexical_search(db, "فشار طراحی سمت پوسته", scope="project", project_id=project["id"], k=4)
    assert hits
    assert "18 barg" in hits[0].text
    assert "ي" not in hits[0].text
    assert "ك" not in hits[0].text


def test_persian_question_cites_the_english_specification(client):
    with session_scope() as db:
        seed_demo(db)
    admin = login_admin(client)
    project = next(item for item in client.get("/api/projects", headers=admin).json()["projects"] if item["code"] == "HX-2201")
    response = client.post(
        "/api/chat",
        headers={**admin, "X-Lang": "fa"},
        json={
            "project_id": project["id"],
            "message": "فشار طراحی سمت پوسته برای HX-2201 چقدر است و کدام سند حاکم است؟",
            "mode": "qa",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer_language"] == "fa"
    prose = " ".join(block["text"] for block in body["blocks"])
    assert any("\u0600" <= ch <= "\u06ff" for ch in prose)
    matched = [
        citation
        for citation in body["citations"]
        if "SP-2201" in citation["source_document"] and citation["clause"] == "4.2"
    ]
    assert matched
    assert "18 barg" in matched[0]["excerpt"]
    assert matched[0]["revision"] == "C"
    assert matched[0]["statement_label"] == "الزام صریح"
    assert "18 barg" in prose


def test_mocked_llm_follows_the_question_language(client, monkeypatch):
    with session_scope() as db:
        seed_demo(db)

    def fake_complete(system, user):
        assert "Persian" in system
        question = json.loads(user)["question"]
        if "فشار" in question:
            return json.dumps(
                {
                    "blocks": [
                        {
                            "kind": "explicit_requirement",
                            "text": "فشار طراحی سمت پوسته در سند برابر 18 barg است.",
                            "citation_ids": ["C1"],
                        }
                    ],
                    "limitations": ["این یادداشت نمایشی است."],
                }
            )
        return json.dumps(
            {
                "blocks": [
                    {
                        "kind": "explicit_requirement",
                        "text": "The shell-side design pressure is 18 barg.",
                        "citation_ids": ["C1"],
                    }
                ],
                "limitations": [],
            }
        )

    monkeypatch.setattr("app.rag.answer.complete", fake_complete)
    admin = login_admin(client)
    project = next(item for item in client.get("/api/projects", headers=admin).json()["projects"] if item["code"] == "HX-2201")

    persian = client.post(
        "/api/chat",
        headers=admin,
        json={
            "project_id": project["id"],
            "message": "فشار طراحی سمت پوسته HX-2201 را بگو",
            "mode": "qa",
        },
    )
    assert persian.status_code == 200, persian.text
    fa = persian.json()
    assert fa["generator"] == "llm"
    assert fa["answer_language"] == "fa"
    assert "فشار" in fa["blocks"][0]["text"]
    assert "18 barg" in fa["blocks"][0]["text"]
    assert any("SP-2201" in citation["source_document"] for citation in fa["citations"])

    english = client.post(
        "/api/chat",
        headers=admin,
        json={
            "project_id": project["id"],
            "message": "What is the shell-side design pressure for HX-2201?",
            "mode": "qa",
        },
    )
    assert english.status_code == 200, english.text
    en = english.json()
    assert en["answer_language"] == "en"
    assert en["generator"] == "llm"
    assert "18 barg" in en["blocks"][0]["text"]
    assert not any("\u0600" <= ch <= "\u06ff" for ch in en["blocks"][0]["text"])
