# SPDX-License-Identifier: GPL-3.0-or-later
"""A home's workspaces and their designs: structural shapes refuse a broken
file, norm findings are reported. Every home, room and label here is invented."""

from __future__ import annotations

from pathlib import Path

import pytest
from rdflib import Graph

from digitalhome_pro_edge import designs as dz
from digitalhome_pro_edge.edge import knowledge as kn


@pytest.fixture
def d(tmp_path):
    return dz.Designs(kn.KnowledgeBase(tmp_path / "abox"))


def board_like_a_cheap_quote(d):
    """One row of 13 modules, one type AC RCD, a day/night contactor: what a
    quick board replacement often looks like."""
    w = d.new_workspace("Board swap", "demo-house")["workspace"]
    b = d.add_board(w, "Main board", 1, 13)["id"]
    r = d.add_rcd(w, b, "RCD 40 A", 40, 30, "AC")["id"]
    d.add_device(w, b, "contactor", "Day/night contactor", 20)
    d.add_device(w, b, "breaker", "Contactor control", 2)
    for label, kind, amps, mm2, app in [("Lights", "lighting", 16, 1.5, ""), ("Sockets", "socket", 16, 1.5, ""),
                                         ("Lights upstairs", "lighting", 16, 1.5, ""), ("Bedrooms", "socket", 16, 1.5, ""),
                                         ("Hob", "cooking", 32, 6, ""), ("Washer", "dedicated", 20, 2.5, "washing_machine"),
                                         ("Water heater", "water_heater", 20, 2.5, "")]:
        d.add_circuit(w, r, label, kind, amps, mm2, appliance=app)
    return w, b, r


def rules(report):
    return {f["rule"] for f in report["findings"]}


def test_a_home_holds_several_workspaces(d):
    d.new_workspace("Board swap", "demo-house")
    d.new_workspace("Kitchen", "demo-house")
    d.new_workspace("Garage", "other-house")
    homes = {h["home"]: [w["title"] for w in h["workspaces"]] for h in d.homes()}
    assert homes == {"demo-house": ["Board swap", "Kitchen"], "other-house": ["Garage"]}


def test_same_title_gets_its_own_workspace(d):
    a = d.new_workspace("Kitchen", "demo-house")["workspace"]
    b = d.new_workspace("Kitchen", "demo-house")["workspace"]
    assert a != b and len(d.workspaces()) == 2


def test_the_cheap_board_is_reported_not_refused(d):
    w, _, _ = board_like_a_cheap_quote(d)
    rep = d.report(w, "fr")
    assert not rep["conforms"]
    assert {"rcd-count", "rcd-type-a", "board-reserve"} <= rules(rep)
    hob = next(f for f in rep["findings"] if f["rule"] == "rcd-type-a" and f["label"] == "Hob")
    assert "type A" in hob["message"] and "différentiel" in hob["message"]
    assert len(d.design(w)["boards"][0]["rcds"][0]["circuits"]) == 7      # saved all the same


def test_the_counter_proposal_conforms(d):
    w = d.new_workspace("Board, two rows", "demo-house")["workspace"]
    b = d.add_board(w, "Main board", 2, 13)["id"]
    r1 = d.add_rcd(w, b, "RCD 1", 40, 30, "A")["id"]
    r2 = d.add_rcd(w, b, "RCD 2", 40, 30, "A")["id"]
    d.add_device(w, b, "contactor", "Day/night contactor", 20)
    d.add_device(w, b, "breaker", "Contactor control", 2)
    d.add_circuit(w, r1, "Hob", "cooking", 32, 6)
    d.add_circuit(w, r1, "Washer", "dedicated", 20, 2.5, appliance="washing_machine")
    d.add_circuit(w, r2, "Lights", "lighting", 16, 1.5, points=6)
    d.add_circuit(w, r2, "Water heater", "water_heater", 20, 2.5)
    rep = d.report(w)
    assert rep["conforms"], rep["findings"]
    assert rep["findings"] == []


def test_norm_shapes_explain_themselves(d):
    w, _, r = board_like_a_cheap_quote(d)
    d.add_circuit(w, r, "Too many lights", "lighting", 16, 1.5, points=10)
    d.add_circuit(w, r, "Hob, thin wire", "cooking", 32, 2.5)
    msgs = {f["label"]: f["message"] for f in d.report(w, "en")["findings"] if f["rule"].endswith("Shape")}
    assert "8 points" in msgs["Too many lights"]
    assert "6 mm" in msgs["Hob, thin wire"]
    assert not any("must conform" in m for m in msgs.values())


def test_more_than_eight_circuits_on_one_rcd(d):
    w = d.new_workspace("Big", "demo-house")["workspace"]
    b = d.add_board(w, "B", 3, 13)["id"]
    r = d.add_rcd(w, b, "R", 63, 30, "A")["id"]
    d.add_rcd(w, b, "R2", 40, 30, "A")
    for i in range(9):
        d.add_circuit(w, r, f"Sockets {i}", "socket", 16, 1.5)
    assert "rcd-circuits" in rules(d.report(w))


def test_structural_shapes_refuse_a_broken_design(d):
    w = d.new_workspace("W", "demo-house")["workspace"]
    b = d.add_board(w, "B", 1, 13)["id"]
    with pytest.raises(kn.Invalid):
        d.add_rcd(w, b, "R", 40, 30, "X")                 # no such RCD type
    assert d.design(w)["boards"][0]["rcds"] == []


def test_points_count_and_rooms(d):
    w, _, _ = board_like_a_cheap_quote(d)
    room = d.add_room(w, "Living room", "ground floor")["id"]
    lights = next(c for c in d.design(w)["boards"][0]["rcds"][0]["circuits"] if c["label"] == "Lights")
    for i in range(3):
        d.add_point(w, lights["id"], "light", f"Ceiling {i}", room)
    got = d.design(w)
    lights = next(c for c in got["boards"][0]["rcds"][0]["circuits"] if c["label"] == "Lights")
    assert lights["points"] == 3
    assert len(got["rooms"][0]["items"]) == 3
    d.remove(w, lights["point_list"][0]["id"])
    lights = next(c for c in d.design(w)["boards"][0]["rcds"][0]["circuits"] if c["label"] == "Lights")
    assert lights["points"] == 2


def test_removing_a_circuit_takes_its_breaker(d):
    w, b, r = board_like_a_cheap_quote(d)
    before = d.design(w)["boards"][0]["modules_used"]
    hob = next(c for c in d.design(w)["boards"][0]["rcds"][0]["circuits"] if c["label"] == "Hob")
    d.remove(w, hob["id"])
    assert d.design(w)["boards"][0]["modules_used"] == before - 1
    with pytest.raises(ValueError):
        d.remove(w, r)                                    # circuits still on it


def test_move_circuit_between_rcds(d):
    w, b, r = board_like_a_cheap_quote(d)
    hob = next(c for c in d.design(w)["boards"][0]["rcds"][0]["circuits"] if c["label"] == "Hob")
    r2 = d.add_rcd(w, b, "RCD type A", 40, 30, "A")["id"]
    d.move_circuit(w, hob["id"], r2)
    labels = [f["label"] for f in d.report(w)["findings"] if f["rule"] == "rcd-type-a"]
    assert "Hob" not in labels and "Washer" in labels


def test_bom_counts(d):
    w, _, _ = board_like_a_cheap_quote(d)
    bom = {(l["kind"], l["description"]): l["quantity"] for l in d.bom(w)}
    assert bom[("board", "1 × 13 modules")] == 1
    assert bom[("rcd", "RCD 40 A 30 mA type AC")] == 1
    assert bom[("breaker", "breaker 20 A")] == 2
    assert bom[("breaker", "breaker 16 A")] == 4
    assert bom[("contactor", "contactor 20 A")] == 1


def test_export_is_turtle_in_the_designer_scheme(d):
    w, _, _ = board_like_a_cheap_quote(d)
    g = Graph().parse(data=d.export(w), format="turtle")
    subjects = {str(s) for s in g.subjects()}
    assert all(s.startswith("https://digitalhome.cloud/instance/demo-house/") for s in subjects)


def test_the_reference_abox_trips_its_planted_defect(d):
    """darkfactory's reference A-Box plants one non-compliant circuit (32 A EV
    charger in 1.5 mm²); the norm shapes copied here must find it."""
    ref = Path.home() / "digitalhomeCloud/digitalhome-cloud-darkfactory/repos/core/schema/abox/electrical-installation-house.ttl"
    if not ref.exists():
        pytest.skip("no darkfactory checkout")
    g = Graph().parse(ref, format="turtle")
    found = d._norm_findings(g, "en")
    assert any(f["item"] == "circuit-ev-legacy" for f in found), found
