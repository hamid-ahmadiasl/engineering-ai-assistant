"""Original demo corpus. These notes are not the text of any code or standard."""

from __future__ import annotations

CORPUS_LABEL = "DEMO CORPUS — original note, not a licensed standard"

PRECEDENCE = {
    "summary": (
        "Mechanical requirements follow specification SP-2201. Process conditions follow datasheet "
        "DS-HX-2201. The code edition named in SP-2201 applies. A vendor offer does not govern."
    ),
    "order": [
        "Site law and regulation",
        "Project specification, latest revision, for mechanical requirements",
        "Datasheet, latest revision, for process conditions only",
        "Code editions named in the specification",
        "Vendor documents, which remain offers until a deviation is approved",
    ],
}


def _lines(title: str, banner: str, sections: list[tuple[str, str, str]]) -> tuple[str, dict]:
    """sections: (clause, heading, body)."""
    parts = [
        title,
        banner,
        "This file is original text written for the prototype. It is not a copy of ASME, API, TEMA, ASTM, ISO, or EN.",
    ]
    meta_sections = {}
    for clause, heading, body, statement in sections:
        parts.append(f"{clause} {heading}")
        parts.append(body.strip())
        meta_sections[clause] = {"statement_class": statement}
    return "\n\n".join(parts), meta_sections


def global_notes() -> list[dict]:
    pv_text, pv_sections = _lines(
        "Demo knowledge note — pressure equipment concepts",
        CORPUS_LABEL,
        [
            (
                "1",
                "Purpose of this note",
                "This note explains words an engineer will meet on a pressure-equipment project: design pressure, "
                "maximum allowable working pressure, corrosion allowance, and minimum design metal temperature. "
                "It is background for the prototype. The requirement that applies on a project is the edition named "
                "in that project's specification, read from a licensed copy.",
                "informative",
            ),
            (
                "2",
                "Design pressure and MAWP",
                "Design pressure is the pressure the purchaser states for the mechanical design, together with the "
                "matching design temperature. Maximum allowable working pressure is a result of the finished design "
                "and the code rules, not a substitute for the purchaser's design pressure. A knowledge note must not "
                "be used to calculate either value. Relief, hydrotest, and nozzle ratings are checked by the engineer "
                "against the licensed edition.",
                "informative",
            ),
            (
                "3",
                "Corrosion allowance",
                "Corrosion allowance is extra thickness the purchaser specifies so that corrosion or erosion can "
                "occur without immediately dropping the pressure part below its required thickness. The number is a "
                "project decision. It is not chosen by comparing vendor offers and keeping the largest or the smallest.",
                "engineering_recommendation",
            ),
            (
                "4",
                "Minimum design metal temperature",
                "The minimum design metal temperature (MDMT) is the lowest metal temperature the design is intended "
                "to cover. Operating at a colder metal temperature is a brittle-fracture concern and is an operating "
                "limit, not a software output. Impact-test exemptions live in the licensed code and are not restated here.",
                "engineering_recommendation",
            ),
            (
                "5",
                "What this note is not",
                "This note does not contain design formulas, allowable stresses, joint efficiencies, or acceptance "
                "criteria. Do not cite it as ASME BPVC Section VIII. Load the licensed edition into the global "
                "knowledge base when your organisation is entitled to use it.",
                "informative",
            ),
        ],
    )
    tema_text, tema_sections = _lines(
        "Demo knowledge note — TEMA type letters",
        CORPUS_LABEL,
        [
            (
                "1",
                "How the three letters are read",
                "A TEMA type is three letters. The first describes the front-end head, the second the shell, and the "
                "third the rear end. This note records the letter meanings used in teaching and in project language. "
                "The dimensional and tolerance requirements stay in the licensed TEMA edition named by the project.",
                "informative",
            ),
            (
                "2",
                "Letters used on HX type calls",
                "A means a channel with a removable cover. B means a bonnet, an integral cover. E means a one-pass shell. "
                "S means a floating head with a backing device (split ring). U means a U-tube bundle. "
                "AES therefore means a removable-cover channel, a one-pass shell, and a split-ring floating head: the "
                "bundle can be pulled and the shell side can be inspected. BEU means a bonnet, a one-pass shell, and a "
                "U-tube bundle: there is no floating head, and the shell side cannot be cleaned mechanically around the U-bends.",
                "informative",
            ),
            (
                "3",
                "How to use the letters on a project",
                "The project specification states the type the purchaser requires. A vendor may offer a different type. "
                "That offer is a deviation. It is not accepted because it is cheaper, and it is not rejected by an "
                "automatic rule. The engineer records the effect on cleaning, bundle removal, thermal expansion, and plot.",
                "engineering_recommendation",
            ),
        ],
    )
    api_text, api_sections = _lines(
        "Demo knowledge note — roles of the equipment standards",
        CORPUS_LABEL,
        [
            (
                "1",
                "Three documents do different jobs",
                "On a refinery shell-and-tube exchanger the engineer typically meets three named publications plus "
                "the project specification. ASME Section VIII is the pressure-boundary code. TEMA describes the "
                "exchanger configuration language and its own mechanical practice. API 660 is an equipment standard "
                "for shell-and-tube exchangers in petroleum and petrochemical service and points back to the code and "
                "to TEMA. This note only separates those roles.",
                "informative",
            ),
            (
                "2",
                "Edition named by the project",
                "A later edition sitting in a library does not replace the edition the specification names. An older "
                "edition does not apply either, unless the specification says so. Explanatory notes, including this one, "
                "are not an edition of the code.",
                "engineering_recommendation",
            ),
            (
                "3",
                "Air cooled exchangers",
                "API 661 is the usual equipment standard for air-cooled exchangers. It is a different document from "
                "API 660. Do not move requirements from one to the other without the project saying so.",
                "informative",
            ),
        ],
    )
    trouble_text, trouble_sections = _lines(
        "Demo knowledge note — exchanger troubleshooting considerations",
        CORPUS_LABEL,
        [
            (
                "1",
                "How to use this note",
                "These are field considerations for a shell-and-tube exchanger. They are not a diagnosis and they are "
                "not a repair procedure. Start from the project design pressure, design temperature, MDMT, and the "
                "datasheet operating window before proposing any change.",
                "engineering_recommendation",
            ),
            (
                "2",
                "Channel cover weep after a thermal cycle",
                "A weep at the channel cover after a temperature cycle can come from gasket relaxation, uneven bolt "
                "load, a damaged facing, or differential movement between the cover and the channel. Considerations: "
                "confirm the metal temperature stayed inside the design range and above the MDMT; inspect the gasket "
                "style against the requisition; do not increase bolt load past the flange design without a check. "
                "Limitations: this note cannot see the joint, the gasket material, or the last assembly record.",
                "engineering_recommendation",
            ),
            (
                "3",
                "Rising tube side pressure drop",
                "A rise against the datasheet clean duty can be fouling, blocked tubes, or debris at the pass partition. "
                "Consider the fouling factor on the datasheet and whether the fluid matches the datasheet. Do not "
                "retube or change baffles from this note alone.",
                "engineering_recommendation",
            ),
            (
                "4",
                "Suspected tube leak",
                "A tube leak mixes the two sides and can move the operating pressure toward the higher side. "
                "Consider isolation, the relative design pressures, and whether the leak could overpressure the lower "
                "side. A test method is an engineering decision. This note does not authorise continued operation.",
                "engineering_recommendation",
            ),
            (
                "5",
                "Flow induced vibration concern",
                "If the shell side is noisy or tubes have failed at baffles, span, baffle spacing, and crossflow "
                "velocity are the usual considerations. Any check against TEMA methods has to be done with the licensed "
                "edition. This note has no formulas.",
                "engineering_recommendation",
            ),
        ],
    )
    return [
        {
            "external_id": "DEMO-NOTE-PV",
            "filename": "DEMO-NOTE-PV.txt",
            "title": "Demo knowledge note — pressure equipment concepts",
            "doc_type": "standard_note",
            "revision": "1",
            "edition": "demo-2026",
            "hierarchy_level": 6,
            "corpus_label": CORPUS_LABEL,
            "statement_class_default": "informative",
            "text": pv_text,
            "sections": pv_sections,
            "claims": [],
        },
        {
            "external_id": "DEMO-NOTE-TEMA",
            "filename": "DEMO-NOTE-TEMA.txt",
            "title": "Demo knowledge note — TEMA type letters",
            "doc_type": "standard_note",
            "revision": "1",
            "edition": "demo-2026",
            "hierarchy_level": 6,
            "corpus_label": CORPUS_LABEL,
            "statement_class_default": "informative",
            "text": tema_text,
            "sections": tema_sections,
            "claims": [],
        },
        {
            "external_id": "DEMO-NOTE-API660",
            "filename": "DEMO-NOTE-API660.txt",
            "title": "Demo knowledge note — roles of the equipment standards",
            "doc_type": "standard_note",
            "revision": "1",
            "edition": "demo-2026",
            "hierarchy_level": 6,
            "corpus_label": CORPUS_LABEL,
            "statement_class_default": "informative",
            "text": api_text,
            "sections": api_sections,
            "claims": [],
        },
        {
            "external_id": "DEMO-NOTE-TROUBLE",
            "filename": "DEMO-NOTE-TROUBLE.txt",
            "title": "Demo knowledge note — exchanger troubleshooting considerations",
            "doc_type": "handbook",
            "revision": "1",
            "edition": "demo-2026",
            "hierarchy_level": 6,
            "corpus_label": CORPUS_LABEL,
            "statement_class_default": "engineering_recommendation",
            "text": trouble_text,
            "sections": trouble_sections,
            "claims": [],
        },
    ]


def project_hx_documents() -> list[dict]:
    spec = """
Project specification SP-2201
DEMO PROJECT DOCUMENT — fictional specification for the prototype. Not a client deliverable.

1 Purpose
This specification states the mechanical requirements for heat exchanger HX-2201, crude preheat service, on the Northwind Stabilizer project.

1.4 Order of precedence
The following order applies to HX-2201. A value shall not be selected only because it is more restrictive or less restrictive than another value.
Level 1. Mandatory law and regulation at the site.
Level 2. This specification, latest revision. It governs the mechanical design basis, materials, code editions, corrosion allowance, TEMA configuration, and inspection.
Level 3. Datasheet DS-HX-2201, latest revision. It governs process conditions: flow, fluid, operating temperature, operating pressure, and fouling factors. If the datasheet states a mechanical design pressure, corrosion allowance, material, or TEMA type that differs from this specification, this specification remains mandatory and the difference shall be recorded as a conflict. The datasheet does not relax this specification.
Level 4. The code editions named in Section 2 of this specification. No other edition applies. Explanatory notes in the global knowledge base are not requirements.
Level 5. Vendor documents describe the offer only. A difference from Level 2, Level 3, or Level 4 is a deviation. It is not accepted unless the project records an approved deviation. A vendor value does not govern, whether it is higher or lower than the specified value.

2 Applicable editions
The pressure boundary shall conform to ASME BPVC Section VIII Division 1, Edition 2023.
The exchanger configuration shall follow TEMA, 10th edition, of the type required in Section 5.
Where this specification is silent, the supplemental equipment practice of API 660, 9th edition, applies.
These sentences name editions. They are not quotations from those publications.

3 Equipment
The tag shall be HX-2201. The service is crude against hot crude. The unit has one shell.

4.1 Process conditions
Process conditions shall be taken from datasheet DS-HX-2201 revision B. A vendor-stated operating condition shall not replace the datasheet.

4.2 Design pressure
The shell-side design pressure shall be 18 barg.
The tube-side design pressure shall be 12 barg.
Design pressure is a mechanical requirement of this specification.

4.3 Temperatures
The shell-side design temperature shall be 180 C.
The tube-side design temperature shall be 160 C.
The minimum design metal temperature shall be -20 C. The exchanger shall not be operated at a metal temperature below the MDMT.

4.4 Corrosion allowance
A corrosion allowance of 3.0 mm shall be provided on shell-side wetted carbon-steel surfaces.
A corrosion allowance of 3.0 mm shall be provided on tube-side wetted carbon-steel surfaces.

5 Configuration
The exchanger shall be TEMA type AES.
A U-tube configuration shall not be substituted without an approved deviation.

6 Materials
The shell shall be carbon steel SA-516 Grade 70.
The tubes shall be SA-179.
Wetted carbon steel shall be suitable for the project sour-service requisition. This demo text does not reproduce that requisition.

7 Deviations
The vendor shall list every difference from this specification. Silence is not acceptance.
""".strip()

    vendor = """
Vendor offer VD-HX-2201
DEMO PROJECT DOCUMENT — fictional vendor offer. It does not amend SP-2201.

1 Offer status
This offer describes the equipment the vendor proposes for tag HX-2201. It is not an approved deviation. It does not change project specification SP-2201 revision C.

2 Exceptions
The vendor offers TEMA type BEU in place of the specified AES configuration.
The vendor offers a shell-side design pressure of 15 barg.
The vendor offers a tube-side design pressure of 14 barg.
The vendor offers a corrosion allowance of 1.6 mm on shell-side and tube-side carbon steel.
The vendor offers shell material SA-516 Grade 70 and tubes SA-179.
Each of these items is an exception to SP-2201 revision C until the project approves it in writing.

3 Operating window
The vendor has copied operating temperatures from the enquiry. Those copies do not replace datasheet DS-HX-2201 revision B.
""".strip()

    spec_sections = {
        "1": {"statement_class": "informative"},
        "1.4": {"statement_class": "explicit_requirement"},
        "2": {"statement_class": "explicit_requirement"},
        "3": {"statement_class": "explicit_requirement"},
        "4.1": {"statement_class": "explicit_requirement"},
        "4.2": {"statement_class": "explicit_requirement"},
        "4.3": {"statement_class": "explicit_requirement"},
        "4.4": {"statement_class": "explicit_requirement"},
        "5": {"statement_class": "explicit_requirement"},
        "6": {"statement_class": "explicit_requirement"},
        "7": {"statement_class": "explicit_requirement"},
    }
    return [
        {
            "external_id": "SP-2201",
            "filename": "SP-2201.pdf",
            "title": "SP-2201 Project specification for HX-2201",
            "doc_type": "project_spec",
            "revision": "C",
            "edition": "",
            "hierarchy_level": 2,
            "corpus_label": "DEMO PROJECT",
            "statement_class_default": "explicit_requirement",
            "text": spec,
            "sections": spec_sections,
            "render": "pdf",
            "claims": [
                {"parameter": "shell_design_pressure", "value": "18 barg", "unit": "barg", "side": "shell", "clause": "4.2", "statement_class": "explicit_requirement"},
                {"parameter": "tube_design_pressure", "value": "12 barg", "unit": "barg", "side": "tube", "clause": "4.2", "statement_class": "explicit_requirement"},
                {"parameter": "shell_design_temperature", "value": "180 C", "unit": "C", "side": "shell", "clause": "4.3", "statement_class": "explicit_requirement"},
                {"parameter": "tube_design_temperature", "value": "160 C", "unit": "C", "side": "tube", "clause": "4.3", "statement_class": "explicit_requirement"},
                {"parameter": "mdmt", "value": "-20 C", "unit": "C", "clause": "4.3", "statement_class": "explicit_requirement"},
                {"parameter": "corrosion_allowance_shell", "value": "3.0 mm", "unit": "mm", "side": "shell", "clause": "4.4", "statement_class": "explicit_requirement"},
                {"parameter": "corrosion_allowance_tube", "value": "3.0 mm", "unit": "mm", "side": "tube", "clause": "4.4", "statement_class": "explicit_requirement"},
                {"parameter": "tema_type", "value": "AES", "clause": "5", "statement_class": "explicit_requirement"},
                {"parameter": "shell_material", "value": "SA-516 Grade 70", "clause": "6", "statement_class": "explicit_requirement"},
                {"parameter": "tube_material", "value": "SA-179", "clause": "6", "statement_class": "explicit_requirement"},
                {"parameter": "code_edition", "value": "ASME VIII Division 1 Edition 2023", "clause": "2", "statement_class": "explicit_requirement"},
            ],
        },
        {
            "external_id": "DS-HX-2201",
            "filename": "DS-HX-2201.xlsx",
            "title": "DS-HX-2201 Equipment datasheet",
            "doc_type": "datasheet",
            "revision": "B",
            "edition": "",
            "hierarchy_level": 3,
            "corpus_label": "DEMO PROJECT",
            "statement_class_default": "informative",
            "render": "xlsx",
            "rows": [
                ("Cover", ["Field", "Value", "Note"]),
                ("Cover", ["Document", "DS-HX-2201", "Equipment datasheet"]),
                ("Cover", ["Revision", "B", "Latest process issue"]),
                ("Cover", ["Tag", "HX-2201", "Crude preheat"]),
                ("Cover", ["Hierarchy", "Process data govern operating conditions", "Mechanical requirements remain in SP-2201"]),
                ("Process", ["Parameter", "Shell", "Tube", "Unit"]),
                ("Process", ["Fluid", "Crude", "Hot crude", ""]),
                ("Process", ["Operating pressure", "10", "6", "barg"]),
                ("Process", ["Operating temperature in", "40", "150", "C"]),
                ("Process", ["Operating temperature out", "95", "80", "C"]),
                ("Process", ["Flow rate", "120000", "110000", "kg/h"]),
                ("Process", ["Fouling factor", "0.00035", "0.0002", "m2K/W"]),
                ("Mechanical", ["Parameter", "Value", "Unit", "Note"]),
                ("Mechanical", ["Shell design pressure", "16", "barg", "Stated on the datasheet. Does not relax SP-2201."]),
                ("Mechanical", ["Tube design pressure", "12", "barg", "Matches the specification."]),
                ("Mechanical", ["Shell design temperature", "180", "C", ""]),
                ("Mechanical", ["Tube design temperature", "160", "C", ""]),
                ("Mechanical", ["Corrosion allowance shell", "3.0", "mm", ""]),
                ("Mechanical", ["Corrosion allowance tube", "1.5", "mm", "Lower than SP-2201 clause 4.4."]),
                ("Mechanical", ["TEMA type", "AES", "", ""]),
                ("Mechanical", ["MDMT", "-20", "C", ""]),
            ],
            "sections": {
                "Operating pressure": {"statement_class": "explicit_requirement", "clause": "Operating pressure"},
                "Flow rate": {"statement_class": "explicit_requirement", "clause": "Flow rate"},
                "Fouling factor": {"statement_class": "explicit_requirement", "clause": "Fouling factor"},
                "Shell design pressure": {"statement_class": "informative", "clause": "Shell design pressure"},
                "Tube design pressure": {"statement_class": "informative", "clause": "Tube design pressure"},
                "Corrosion allowance tube": {"statement_class": "informative", "clause": "Corrosion allowance tube"},
                "Corrosion allowance shell": {"statement_class": "informative", "clause": "Corrosion allowance shell"},
                "TEMA type": {"statement_class": "informative", "clause": "TEMA type"},
                "MDMT": {"statement_class": "informative", "clause": "MDMT"},
            },
            "claims": [
                {"parameter": "shell_design_pressure", "value": "16 barg", "unit": "barg", "side": "shell", "clause": "Shell design pressure", "statement_class": "informative"},
                {"parameter": "tube_design_pressure", "value": "12 barg", "unit": "barg", "side": "tube", "clause": "Tube design pressure", "statement_class": "informative"},
                {"parameter": "corrosion_allowance_shell", "value": "3.0 mm", "unit": "mm", "side": "shell", "clause": "Corrosion allowance shell", "statement_class": "informative"},
                {"parameter": "corrosion_allowance_tube", "value": "1.5 mm", "unit": "mm", "side": "tube", "clause": "Corrosion allowance tube", "statement_class": "informative"},
                {"parameter": "tema_type", "value": "AES", "clause": "TEMA type", "statement_class": "informative"},
                {"parameter": "mdmt", "value": "-20 C", "clause": "MDMT", "statement_class": "informative"},
                {"parameter": "operating_pressure_shell", "value": "10 barg", "unit": "barg", "side": "shell", "clause": "Operating pressure", "statement_class": "explicit_requirement"},
                {"parameter": "operating_pressure_tube", "value": "6 barg", "unit": "barg", "side": "tube", "clause": "Operating pressure", "statement_class": "explicit_requirement"},
            ],
        },
        {
            "external_id": "VD-HX-2201",
            "filename": "VD-HX-2201.pdf",
            "title": "VD-HX-2201 Vendor offer for HX-2201",
            "doc_type": "vendor",
            "revision": "A",
            "edition": "",
            "hierarchy_level": 5,
            "corpus_label": "DEMO PROJECT",
            "statement_class_default": "vendor_offer",
            "text": vendor,
            "render": "pdf",
            "sections": {
                "1": {"statement_class": "vendor_offer"},
                "2": {"statement_class": "vendor_offer"},
                "3": {"statement_class": "vendor_offer"},
            },
            "claims": [
                {"parameter": "tema_type", "value": "BEU", "clause": "2", "statement_class": "vendor_offer"},
                {"parameter": "shell_design_pressure", "value": "15 barg", "unit": "barg", "side": "shell", "clause": "2", "statement_class": "vendor_offer"},
                {"parameter": "tube_design_pressure", "value": "14 barg", "unit": "barg", "side": "tube", "clause": "2", "statement_class": "vendor_offer"},
                {"parameter": "corrosion_allowance_shell", "value": "1.6 mm", "unit": "mm", "side": "shell", "clause": "2", "statement_class": "vendor_offer"},
                {"parameter": "corrosion_allowance_tube", "value": "1.6 mm", "unit": "mm", "side": "tube", "clause": "2", "statement_class": "vendor_offer"},
                {"parameter": "shell_material", "value": "SA-516 Grade 70", "clause": "2", "statement_class": "vendor_offer"},
                {"parameter": "tube_material", "value": "SA-179", "clause": "2", "statement_class": "vendor_offer"},
            ],
        },
    ]


def project_b_documents() -> list[dict]:
    text = """
Project specification SP-B
DEMO PROJECT DOCUMENT — private project used to prove store isolation.

1 Purpose
This specification applies only to tag HX-900, the amine contactor overhead condenser. It is not part of HX-2201.

2 Design pressure
The shell-side design pressure shall be 42 barg.
PROJECT-B-SENTINEL-7741 applies only to project B and must never be retrieved for HX-2201.

3 Configuration
The exchanger shall be TEMA type BEM.
""".strip()
    return [
        {
            "external_id": "SP-B",
            "filename": "SP-B.pdf",
            "title": "SP-B Project specification for HX-900",
            "doc_type": "project_spec",
            "revision": "A",
            "edition": "",
            "hierarchy_level": 2,
            "corpus_label": "DEMO PROJECT",
            "statement_class_default": "explicit_requirement",
            "text": text,
            "render": "pdf",
            "sections": {
                "1": {"statement_class": "informative"},
                "2": {"statement_class": "explicit_requirement"},
                "3": {"statement_class": "explicit_requirement"},
            },
            "claims": [
                {"parameter": "shell_design_pressure", "value": "42 barg", "unit": "barg", "side": "shell", "clause": "2", "statement_class": "explicit_requirement"},
                {"parameter": "tema_type", "value": "BEM", "clause": "3", "statement_class": "explicit_requirement"},
            ],
        }
    ]
