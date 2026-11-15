#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
app.py — the digitalhome.pro page and its API: workspaces and their designs
(designs.py), labels (labels.py) and partner sources (partners.py).

    digitalhome-pro-edge-web                       # http://127.0.0.1:8773
    digitalhome-pro-edge-web --port 9000
    python3 -m digitalhome_pro_edge.app            # the same, from a checkout

The page, stop, restart, update and the About box come from core.server; the
chat and the cloud link from the edge layer.
"""

from __future__ import annotations

import argparse
import sys

from flask import abort, jsonify, render_template, request, send_file

from . import catalogue as cat
from . import market as mk
from . import designs as dz
from . import homes as hm
from . import inbox as ib
from . import labels as lb
from . import partners as pt
from . import selection as sel
from .core import server
from .edge import cloud
from .edge import knowledge as kn
from .core import workspace as ws

app = server.create_app(__name__)

from .edge import routes as edge_routes  # edge layer
edge_routes.install(app)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024   # partner catalogues are large


def body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, "expected a JSON object body")
    return data


# ------------------------------------------------------------------ page ----

@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.get("/favicon.ico")
def favicon():
    """Browsers ask for this by name whatever the page links to."""
    return app.send_static_file("favicon.svg")


# ------------------------------------------------------------- designs ----
#
# A home has workspaces (active projects); each holds one design (designs.py).
# Every change goes through Designs, so the structural shapes refuse a broken
# file (422) while a norm finding is only reported.

_designs = None


def designs() -> dz.Designs:
    global _designs
    if _designs is None:
        _designs = dz.Designs()
    return _designs


def run(fn, *args, **kwargs):
    try:
        return jsonify(fn(*args, **kwargs))
    except dz.NotFound as e:
        return jsonify({"errors": [str(e)]}), 404
    except kn.Invalid as e:
        return jsonify({"errors": e.messages}), 422
    except (ValueError, TypeError) as e:
        return jsonify({"errors": [str(e)]}), 400


def fields(*names: str) -> dict:
    b = body()
    return {k: b[k] for k in names if k in b}


@app.get("/api/selection")
def get_selection():
    return jsonify(sel.get())


@app.post("/api/selection")
def set_selection():
    return run(sel.set, **fields("workspace", "item", "file"))


@app.get("/api/homes")
def homes():
    return run(designs().homes)


@app.get("/api/workspaces")
def workspaces():
    return run(designs().workspaces)


@app.get("/api/cloud-homes")
def cloud_homes():
    return jsonify(hm.cloud_homes(refresh=request.args.get("refresh") == "1"))


@app.post("/api/workspaces")
def new_workspace():
    def make(title: str = "", home: str = "", country: str = "FR"):
        hm.check((home or "").strip())
        return designs().new_workspace(title, home, country)
    return run(make, **fields("title", "home", "country"))


@app.get("/api/workspaces/<ws>")
def design(ws: str):
    return run(designs().design, ws)


@app.post("/api/workspaces/<ws>")
def set_workspace(ws: str):
    return run(designs().set_workspace, ws, **fields("title", "status"))


@app.get("/api/workspaces/<ws>/report")
def report(ws: str):
    return run(designs().report, ws, request.args.get("lang", "en"))


@app.get("/api/workspaces/<ws>/bom")
def bom(ws: str):
    def priced():
        return pt.price_bom(designs().bom(ws))
    return run(priced)


@app.get("/api/workspaces/<ws>/export.ttl")
def export(ws: str):
    try:
        ttl = designs().export(ws)
    except dz.NotFound:
        abort(404)
    return app.response_class(ttl, mimetype="text/turtle",
                              headers={"Content-Disposition": f'attachment; filename="{ws}.ttl"'})


@app.get("/workspaces/<ws>/labels")
def labels(ws: str):
    try:
        d = designs().design(ws)
    except dz.NotFound:
        abort(404)
    try:
        skip = int(request.args.get("skip", 0))
        module = float(request.args.get("module", lb.MODULE_MM))
    except ValueError:
        abort(400, "skip and module are numbers")
    return lb.sheet(d, request.host_url, request.args.get("layout", "grid"), skip, module)


@app.post("/api/workspaces/<ws>/boards")
def add_board(ws: str):
    return run(designs().add_board, ws, **fields("label", "rows", "modules_per_row"))


@app.post("/api/workspaces/<ws>/boards/<board>")
def set_board(ws: str, board: str):
    return run(designs().set_board, ws, board, **fields("rows", "modules_per_row"))


@app.post("/api/workspaces/<ws>/rcds")
def add_rcd(ws: str):
    return run(designs().add_rcd, ws, **fields("board", "label", "rated_current", "sensitivity_ma", "rcd_type"))


@app.post("/api/workspaces/<ws>/devices")
def add_device(ws: str):
    return run(designs().add_device, ws, **fields("board", "kind", "label", "rated_current", "modules"))


@app.post("/api/workspaces/<ws>/circuits")
def add_circuit(ws: str):
    return run(designs().add_circuit, ws, **fields("rcd", "label", "circuit_type", "rated_current",
                                                   "cross_section", "points", "appliance", "dedicated"))


@app.post("/api/workspaces/<ws>/circuits/<circuit>/move")
def move_circuit(ws: str, circuit: str):
    return run(designs().move_circuit, ws, circuit, **fields("rcd"))


@app.post("/api/workspaces/<ws>/rooms")
def add_room(ws: str):
    return run(designs().add_room, ws, **fields("label", "level"))


@app.post("/api/workspaces/<ws>/points")
def add_point(ws: str):
    return run(designs().add_point, ws, **fields("circuit", "kind", "label", "room"))


@app.post("/api/workspaces/<ws>/items/<item>/place")
def place(ws: str, item: str):
    return run(designs().place, ws, item, **fields("room"))


@app.post("/api/workspaces/<ws>/items/<item>/rename")
def rename(ws: str, item: str):
    return run(designs().rename, ws, item, **fields("label"))


@app.post("/api/workspaces/<ws>/items/<item>/reference")
def set_reference(ws: str, item: str):
    return run(designs().set_reference, ws, item, **fields("partner", "reference"))


@app.delete("/api/workspaces/<ws>/items/<item>")
def remove(ws: str, item: str):
    return run(designs().remove, ws, item)


# ------------------------------------------------------------ partners ----
#
# Product data and prices per partner, by API or by file (partners.py). The
# partner list and the credentials are private: kept on this computer or in
# the connected cloud. The chat may propose adding a partner; file imports,
# credentials and where they are stored come from the page only, and
# credentials are never returned.

# The digitalhome.cloud marketplace (market.py, ADR-0006): a partner with the
# same id as a seller syncs its catalogue with the seller's graph. Subscribe
# and sync change things, so the chat only proposes them.

def cloud_run(fn, *args, **kwargs):
    try:
        return run(fn, *args, **kwargs)
    except cloud.NotLinked as e:
        return jsonify({"errors": [f"{e} — link this edge to digitalhome.cloud first (Connections)"]}), 409
    except PermissionError as e:
        return jsonify({"errors": [str(e)]}), 403
    except cloud.CloudError as e:
        return jsonify({"errors": [str(e)]}), 502


@app.get("/api/market")
def market_sellers():
    return cloud_run(lambda: {"sellers": mk.sellers()})


@app.post("/api/market/subscribe")
def market_subscribe():
    return cloud_run(mk.subscribe, str(body().get("seller", "")))


@app.post("/api/market/sync")
def market_sync():
    b = body()
    resolve = b.get("resolve") or None
    if resolve is not None and not (isinstance(resolve, dict)
                                    and all(v in ("mine", "theirs") for v in resolve.values())):
        return jsonify({"errors": ["resolve maps a conflict's key to \"mine\" or \"theirs\""]}), 400
    return cloud_run(mk.sync, str(b.get("partner", "")), resolve)


@app.post("/api/partners/<partner>/articles/file")
def partner_article_file(partner: str):
    f = request.files.get("file")
    if f is None:
        return jsonify({"errors": ["send a file"]}), 400
    return run(mk.attach, partner, request.form.get("reference", ""), f.read(mk.MAX_FILE + 1), f.filename or "")


@app.get("/api/market/files/<name>")
def market_file(name: str):
    path = mk.file_path(name)
    if path is None:
        abort(404)
    return send_file(path, max_age=31536000)


@app.get("/api/partners")
def partners():
    return run(pt.capabilities)


@app.post("/api/partners")
def add_partner():
    return run(pt.add_partner, **fields("id", "name", "kind", "formats", "api", "note", "markets"))


@app.delete("/api/partners/<partner>")
def remove_partner(partner: str):
    return run(pt.remove_partner, partner)


@app.get("/api/partners/<partner>/catalogue.ttl")
def partner_catalogue(partner: str):
    if pt.partner(partner) is None:
        abort(404)
    return app.response_class(cat.turtle(partner), mimetype="text/turtle")


@app.get("/api/partners/<partner>/article")
def partner_article(partner: str):
    ref = request.args.get("reference", "")
    norm = request.args.get("norm", "")
    def got():
        art = cat.article(partner, ref)
        if art is None:
            raise dz.NotFound(f"{ref} is not in {partner}'s catalogue")
        if norm:
            art["usable"] = cat.usable(partner, ref, cat._norm(norm), request.args.get("country", ""))
        return art
    return run(got)


@app.post("/api/partners/<partner>/article")
def partner_set_article(partner: str):
    if pt.partner(partner) is None:
        return jsonify({"errors": [f"{partner} is not in the partner list"]}), 404
    return run(cat.set_article, partner, **fields("reference", "usable_in", "approved_for", "conforms_to", "label"))


@app.post("/api/partners/store")
def partner_store():
    return run(pt.set_store, **fields("where", "profile"))


@app.get("/api/partners/<partner>/search")
def partner_search(partner: str):
    return run(pt.search, partner, request.args.get("q", ""), int(request.args.get("limit", 20)))


@app.get("/api/partners/<partner>/price")
def partner_price(partner: str):
    return run(lambda: pt.price(partner, request.args.get("reference", "")) or {})


@app.post("/api/partners/<partner>/import")
def partner_import(partner: str):
    f = request.files.get("file")
    if f is None:
        return jsonify({"errors": ["send the file as multipart field 'file'"]}), 400
    return run(pt.import_file, partner, request.form.get("format", ""), f.read(), f.filename or "")


@app.post("/api/partners/<partner>/credentials")
def partner_credentials(partner: str):
    return run(pt.set_credentials, partner, body())


@app.delete("/api/partners/<partner>/credentials")
def partner_forget(partner: str):
    return run(pt.forget_credentials, partner)



# --------------------------------------------------------------- inbox ----
#
# Files given to the chat (inbox.py, ADR-0004). Uploading is the person's act
# on the page; the chat reads them and proposes what to do with them.

@app.get("/api/inbox")
def inbox_files():
    return jsonify(ib.files())


@app.post("/api/inbox")
def inbox_add():
    f = request.files.get("file")
    if f is None:
        return jsonify({"errors": ["send the file as multipart field 'file'"]}), 400
    def added():
        m = ib.add(f.filename or "", f.read())
        cur = sel.get()
        sel.set(cur.get("workspace", ""), cur.get("item", ""), m["id"])
        return m
    return run(added)


@app.get("/api/inbox/<fid>")
def inbox_read(fid: str):
    return run(ib.read, fid, request.args.get("offset", 0, type=int),
               request.args.get("limit", ib.TEXT_LIMIT, type=int))


@app.delete("/api/inbox/<fid>")
def inbox_remove(fid: str):
    return run(ib.remove, fid)


@app.post("/api/inbox/<fid>/import-partner")
def inbox_import_partner(fid: str):
    return run(ib.import_partner, fid, **fields("partner", "fmt"))


# ------------------------------------------------------------------ main ----

def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(prog="digitalhome-pro-edge-web",
                                 description=__doc__.strip().splitlines()[0])
    server.add_server_args(ap)
    ap.add_argument("--dir", default=ws.FOLDERS[ws.USER].name,
                    help="your own notes (default: ./mydocs)")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    ws.configure(user_dir=args.dir)
    # One folder per workspace (ADR-0007): the edge layer's routes and first
    # start build kn.KnowledgeBase() when called, so binding it here gives
    # them the same layout as the designs.
    dz.migrate_layout()
    kn.KnowledgeBase = dz.WorkspaceKB
    lines = [f"  {f['label'].lower():<13} {f['path']}" for f in ws.folders()]
    edge_routes.start_background()  # edge layer
    return server.serve(app, args, lines=lines)


if __name__ == "__main__":
    raise SystemExit(main())
