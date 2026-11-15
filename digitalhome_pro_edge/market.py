# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
market.py — partner catalogues as graphs of the digitalhome.cloud marketplace
(ADR-0006).

The cloud keeps one catalogue graph per SELLER (a manufacturer, distributor or
wholesaler, or `digitalhome-cloud`, the platform's own curated catalogue),
with a version. On this edge, a seller is a partner with the SAME id and its
catalogue is the partner's graph (<data>/partners/<id>.catalogue.ttl), so the
designs, the norms rules and the materials list use it unchanged.

They are kept in step exactly as the Mediathek keeps its A-Boxes (the edge
layer's sync.merge, template-dlab5-cloud ADR-0007): statement by statement
against the version both last agreed on (the BASE, per connection, in
<data>/partners/.sync/<connection>/<seller>.ttl):

    merged = base − removed here − removed there + added here + added there

Two different values for a fact that may have only one (a brand, a label …)
are a CONFLICT the person settles with "mine" or "theirs".

    subscribe(seller)  take a seller of the marketplace as a partner
    sync(partner)      merge; push the result when the person who linked this
                       edge is the seller's editor (the cloud says so: mayEdit)
                       — otherwise only pull, and keep what was added here
                       on this edge only
    attach(...)        an image or datasheet for an article, kept here by its
                       SHA-256 and uploaded (once, by hash) on the next push

Prices are never in these graphs (partners.py keeps them), so none can leave.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from rdflib import Graph, Literal

from . import catalogue as cat
from . import partners as pt
from .edge import cloud
from .edge import knowledge as kn
from .edge.sync import Base, _graph, _parse, _set, merge

FILE_TYPES = {"jpg": "image", "jpeg": "image", "png": "image", "webp": "image", "pdf": "datasheet"}
MAX_FILE = 25 * 1024 * 1024
_KIND = {"platform": "platform", "manufacturer": "manufacturer", "distributor": "distributor",
         "wholesaler": "wholesaler"}


def _partners_dir() -> Path:
    d = kn.data_dir() / "partners"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def _files_dir() -> Path:
    d = _partners_dir() / "files"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def _base(profile: str, seller: str) -> Base:
    # The edge layer's Base keeps <kb.dir>/.sync/<profile>/<graph>.ttl: here
    # the partners' folder stands in for the knowledge base.
    return Base(SimpleNamespace(dir=_partners_dir()), profile, seller)


def _state_path() -> Path:
    return _partners_dir() / "market.json"


def state() -> Dict[str, Dict]:
    """Per seller: {profile, version, synced_at, may_edit, local_only} of the last sync."""
    try:
        return json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return {}


def _save_state(seller: str, entry: Dict) -> None:
    s = state()
    s[seller] = entry
    p = _state_path()
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(s, indent=1))
    os.replace(tmp, p)


def _call(path: str, body: Dict, profile: str) -> Dict:
    try:
        return cloud.call(path, body, profile)
    except cloud.CloudError as e:
        if e.status == 404 and path == "market/sellers":
            raise ValueError("the connected cloud has no marketplace yet (/edge/v1/market)") from e
        if e.status == 404:
            raise ValueError(f"the marketplace has no seller {body.get('name') or body.get('seller')}") from e
        raise


def _http(method: str, url: str, data: Optional[bytes] = None, headers: Optional[Dict] = None) -> bytes:
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=120) as res:          # presigned S3 links, 15–60 minutes
        return res.read()


# ------------------------------------------------------------- sellers ----

def sellers(profile: Optional[str] = None) -> List[Dict]:
    """The marketplace's sellers, with whether each is a partner here and the last sync."""
    name = profile or cloud.active_profile()
    st = state()
    out = []
    for s in _call("market/sellers", {}, name).get("sellers") or []:
        try:
            p = pt.partner(s["id"])
        except ValueError:                       # an id this edge cannot use as a partner id
            p = None
        out.append({**s, "subscribed": bool(p and p.get("market")), "synced": st.get(s["id"])})
    return out


def subscribe(seller: str, profile: Optional[str] = None) -> Dict:
    """Take a marketplace seller as a partner (same id), and sync it once."""
    name = profile or cloud.active_profile()
    found = next((s for s in sellers(name) if s["id"] == seller), None)
    if found is None:
        raise ValueError(f"the marketplace has no seller {seller}")
    before = pt.partner(seller) or {}
    pt.add_partner(seller, before.get("name") or found["name"], before.get("kind") or _KIND.get(found["kind"], "manufacturer"),
                   before.get("formats") or ["csv"], api=before.get("api", ""), note=before.get("note", ""),
                   markets=before.get("markets") or [], market=True)
    return sync(seller, profile=name)


# ---------------------------------------------------------------- sync ----

def sync(partner: str, resolve: Optional[Dict[str, str]] = None, profile: Optional[str] = None,
         _attempt: int = 0) -> Dict[str, Any]:
    """Merge a partner's catalogue with its seller's graph on one connection."""
    name = profile or cloud.active_profile()
    p = pt.partner(partner)
    if p is None or not p.get("market"):
        raise ValueError(f"{partner} is not a marketplace seller here (subscribe to it first)")
    info = next((s for s in _call("market/sellers", {}, name).get("sellers") or [] if s["id"] == partner), None)
    if info is None:
        raise ValueError(f"the marketplace of {name} has no seller {partner}")
    may_edit = bool(info.get("mayEdit"))

    base_store = _base(name, partner)
    base_graph, _ = base_store.load()
    remote = _call("market/graphs/get", {"name": partner}, name)
    remote_version = int(remote.get("version") or 0)
    theirs_graph = _parse(_http("GET", remote["url"]).decode("utf-8")) if remote.get("url") else Graph()
    mine_graph = cat.load(partner)

    base, mine, theirs = _set(base_graph), _set(mine_graph), _set(theirs_graph)
    merged, conflicts = merge(base, mine, theirs, resolve)
    stats = {"partner": partner, "profile": name, "may_edit": may_edit,
             "pulled": len(theirs - base), "removed_there": len(base - theirs),
             "pushed": 0, "removed_here": len(base - mine)}
    if conflicts:
        return {**stats, "status": "conflict", "conflicts": conflicts}

    merged_graph = _graph(merged)
    version, agreed = remote_version, merged
    if merged != theirs and may_edit:
        try:
            files = _upload_files(partner, merged_graph, name)
            step = _call("market/graphs/put", {"name": partner, "baseVersion": remote_version}, name)
            _http("PUT", step["url"], merged_graph.serialize(format="turtle").encode("utf-8"), step.get("headers"))
            out = _call("market/graphs/put", {"name": partner, "baseVersion": remote_version,
                                              "key": step["key"], "commit": True}, name)
            version = int(out["version"])
            stats.update(pushed=len(merged - theirs), files_uploaded=files)
        except cloud.CloudError as e:
            if e.status == 409 and _attempt < 2:              # someone saved meanwhile: merge again
                return sync(partner, resolve, name, _attempt + 1)
            if e.status == 422:
                return {**stats, "status": "invalid", "problems": (e.payload or {}).get("problems") or [str(e)]}
            if e.status == 403:
                raise PermissionError(f"digitalhome.cloud lets only the editors of {partner} change its catalogue "
                                      "(with an authenticator app)") from e
            raise
    elif merged != theirs:
        agreed = theirs                  # not ours to push: what was added here stays on this edge only
    if merged != mine:
        cat._save(partner, merged_graph)
    base_store.save(_graph(agreed), version)
    entry = {"profile": name, "version": version, "may_edit": may_edit, "local_only": len(merged - agreed),
             "synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    _save_state(partner, entry)
    return {**stats, "status": "ok", "version": version, "statements": len(merged), "local_only": entry["local_only"]}


def sync_all(profile: Optional[str] = None) -> Dict[str, Any]:
    """Every marketplace partner on one connection."""
    out: Dict[str, Any] = {}
    for p in pt.register():
        if p.get("market"):
            try:
                out[p["id"]] = sync(p["id"], profile=profile)
            except (cloud.CloudError, ValueError, PermissionError) as e:
                out[p["id"]] = {"status": "error", "error": str(e)}
    return out


# --------------------------------------------------------------- files ----

def attach(partner: str, reference: str, data: bytes, filename: str) -> Dict:
    """Keep an image or datasheet for an article by its SHA-256, and name it in the catalogue."""
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    kind = FILE_TYPES.get(ext)
    if kind is None:
        raise ValueError(f"an image (jpg, png, webp) or a datasheet (pdf), not .{ext or '?'}")
    if not data or len(data) > MAX_FILE:
        raise ValueError("a file of 1 byte to 25 MB")
    if cat.article(partner, reference) is None:
        raise ValueError(f"{partner} has no article {reference}")
    ext = "jpg" if ext == "jpeg" else ext
    name = f"{hashlib.sha256(data).hexdigest()}.{ext}"
    dest = _files_dir() / name
    if not dest.exists():
        tmp = dest.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, dest)
    g = cat.load(partner)
    g.add((cat.article_iri(partner, reference), cat.DHP[kind], Literal(name)))
    cat._save(partner, g)
    return {"partner": partner, "reference": reference, kind: name}


def file_path(name: str) -> Optional[Path]:
    """A file kept here (by its SHA-256 name), or None."""
    if not name or "/" in name or name.startswith("."):
        return None
    p = _files_dir() / name
    return p if p.is_file() else None


def _upload_files(partner: str, g: Graph, profile: str) -> int:
    """Upload the images and datasheets the catalogue names and this edge holds,
    once, by hash; the cloud answers `exists` for the ones it has."""
    local = []
    for prop in (cat.DHP.image, cat.DHP.datasheet):
        for name in {str(o) for o in g.objects(None, prop)}:
            path = file_path(name)
            if path is not None:
                sha, ext = name.split(".", 1)
                local.append((path, {"sha256": sha, "ext": ext, "size": path.stat().st_size}))
    sent = 0
    for i in range(0, len(local), 50):
        chunk = local[i:i + 50]
        grants = _call("market/uploads", {"seller": partner, "files": [f for _, f in chunk]}, profile)["files"]
        for (path, _), grant in zip(chunk, grants):
            if not grant.get("exists"):
                _http("PUT", grant["url"], path.read_bytes(), grant.get("headers"))
                sent += 1
    return sent

