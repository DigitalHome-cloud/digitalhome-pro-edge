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
import re
from datetime import datetime, timezone
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
# what a survey photo shows (ADR 0018 point 10): a vault tag that is not a version
SUBJECT_TAG = re.compile(r"^(survey|(item|kind|room):.+)$")
TAG_ID = re.compile(r"^t-[abcdefghjkmnpqrstuvwxyz23456789]{10}$")
BLANK_FILE = "blank-tags.json"            # the workspace's minted blank tags (runtime data, never committed)
MAX_MINT = 200


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

    def withdraw(self, ws: str, version: str = "") -> Dict[str, Any]:
        """Take back a live major that changed nothing (promoted from an option
        identical to the live version). The version before it is live again;
        the cloud removes the version and its option and refuses anything
        else. Here the link goes back to that version and the baseline tag
        goes. A person's act."""
        link = self.link(ws)
        vid = version or link["basedOn"]
        if not vid:
            raise ConfigError("say which version to withdraw")
        home = self.home_id(ws)
        if not vid.startswith(home):
            vid = f"{home}-{vid}"                       # "0002-0000" is short for this home's
        r = self._call(ws, "withdraw", {"id": vid})
        if r.get("status") != "ok":
            raise ConfigError(self._why(r))
        try:
            self.d._history(ws).untag(vid, withdrawn=True)
        except rv.RevisionError:
            pass                                    # never tagged here
        if link["basedOn"] == vid:
            self._set(ws, f"{vid} withdrawn: {r['id']} is live again", basedOn=r["id"], option="", optionVersion="")
        return {**r, "withdrawn": vid}

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
        return self._vault(ws, "items", {"tag": config_version} if config_version else {})

    def vault_tag(self, ws: str, items: Optional[List[str]] = None, add: Optional[List[str]] = None,
                  remove: Optional[List[str]] = None) -> Dict[str, Any]:
        """Add and remove version tags (version or option ids, or "0001-0000"
        short for this home's) on several vault items at once. `items`: their
        names or SHA-256s; none means every item."""
        home = self.home_id(ws)
        full = lambda t: t if str(t).startswith(home) or SUBJECT_TAG.match(str(t)) else f"{home}-{t}"  # noqa: E731
        add = [full(t) for t in (add or []) if str(t).strip()]
        remove = [full(t) for t in (remove or []) if str(t).strip()]
        if not add and not remove:
            raise ConfigError("say which tags to add or remove")
        known = self._vault(ws, "items", {}).get("items", [])
        wanted = [str(x) for x in (items or [])]
        picked = [i for i in known if not wanted or i["sha256"] in wanted or i["name"] in wanted]
        missing = [w for w in wanted if not any(w in (i["sha256"], i["name"]) for i in known)]
        if missing:
            raise ConfigError(f"not in the vault: {', '.join(missing)}")
        if not picked:
            return {"status": "ok", "items": []}
        r = self._vault(ws, "tag", {"sha256s": [i["sha256"] for i in picked], "add": add, "remove": remove})
        names = {i["sha256"]: i["name"] for i in picked}
        return {"status": r.get("status"), "items": [{"name": names.get(x["sha256"]), **x} for x in r.get("items", [])]}

    # ------------------------------------------------- the site survey (point 10)

    def _blank_path(self, ws: str) -> Path:
        return self.d.kb.folder(ws) / BLANK_FILE

    def blank_tags(self, ws: str) -> Dict[str, Any]:
        """The blank tags minted for this workspace's home, in batches, newest last."""
        p = self._blank_path(ws)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        return {"batches": data.get("batches", [])}

    def mint_tags(self, ws: str, count: int) -> Dict[str, Any]:
        """Mint `count` blank QR tags for the home in the cloud and keep them
        here, numbered on from the last batch, so a sheet can be printed again
        without minting again."""
        n = int(count)
        if not 1 <= n <= MAX_MINT:
            raise ConfigError(f"mint 1 to {MAX_MINT} tags at a time")
        got = self._call(ws, "tags", {"count": n})
        tags = [t for t in got.get("tags", []) if TAG_ID.match(str(t))]
        have = self.blank_tags(ws)["batches"]
        first = 1 + sum(len(b["tags"]) for b in have)
        batch = {"mintedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "tags": [{"tagId": t, "n": first + k} for k, t in enumerate(tags)]}
        p = self._blank_path(ws)
        p.write_text(json.dumps({"batches": have + [batch]}, ensure_ascii=False, indent=1), encoding="utf-8")
        return batch

    def bind_tag(self, ws: str, tag: str, item: str = "") -> Dict[str, Any]:
        """Bind a blank tag of this home to an item (or unbind it)."""
        if not TAG_ID.match(str(tag)):
            raise ConfigError("a tag id looks like t- and ten letters or digits")
        return self._call(ws, "tag-bind", {"tagId": tag, "item": item or None})

    def observations(self, ws: str) -> Dict[str, Any]:
        """What the phone filed on site: the vault items tagged `survey`, each
        with the item it shows (an observation obs-… is something the design
        does not have yet), its kind, room and note, newest first."""
        got = self._vault(ws, "items", {"tag": "survey"}).get("items", [])
        known = self._design_ids(ws)
        out = []
        for i in got:
            tags = i.get("tags") or []
            pick = lambda key: next((t.split(":", 1)[1] for t in tags if t.startswith(f"{key}:")), "")  # noqa: E731
            item = pick("item")
            out.append({"sha256": i["sha256"], "name": i.get("name"), "kind": pick("kind"), "room": pick("room"),
                        "item": item, "note": i.get("caption") or "", "uploadedAt": i.get("uploadedAt"),
                        "new": item.startswith("obs-"), "in_design": item in known,
                        "tag": f"t-{item[4:]}" if item.startswith("obs-") else ""})
        out.sort(key=lambda o: str(o["uploadedAt"]), reverse=True)
        return {"observations": out}

    def _design_ids(self, ws: str) -> set:
        g = self.d.kb.load(ws)
        return {str(s).rstrip("/").rsplit("/", 1)[-1] for s in g.subjects()}

    def adopt_observation(self, ws: str, observation: str, item: str) -> Dict[str, Any]:
        """The chat made the design item an observation stood for (the person
        confirmed it): its photos move to item:<item>, and its tag follows."""
        if not observation.startswith("obs-"):
            raise ConfigError("an observation id starts with obs-")
        if item not in self._design_ids(ws):
            raise ConfigError(f"no item {item} in this design")
        shas = [i["sha256"] for i in self._vault(ws, "items", {"tag": f"item:{observation}"}).get("items", [])]
        moved = self._vault(ws, "tag", {"sha256s": shas, "add": [f"item:{item}"], "remove": [f"item:{observation}"]}) if shas else {}
        tag = self.bind_tag(ws, f"t-{observation[4:]}", item)
        return {"photos": len(shas), "tag": tag, "items": moved.get("items", [])}


def as_json(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False)
