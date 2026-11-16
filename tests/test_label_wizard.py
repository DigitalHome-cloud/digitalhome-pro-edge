# SPDX-License-Identifier: GPL-3.0-or-later
"""The Labels tab: what a label says (overrides, pictograms, phases), its
warnings, the cable labels and the wizard's routes. Invented data."""

from __future__ import annotations

import math
import re

import pytest

from digitalhome_pro_edge import app as web
from digitalhome_pro_edge import designs as dz
from digitalhome_pro_edge import labels as lb
from digitalhome_pro_edge import symbols
from digitalhome_pro_edge.core import version
from digitalhome_pro_edge.edge import settings


CARDS = {"site": "https://portal.example", "home_id": "h-abcdefghjk"}


@pytest.fixture
def d(tmp_path):
    return dz.Designs(dz.WorkspaceKB(tmp_path))


@pytest.fixture
def house(d):
    ws = d.new_workspace("Haus", "DE-00000-ABC1-01", country="DE")["workspace"]
    b = d.add_board(ws, "UV", rows=1, modules_per_row=12)["id"]
    r = d.add_rcd(ws, b, "FI 1", poles=4)["id"]
    light = d.add_circuit(ws, rcd=r, label="Licht Wohnzimmer und Flur und Treppenhaus oben", circuit_type="lighting",
                          rated_current=10, cross_section=1.5)["id"]
    wash = d.add_circuit(ws, rcd=r, label="Waschmaschine", circuit_type="dedicated", appliance="washing_machine",
                         rated_current=16, cross_section=2.5)["id"]
    hob = d.add_circuit(ws, rcd=r, label="Herd", circuit_type="cooking", rated_current=16, cross_section=2.5,
                        poles=3)["id"]
    return ws, b, r, light, wash, hob


def by_item(labels):
    return {x["item"]: x for x in labels}


def test_pictograms_follow_the_design_and_an_override_wins(d, house):
    ws, b, r, light, wash, hob = house
    labs = by_item(lb.board_labels(d.design(ws)))
    assert (labs[r]["symbol"], labs[light]["symbol"], labs[wash]["symbol"], labs[hob]["symbol"]) == \
        ("rcd", "lighting", "washing_machine", "hob")
    d.set_label(ws, wash, text="WaMa Keller", short="16 A B", symbol="dryer")
    lab = by_item(lb.board_labels(d.design(ws)))[wash]
    assert (lab["title"], lab["short"], lab["symbol"], lab["name"]) == ("WaMa Keller", "16 A B", "dryer", "Waschmaschine")
    d.set_label(ws, wash, text="", symbol="")                        # back to the design's; short stays
    lab = by_item(lb.board_labels(d.design(ws)))[wash]
    assert (lab["title"], lab["short"], lab["symbol"]) == ("Waschmaschine", "16 A B", "washing_machine")
    with pytest.raises(ValueError):
        d.set_label(ws, wash, symbol="rocket")
    with pytest.raises(ValueError):
        d.set_label(ws, wash, text="x" * 61)
    assert len(symbols.ALL) >= 22 and all(symbols.svg(s["id"]).startswith("<svg") for s in symbols.ALL)


def test_warnings_name_what_to_look_at_before_printing(d, house):
    ws, b, r, light, wash, hob = house
    d.add_circuit(ws, rcd=r, label="Waschmaschine", rated_current=16)       # the same text twice
    got = {x["item"]: {w["code"] for w in x["warnings"]} for x in lb.warnings(d.design(ws))}
    assert "too_long" in got[light]                                 # a 1-module cell, upright text
    assert "no_phase" in got[light] and "no_phase" in got[r]        # 3N~400V, nothing set
    assert any("duplicate" in v for v in got.values())
    d.set_phase(ws, r, "L1L2L3")
    d.set_phase(ws, light, "L2")
    got = {x["item"]: {w["code"] for w in x["warnings"]} for x in lb.warnings(d.design(ws))}
    assert "no_phase" not in got[light] and "no_phase" not in got[r]
    fr = d.new_workspace("FR", "FR-00000-ABC1-01")["workspace"]
    fb = d.add_board(fr, "TD")["id"]
    fc = d.add_circuit(fr, rcd=d.add_rcd(fr, fb, "30 mA")["id"], label="Prises", rated_current=20)["id"]
    assert "no_phase" not in {w["code"] for w in by_item(lb.warnings(d.design(fr)))[fc]["warnings"]}


def test_strips_carry_the_pictogram_and_the_phase_bar_on_three_phase(d, house):
    ws, b, r, light, wash, hob = house
    d.set_phase(ws, light, "L2")
    page = lb.sheet(d.design(ws), CARDS)
    assert 'class="sy"' in page and 'title="L2"' in page and lb.PHASE_COLOURS["L2"] in page
    assert 'title="L1-L2-L3"' not in page                            # the hob has none set yet
    plain = lb.sheet(d.design(ws), CARDS, settings={"show_symbol": False, "show_phase": False})
    assert 'class="sy"' not in plain and 'class="ph"' not in plain


def test_cable_labels_are_two_per_circuit_and_wrap_once_around(d, house):
    ws, b, r, light, wash, hob = house
    cabs = lb.cable_labels(d.design(ws))
    assert len(cabs) == 6 and {c["end"] for c in cabs} == {"board", "load"}
    by = {(c["item"], c["end"]): c for c in cabs}
    l, h = by[(light, "board")], by[(hob, "load")]
    assert l["cable"] == "3G1.5" and h["cable"] == "5G2.5"
    assert l["diameter"] == lb.CABLE_OD[3][1.5] and h["diameter"] == lb.CABLE_OD[5][2.5]
    assert l["text_len"] == round(math.pi * l["diameter"] + lb.CABLE_OVERLAP / 2, 1)
    assert l["length"] == pytest.approx(2 * l["text_len"])          # the blank half wraps over the text
    fixed = lb.cable_labels(d.design(ws), {"cable_d": 7})
    assert all(c["diameter"] == 7 for c in fixed)
    page = lb.sheet(d.design(ws), CARDS, settings={"kind": "cable"})
    assert page.count('class="cab"') == 6 and "size: A4 portrait" in page and "→ load" in page


def test_settings_and_picks_choose_what_prints(d, house, tmp_path):
    ws, b, r, light, wash, hob = house
    folder = d.kb.folder(ws)
    assert lb.load_settings(folder)["kind"] == "board"
    lb.save_settings(folder, {"kind": "cable", "items": [wash]})
    s = lb.load_settings(folder)
    assert s["kind"] == "cable" and s["items"] == [wash]
    page = lb.sheet(d.design(ws), CARDS, settings=s)
    assert page.count('class="cab"') == 2
    with pytest.raises(ValueError):
        lb.save_settings(folder, {"module_mm": 99})


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DHPRO_EDGE_EDGE_STATE", str(tmp_path / "cloud.json"))
    monkeypatch.setenv("DHPRO_EDGE_EDGE_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(version, "UPDATE_CHECK", False)
    monkeypatch.setattr(web, "_designs", None)
    from digitalhome_pro_edge import homes as hm
    from digitalhome_pro_edge.edge import cloud
    monkeypatch.setattr(cloud, "call", lambda path, body, profile=None:
                        {"homes": [{"smartHomeId": "demo-house", "label": "Demo house"}]})
    hm.reset()
    web.app.config["TESTING"] = True
    yield web.app.test_client()
    hm.reset()


def test_the_wizard_routes(client):
    w = client.post("/api/workspaces", json={"title": "Board", "home": "demo-house", "country": "BE"}).get_json()["workspace"]
    b = client.post(f"/api/workspaces/{w}/boards", json={"label": "Main", "rows": 1, "modules_per_row": 13}).get_json()["id"]
    r = client.post(f"/api/workspaces/{w}/rcds", json={"board": b, "label": "300 mA", "sensitivity_ma": 300,
                                                       "poles": 4}).get_json()["id"]
    c = client.post(f"/api/workspaces/{w}/circuits", json={"rcd": r, "label": "Prises", "circuit_type": "socket",
                                                         "rated_current": 16, "poles": 2}).get_json()["id"]
    draft = client.get(f"/api/workspaces/{w}/labels").get_json()
    assert draft["supply"] == "" and draft["settings"]["kind"] == "board" and len(draft["labels"]) == 2
    assert client.post(f"/api/workspaces/{w}/items/{c}/phase", json={"phase": "L1L2"}).status_code == 400  # no supply
    assert client.post(f"/api/workspaces/{w}", json={"supply": "3~230V"}).status_code == 200
    assert client.post(f"/api/workspaces/{w}/items/{c}/phase", json={"phase": "L1L2"}).status_code == 200
    assert client.post(f"/api/workspaces/{w}/items/{c}/label", json={"text": "Prises cuisine"}).status_code == 200
    assert client.post(f"/api/workspaces/{w}/labels/settings", json={"kind": "cable"}).get_json()["kind"] == "cable"
    assert client.post(f"/api/workspaces/{w}/labels/settings", json={"strip_h": 5}).status_code == 400
    res = client.get(f"/workspaces/{w}/labels")
    assert res.headers["X-Frame-Options"] == "SAMEORIGIN" and "frame-ancestors 'self'" in res.headers["Content-Security-Policy"]
    page = res.get_data(as_text=True)
    assert 'class="cab"' in page and "Prises cuisine" in page and "L1-L2" in page   # the saved kind: cable
    assert 'class="cells"' in client.get(f"/workspaces/{w}/labels?layout=strip").get_data(as_text=True)
    assert client.get(f"/api/workspaces/{w}/phase-plan").get_json()["supply"] == "3~230V"
    assert {x["id"] for x in client.get("/api/symbols").get_json()} == symbols.IDS
    assert client.get("/symbols/socket.svg").mimetype == "image/svg+xml"
    assert client.get("/symbols/nope.svg").status_code == 404


def test_the_chat_may_propose_labels_phases_and_settings():
    ws, item = "ws-abcdefgh", "circuit-abcdefgh"
    for path in (f"/api/workspaces/{ws}/items/{item}/label", f"/api/workspaces/{ws}/items/{item}/phase",
                 f"/api/workspaces/{ws}/labels/settings"):
        assert any(m == "POST" and re.fullmatch(rx, path) for m, rx in settings.CHAT_ALLOWED), path


def test_points_get_small_tags_that_open_their_card_and_never_name_the_address(d, house):
    ws, b, r, light, wash, hob = house
    kitchen = d.add_room(ws, "Küche")["id"]
    p = d.add_point(ws, wash, "socket", "Steckdose Spüle", room=kitchen)["id"]
    sw = d.add_point(ws, light, "switch", "Schalter Flur")["id"]
    d.set_phase(ws, wash, "L3")
    pts = {x["item"]: x for x in lb.point_labels(d.design(ws))}
    assert pts[p]["room"] == "Küche" and pts[p]["symbol"] == "socket" and pts[p]["phase"] == "L3"
    assert pts[sw]["symbol"] == "switch" and pts[sw]["circuit"].startswith("Licht")
    rows = {x["item"]: x for x in lb.warnings(d.design(ws), cards=CARDS)}
    assert rows[p]["kind"] == "point" and rows[p]["card"].endswith(f"i={p}")
    assert "no_room" in {w["code"] for w in rows[sw]["warnings"]}
    page = lb.sheet(d.design(ws), CARDS, settings={"kind": "tag", "tag_mm": 15})
    assert page.count('class="tag"') == 2 + 0          # the two points; the board has no other devices
    assert f"portal.example/id/?h=h-abcdefghjk&amp;i={p}" in page
    assert "DE-00000-ABC1-01" not in page              # the SmartHome ID spells an address
    assert "width: 15mm" in page.replace("15.0mm", "15mm")
    none = lb.sheet(d.design(ws), None, settings={"kind": "tag"})
    assert "<svg" not in none and "No QR codes" in none
    with pytest.raises(ValueError):
        lb.clean_settings({"tag_mm": 40})
    picked = lb.sheet(d.design(ws), CARDS, settings={"kind": "tag", "items": [sw]})
    assert picked.count('class="tag"') == 1
