# SPDX-License-Identifier: GPL-3.0-or-later
"""A design can hold an as-is survey of an old board: fuses, values not read
yet, no RCD, the supply's main breaker, a device nobody identified. What a
survey left open is reported as unchecked, never as compliant. Every home and
label here is invented."""

from __future__ import annotations

import pytest
from rdflib import Literal
from rdflib.namespace import XSD

from digitalhome_pro_edge import designs as dz


@pytest.fixture
def d(tmp_path):
    return dz.Designs(dz.WorkspaceKB(tmp_path))


@pytest.fixture
def ws(d):
    return d.new_workspace("As-is", "FR-00000-ABC1-01", instance="stage")["workspace"]


def test_an_old_fuse_board_with_unread_values_saves(d, ws):
    b = d.add_board(ws, "Fuse board 1986", rows=2)["id"]
    main = d.add_device(ws, b, "main_breaker", "Supply main breaker", rated_current=45, sensitivity_ma=500)["id"]
    hob = d.add_circuit(ws, board=b, label="Plaque", circuit_type="cooking", protection="fuse")["id"]
    unknown = d.add_circuit(ws, board=b, label="(none)", protection="fuse")["id"]
    dev = d.add_device(ws, b, "unidentified", "Chauffage")["id"]
    d.add_device(ws, b, "fuse", "Water heater control", rated_current=2)

    board = d.design(ws)["boards"][0]
    assert board["rcds"] == []
    loose = {c["id"]: c for c in board["circuits"]}
    assert loose[hob]["to_verify"] and loose[hob]["protection"] == "fuse" and loose[hob]["type"] == "cooking"
    assert loose[hob]["rated_current"] is None and loose[unknown]["type"] == ""
    devices = {x["id"]: x for x in board["devices"]}
    assert devices[main]["kind"] == "main_breaker" and devices[main]["sensitivity_ma"] == 500 and devices[main]["modules"] == 0
    assert devices[dev]["kind"] == "unidentified" and devices[dev]["to_verify"]


def test_what_a_survey_left_open_is_unchecked_not_ok(d, ws):
    b = d.add_board(ws, "Fuse board", rows=2)["id"]
    d.add_device(ws, b, "main_breaker", "Supply main breaker", rated_current=45, sensitivity_ma=500)
    c = d.add_circuit(ws, board=b, label="Plaque", circuit_type="cooking", protection="fuse")["id"]
    u = d.add_device(ws, b, "unidentified", "Chauffage")["id"]
    r = d.report(ws)
    assert r["conforms"] is False
    unchecked = {f["item"]: f for f in r["findings"] if f["severity"] == "unchecked"}
    assert "rating" in unchecked[c]["message"] and "section" in unchecked[c]["message"]
    assert u in unchecked
    rules = {(f["rule"], f["item"]) for f in r["findings"]}
    assert ("circuit-rcd", c) in rules                 # no RCD at all
    assert ("rcd-count", "") in rules                  # the 500 mA main breaker is not a 30 mA RCD
    assert not any(f["item"] == "" and f["rule"] == "RCDSensitivityShape" for f in r["findings"])


def test_a_designed_circuit_still_states_its_values(d, ws):
    b = d.add_board(ws, "New board")["id"]
    r = d.add_rcd(ws, b, "RCD 1")["id"]
    with pytest.raises(Exception):                     # a guessed-free design still needs a label
        d.add_circuit(ws, rcd=r, label="")
    c = d.add_circuit(ws, rcd=r, label="Sockets", circuit_type="socket", rated_current=20, cross_section=2.5)["id"]
    assert not d.design(ws)["boards"][0]["rcds"][0]["circuits"][0]["to_verify"]
    assert not [f for f in d.report(ws)["findings"] if f["item"] == c and f["severity"] == "unchecked"]
    with pytest.raises(ValueError, match="RCD .* or the board"):
        d.add_circuit(ws, label="Nowhere", circuit_type="socket", rated_current=20, cross_section=2.5)


def test_decimals_are_short_for_the_norm_guards():
    assert dz._dec(32.0) == Literal("32", datatype=XSD.decimal)
    assert str(dz._for_shapes(Literal("32.0", datatype=XSD.decimal))) == "32"
    assert str(dz._dec(2.50)) == "2.5" and str(dz._dec(10)) == "10" and str(dz._dec(0.0)) == "0"


def test_a_32_a_ev_charger_is_checked(d, ws):
    """The IRVE 32 A guard is sh:hasValue "32"^^xsd:decimal: with 32.0 from
    JSON written as "32.0" it never matched, and 6 mm² passed unnoticed."""
    b = d.add_board(ws, "Board")["id"]
    r = d.add_rcd(ws, b, "RCD EV", rcd_type="A")["id"]
    c = d.add_circuit(ws, rcd=r, label="EV charger", circuit_type="ev_charger", rated_current=32.0, cross_section=6.0)["id"]
    rules = {f["rule"] for f in d.report(ws)["findings"] if f["item"] == c}
    assert "IRVE32AMonoShape" in rules


def test_built_under_names_an_edition_of_the_t_box(d, ws):
    d.set_workspace(ws, built_under="nfc15100-2015")
    assert d.design(ws)["built_under"] == "NormEdition_NFC15100_2015"
    b = d.add_board(ws, "Fuse board")["id"]
    d.set_board(ws, b, built_under="nfc15100-1976")          # a 1986 board: the edition before 1991
    assert d.design(ws)["boards"][0]["built_under"] == "NormEdition_NFC15100_1976"
    with pytest.raises(ValueError, match="no edition"):
        d.set_workspace(ws, built_under="nfc15100-1901")
    with pytest.raises(ValueError, match="looks like"):
        d.set_workspace(ws, built_under="1986")


def test_a_quote_that_states_no_rcd_values_is_modelled_to_verify(tmp_path):
    """A quote says "one 30 mA RCD" and nothing more: the RCD is marked to
    verify, the report says what is missing, and a surveyed fuse circuit
    moved below it becomes a breaker with its rating unchanged."""
    d = dz.Designs(dz.WorkspaceKB(tmp_path))
    ws = d.new_workspace("Quote", "FR-00000-ABC1-01")["workspace"]
    old = d.add_board(ws, "Old", rows=1)["id"]
    c = d.add_circuit(ws, board=old, label="01 · Plaque", circuit_type="cooking", protection="fuse", to_verify=True)["id"]
    new = d.add_board(ws, "New", rows=1)["id"]
    with pytest.raises(ValueError):
        d.add_rcd(ws, new, "ID 30 mA", rated_current=None, rcd_type=None)
    r = d.add_rcd(ws, new, "ID 30 mA", rated_current=None, rcd_type=None, to_verify=True)["id"]
    d.move_circuit(ws, c, r, protection="breaker")
    design = d.design(ws)
    board = next(b for b in design["boards"] if b["id"] == new)
    rcd = board["rcds"][0]
    assert rcd["rated_current"] is None and rcd["rcd_type"] == "" and rcd["to_verify"]
    assert [x["protection"] for x in rcd["circuits"]] == ["breaker"]
    report = d.report(ws)
    unchecked = [f for f in report["findings"] if f["severity"] == "unchecked" and f.get("item") == r]
    assert unchecked and "rated current" in unchecked[0]["message"] and not report["conforms"]
    assert any(m["description"] == "RCD ? A 30 mA type ?" for m in d.bom(ws))
    with pytest.raises(ValueError):
        d.move_circuit(ws, c, r, protection="main_breaker")
