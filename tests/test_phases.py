# SPDX-License-Identifier: GPL-3.0-or-later
"""The supply system, the phase each item is on, a balanced split and the
report's load per phase. Every home and label is invented."""

from __future__ import annotations

import pytest

from digitalhome_pro_edge import designs as dz


@pytest.fixture
def d(tmp_path):
    return dz.Designs(dz.WorkspaceKB(tmp_path))


def board(d, country="DE"):
    ws = d.new_workspace("Haus", f"{country}-00000-ABC1-01", country=country)["workspace"]
    b = d.add_board(ws, "UV", rows=2, modules_per_row=12)["id"]
    return ws, b


def test_the_supply_comes_from_the_country_and_can_be_set(d):
    de, _ = board(d, "DE")
    assert d.design(de)["supply"] == "3N~400V" and not d.design(de)["supply_set"]
    fr, _ = board(d, "FR")
    assert d.design(fr)["supply"] == "1N~230V"
    be, _ = board(d, "BE")
    assert d.design(be)["supply"] == ""
    d.set_workspace(be, supply="3~230V")
    assert d.design(be)["supply"] == "3~230V" and d.design(be)["supply_set"]
    with pytest.raises(ValueError):
        d.set_workspace(be, supply="2~110V")


def test_each_supply_allows_its_own_phases(d):
    ws, b = board(d, "DE")
    r = d.add_rcd(ws, b, "FI 1", poles=4)["id"]
    c = d.add_circuit(ws, rcd=r, label="Licht", circuit_type="lighting", rated_current=16)["id"]
    hob = d.add_circuit(ws, rcd=r, label="Herd", circuit_type="cooking", rated_current=16, poles=3)["id"]
    d.set_phase(ws, c, "l2")
    with pytest.raises(ValueError, match="three-phase"):
        d.set_phase(ws, hob, "L1")
    d.set_phase(ws, hob, "L1L2L3")
    with pytest.raises(ValueError, match="one phase"):
        d.set_phase(ws, c, "L1L2L3")
    with pytest.raises(ValueError):
        d.set_phase(ws, c, "L1L2")                       # a pair is for 3~230V
    circuits = {x["id"]: x for x in d.design(ws)["boards"][0]["rcds"][0]["circuits"]}
    assert circuits[c]["phase"] == "L2" and circuits[hob]["phase"] == "L1L2L3"
    d.set_phase(ws, c, "")
    assert "phase_conductor" not in {x["id"]: x for x in d.design(ws)["boards"][0]["rcds"][0]["circuits"]}[c]
    be, bb = board(d, "BE")
    br = d.add_rcd(be, bb, "300 mA", sensitivity_ma=300, poles=4)["id"]
    bc = d.add_circuit(be, rcd=br, label="Prises", circuit_type="socket", poles=2)["id"]
    with pytest.raises(ValueError, match="supply"):
        d.set_phase(be, bc, "L1L2")                      # the supply is not known yet
    d.set_workspace(be, supply="3~230V")
    d.set_phase(be, bc, "L1-L2")
    with pytest.raises(ValueError):
        d.set_phase(be, bc, "L1")


def test_a_circuit_is_on_its_two_pole_rcds_phase_unless_it_has_its_own(d):
    ws, b = board(d, "DE")
    r = d.add_rcd(ws, b, "FI 2P", poles=2)["id"]
    a = d.add_circuit(ws, rcd=r, label="A", rated_current=16)["id"]
    x = d.add_circuit(ws, rcd=r, label="B", rated_current=16)["id"]
    d.set_phase(ws, r, "L3")
    d.set_phase(ws, x, "L1")
    circuits = {c["id"]: c for c in d.design(ws)["boards"][0]["rcds"][0]["circuits"]}
    assert circuits[a]["phase"] == "L3" and circuits[x]["phase"] == "L1"


def test_the_plan_balances_keeps_what_is_set_and_groups_a_two_pole_rcd(d):
    ws, b = board(d, "DE")
    big = d.add_rcd(ws, b, "FI 4P", poles=4)["id"]
    small = d.add_rcd(ws, b, "FI 2P", poles=2)["id"]
    ids = {}
    for name, amps in (("Durchlauferhitzer", 32), ("Waschmaschine", 16), ("Trockner", 16), ("Licht", 10)):
        ids[name] = d.add_circuit(ws, rcd=big, label=name, rated_current=amps)["id"]
    hob = d.add_circuit(ws, rcd=big, label="Herd", rated_current=16, poles=3)["id"]
    s1 = d.add_circuit(ws, rcd=small, label="Bad 1", rated_current=16)["id"]
    s2 = d.add_circuit(ws, rcd=small, label="Bad 2", rated_current=16)["id"]
    d.set_phase(ws, ids["Licht"], "L3")
    plan = d.phase_plan(ws)
    got = {a["item"]: a["phase"] for a in plan["assign"]}
    assert ids["Licht"] not in got                      # set: stays
    assert got[hob] == "L1L2L3" and got[big] == "L1L2L3"   # three-phase, and the 4-pole RCD: on all three
    assert got[s1] == got[s2] == got[small]             # the 2-pole RCD and its circuits together
    singles = [got[ids[n]] for n in ("Durchlauferhitzer", "Waschmaschine", "Trockner")]
    assert len(set(singles + [got[small]])) >= 2
    load = plan["load"]
    assert max(load.values()) - min(load.values()) <= 32
    assert d.design(ws)["boards"][0]["rcds"][0]["circuits"][0].get("phase_conductor") is None   # nothing changed
    fr, _ = board(d, "FR")
    assert d.phase_plan(fr)["assign"] == [] and "single phase" in d.phase_plan(fr)["note"]


def test_the_report_sums_the_phases_and_warns_when_they_are_uneven(d):
    ws, b = board(d, "DE")
    r = d.add_rcd(ws, b, "FI", poles=4)["id"]
    cs = [d.add_circuit(ws, rcd=r, label=f"K{i}", rated_current=16)["id"] for i in range(4)]
    for c in cs[:3]:
        d.set_phase(ws, c, "L1")
    rep = d.report(ws)
    assert rep["phases"]["unknown"] == [cs[3]]
    assert not any(f["rule"] == "phase-balance" for f in rep["findings"])    # not all known yet
    d.set_phase(ws, cs[3], "L2")
    rep = d.report(ws, "de")
    assert rep["phases"]["load"] == {"L1": 48.0, "L2": 16.0, "L3": 0.0}
    f = [f for f in rep["findings"] if f["rule"] == "phase-balance"]
    assert f and "L1" in f[0]["message"] and f[0]["severity"] == "warning"
    d.remove(ws, cs[3])
    for c, p in zip(cs, ("L1", "L2", "L3")):
        d.set_phase(ws, c, p)
    assert not any(f["rule"] == "phase-balance" for f in d.report(ws)["findings"])   # 16 / 16 / 16
