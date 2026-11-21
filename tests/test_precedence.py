"""Precedence follows the project hierarchy, including when the vendor number is higher."""

from types import SimpleNamespace

from app.db import session_scope
from app.rag.precedence import compare_claims
from app.seed.bootstrap import seed_demo
from tests.conftest import login_admin


def _claim(**kwargs):
    base = dict(
        parameter="tube_design_pressure",
        value="",
        doc_type="project_spec",
        title="",
        filename="",
        revision="A",
        edition="",
        clause="4.2",
        page="1",
        statement_class="explicit_requirement",
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_higher_vendor_value_does_not_govern():
    claims = [
        _claim(title="SP-2201", filename="SP-2201.pdf", revision="C", value="12 barg", doc_type="project_spec"),
        _claim(title="DS-HX-2201", filename="DS-HX-2201.xlsx", revision="B", value="12 barg", doc_type="datasheet", statement_class="informative"),
        _claim(
            title="VD-HX-2201",
            filename="VD-HX-2201.pdf",
            revision="A",
            value="14 barg",
            doc_type="vendor",
            statement_class="vendor_offer",
        ),
    ]
    found = compare_claims(claims, "Mechanical requirements follow the specification.")
    conflict = found[0]
    assert conflict.governing is not None
    assert conflict.governing.value == "12 barg"
    assert conflict.governing.document == "SP-2201"
    vendor = next(item for item in conflict.observed if item.doc_type == "vendor")
    assert vendor.role == "deviation"
    assert vendor.value == "14 barg"
    assert "most restrictive" in conflict.implication
    assert "does not" in conflict.implication


def test_lower_datasheet_pressure_stays_a_conflict():
    claims = [
        _claim(parameter="shell_design_pressure", title="SP-2201", value="18 barg", doc_type="project_spec", revision="C"),
        _claim(parameter="shell_design_pressure", title="DS-HX-2201", value="16 barg", doc_type="datasheet", revision="B", statement_class="informative"),
        _claim(parameter="shell_design_pressure", title="VD-HX-2201", value="15 barg", doc_type="vendor", revision="A", statement_class="vendor_offer"),
    ]
    conflict = compare_claims(claims)[0]
    assert conflict.status == "conflict"
    assert conflict.governing.value == "18 barg"
    assert conflict.governing.document == "SP-2201"
    roles = {item.document: item.role for item in conflict.observed}
    assert roles["DS-HX-2201"] == "conflict"
    assert roles["VD-HX-2201"] == "deviation"


def test_folder_role_outranks_vendor_and_general_is_baseline():
    claims = [
        _claim(title="Vendor offer", value="14 barg", doc_type="vendor", folder_role="vendor"),
        _claim(title="Owner spec", value="12 barg", doc_type="upload", folder_role="owner"),
        _claim(title="General code", value="10 barg", doc_type="reference", folder_role="general"),
    ]
    conflict = compare_claims(claims, role_order=["consultant", "owner", "third_party", "vendor", "general"])[0]
    assert conflict.governing is not None
    assert conflict.governing.document == "Owner spec"
    assert conflict.governing.folder_role == "owner"
    general = next(item for item in conflict.observed if item.folder_role == "general")
    assert general.role == "conflict"
    vendor = next(item for item in conflict.observed if item.folder_role == "vendor")
    assert vendor.role == "deviation"


def test_demo_compare_reports_governing_specification(client):
    with session_scope() as db:
        seed_demo(db)
    admin = login_admin(client)
    project = next(
        item for item in client.get("/api/projects", headers=admin).json()["projects"] if item["code"] == "HX-2201"
    )
    response = client.post(
        "/api/chat",
        headers=admin,
        json={
            "project_id": project["id"],
            "message": "Compare tube-side design pressure. The vendor offer is higher. Which value governs?",
            "mode": "compare",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    match = next(item for item in body["conflicts"] if item["parameter"] == "tube_design_pressure")
    assert match["governing"]["value"] == "12 barg"
    assert "SP-2201" in match["governing"]["document"]
    vendor = next(item for item in match["observed"] if item["doc_type"] == "vendor")
    assert vendor["value"] == "14 barg"
    assert vendor["role"] == "deviation"
