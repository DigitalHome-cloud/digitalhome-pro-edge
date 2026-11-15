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

from flask import abort, jsonify, render_template, request

from . import designs as dz
from . import labels as lb
from . import partners as pt
from . import selection as sel
from .core import server
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
    return run(sel.set, **fields("workspace", "item"))


@app.get("/api/homes")
def homes():
    return run(designs().homes)


@app.get("/api/workspaces")
def workspaces():
    return run(designs().workspaces)


@app.post("/api/workspaces")
def new_workspace():
    return run(designs().new_workspace, **fields("title", "home", "country"))


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
    return lb.sheet(d, request.host_url)


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
# file import and the credentials come from the page only: neither is in the
# chat's allowed calls, and credentials are never returned.

@app.get("/api/partners")
def partners():
    return run(pt.capabilities)


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



# ------------------------------------------------------------------ main ----

def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(prog="digitalhome-pro-edge-web",
                                 description=__doc__.strip().splitlines()[0])
    server.add_server_args(ap)
    ap.add_argument("--dir", default=ws.FOLDERS[ws.USER].name,
                    help="your own notes (default: ./mydocs)")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    ws.configure(user_dir=args.dir)
    lines = [f"  {f['label'].lower():<13} {f['path']}" for f in ws.folders()]
    edge_routes.start_background()  # edge layer
    return server.serve(app, args, lines=lines)


if __name__ == "__main__":
    raise SystemExit(main())
