# SPDX-License-Identifier: GPL-3.0-or-later
"""A Belgian workspace: governed by the RGIE (a draft profile), checked
against the Belgian norm shapes only, on a 3 × 230 V board whose breakers
have 2 or 3 poles and whose RCDs have 4. Every home and label is invented."""

from __future__ import annotations

import pytest
from rdflib import URIRef

from digitalhome_pro_edge import designs as dz
from digitalhome_pro_edge import labels as lb


@pytest.fixture
def d(tmp_path):
    return dz.Designs(dz.WorkspaceKB(tmp_path))


@pytest.fixture
def be(d):
    return d.new_workspace("As-is 2009", "BE-0000-XYZ1-01", country="BE")["workspace"]


def _governed(d, ws):
    g = d.kb.load(ws)
    return {str(o).rsplit("#", 1)[-1] for o in g.objects(None, dz.DHC.governedBy)}


def test_a_belgian_workspace_and_its_circuits_are_governed_by_the_rgie(d, be):
    b = d.add_board(be, "Board", rows=3, modules_per_row=24)["id"]
    r = d.add_rcd(be, b, "General 300 mA", rated_current=40, sensitivity_ma=300, rcd_type="A", poles=4)["id"]
    d.add_circuit(be, rcd=r, label="Lighting", circuit_type="lighting", rated_current=16, cross_section=1.5, poles=2)
    assert _governed(d, be) == {"Norm_RGIE"}
    fr = d.new_workspace("FR", "FR-00000-ABC1-01")["workspace"]
    fb = d.add_board(fr, "Board")["id"]
    fr_rcd = d.add_rcd(fr, fb, "30 mA")["id"]
    d.add_circuit(fr, rcd=fr_rcd, label="Lighting", circuit_type="lighting", rated_current=10, cross_section=1.5)
    assert _governed(d, fr) == {"Norm_NFC15100"}
    other = d.new_workspace("NL", "NL-0000-ABC1-01", country="NL")["workspace"]
    assert _governed(d, other) == set()


def test_poles_set_the_modules_and_a_three_pole_circuit_is_three_phase(d, be):
    b = d.add_board(be, "Board", rows=3, modules_per_row=24)["id"]
    r = d.add_rcd(be, b, "General 300 mA", rated_current=40, sensitivity_ma=300, rcd_type="A", poles=4)["id"]
    two = d.add_circuit(be, rcd=r, label="Sockets", circuit_type="socket", rated_current=16, cross_section=2.5, poles=2)["id"]
    hob = d.add_circuit(be, rcd=r, label="Hob", circuit_type="cooking", rated_current=25, cross_section=4, poles=3)["id"]
    board = d.design(be)["boards"][0]
    assert board["rcds"][0]["modules"] == 4 and board["rcds"][0]["poles"] == 4
    circuits = {c["id"]: c for c in board["rcds"][0]["circuits"]}
    assert circuits[two]["modules"] == 2 and circuits[hob]["modules"] == 3 and circuits[hob]["poles"] == 3
    assert board["modules_used"] == 4 + 2 + 3
    g = d.kb.load(be)
    phase = {str(g.value(c, dz.RDFS.label)): int(g.value(c, dz.DHC.phase)) for c in g.subjects(dz.RDF.type, dz.DHC.Circuit)}
    assert phase == {"Sockets": 1, "Hob": 3}
    bom = {line["description"] for line in d.bom(be)}
    assert "RCD 40 A 300 mA type A 4P" in bom and "breaker 16 A 2P" in bom and "breaker 25 A 3P" in bom
    compact = d.add_circuit(be, rcd=r, label="Compact", circuit_type="socket", rated_current=20,
                            cross_section=2.5, poles=2, modules=1)["id"]
    assert {c["id"]: c["modules"] for c in d.design(be)["boards"][0]["rcds"][0]["circuits"]}[compact] == 1
    with pytest.raises(ValueError):
        d.add_circuit(be, rcd=r, label="x", poles=2, modules=3)
    with pytest.raises(ValueError):
        d.add_circuit(be, rcd=r, label="x", poles=4)
    with pytest.raises(ValueError):
        d.add_rcd(be, b, "x", poles=3)


def test_a_belgian_report_has_the_belgian_rules_and_none_of_the_french(d, be):
    b = d.add_board(be, "Board", rows=1, modules_per_row=13)["id"]
    general = d.add_rcd(be, b, "General 300 mA", rated_current=40, sensitivity_ma=300, rcd_type="A", poles=4)["id"]
    thin = d.add_circuit(be, rcd=general, label="Sockets on 1.5", circuit_type="socket",
                         rated_current=16, cross_section=1.5, poles=2)["id"]
    washer = d.add_circuit(be, rcd=general, label="Washing machine", circuit_type="dedicated",
                           appliance="washing_machine", rated_current=16, cross_section=2.5, poles=2)["id"]
    for i in range(8):                                    # 9 circuits below one RCD: fine under the RGIE
        d.add_circuit(be, rcd=general, label=f"Lighting {i}", circuit_type="lighting",
                      rated_current=16, cross_section=1.5, poles=2)
    r = d.report(be)
    rules = {(f["rule"], f["item"]) for f in r["findings"]}
    assert ("rcd-30-wet", washer) in rules
    assert any(f["item"] == thin and "RGIE" in f["message"] for f in r["findings"])
    assert not any(f["rule"] in ("rcd-count", "rcd-circuits", "board-reserve", "rcd-type-a") for f in r["findings"])
    assert not any("NF C 15-100" in f["message"] for f in r["findings"])
    assert ("board-full", b) in rules                    # 4 + 10 × 2 modules on 13: a fact, not a norm


def test_the_washing_machine_below_30_ma_passes(d, be):
    b = d.add_board(be, "Board", rows=2, modules_per_row=24)["id"]
    d.add_rcd(be, b, "General 300 mA", rated_current=40, sensitivity_ma=300, rcd_type="A", poles=4)
    wet = d.add_rcd(be, b, "Wet rooms 30 mA", rated_current=40, sensitivity_ma=30, rcd_type="A", poles=4)["id"]
    d.add_circuit(be, rcd=wet, label="Washing machine", circuit_type="dedicated", appliance="washing_machine",
                  rated_current=16, cross_section=2.5, poles=2)
    r = d.report(be)
    assert r["conforms"], r["findings"]


def test_the_edition_and_labels_of_a_surveyed_belgian_board(d, be):
    d.set_workspace(be, built_under="rgie-1981")
    assert d.design(be)["built_under"] == "NormEdition_RGIE_1981"
    b = d.add_board(be, "Board", rows=1, modules_per_row=24)["id"]
    r = d.add_rcd(be, b, "30 mA", rated_current=40, sensitivity_ma=30, rcd_type=None, to_verify=True, poles=4)["id"]
    c = d.add_circuit(be, rcd=r, label="Unnamed", poles=2)["id"]   # nothing read yet
    labels = {x["item"]: x for x in lb.board_labels(d.design(be))}
    assert labels[r]["modules"] == 4 and "type ?" in labels[r]["detail"]
    assert labels[c]["modules"] == 2 and labels[c]["short"] == "? A" and "? mm²" in labels[c]["detail"]
    row = lb.strips(d.design(be))[0]
    assert [cell["width"] for cell in row["cells"] if not cell.get("free")] == [4 * lb.MODULE_MM, 2 * lb.MODULE_MM]
