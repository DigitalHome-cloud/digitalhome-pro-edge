# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
configs.py — a workspace and its home's configurations in the cloud
(ADR-0010; darkfactory ADRs 0018 and 0019).

The cloud keeps, per home (named by its meaningless homeId):

- one **live** configuration and every version before it,
  `<homeId>-MMMM-mmmm`; a promoted planning option makes the next major,
  added components a minor;
- **planning options**, `<homeId>-pNN`, each based on one version;
- the home's **vault**: photos and documents, each grouped under the
  version or option it documents.

A workspace works on one of them. Its workspace node records the link:

    dhp:homeId      the home's id                        (from /edge/v1/homes)
    dhp:basedOn     the version the work started from
    dhp:option      the planning option it is a checkout of
    dhp:optionVersion  the option's save counter last pulled or pushed

What goes to the cloud is the design without the workspace node: titles,
status and links stay on the edge. The edge's own revisions (ADR-0009) stay
its working history; the revision that became a version is tagged with the
version's id, frozen.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from rdflib import Graph, Literal

from . import homes as hm
from . import revisions as rv
from .designs import DHP, Designs, NotFound
from .edge import cloud

HOME_ID_PREFIX = "h-"
MAX_FILES = 100


class ConfigError(ValueError):
    pass


def _put(url: str, data: bytes, headers: Dict[str, str]) -> None:
    req = urllib.request.Request(url, data=data, method="PUT", headers=headers)
    with urllib.request.urlopen(req, timeout=300) as r:  # noqa: S310 — a presigned S3 URL from our cloud
        if r.status not in (200, 204):
            raise ConfigError(f"upload refused ({r.status})")


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310 — a presigned S3 URL from our cloud
        return r.read().decode("utf-8")


class Configs:
    def __init__(self, designs: Designs):
        self.d = designs

    # ------------------------------------------------------------- the link

    def _node(self, ws: str):
        g = self.d.kb.load(ws)
        node = self.d._workspace_node(g)
        if node is None:
            raise NotFound(f"no workspace {ws}")
        return g, node

    def link(self, ws: str) -> Dict[str, Any]:
        g, node = self._node(ws)
        val = lambda p: str(g.value(node, p) or "")  # noqa: E731
        return {"workspace": ws, "home": val(DHP.home), "instance": val(DHP.instance), "homeId": val(DHP.homeId),
                "basedOn": val(DHP.basedOn), "option": val(DHP.option),
                "optionVersion": int(g.value(node, DHP.optionVersion) or 0)}

    def _set(self, ws: str, note: str, **values: Any) -> None:
        def apply(g: Graph) -> None:
            node = self.d._workspace_node(g)
            for key, value in values.items():
                p = DHP[key]
                g.remove((node, p, None))
                if value not in (None, ""):
                    g.add((node, p, Literal(value)))
        with rv.noting(note):
            self.d._change(ws, apply)

    def home_id(self, ws: str) -> str:
        """The workspace's homeId; asked from the cloud once and kept."""
        link = self.link(ws)
        if link["homeId"]:
            return link["homeId"]
        if not link["instance"]:
            raise ConfigError("this workspace belongs to no connection (link the edge, then attach it)")
        got = hm.cloud_homes(refresh=True, profile=link["instance"])
        home = next((h for h in got["homes"] if h.get("smartHomeId") == link["home"]), None)
        if not home or not str(home.get("homeId", "")).startswith(HOME_ID_PREFIX):
            raise ConfigError(f"{link['instance']} does not list {link['home']} with a home id: {got.get('why') or 'is the cloud up to date?'}")
        self._set(ws, "home id from the cloud", homeId=home["homeId"])
        return home["homeId"]

    def _call(self, ws: str, route: str, body: Dict[str, Any]) -> Dict[str, Any]:
        link = self.link(ws)
        home = self.home_id(ws)
        try:
            return cloud.call(f"configurations/{route}", {"homeId": home, **body}, profile=link["instance"])
        except cloud.CloudError as e:
            raise ConfigError(str(e)) from e

    # ------------------------------------------------------------- reading

    def status(self, ws: str) -> Dict[str, Any]:
        """The workspace's link and the home's configurations in the cloud."""
        got = self._call(ws, "versions", {})        # first: it records the homeId the link shows
        return {"link": self.link(ws), **got}

    # ------------------------------------------------------------- the design as a configuration

    def _configuration(self, g: Graph) -> str:
        """The design without the workspace node: what the cloud keeps."""
        node = self.d._workspace_node(g)
        out = Graph()
        for prefix, ns in g.namespaces():
            out.bind(prefix, ns)
        for s, p, o in g:
            if s != node and o != node:
                out.add((s, p, o))
        return out.serialize(format="turtle")

    def _replace_design(self, ws: str, ttl: str, note: str) -> None:
        incoming = Graph()
        incoming.parse(data=ttl, format="turtle")

        def apply(g: Graph) -> None:
            node = self.d._workspace_node(g)
            for s, p, o in list(g):
                if s != node:
                    g.remove((s, p, o))
            for t in incoming:
                g.add(t)
        with rv.noting(note):
            self.d._change(ws, apply)

    def _tag(self, ws: str, version_id: str) -> None:
        try:
            self.d.tag_revision(ws, "latest", version_id, frozen=True)
        except ValueError:
            pass                                   # already a baseline: the cloud said so before

    # ------------------------------------------------------------- writing

    def publish_first_live(self, ws: str, revision: str = "latest") -> Dict[str, Any]:
        """A survey (or a first design) becomes the home's first live
        configuration, <homeId>-0001-0000. The cloud refuses when the home has one."""
        n = self.d._history(ws).resolve(revision)
        ttl = self._configuration(self.d._history(ws).graph(n))
        r = self._call(ws, "seed", {"ttl": ttl})
        if r.get("status") != "ok":
            raise ConfigError(self._why(r))
        self.d.tag_revision(ws, str(n), r["id"], frozen=True)
        self._set(ws, f"published as {r['id']}", basedOn=r["id"])
        return {**r, "revision": n}

    def create_option(self, ws: str, label: str, based_on: str = "") -> Dict[str, Any]:
        """A planning option in the cloud, based on a version (default: the
        live one), and this workspace becomes its checkout."""
        if not based_on:
            based_on = self._call(ws, "versions", {}).get("live") or ""
            if not based_on:
                raise ConfigError("the home has no live configuration yet: publish one first")
        r = self._call(ws, "option", {"basedOn": based_on, "label": label})
        self._set(ws, f"option {r['id']}", option=r["id"], basedOn=r["basedOn"], optionVersion=r["version"])
        return r

    def pull(self, ws: str, option: str = "") -> Dict[str, Any]:
        """The option's current graph becomes this workspace's design (a new revision)."""
        link = self.link(ws)
        option = option or link["option"]
        if not option:
            raise ConfigError("this workspace is no checkout of a planning option")
        got = self._call(ws, "get", {"id": option})
        if not got.get("url"):
            raise ConfigError(f"{option} has no graph yet")
        self._replace_design(ws, _get(got["url"]), f"pulled {option} v{got['version']}")
        options = {o["id"]: o for o in self._call(ws, "versions", {}).get("options", [])}
        self._set(ws, f"checkout of {option}", option=option, optionVersion=int(got["version"]),
                  basedOn=(options.get(option) or {}).get("basedOn") or link["basedOn"])
        return {"option": option, "version": int(got["version"])}

    def push(self, ws: str) -> Dict[str, Any]:
        """Save this workspace's design as the option's next version. A
        conflict means someone else saved since: pull first."""
        link = self.link(ws)
        if not link["option"]:
            raise ConfigError("this workspace is no checkout of a planning option: create or pull one first")
        g, _ = self._node(ws)
        ttl = self._configuration(g).encode("utf-8")
        base = link["optionVersion"]
        step = self._call(ws, "save-option", {"option": link["option"], "baseVersion": base})
        if step.get("status") == "conflict":
            return {"status": "conflict", "option": link["option"], "currentVersion": step.get("currentVersion"),
                    "why": f"{link['option']} is at v{step.get('currentVersion')}, this workspace has v{base}: pull it first"}
        _put(step["url"], ttl, step.get("headers") or {"Content-Type": "text/turtle"})
        done = self._call(ws, "save-option", {"option": link["option"], "baseVersion": base, "key": step["key"]})
        if done.get("status") != "ok":
            return {**done, "option": link["option"], "why": self._why(done)}
        self._set(ws, f"pushed {link['option']} v{done['version']}", optionVersion=int(done["version"]))
        return {"status": "ok", "option": link["option"], "version": int(done["version"])}

    def promote(self, ws: str) -> Dict[str, Any]:
        """The option this workspace checks out becomes the home's live
        configuration (the next major). A person's act: the page asks twice,
        the chat only proposes it."""
        link = self.link(ws)
        if not link["option"]:
            raise ConfigError("this workspace is no checkout of a planning option")
        r = self._call(ws, "promote", {"option": link["option"]})
        if r.get("status") != "ok":
            raise ConfigError(self._why(r))
        self._tag(ws, r["id"])
        self._set(ws, f"{link['option']} promoted to {r['id']}", option="", optionVersion="", basedOn=r["id"])
        return r

    @staticmethod
    def _why(r: Dict[str, Any]) -> str:
        if r.get("status") == "conflict":
            return f"the live configuration moved (now {r.get('live')}): look again"
        return "; ".join(r.get("problems") or []) or str(r.get("status"))

    # ------------------------------------------------------------- the vault

    def _vault(self, ws: str, route: str, body: Dict[str, Any]) -> Dict[str, Any]:
        link = self.link(ws)
        try:
            return cloud.call(f"vault/{route}", {"homeId": self.home_id(ws), **body}, profile=link["instance"])
        except cloud.CloudError as e:
            raise ConfigError(str(e)) from e

    def _files(self, ws: str, names: Optional[List[str]] = None) -> List[Path]:
        root = self.d.kb.folder(ws) / "files"
        if not root.is_dir():
            return []
        found = sorted(p for p in root.rglob("*") if p.is_file() and not p.name.startswith("."))
        if names:
            want = set(names)
            found = [p for p in found if str(p.relative_to(root)) in want or p.name in want]
        if len(found) > MAX_FILES:
            raise ConfigError(f"at most {MAX_FILES} files at a time")
        return found

    def vault_upload(self, ws: str, config_version: str = "", names: Optional[List[str]] = None,
                     dry_run: bool = True) -> Dict[str, Any]:
        """The workspace's files to the home's vault, each once. Grouped under
        `config_version` (default: the option this workspace checks out, else
        the version it is based on). dry_run: say what would be uploaded."""
        link = self.link(ws)
        group = config_version or link["option"] or link["basedOn"]
        files = self._files(ws, names)
        if not files:
            return {"files": [], "group": group}
        root = self.d.kb.folder(ws) / "files"
        offers = []
        for p in files:
            data = p.read_bytes()
            offers.append({"sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
                           "name": p.name, "contentType": mimetypes.guess_type(p.name)[0] or "application/octet-stream",
                           "caption": str(p.relative_to(root)), "configVersion": group or None, "_path": p})
        wire = [{k: v for k, v in o.items() if not k.startswith("_") and v is not None} for o in offers]
        plan = self._vault(ws, "upload", {"files": wire, "dryRun": True if dry_run else False})
        if dry_run:
            return {"group": group, "files": plan["files"]}
        out = []
        for o, f in zip(offers, plan["files"]):
            if f["status"] == "new":
                _put(f["url"], o["_path"].read_bytes(), f.get("headers") or {})
                done = self._vault(ws, "commit", {k: v for k, v in o.items() if not k.startswith("_") and v is not None})
                out.append({"name": o["name"], "status": done["status"], "sha256": o["sha256"]})
            else:
                out.append({"name": o["name"], "status": f["status"], "sha256": o["sha256"]})
        return {"group": group, "files": out}

    def vault_items(self, ws: str, config_version: str = "") -> Dict[str, Any]:
        return self._vault(ws, "items", {"configVersion": config_version} if config_version else {})


def as_json(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False)
