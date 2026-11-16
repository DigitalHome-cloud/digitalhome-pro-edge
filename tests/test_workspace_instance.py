# SPDX-License-Identifier: GPL-3.0-or-later
"""A workspace belongs to one home on one instance (ADR-0008): minted ids,
linked-only, the same SmartHome ID on two connections, attaching an old one.
Every home and label here is invented."""

from __future__ import annotations

import re

import pytest
from rdflib import URIRef

from digitalhome_pro_edge import app as web
from digitalhome_pro_edge import designs as dz
from digitalhome_pro_edge import homes as hm
from digitalhome_pro_edge.core import version
from digitalhome_pro_edge.edge import cloud
from digitalhome_pro_edge.edge import knowledge as kn

HOMES = {"stage": ["FR-00000-ABC1-01", "FR-DEMO"], "prod": ["FR-DEMO"]}


@pytest.fixture
def d(tmp_path):
    return dz.Designs(kn.KnowledgeBase(tmp_path / "abox"))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DHPRO_EDGE_EDGE_STATE", str(tmp_path / "cloud.json"))
    monkeypatch.setenv("DHPRO_EDGE_EDGE_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(version, "UPDATE_CHECK", False)
    monkeypatch.setattr(web, "_designs", None)
    monkeypatch.setattr(cloud, "active_profile", lambda: "stage")

    def call(path, body, profile=None):
        name = profile or "stage"
        if name not in HOMES:
            raise cloud.NotLinked(f"{name} is not linked")
        return {"homes": [{"smartHomeId": h, "label": h} for h in HOMES[name]]}
    monkeypatch.setattr(cloud, "call", call)
    hm.reset()
    web.app.config["TESTING"] = True
    yield web.app.test_client()
    hm.reset()


def test_ids_are_minted_and_stay_when_renamed(d):
    w = d.new_workspace("Kitchen", "FR-DEMO", instance="stage")["workspace"]
    assert re.fullmatch(r"ws-[a-z0-9]{8}", w)
    d.set_workspace(w, title="Kitchen and pantry")
    got = d.workspaces()[0]
    assert (got["workspace"], got["title"], got["instance"]) == (w, "Kitchen and pantry", "stage")


def test_the_same_home_on_two_instances_is_two_homes(d):
    d.new_workspace("Board", "FR-DEMO", instance="stage")
    d.new_workspace("Board", "FR-DEMO", instance="prod")
    d.new_workspace("Old one", "demo-house")                    # made before instances
    homes = [(h["instance"], h["home"], len(h["workspaces"])) for h in d.homes()]
    assert homes == [("prod", "FR-DEMO", 1), ("stage", "FR-DEMO", 1), ("", "demo-house", 1)]


def test_a_bad_instance_name_is_refused(d):
    with pytest.raises(ValueError):
        d.new_workspace("K", "FR-DEMO", instance="Stage!")


def test_attach_moves_every_iri_to_the_new_home_and_still_validates(d):
    w = d.new_workspace("Board swap", "demo-house")["workspace"]
    b = d.add_board(w, "Main", 1, 13)["id"]
    r = d.add_rcd(w, b, "RCD 1", 40, 30, "A")["id"]
    d.add_circuit(w, r, "Lights", "lighting", 16, 1.5)
    d.attach_workspace(w, "stage", "FR-00000-ABC1-01")
    g = d.kb.load(w)
    iris = {str(x) for t in g for x in t if isinstance(x, URIRef) and str(x).startswith(dz.INSTANCE)}
    assert iris and all(i.startswith(f"{dz.INSTANCE}FR-00000-ABC1-01/") for i in iris)
    got = d.design(w)
    assert (got["home"], got["instance"]) == ("FR-00000-ABC1-01", "stage")
    assert got["boards"][0]["rcds"][0]["circuits"][0]["label"] == "Lights"
    with pytest.raises(ValueError):
        d.attach_workspace(w, "", "FR-DEMO")                       # an instance is needed


def test_a_workspace_is_made_on_the_named_connection(client):
    r = client.post("/api/workspaces", json={"title": "Board", "home": "FR-DEMO", "connection": "prod"})
    assert r.status_code == 200 and r.get_json()["instance"] == "prod"
    r = client.post("/api/workspaces", json={"title": "Board", "home": "FR-00000-ABC1-01", "connection": "prod"})
    assert r.status_code == 400 and "prod" in r.get_json()["errors"][0]       # stage lists it, prod does not
    r = client.post("/api/workspaces", json={"title": "Board", "home": "FR-DEMO", "connection": "sandbox"})
    assert r.status_code == 400 and "not linked" in r.get_json()["errors"][0]
    r = client.post("/api/workspaces", json={"title": "Board", "home": "FR-00000-ABC1-01"})
    assert r.status_code == 200 and r.get_json()["instance"] == "stage"       # the current connection


def test_attach_over_http_checks_the_home(client):
    web.designs().new_workspace("Old", "demo-house")
    w = web.designs().workspaces()[0]["workspace"]
    bad = client.post(f"/api/workspaces/{w}/attach", json={"home": "made-up"})
    assert bad.status_code == 400
    ok = client.post(f"/api/workspaces/{w}/attach", json={"home": "FR-00000-ABC1-01", "connection": "stage"})
    assert ok.status_code == 200
    assert client.get(f"/api/workspaces/{w}").get_json()["instance"] == "stage"
