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
    for path in ("/api/partners/schneider/credentials", "/api/partners/hager/import"):
        assert not any(re.fullmatch(rx, path) for _, rx in settings.CHAT_ALLOWED)


def test_selection_is_what_the_page_has_open(client):
    w, b, r, c = build(client)
    client.post("/api/selection", json={"workspace": w, "item": c})
    assert client.get("/api/selection").get_json() == {"workspace": w, "item": c}
    assert settings.CHAT_SELECTION() == f"{w}/{c}"
