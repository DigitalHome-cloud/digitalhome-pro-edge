# SPDX-License-Identifier: GPL-3.0-or-later
"""The page's API, the labels and the chat's allowed calls. Invented data."""

from __future__ import annotations

import re

import pytest

from digitalhome_pro_edge import app as web
from digitalhome_pro_edge import labels as lb
from digitalhome_pro_edge.core import version
from digitalhome_pro_edge.edge import settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DHPRO_EDGE_EDGE_STATE", str(tmp_path / "cloud.json"))
    monkeypatch.setenv("DHPRO_EDGE_EDGE_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(version, "UPDATE_CHECK", False)
    monkeypatch.setattr(web, "_designs", None)
    web.app.config["TESTING"] = True
    return web.app.test_client()


def build(client):
    w = client.post("/api/workspaces", json={"title": "Board swap", "home": "demo-house"}).get_json()["workspace"]
    b = client.post(f"/api/workspaces/{w}/boards", json={"label": "Main", "rows": 2, "modules_per_row": 13}).get_json()["id"]
    r = client.post(f"/api/workspaces/{w}/rcds", json={"board": b, "label": "RCD 1", "rcd_type": "A"}).get_json()["id"]
    c = client.post(f"/api/workspaces/{w}/circuits", json={"rcd": r, "label": "Lights", "circuit_type": "lighting",
                                                         "rated_current": 16, "cross_section": 1.5}).get_json()["id"]
    return w, b, r, c


def test_build_read_and_report_over_http(client):
    w, b, r, c = build(client)
    d = client.get(f"/api/workspaces/{w}").get_json()
    assert d["boards"][0]["rcds"][0]["circuits"][0]["id"] == c
    rep = client.get(f"/api/workspaces/{w}/report?lang=de").get_json()
    assert any("FI" in f["message"] for f in rep["findings"])          # only one RCD
    assert client.post(f"/api/workspaces/{w}/rcds", json={"board": b, "label": "X", "rcd_type": "Q"}).status_code == 422
    assert client.get("/api/workspaces/nope").status_code == 404
    assert client.get(f"/api/workspaces/{w}/export.ttl").mimetype == "text/turtle"


def test_label_sheet_has_one_qr_per_device(client):
    w, b, r, c = build(client)
    page = client.get(f"/workspaces/{w}/labels").get_data(as_text=True)
    assert page.count("<svg") == 2                                     # the RCD and the circuit
    assert "Lights" in page and "window.print()" in page


def test_label_link_opens_the_item():
    assert lb.link("http://192.0.2.10:8773/", "board-swap", "circuit-abcdefgh") == \
        "http://192.0.2.10:8773/#w=board-swap&i=circuit-abcdefgh"


def test_every_change_the_tools_propose_is_allowed(client):
    w, b, r, c = build(client)
    paths = [("POST", "/api/workspaces"), ("POST", f"/api/workspaces/{w}"),
             ("POST", f"/api/workspaces/{w}/circuits"), ("POST", f"/api/workspaces/{w}/boards/{b}"),
             ("POST", f"/api/workspaces/{w}/circuits/{c}/move"),
             ("POST", f"/api/workspaces/{w}/items/{r}/rename"), ("DELETE", f"/api/workspaces/{w}/items/{c}")]
    for method, path in paths:
        assert any(m == method and re.fullmatch(rx, path) for m, rx in settings.CHAT_ALLOWED), path


def test_partner_imports_and_credentials_are_not_for_the_chat():
    for path in ("/api/partners/maker-a/credentials", "/api/partners/maker-a/import", "/api/partners/store"):
        assert not any(re.fullmatch(rx, path) for _, rx in settings.CHAT_ALLOWED)


def test_selection_is_what_the_page_has_open(client):
    w, b, r, c = build(client)
    client.post("/api/selection", json={"workspace": w, "item": c})
    assert client.get("/api/selection").get_json() == {"workspace": w, "item": c}
    assert settings.CHAT_SELECTION() == f"{w}/{c}/"


def big_design():
    circuits = [{"id": f"circuit-{i:08d}", "label": f"Circuit {i}", "rated_current": 16.0, "cross_section": 1.5}
                for i in range(30)]
    return {"workspace": "w", "title": "T", "boards": [{
        "id": "board-00000001", "label": "Main", "rows": 3, "modules_per_row": 13,
        "rcds": [{"id": "rcd-00000001", "label": "R1", "rated_current": 40.0, "sensitivity_ma": 30.0,
                  "rcd_type": "A", "circuits": circuits}],
        "devices": [{"id": "contactor-00000001", "label": "Day/night", "kind": "contactor",
                     "rated_current": 20.0, "modules": 1}]}]}


def test_grid_fills_a4_sheets_of_24_and_skips_used_cells():
    page = lb.sheet(big_design(), "http://127.0.0.1:8773/")
    assert page.count('class="sheet"') == 2                       # 32 labels → 2 sheets of 24
    assert "size: A4 portrait" in page and page.count("<svg") == 32
    skipped = lb.sheet(big_design(), "http://127.0.0.1:8773/", skip=20)
    assert skipped.count('class="lbl used"') == 20 and skipped.count('class="sheet"') == 3   # 20 + 32 = 52 cells


def test_strips_follow_the_board_rows_and_fit_the_sheet():
    rows = lb.strips(big_design())
    assert all(sum(c["width"] for c in r["cells"]) <= lb.PAGE_H - 2 * lb.MARGIN for r in rows)
    first = rows[0]["cells"]
    assert first[0]["kind"] == "rcd" and first[0]["width"] == 2 * lb.MODULE_MM
    modules = sum(c["modules"] for r in rows for c in r["cells"])
    assert modules == 2 + 30 + 1
    page = lb.sheet(big_design(), "http://x/", layout="strip")
    assert "size: A4 landscape" in page


def test_a_row_wider_than_the_sheet_is_cut_into_pieces():
    d = big_design()
    d["boards"][0]["modules_per_row"] = 18                      # 18 × 17.5 = 315 mm > 281 mm
    rows = lb.strips(d)
    assert any(r["part"] for r in rows)
    assert all(sum(c["width"] for c in r["cells"]) <= lb.PAGE_H - 2 * lb.MARGIN for r in rows)


def test_label_route_takes_layout_skip_and_module(client):
    w, b, r, c = build(client)
    page = client.get(f"/workspaces/{w}/labels?layout=strip&module=18").get_data(as_text=True)
    assert "A4 landscape" in page and "width:36.0mm" in page          # the RCD: 2 modules of 18 mm
    assert client.get(f"/workspaces/{w}/labels?skip=x").status_code == 400


def test_a_dropped_file_becomes_the_chats_selection(client):
    import io
    w, b, r, c = build(client)
    client.post("/api/selection", json={"workspace": w, "item": c})
    res = client.post("/api/inbox", data={"file": (io.BytesIO(b"reference;description;price\nQ-1;RCD;9\n"), "q.csv")},
                      content_type="multipart/form-data")
    assert res.status_code == 200 and res.get_json()["kind"] == "csv"
    fid = res.get_json()["id"]
    assert client.get("/api/selection").get_json() == {"workspace": w, "item": c, "file": fid}
    assert "Q-1" in client.get(f"/api/inbox/{fid}").get_json()["text"]
    assert client.get("/api/inbox/in-0000000000").status_code == 404
    assert client.get("/api/inbox/nope").status_code == 400
    assert client.delete(f"/api/inbox/{fid}").status_code == 200


def test_a_linked_edge_only_starts_workspaces_for_its_cloud_homes(client, monkeypatch):
    from digitalhome_pro_edge import homes as hm
    from digitalhome_pro_edge.edge import cloud
    calls = []

    def call(path, body, profile=None):
        calls.append(path)
        return {"homes": [{"smartHomeId": "DE-39576-0001", "label": "Main street 1, Town", "linked": True}]}
    monkeypatch.setattr(cloud, "call", call)
    hm._cache.update(at=0.0, value=None)
    got = client.get("/api/cloud-homes").get_json()
    assert got["linked"] and got["homes"][0]["smartHomeId"] == "DE-39576-0001"
    bad = client.post("/api/workspaces", json={"title": "Kitchen", "home": "made-up", "country": "DE"})
    assert bad.status_code == 400 and "Portal" in bad.get_json()["errors"][0]
    ok = client.post("/api/workspaces", json={"title": "Kitchen", "home": "DE-39576-0001", "country": "DE"})
    assert ok.status_code == 200
    assert calls == ["homes"]                      # cached for the page's polling
    hm._cache.update(at=0.0, value=None)


def test_an_unlinked_edge_may_start_a_draft(client, monkeypatch):
    from digitalhome_pro_edge import homes as hm
    from digitalhome_pro_edge.edge import cloud

    def call(path, body, profile=None):
        raise cloud.NotLinked("not linked")
    monkeypatch.setattr(cloud, "call", call)
    hm._cache.update(at=0.0, value=None)
    assert client.get("/api/cloud-homes").get_json()["linked"] is False
    assert client.post("/api/workspaces", json={"title": "Draft", "home": "rue-des-lilas"}).status_code == 200
    hm._cache.update(at=0.0, value=None)
