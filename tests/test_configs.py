# SPDX-License-Identifier: GPL-3.0-or-later
"""A workspace and its home's configurations and vault in the cloud
(ADR-0010), against a cloud kept in memory. Every home and label is invented."""

from __future__ import annotations

import pytest
from rdflib import Graph

from digitalhome_pro_edge import configs as cf
from digitalhome_pro_edge import designs as dz
from digitalhome_pro_edge import homes as hm
from digitalhome_pro_edge.edge import cloud

HOME, HID = "FR-00000-ABC1-01", "h-abcdefghjk"


class FakeCloud:
    """Just enough of /edge/v1/configurations/* and /edge/v1/vault/*."""

    def __init__(self):
        self.versions, self.options, self.objects, self.vault = [], {}, {}, {}
        self.calls = []

    def __call__(self, path, body, profile=None):
        self.calls.append((path, body))
        if path == "homes":
            return {"homes": [{"smartHomeId": HOME, "homeId": HID, "label": "x"}]}
        assert body["homeId"] == HID
        route = path.split("/", 1)[1]
        live = self.versions[-1]["id"] if self.versions else None
        if route == "versions":
            return {"homeId": HID, "live": live, "versions": list(reversed(self.versions)),
                    "options": list(self.options.values())}
        if route == "seed":
            if self.versions:
                return {"status": "conflict", "live": live}
            self.versions.append({"id": f"{HID}-0001-0000", "version": "0001-0000", "ttl": body["ttl"]})
            return {"status": "ok", "id": f"{HID}-0001-0000", "version": "0001-0000", "summary": "+n"}
        if route == "option":
            oid = f"{HID}-p{len(self.options) + 1:02d}"
            base = next(v for v in self.versions if v["id"] == body["basedOn"])
            self.options[oid] = {"id": oid, "label": body["label"], "basedOn": base["id"], "version": 1,
                                 "status": "open", "ttl": base["ttl"]}
            return {k: self.options[oid][k] for k in ("id", "label", "basedOn", "status", "version")}
        if route == "get":
            o = self.options[body["id"]]
            self.objects["get:" + o["id"]] = o["ttl"]
            return {"id": o["id"], "kind": "option", "version": str(o["version"]), "url": "get:" + o["id"]}
        if route == "save-option":
            o = self.options[body["option"]]
            if body["baseVersion"] != o["version"]:
                return {"status": "conflict", "currentVersion": o["version"]}
            if "key" not in body:
                return {"status": "ready", "key": "staged", "url": "put:staged", "headers": {}}
            o["ttl"], o["version"] = self.objects.pop("put:staged"), o["version"] + 1
            return {"status": "ok", "version": o["version"]}
        if route == "promote":
            o = self.options[body["option"]]
            o["status"] = "promoted"
            self.versions.append({"id": f"{HID}-0002-0000", "version": "0002-0000", "ttl": o["ttl"]})
            return {"status": "ok", "id": f"{HID}-0002-0000", "version": "0002-0000", "summary": "~"}
        if route == "withdraw":
            assert body["id"] == live and len(self.versions) > 1
            self.versions.pop()
            before = self.versions[-1]
            return {"status": "ok", "id": before["id"], "version": before["version"], "summary": "withdrew"}
        if route == "items":
            items = [{"sha256": s, "name": v["name"], "caption": v.get("caption"), "tags": v.setdefault("tags", [v["configVersion"]] if v.get("configVersion") else [])}
                     for s, v in self.vault.items()]
            return {"homeId": HID, "items": [i for i in items if not body.get("tag") or body["tag"] in i["tags"]]}
        if route == "tag":
            out = []
            for s in body["sha256s"]:
                v = self.vault[s]
                v["tags"] = sorted((set(v.get("tags", [])) | set(body["add"])) - set(body["remove"]))
                out.append({"sha256": s, "tags": v["tags"]})
            return {"status": "ok", "items": out}
        if route == "upload":
            out = []
            for f in body["files"]:
                st = "known" if f["sha256"] in self.vault else "new"
                out.append({"sha256": f["sha256"], "name": f["name"], "status": st,
                            **({} if body["dryRun"] or st == "known" else {"url": "put:" + f["sha256"], "headers": {}})})
            return {"files": out}
        if route == "tags":                                              # blank QR tags (ADR 0018 point 10)
            self.tags = getattr(self, "tags", {})
            minted = [f"t-{c * 10}" for c in "mnpqrstuvwxyz"[len(self.tags):len(self.tags) + body["count"]]]
            for t in minted:
                self.tags[t] = None
            return {"homeId": HID, "tags": minted}
        if route == "tag-bind":
            self.tags[body["tagId"]] = body["item"]
            return {"tagId": body["tagId"], "homeId": HID, "item": body["item"]}
        if route == "commit":
            assert self.objects.pop("put:" + body["sha256"])
            self.vault[body["sha256"]] = body
            return {"status": "ok", "sha256": body["sha256"]}
        raise AssertionError(path)


@pytest.fixture
def fake(tmp_path, monkeypatch):
    f = FakeCloud()
    monkeypatch.setattr(cloud, "call", f)
    monkeypatch.setattr(cloud, "load_state", lambda profile=None: {})
    monkeypatch.setattr(cf, "_put", lambda url, data, headers: f.objects.__setitem__(url, data.decode("utf-8") if url == "put:staged" else data))
    monkeypatch.setattr(cf, "_get", lambda url: f.objects[url])
    hm.reset()
    yield f
    hm.reset()


@pytest.fixture
def d(tmp_path):
    return dz.Designs(dz.WorkspaceKB(tmp_path))


def survey(d):
    ws = d.new_workspace("As-is", HOME, instance="stage")["workspace"]
    b = d.add_board(ws, "Fuse board", rows=2)["id"]
    d.add_circuit(ws, board=b, label="01 · Plaque", circuit_type="cooking", protection="fuse")
    d.tag_revision(ws, "latest", "As-is (baseline)", frozen=True)
    return ws, b


def test_a_survey_becomes_the_first_live_configuration(d, fake):
    ws, _ = survey(d)
    c = cf.Configs(d)
    r = c.publish_first_live(ws, "As-is (baseline)")
    assert r["id"] == f"{HID}-0001-0000"
    sent = Graph().parse(data=fake.versions[0]["ttl"], format="turtle")
    assert not list(sent.subjects(None, dz.DHP.Workspace))               # the workspace stays on the edge
    assert any(str(o) == "01 · Plaque" for o in sent.objects())
    tags = {t["name"]: t for rev in d.revisions(ws) for t in rev["tags"]}
    assert tags[f"{HID}-0001-0000"]["frozen"]
    assert c.link(ws)["homeId"] == HID and c.link(ws)["basedOn"] == f"{HID}-0001-0000"
    with pytest.raises(cf.ConfigError, match="live configuration moved"):
        c.publish_first_live(ws)


def test_an_option_is_pushed_pulled_and_promoted(d, fake):
    ws, b = survey(d)
    c = cf.Configs(d)
    c.publish_first_live(ws)
    o = c.create_option(ws, "Modernisation")
    assert o["id"] == f"{HID}-p01" and c.link(ws)["option"] == o["id"] and c.link(ws)["optionVersion"] == 1
    d.add_rcd(ws, b, "RCD 30 mA")
    assert c.push(ws) == {"status": "ok", "option": o["id"], "version": 2}
    assert "RCD 30 mA" in fake.options[o["id"]]["ttl"]

    fake.options[o["id"]]["version"] = 3                                 # someone else saved
    assert c.push(ws)["status"] == "conflict"
    fake.options[o["id"]]["ttl"] = fake.options[o["id"]]["ttl"].replace("RCD 30 mA", "RCD 30 mA type A")
    assert c.pull(ws)["version"] == 3
    labels = {r["label"] for b in d.design(ws)["boards"] for r in b["rcds"]}
    assert labels == {"RCD 30 mA type A"}
    assert d.design(ws)["home"] == HOME                                  # the workspace node survived the pull

    r = c.promote(ws)
    assert r["id"] == f"{HID}-0002-0000"
    link = c.link(ws)
    assert link["option"] == "" and link["basedOn"] == f"{HID}-0002-0000"
    assert any(t["name"] == f"{HID}-0002-0000" for rev in d.revisions(ws) for t in rev["tags"])


def test_files_go_to_the_vault_once_after_a_dry_run(d, fake, tmp_path):
    ws, _ = survey(d)
    c = cf.Configs(d)
    c.publish_first_live(ws)
    files = d.kb.folder(ws) / "files" / "photos"
    files.mkdir(parents=True)
    (files / "panel.png").write_bytes(b"\x89PNG fake")
    (files.parent / "notes.md").write_text("as-is notes")
    plan = c.vault_upload(ws)
    assert plan["group"] == f"{HID}-0001-0000"
    assert [f["status"] for f in plan["files"]] == ["new", "new"]
    assert not fake.vault                                                # a dry run sends nothing
    done = c.vault_upload(ws, dry_run=False)
    assert [f["status"] for f in done["files"]] == ["ok", "ok"]
    assert {v["caption"] for v in fake.vault.values()} == {"notes.md", "photos/panel.png"}
    assert {v["configVersion"] for v in fake.vault.values()} == {f"{HID}-0001-0000"}
    assert [f["status"] for f in c.vault_upload(ws, dry_run=False)["files"]] == ["known", "known"]


def test_a_workspace_without_a_connection_says_so(d, fake):
    ws = d.new_workspace("Local", HOME)["workspace"]
    with pytest.raises(cf.ConfigError, match="no connection"):
        cf.Configs(d).status(ws)


def test_an_unchanged_promote_is_withdrawn_and_the_baseline_tag_goes(d, fake):
    ws, _ = survey(d)
    c = cf.Configs(d)
    c.publish_first_live(ws)
    c.create_option(ws, "Baseline")
    c.promote(ws)                                                        # the fake cloud has no guard
    assert c.link(ws)["basedOn"] == f"{HID}-0002-0000"
    r = c.withdraw(ws, "0002-0000")                                      # short for this home's
    assert r["id"] == f"{HID}-0001-0000" and r["withdrawn"] == f"{HID}-0002-0000"
    assert c.link(ws)["basedOn"] == f"{HID}-0001-0000"
    tags = {t["name"] for rev in d.revisions(ws) for t in rev["tags"]}
    assert f"{HID}-0002-0000" not in tags and f"{HID}-0001-0000" in tags
    with pytest.raises(ValueError, match="baseline"):
        d.untag_revision(ws, f"{HID}-0001-0000")                         # a baseline still stays


def test_vault_items_are_tagged_several_at_once(d, fake):
    ws, _ = survey(d)
    c = cf.Configs(d)
    files = d.kb.folder(ws) / "files"
    files.mkdir(parents=True)
    (files / "a.jpg").write_bytes(b"a")
    (files / "b.jpg").write_bytes(b"b")
    c.publish_first_live(ws)
    c.vault_upload(ws, dry_run=False)
    r = c.vault_tag(ws, add=["0002-0000"])                               # none named: every item; short ids
    assert {i["name"]: i["tags"] for i in r["items"]} == {
        "a.jpg": [f"{HID}-0001-0000", f"{HID}-0002-0000"], "b.jpg": [f"{HID}-0001-0000", f"{HID}-0002-0000"]}
    c.vault_tag(ws, items=["b.jpg"], remove=[f"{HID}-0002-0000"])
    assert [i["name"] for i in c.vault_items(ws, f"{HID}-0002-0000")["items"]] == ["a.jpg"]
    with pytest.raises(cf.ConfigError, match="not in the vault: c.jpg"):
        c.vault_tag(ws, items=["c.jpg"], add=["0001-0000"])
    with pytest.raises(cf.ConfigError, match="which tags"):
        c.vault_tag(ws, items=["a.jpg"])


def test_blank_tags_are_minted_numbered_on_and_an_observation_is_adopted(d, fake):
    ws, b = survey(d)
    c = cf.Configs(d)
    c.publish_first_live(ws)
    assert [t["n"] for t in c.mint_tags(ws, 2)["tags"]] == [1, 2]
    second = c.mint_tags(ws, 3)["tags"]
    assert [t["n"] for t in second] == [3, 4, 5]                         # numbered on: a sheet can be counted
    assert len(c.blank_tags(ws)["batches"]) == 2
    with pytest.raises(cf.ConfigError, match="1 to 200"):
        c.mint_tags(ws, 0)
    # on site, the phone filed a photo of a socket the design does not have
    obs = f"obs-{second[0]['tagId'][2:]}"
    fake.vault["c" * 64] = {"name": "survey-1.jpg", "caption": "socket by the door",
                            "tags": [f"{HID}-0001-0000", "survey", f"item:{obs}", "kind:socket", "room:Hall"]}
    seen = c.observations(ws)["observations"]
    assert seen[0]["new"] and seen[0]["kind"] == "socket" and seen[0]["room"] == "Hall"
    assert seen[0]["tag"] == second[0]["tagId"] and seen[0]["note"] == "socket by the door"
    item = next(i for i in c._design_ids(ws) if i.startswith("circuit-"))
    r = c.adopt_observation(ws, obs, item)
    assert r["photos"] == 1 and fake.tags[second[0]["tagId"]] == item
    assert f"item:{item}" in fake.vault["c" * 64]["tags"] and f"item:{obs}" not in fake.vault["c" * 64]["tags"]
    with pytest.raises(cf.ConfigError, match="no item"):
        c.adopt_observation(ws, obs, "point-nothere1")


def test_survey_tags_are_not_taken_for_short_version_ids(d, fake):
    ws, _ = survey(d)
    c = cf.Configs(d)
    c.publish_first_live(ws)
    fake.vault["d" * 64] = {"name": "x.jpg", "tags": []}
    c.vault_tag(ws, items=["x.jpg"], add=["survey", "item:point-abcdefgh", "0001-0000"])
    assert fake.vault["d" * 64]["tags"] == sorted(["survey", "item:point-abcdefgh", f"{HID}-0001-0000"])
