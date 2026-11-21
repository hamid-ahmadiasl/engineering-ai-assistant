"""Context-aware precedence. The project hierarchy decides, not the stricter number."""

from __future__ import annotations

from dataclasses import dataclass, field

# Mechanical values are governed by the project specification.
# Process values are governed by the datasheet.
# Vendor offers never govern. Global notes never govern a project number.
MECHANICAL = {
    "shell_design_pressure",
    "tube_design_pressure",
    "shell_design_temperature",
    "tube_design_temperature",
    "mdmt",
    "corrosion_allowance_shell",
    "corrosion_allowance_tube",
    "tema_type",
    "shell_material",
    "tube_material",
    "code_edition",
}
PROCESS = {
    "operating_pressure_shell",
    "operating_pressure_tube",
    "operating_temperature",
    "flow_rate",
    "fouling_factor",
}

DOC_RANK_MECHANICAL = {
    "project_spec": 0,
    "datasheet": 1,
    "requisition": 1,
    "vendor": 2,
    "standard_note": 3,
    "handbook": 4,
}
DOC_RANK_PROCESS = {
    "datasheet": 0,
    "project_spec": 1,
    "requisition": 1,
    "vendor": 2,
    "standard_note": 3,
    "handbook": 4,
}

LABELS = {
    "shell_design_pressure": "Shell-side design pressure",
    "tube_design_pressure": "Tube-side design pressure",
    "shell_design_temperature": "Shell-side design temperature",
    "tube_design_temperature": "Tube-side design temperature",
    "mdmt": "Minimum design metal temperature",
    "corrosion_allowance_shell": "Shell-side corrosion allowance",
    "corrosion_allowance_tube": "Tube-side corrosion allowance",
    "tema_type": "TEMA type",
    "shell_material": "Shell material",
    "tube_material": "Tube material",
    "code_edition": "Applicable code edition",
    "operating_pressure_shell": "Shell-side operating pressure",
    "operating_pressure_tube": "Tube-side operating pressure",
    "operating_temperature": "Operating temperature",
    "flow_rate": "Mass flow",
    "fouling_factor": "Fouling factor",
}


def revision_rank(revision: str) -> int:
    text = (revision or "").strip()
    if text.isdigit():
        return int(text)
    if len(text) == 1 and text.isalpha():
        return ord(text.upper())
    return 0


def _norm(value: str) -> str:
    return " ".join((value or "").lower().replace("°", " ").split())


@dataclass
class Observed:
    value: str
    document: str
    filename: str
    doc_type: str
    revision: str
    edition: str
    clause: str
    page: str
    statement_class: str
    role: str


@dataclass
class Conflict:
    parameter: str
    label: str
    status: str
    governing: Observed | None
    observed: list[Observed] = field(default_factory=list)
    implication: str = ""
    why: str = ""

    def as_dict(self) -> dict:
        def obs(item: Observed | None) -> dict | None:
            if item is None:
                return None
            return {
                "value": item.value,
                "document": item.document,
                "source_file": item.filename,
                "doc_type": item.doc_type,
                "revision": item.revision,
                "edition": item.edition,
                "clause": item.clause,
                "page": item.page,
                "statement_class": item.statement_class,
                "role": item.role,
            }

        return {
            "parameter": self.parameter,
            "label": self.label,
            "status": self.status,
            "governing": obs(self.governing),
            "observed": [obs(item) for item in self.observed],
            "implication": self.implication,
            "why": self.why,
        }


def _rank(doc_type: str, parameter: str) -> int:
    table = DOC_RANK_PROCESS if parameter in PROCESS else DOC_RANK_MECHANICAL
    return table.get(doc_type, 9)


def _family(parameter: str) -> str:
    if parameter in PROCESS:
        return "process"
    return "mechanical"


def compare_claims(claims: list, rules_note: str = "") -> list[Conflict]:
    grouped: dict[str, list] = {}
    for claim in claims:
        grouped.setdefault(claim.parameter, []).append(claim)

    results: list[Conflict] = []
    for parameter, items in grouped.items():
        ordered = sorted(
            items,
            key=lambda c: (_rank(c.doc_type, parameter), -revision_rank(c.revision), c.title),
        )
        # Prefer a real project document over a note when ranks tie.
        governing_claim = ordered[0]
        values = {_norm(c.value) for c in items}
        aligned = len(values) == 1
        observed: list[Observed] = []
        for claim in items:
            same = _norm(claim.value) == _norm(governing_claim.value)
            if claim is governing_claim:
                role = "governing"
            elif same:
                role = "aligned"
            elif claim.doc_type == "vendor":
                role = "deviation"
            else:
                role = "conflict"
            observed.append(
                Observed(
                    value=claim.value,
                    document=claim.title,
                    filename=claim.filename,
                    doc_type=claim.doc_type,
                    revision=claim.revision,
                    edition=claim.edition,
                    clause=claim.clause,
                    page=claim.page,
                    statement_class=claim.statement_class,
                    role=role,
                )
            )
        governing = next(item for item in observed if item.role == "governing")
        status = "aligned" if aligned else ("deviation" if all(i.role in {"governing", "aligned", "deviation"} for i in observed) and any(i.role == "deviation" for i in observed) and not any(i.role == "conflict" for i in observed) else "conflict")
        if aligned:
            status = "aligned"
        elif any(i.role == "conflict" for i in observed):
            status = "conflict"
        else:
            status = "deviation"

        why, implication = _explain(parameter, governing, observed, status)
        if rules_note and status != "aligned":
            implication = implication + " Project hierarchy: " + rules_note
        results.append(
            Conflict(
                parameter=parameter,
                label=LABELS.get(parameter, parameter.replace("_", " ")),
                status=status,
                governing=governing,
                observed=observed,
                implication=implication,
                why=why,
            )
        )
    rank = {"conflict": 0, "deviation": 1, "aligned": 2}
    results.sort(key=lambda item: (rank.get(item.status, 9), item.label))
    return results


def _explain(parameter: str, governing: Observed, observed: list[Observed], status: str) -> tuple[str, str]:
    family = _family(parameter)
    others = [item for item in observed if item.role != "governing"]
    other_text = "; ".join(f"{item.document} rev {item.revision or '—'} states {item.value}" for item in others)
    if family == "process":
        why = (
            f"{governing.document} rev {governing.revision or '—'} governs {LABELS.get(parameter, parameter)} "
            "because this project's hierarchy assigns process conditions to the datasheet."
        )
    else:
        why = (
            f"{governing.document} rev {governing.revision or '—'} governs {LABELS.get(parameter, parameter)} "
            "because mechanical requirements stay with the project specification. "
            "A higher or lower value in a datasheet or vendor offer does not replace it."
        )
    if status == "aligned":
        return why, f"The retrieved sources agree on {governing.value}. The governing statement remains {governing.document}."
    direction_bits = []
    for item in others:
        if _norm(item.value) == _norm(governing.value):
            continue
        direction_bits.append(
            f"{item.document} ({item.doc_type}) gives {item.value}, while the governing value is {governing.value}."
        )
    implication = (
        "This is a conflict for the engineer to resolve. The assistant does not select a design and does not "
        "treat the most restrictive number as the winner. "
        + " ".join(direction_bits)
    )
    if other_text:
        implication += f" Sources compared: {other_text}."
    if any(item.doc_type == "vendor" and item.role == "deviation" for item in observed):
        implication += (
            " The vendor document describes the offer. It becomes binding only after an approved deviation."
        )
    return why, implication.strip()


def named_conflicts(question: str, conflicts: list[Conflict]) -> list[Conflict]:
    """Conflicts whose parameter is actually named in the question."""
    text = question.lower()
    aliases = {
        "shell_design_pressure": ["shell-side design pressure", "shell design pressure"],
        "tube_design_pressure": ["tube-side design pressure", "tube design pressure"],
        "corrosion_allowance_shell": ["corrosion allowance"],
        "corrosion_allowance_tube": ["corrosion allowance", "tube-side corrosion"],
        "tema_type": ["tema"],
        "mdmt": ["mdmt", "minimum design metal"],
        "code_edition": ["asme", "code edition", "division 1"],
        "shell_material": ["shell material", "sa-516"],
        "tube_material": ["tube material", "sa-179"],
        "shell_design_temperature": ["shell-side design temperature", "design temperature"],
        "tube_design_temperature": ["tube-side design temperature"],
    }
    chosen = []
    for conflict in conflicts:
        keys = aliases.get(conflict.parameter, [conflict.parameter.replace("_", " ")])
        if any(key in text for key in keys):
            chosen.append(conflict)
    return chosen


def filter_parameters(question: str, conflicts: list[Conflict]) -> list[Conflict]:
    text = question.lower()
    aliases = {
        "shell_design_pressure": ["shell-side design pressure", "shell design pressure", "design pressure"],
        "tube_design_pressure": ["tube-side design pressure", "tube design pressure"],
        "corrosion_allowance_shell": ["corrosion allowance", "shell-side corrosion"],
        "corrosion_allowance_tube": ["tube-side corrosion", "corrosion allowance"],
        "tema_type": ["tema"],
        "mdmt": ["mdmt", "minimum design metal"],
        "code_edition": ["edition", "asme", "division 1"],
        "shell_material": ["material", "sa-516"],
        "tube_material": ["tube material", "sa-179"],
    }
    chosen = []
    for conflict in conflicts:
        keys = aliases.get(conflict.parameter, [conflict.parameter.replace("_", " ")])
        if any(key in text for key in keys):
            chosen.append(conflict)
    if chosen:
        return chosen
    # A broad comparison asks for every disagreement, not every aligned row.
    disagreements = [c for c in conflicts if c.status != "aligned"]
    return disagreements or conflicts
