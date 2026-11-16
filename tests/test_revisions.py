# SPDX-License-Identifier: GPL-3.0-or-later
"""Every saved state of a design is kept (ADR-0009): one revision per change,
none for a save that changes nothing, baselines that never move, compare,
restore as a new revision. Every home and label here is invented."""

from __future__ import annotations

import json

import pytest

from digitalhome_pro_edge import app as web
from digitalhome_pro_edge import designs as dz
from digitalhome_pro_edge import homes as hm
from digitalhome_pro_edge import revisions as rv
from digitalhome_pro_edge.core import version
from digitalhome_pro_edge.edge import cloud


@pytest.fixture
def d(tmp_path):
    return dz.Designs(dz.WorkspaceKB(tmp_path))


@pytest.fixture
def ws(d):
    return d.new_workspace("Board", "FR-00000-ABC1-01", instance="stage")["workspace"]


def board(d, ws):
    b = d.add_board(ws, "Main board", rows=2)["id"]
    r = d.add_rcd(ws, b, "RCD 1", rated_current=40, sensitivity_ma=30, rcd_type="A")["id"]
    return b, r


def test_each_change_is_a_revision_and_a_no_op_is_none(d, ws, tmp_path):
    b, r = board(d, ws)
    n = len(d.revisions(ws))
    assert n == 3                                    # the workspace, the board, the RCD
    d.set_workspace(ws, status="active")             # already active: nothing changes
    assert len(d.revisions(ws)) == n
    d.add_circuit(ws, r, "Kitchen sockets", "socket", 20, 2.5, points=6, dedicated=True)
    revs = d.revisions(ws)
    assert [x["n"] for x in revs][:2] == [4, 3]      # newest first
    assert revs[0]["summary"].startswith("+ ")
    assert "Kitchen sockets" in revs[0]["summary"]
    assert (tmp_path / ws / "revisions" / "r0004.ttl").exists()


def test_diff_names_what_was_added_and_what_changed(d, ws):
    b, r = board(d, ws)
    before = d.revisions(ws)[0]["n"]
    c = d.add_circuit(ws, r, "Lighting", "lighting", 10, 1.5, points=6)["id"]
    d.rename(ws, r, "RCD 1 (lighting)")
    got = d.diff(ws, str(before))
    assert {x["label"] for x in got["added"]} >= {"Lighting"}
    assert [x["id"] for x in got["added"] if x["type"] == "Circuit"] == [c]
    changed = {x["id"]: x for x in got["changed"]}
    assert changed[r]["changes"] == [{"property": "label", "before": ["RCD 1"], "after": ["RCD 1 (lighting)"]}]
    assert got["removed"] == []


def test_a_baseline_never_moves_and_restore_adds_a_revision(d, ws):
    b, r = board(d, ws)
    base = d.revisions(ws)[0]["n"]
    d.tag_revision(ws, str(base), "As-is 1986", frozen=True)
    d.add_circuit(ws, r, "Oven", "dedicated", 20, 2.5, appliance="oven")
    with pytest.raises(ValueError, match="baseline"):
        d.tag_revision(ws, "latest", "As-is 1986")
    with pytest.raises(ValueError, match="baseline"):
        d.untag_revision(ws, "As-is 1986")
    d.tag_revision(ws, "latest", "Quote 1")
    d.tag_revision(ws, "latest", "Quote 1")          # an ordinary tag may move
    d.untag_revision(ws, "Quote 1")

    assert d.diff(ws, "As-is 1986")["added"]         # the oven is new since the baseline
    out = d.restore(ws, "As-is 1986")
    revs = d.revisions(ws)
    assert out == {"restored": base, "revision": revs[0]["n"]} and revs[0]["n"] == base + 2
    assert revs[0]["summary"].startswith(f"restored r{base}")
    assert d.diff(ws, "As-is 1986") == {"from": base, "to": revs[0]["n"], "added": [], "removed": [], "changed": []}
    assert [t["name"] for t in next(x for x in revs if x["n"] == base)["tags"]] == ["As-is 1986"]
    with pytest.raises(dz.NotFound):
        d.diff(ws, "no such tag")


def test_a_design_from_before_history_becomes_revision_one(tmp_path):
    kb = dz.WorkspaceKB(tmp_path)
    d = dz.Designs(kb)
    ws = d.new_workspace("Old", "FR-00000-ABC1-01", instance="stage")["workspace"]
    hist = tmp_path / ws / "revisions"
    for f in hist.iterdir():                          # as if saved by a version without history
        f.unlink()
    hist.rmdir()
    assert [x["n"] for x in d.revisions(ws)] == [1]
    d.add_board(ws, "Main board")
    revs = d.revisions(ws)
    assert [x["n"] for x in revs] == [2, 1] and "Main board" in revs[0]["summary"]


def test_who_and_through_what(d, ws):
    with rv.acting("mcp"):
        d.add_board(ws, "From an agent")
    entry = d.revisions(ws)[0]
    assert entry["via"] == "mcp" and entry["by"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DHPRO_EDGE_EDGE_STATE", str(tmp_path / "cloud.json"))
    monkeypatch.setenv("DHPRO_EDGE_EDGE_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(version, "UPDATE_CHECK", False)
    monkeypatch.setattr(web, "_designs", dz.Designs(dz.WorkspaceKB(tmp_path / "data")))
    monkeypatch.setattr(cloud, "active_profile", lambda: "stage")
    monkeypatch.setattr(cloud, "call", lambda path, body, profile=None:
                        {"homes": [{"smartHomeId": "FR-00000-ABC1-01", "label": "x"}]})
    hm.reset()
    web.app.config["TESTING"] = True
    yield web.app.test_client()
    hm.reset()


def test_the_routes(client):
    ws = client.post("/api/workspaces", json={"title": "Board", "home": "FR-00000-ABC1-01"}).get_json()["workspace"]
    client.post(f"/api/workspaces/{ws}/boards", json={"label": "Main"}, headers={"User-Agent": "Mozilla/5.0"})
    client.post(f"/api/workspaces/{ws}/boards", json={"label": "Second"}, headers={"X-Agent": "digitalhome-pro-edge-mcp"})
    revs = client.get(f"/api/workspaces/{ws}/revisions").get_json()
    assert [r["via"] for r in revs[:2]] == ["mcp", "page"]
    n = revs[1]["n"]
    assert client.post(f"/api/workspaces/{ws}/revisions/{n}/tag", json={"name": "As-is", "frozen": True}).status_code == 200
    got = client.get(f"/api/workspaces/{ws}/diff?from=As-is").get_json()
    assert [a["label"] for a in got["added"]] == ["Second"]
    assert b"Main" in client.get(f"/api/workspaces/{ws}/revisions/As-is.ttl").data
    assert client.delete(f"/api/workspaces/{ws}/tags/As-is").status_code == 400
    r = client.post(f"/api/workspaces/{ws}/revisions/{n}/restore").get_json()
    assert r["restored"] == n
    assert client.get(f"/api/workspaces/{ws}/diff?from=nope").status_code == 404
    log = (web.designs().kb.folder(ws) / "revisions" / "log.jsonl").read_text().splitlines()
    assert json.loads(log[-1])["summary"].startswith(f"restored r{n}")
