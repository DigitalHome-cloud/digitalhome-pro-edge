# SPDX-License-Identifier: GPL-3.0-or-later
"""Board positions read on site, and the labels that follow them: an old
board with its RCD in the middle of the top row, a bell transformer and
blank covers, and breakers below no RCD. Every home and label is invented."""

from __future__ import annotations

import pytest

from digitalhome_pro_edge import designs as dz
from digitalhome_pro_edge import labels as lb


@pytest.fixture
def d(tmp_path):
    return dz.Designs(dz.WorkspaceKB(tmp_path))


@pytest.fixture
def board(d):
    ws = d.new_workspace("As-is", "DE-00000-ABC1-01", country="DE")["workspace"]
    b = d.add_board(ws, "Board", rows=2, modules_per_row=6)["id"]
    r = d.add_rcd(ws, b, "FI 30 mA", rated_current=25, sensitivity_ma=30, rcd_type=None, to_verify=True, poles=4)["id"]
    c1 = d.add_circuit(ws, rcd=r, label="1 Licht", rated_current=16)["id"]
    c2 = d.add_circuit(ws, rcd=r, label="2 Steckdosen", rated_current=16)["id"]
    trafo = d.add_device(ws, b, "bell_transformer", "Klingeltrafo 8 V")["id"]
    hob = d.add_circuit(ws, board=b, label="Herd", rated_current=16, poles=3)["id"]
    return ws, b, r, c1, c2, trafo, hob


def test_items_are_placed_where_they_sit_and_never_overlap(d, board):
    ws, b, r, c1, c2, trafo, hob = board
    assert d.position(ws, c1, row=1, slot=1) == {"id": c1, "row": 1, "slot": 1}
    d.position(ws, r, row=1, slot=3)
    with pytest.raises(ValueError, match="taken by .FI 30 mA"):
        d.position(ws, c2, row=1, slot=4)
    with pytest.raises(ValueError, match="do not fit"):
        d.position(ws, hob, row=2, slot=5)                   # 3 modules from 5 on a row of 6
    with pytest.raises(ValueError, match="row is 1 to 2"):
        d.position(ws, trafo, row=3, slot=1)
    d.position(ws, hob, row=2, slot=4)
    design = d.design(ws)
    loose = design["boards"][0]["circuits"][0]
    assert (loose["row"], loose["slot"]) == (2, 4)
    assert (design["boards"][0]["rcds"][0]["row"], design["boards"][0]["rcds"][0]["slot"]) == (1, 3)
    assert d.position(ws, c1) == {"id": c1, "row": None, "slot": None}


def test_strips_follow_the_board_with_its_blanks_and_numbers(d, board):
    ws, b, r, c1, c2, trafo, hob = board
    d.position(ws, c1, row=1, slot=1)
    d.position(ws, c2, row=1, slot=2)
    d.position(ws, r, row=1, slot=3)
    d.position(ws, trafo, row=2, slot=1)
    d.position(ws, hob, row=2, slot=4)
    rows = lb.layout(d.design(ws))[0]["rows"]
    top = [(c.get("title", "·"), lb.numbers(c)) for c in rows[0]["cells"]]
    assert top == [("1 Licht", "1"), ("2 Steckdosen", "2"), ("FI 30 mA", "3–6")]
    low = [(c.get("title", "·"), lb.numbers(c)) for c in rows[1]["cells"]]
    assert low == [("Klingeltrafo 8 V", "7–8"), ("·", "9"), ("Herd", "10–12")]   # a blank cover at 9
    page = lb.sheet(d.design(ws), "http://x/")
    assert "A4 landscape" in page and "position?" not in page
    assert page.count('class="cell narrow') == 2                # the 1-module breakers: upright text


def test_what_was_not_placed_fills_a_gap_and_says_so(d, board):
    ws, b, r, c1, c2, trafo, hob = board
    d.position(ws, r, row=1, slot=1)
    rows = lb.layout(d.design(ws))[0]["rows"]
    cells = {c["item"]: c for row in rows for c in row["cells"] if not c.get("free")}
    assert cells[r]["placed"] and lb.numbers(cells[r]) == "1–4"
    assert not cells[c1]["placed"] and lb.numbers(cells[c1]) == "5"
    page = lb.sheet(d.design(ws), "http://x/")
    assert "position?" in page and "without a position read on site" in page
    grid = lb.sheet(d.design(ws), "http://x/", layout="grid")
    assert "№ 1–4" in grid and "≈ № 5" in grid


def test_a_board_without_an_rcd_gets_labels_for_its_breakers(d):
    ws = d.new_workspace("Old", "DE-00000-ABC1-01", country="DE")["workspace"]
    b = d.add_board(ws, "Fuse board", rows=1, modules_per_row=12)["id"]
    d.add_circuit(ws, board=b, label="Küche", protection="fuse", rated_current=16)
    assert [x["title"] for x in lb.board_labels(d.design(ws))] == ["Küche"]


def test_more_than_the_board_holds_goes_to_an_extra_strip(d):
    ws = d.new_workspace("Full", "DE-00000-ABC1-01", country="DE")["workspace"]
    b = d.add_board(ws, "Small", rows=1, modules_per_row=2)["id"]
    for i in range(3):
        d.add_circuit(ws, board=b, label=f"C{i}", rated_current=16)
    rows = lb.strips(d.design(ws))
    assert [r["overflow"] for r in rows] == [False, True]
    assert "not on the board yet" in lb.sheet(d.design(ws), "http://x/")
