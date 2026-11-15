# SPDX-License-Identifier: GPL-3.0-or-later
"""One folder per workspace (ADR-0007), its files, the display name, and the
page's three languages. Every home and title here is invented."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from digitalhome_pro_edge import designs as dz
from digitalhome_pro_edge import inbox as ib
from digitalhome_pro_edge import selection as sel
from digitalhome_pro_edge.edge import sync

PKG = Path(dz.__file__).parent


@pytest.fixture
def data(tmp_path, monkeypatch):
    root = tmp_path / "mydocs"
    monkeypatch.setenv("DHPRO_EDGE_EDGE_DATA", str(root))
    sel.set()
    yield root
    sel.set()


def test_a_workspace_is_a_folder_with_its_design(data):
    d = dz.Designs()                                   # WorkspaceKB by default
    w = d.new_workspace("Kitchen extension", "demo-house")["workspace"]
    assert (data / w / "design.ttl").is_file()
    assert not (data / "abox").exists()
    assert d.kb.graphs() == [w]
    assert [x["workspace"] for x in d.workspaces()] == [w]
    assert (data / w).stat().st_mode & 0o777 == 0o700


def test_reserved_folders_are_never_workspaces(data):
    kb = dz.WorkspaceKB()
    for name in ("abox", "inbox", "partners", "files"):
        with pytest.raises(ValueError):
            kb.load(name)
    (data / "partners").mkdir(parents=True)
    (data / "partners" / "design.ttl").write_text("")   # even with a design.ttl inside
    assert "partners" not in kb.graphs()
    d = dz.Designs(kb)
    assert d.new_workspace("Partners", "demo-house")["workspace"] != "partners"


def test_renaming_changes_the_title_not_the_folder(data):
    d = dz.Designs()
    w = d.new_workspace("Board swap", "demo-house")["workspace"]
    d.set_workspace(w, title="Board swap, phase 2")
    assert d.workspaces()[0] == {**d.workspaces()[0], "workspace": w, "title": "Board swap, phase 2"}
    assert (data / w / "design.ttl").is_file() and len([p for p in data.iterdir() if p.is_dir()]) == 1


def test_the_old_layout_moves_once_and_nothing_is_overwritten(data):
    old = data / "abox"
    (old / ".sync" / "stage").mkdir(parents=True)
    d_old = dz.Designs(dz.kn.KnowledgeBase(old))
    w = d_old.new_workspace("New switchboard", "demo-house")["workspace"]
    (old / ".sync" / "stage" / f"{w}.ttl").write_text("# base\n")
    (old / ".sync" / "stage" / f"{w}.json").write_text('{"version": 3}')
    assert dz.migrate_layout(data) == [w]
    assert (data / w / "design.ttl").is_file() and not old.exists()
    assert (data / ".sync" / "stage" / f"{w}.json").read_text() == '{"version": 3}'
    assert dz.migrate_layout(data) == []                     # a second start changes nothing
    assert dz.Designs().workspaces()[0]["title"] == "New switchboard"


def test_migration_leaves_a_clash_where_it_is(data):
    (data / "abox").mkdir(parents=True)
    (data / "abox" / "x.ttl").write_text("# old\n")
    (data / "x").mkdir()
    (data / "x" / "design.ttl").write_text("# new\n")
    assert dz.migrate_layout(data) == []
    assert (data / "abox" / "x.ttl").read_text() == "# old\n"
    assert (data / "x" / "design.ttl").read_text() == "# new\n"


def test_cloud_sync_keeps_its_bases_beside_the_workspaces(data):
    kb = dz.WorkspaceKB()
    base = sync.Base(kb, "stage", "kitchen")
    assert base.ttl == data / ".sync" / "stage" / "kitchen.ttl"


def test_files_given_with_a_workspace_open_go_into_its_folder(data):
    d = dz.Designs()
    w = d.new_workspace("Kitchen extension", "demo-house")["workspace"]
    loose = ib.add("notes.txt", b"no workspace open")
    sel.set(workspace=w)
    kept = ib.add("prices.csv", "Référence;Prix\nX-1;9,80\n".encode())
    assert kept["workspace"] == w and (data / w / "files" / kept["id"] / "file").is_file()
    assert loose["workspace"] == "" and (data / "inbox" / loose["id"]).is_dir()
    assert {f["id"] for f in ib.files()} == {kept["id"], loose["id"]}
    assert ib.read(kept["id"])["text"].startswith("Référence")
    sel.set()                                                # another view: only the shared inbox
    assert [f["id"] for f in ib.files()] == [loose["id"]]
    assert ib.meta(kept["id"])["name"] == "prices.csv"       # still found by its id
    ib.remove(kept["id"])
    assert not (data / w / "files" / kept["id"]).exists()


def test_every_string_is_in_english_german_and_french():
    table = json.loads((PKG / "static" / "i18n.json").read_text())
    keys = set(table["en"])
    assert set(table["de"]) == keys and set(table["fr"]) == keys
    assert set(table["edge"]["de"]) == set(table["edge"]["fr"])
    for lang in ("de", "fr"):
        for k, v in table[lang].items():
            assert set(re.findall(r"\{(\w+)\}", v)) == set(re.findall(r"\{(\w+)\}", table["en"][k])), (lang, k)
    js = (PKG / "static" / "app.js").read_text()
    html = (PKG / "templates" / "index.html").read_text()
    used = set(re.findall(r'(?<![\w.$])t\("([\w.]+)"', js))
    used |= set(re.findall(r'data-i18n(?:-title|-placeholder)?="([\w.]+)"', html))
    assert used and not used - keys, sorted(used - keys)
