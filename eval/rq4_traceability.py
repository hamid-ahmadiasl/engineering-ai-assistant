#!/usr/bin/env python3
"""RQ4 check: answers cite the governing source, clause, and revision.

Run from the repository root:

    EMBEDDING_PROVIDER=hash LLM_PROVIDER=none python eval/rq4_traceability.py

The script builds a temporary database, ingests the demo corpus, and scores
each held-out question. It does not call an external model.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="eai-rq4-")
    os.environ["DATA_DIR"] = tmp
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp) / 'rq4.db'}"
    os.environ["EMBEDDING_PROVIDER"] = os.environ.get("EMBEDDING_PROVIDER", "hash")
    os.environ["LLM_PROVIDER"] = "none"
    os.environ["SEED_ON_STARTUP"] = "false"
    os.environ["ANONYMIZED_TELEMETRY"] = "FALSE"

    from sqlalchemy import select

    from app.db import init_db, reset_engine, session_scope
    from app.models import Project
    from app.rag.orchestrate import run_query
    from app.seed.bootstrap import seed_demo
    from app.stores.vector_store import reset_store

    reset_engine()
    reset_store()
    init_db()
    with session_scope() as db:
        seed_demo(db)

    cases = json.loads((Path(__file__).parent / "cases.json").read_text(encoding="utf-8"))
    passed = 0
    for case in cases:
        with session_scope() as db:
            project = db.scalar(select(Project).where(Project.code == case["project"]))
            result = run_query(db, project=project, message=case["question"], mode=case["mode"])
        ok, notes = _score(case, result)
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {case['id']}")
        for note in notes:
            print(f"       {note}")
        passed += int(ok)
    print(f"\n{passed}/{len(cases)} traceability cases passed")
    return 0 if passed == len(cases) else 1


def _score(case: dict, result: dict) -> tuple[bool, list[str]]:
    notes: list[str] = []
    citations = result.get("citations") or []
    excerpts = "\n".join(citation.get("excerpt", "") for citation in citations)
    documents = "\n".join(citation.get("source_document", "") for citation in citations)
    ok = True

    def fail(message: str) -> None:
        nonlocal ok
        ok = False
        notes.append(message)

    if case.get("expect_document"):
        matched = [
            citation
            for citation in citations
            if case["expect_document"] in citation.get("source_document", "")
            and (not case.get("expect_clause") or citation.get("clause") == case["expect_clause"])
        ]
        if not matched:
            fail(
                f"missing citation for {case['expect_document']} clause {case.get('expect_clause', 'any')}"
            )
        else:
            citation = matched[0]
            if case.get("expect_revision") and not any(item.get("revision") == case["expect_revision"] for item in matched):
                fail(f"revision {citation.get('revision')!r} != {case['expect_revision']!r}")
            if case.get("expect_excerpt") and not any(case["expect_excerpt"] in item.get("excerpt", "") for item in matched):
                fail(f"excerpt missing {case['expect_excerpt']!r}")
            incomplete = [item["citation_id"] for item in matched if item.get("trace_missing")]
            if incomplete:
                fail(f"citation trace incomplete: {incomplete}")
            else:
                notes.append(
                    f"cited {citation['source_document']} clause {citation['clause']} "
                    f"page {citation['page']} rev {citation['revision'] or '—'} "
                    f"({citation['statement_class']})"
                )
    if case.get("expect_conflict_parameter"):
        conflict = next(
            (item for item in result.get("conflicts") or [] if item["parameter"] == case["expect_conflict_parameter"]),
            None,
        )
        if conflict is None:
            fail(f"no conflict for {case['expect_conflict_parameter']}")
        else:
            governing = (conflict.get("governing") or {}).get("value")
            if case.get("expect_governing") and governing != case["expect_governing"]:
                fail(f"governing {governing!r} != {case['expect_governing']!r}")
            if case.get("forbid_governing") and governing == case["forbid_governing"]:
                fail(f"governing value was the forbidden {governing!r}")
            else:
                notes.append(f"governing {conflict['label']} = {governing} ({conflict['status']})")
    if case.get("forbid_excerpt") and case["forbid_excerpt"] in excerpts:
        fail(f"forbidden text appeared in an excerpt: {case['forbid_excerpt']}")
    if case.get("forbid_document") and case["forbid_document"] in documents:
        fail(f"forbidden document cited: {case['forbid_document']}")
    if case.get("expect_language") == "fa":
        prose = _blocks(result)
        if not any("\u0600" <= ch <= "\u06ff" for ch in prose):
            fail("answer text has no Persian letters")
        else:
            notes.append(f"answer language {result.get('answer_language')}")
        if case.get("expect_excerpt") and case["expect_excerpt"] not in excerpts:
            fail(f"Persian answer lost the source value {case['expect_excerpt']!r}")
    if case.get("expect_excerpt") and not case.get("expect_document") and case["expect_excerpt"] not in excerpts:
        # Troubleshooting may mention MDMT in the specification citation or the note.
        if case["expect_excerpt"] not in excerpts and case["expect_excerpt"] not in _blocks(result):
            fail(f"expected trace of {case['expect_excerpt']!r}")
    if ok and not notes:
        notes.append("constraints held")
    return ok, notes


def _blocks(result: dict) -> str:
    return "\n".join(block.get("text", "") for block in result.get("blocks") or [])


if __name__ == "__main__":
    raise SystemExit(main())
