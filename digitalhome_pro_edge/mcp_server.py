#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
mcp_server.py — MCP access to digitalhome-pro-edge.

Exposes the tool over stdio, so an agent can work on the same data a person has
open in the browser. The pure engine calls run in-process; everything that
touches files goes through the web server (core.mcp_bridge), which is started
on demand, so browser and agent never disagree about what is on disk.

    digitalhome-pro-edge-mcp                               # talks to 127.0.0.1:8773
    digitalhome-pro-edge-mcp --port 9000
    digitalhome-pro-edge-mcp --no-autostart                # fail instead of starting one
    python3 -m digitalhome_pro_edge.mcp_server            # the same, from a checkout

Register it in .mcp.json (a checkout already has one), or install the Claude
Code plugin, which brings this server and the skill together.

Nothing may be written to stdout: that is the MCP transport. Log to stderr.
"""

from __future__ import annotations

import argparse
import urllib.parse

from mcp.server.mcpserver import MCPServer

from .core import mcp_bridge as web

server = MCPServer(
    name="digitalhome-pro-edge",
    instructions=(
        "digitalhome.pro designs the electrical installation of a home with you. "
        "A home has one or more workspaces, each an active project (a new board, "
        "a kitchen) holding one design: boards, RCDs, circuits with their own "
        "breakers, rooms and points. Read with workspaces() and design(); change "
        "with the add_/set_/move_/rename/remove tools, each of which the person "
        "confirms. After changes, call report() and explain what it finds in the "
        "person's language: a design that breaks a norm is saved and reported, "
        "never refused. bom() is the bill of materials, priced where a partner "
        "reference is set and the partner has a price (API or imported file); "
        "find references with partners() and partner_search()."
    ),
)

web.add_core_tools(server)

from .edge.mcp_tools import act, add_edge_tools  # edge layer
add_edge_tools(server)


def _q(x: str) -> str:
    return urllib.parse.quote(x, safe="")


def _ws(ws: str) -> str:
    return f"/api/workspaces/{_q(ws)}"


def _get(path: str):
    web.ensure_server()
    return web.call("GET", path)


def _clean(**kw) -> dict:
    return {k: v for k, v in kw.items() if v is not None and v != ""}


# ------------------------------------------------------------- reading ----

@server.tool()
def selection() -> dict:
    """What the person has open on the page: a workspace, an item in it, and
    the file they last dropped for you (read it with read_file)."""
    return _get("/api/selection")


@server.tool()
def workspaces() -> list:
    """Every workspace on this edge: its home, title, status, and how many
    boards and circuits its design has."""
    return _get("/api/workspaces")


@server.tool()
def design(workspace: str) -> dict:
    """One workspace's design: boards (rows, modules, used) → RCDs → circuits
    (type, rating, section, points, breaker) → points; other devices on each
    board; rooms and what is placed in them. Ids are what the change tools take."""
    return _get(_ws(workspace))


@server.tool()
def report(workspace: str, lang: str = "en") -> dict:
    """What in the design breaks a rule, as sentences in en, fr or de: the NF C
    15-100 shapes and the board rules (at least two 30 mA RCDs, at most 8
    circuits per RCD, type A where needed, about 20 % free modules)."""
    return _get(_ws(workspace) + f"/report?lang={_q(lang)}")


@server.tool()
def bom(workspace: str) -> dict:
    """The bill of materials, counted per kind and rating, with unit prices and
    totals where a partner reference is set and priced; each unpriced line says why."""
    return _get(_ws(workspace) + "/bom")


@server.tool()
def partners() -> dict:
    """The person's partners (manufacturers, distributors, wholesalers) and,
    for each, the channel in use (api, file or none) and the imported file;
    also where the list is kept (this computer or the cloud), the API
    connectors and the file formats this edge reads. Never credentials."""
    return _get("/api/partners")


@server.tool()
def add_partner(id: str, name: str, kind: str = "distributor", formats: list[str] | None = None,  # noqa: A002
                api: str = "", note: str = "", markets: list[str] | None = None) -> dict:
    """Add a partner to the person's private list: an id (lowercase, e.g.
    "acme-elec"), its name, kind (manufacturer, distributor, wholesaler), the
    file formats it delivers (csv, bmecat, datanorm) and an API connector if
    one exists, and the markets its articles are sold for by default (EU, FR,
    DE …). Credentials and files are set up on the page, never here."""
    return act(f"Add partner “{name}”", "POST", "/api/partners",
               _clean(id=id, name=name, kind=kind, formats=formats or ["csv"], api=api, note=note,
                      markets=markets or None))


@server.tool()
def inbox() -> list:
    """Files the person gave the chat on the page, newest first: id, name,
    size, the kind found in its content (bmecat, datanorm, csv, xlsx, turtle,
    json, pdf, quote, text) and a short note. selection() names the one just
    dropped."""
    return _get("/api/inbox")


@server.tool()
def read_file(file: str, offset: int = 0, limit: int = 20000) -> dict:
    """The text of an inbox file, in slices (more=true: read on from
    offset+limit). A PDF is its extracted text, a workbook its first sheet as
    semicolon-separated rows. Decide from the content what it is for:
    articles → import_file_to_partner; a quote, a plan, a description or a
    model → propose the design changes it implies with the design tools, one
    by one, and say which facts came from the file."""
    return _get(f"/api/inbox/{_q(file)}?offset={int(offset)}&limit={int(limit)}")


@server.tool()
def import_file_to_partner(file: str, partner: str, fmt: str = "") -> dict:
    """Propose importing an inbox file's articles for a registered partner
    (csv, bmecat, datanorm, or a workbook read as csv). Prices stay private
    on this computer; the product facts go into the partner's catalogue."""
    return act(f"Import {file} for {partner}", "POST", f"/api/inbox/{_q(file)}/import-partner",
               _clean(partner=partner, fmt=fmt))


@server.tool()
def cloud_catalogue(query: str = "", limit: int = 50) -> dict:
    """The device catalogue of digitalhome.cloud as last synced to this edge
    (partner "digitalhome-cloud"): when it was synced, from which connection,
    and the models matching `query` (model number, label, brand, device
    type). Use partner "digitalhome-cloud" and a model number like any
    article."""
    return _get(f"/api/cloud-catalogue?q={_q(query)}&limit={int(limit)}")


@server.tool()
def sync_cloud_catalogue(full: bool = False) -> dict:
    """Propose fetching the models changed on digitalhome.cloud since the last
    sync (full=true: all of them again)."""
    return act("Sync the digitalhome.cloud catalogue" + (" (all models)" if full else ""), "POST",
               "/api/cloud-catalogue/sync", {"full": bool(full)})


@server.tool()
def publish_to_cloud_catalogue(partner: str, reference: str, brand: str, device_type: str,
                               category: str = "", description: str = "", power_source: str = "") -> dict:
    """Propose publishing one article of a partner's catalogue to the
    digitalhome.cloud catalogue, as a device model: its reference becomes the
    model number, its markets the region, its standards the standards. Give a
    brand and a device type (e.g. "Hager", "RCD"); category one of
    COMPUTING_IT, CONTROLLERS_AUTOMATION, FACILITIES_APPLIANCES,
    MEDIA_COMMUNICATION, SECURITY_MONITORING; power source FIXED, SOCKET,
    BATTERY or ACCU. No price is ever sent. The cloud accepts it only when
    the person who linked this edge is a catalogue admin."""
    return act(f"Publish {partner} {reference} to the digitalhome.cloud catalogue", "POST",
               "/api/cloud-catalogue/publish",
               _clean(partner=partner, reference=reference, brand=brand, device_type=device_type,
                      category=category, description=description, power_source=power_source))


@server.tool()
def article(partner: str, reference: str, norm: str = "") -> dict:
    """An article in a partner's catalogue: its label, the markets it is sold
    for (EU, FR …), the installation norms it is approved for and the product
    standards it meets; with a norm (e.g. nfc15100), whether it may be used
    under it: yes, no or unknown, and why."""
    q = f"reference={_q(reference)}" + (f"&norm={_q(norm)}" if norm else "")
    return _get(f"/api/partners/{_q(partner)}/article?{q}")


@server.tool()
def set_article_norms(partner: str, reference: str, usable_in: list[str] | None = None,
                      approved_for: list[str] | None = None, conforms_to: list[str] | None = None) -> dict:
    """Say where an article may be used, from its datasheet: markets (EU, FR,
    BE, DE …), installation norms it is approved for (nfc15100 …) and product
    standards (EN 61008-1 …). A list you pass replaces that fact; one you
    leave out stays. The report then warns when a design uses it elsewhere."""
    body = {"reference": reference}
    for k, v in (("usable_in", usable_in), ("approved_for", approved_for), ("conforms_to", conforms_to)):
        if v is not None:
            body[k] = v
    return act(f"Norms of {partner} {reference}", "POST", f"/api/partners/{_q(partner)}/article", body)


@server.tool()
def partner_search(partner: str, query: str, limit: int = 20) -> list:
    """Articles in a partner's imported file matching every word of the query
    (reference, description, EAN, ETIM class), with their prices."""
    return _get(f"/api/partners/{_q(partner)}/search?q={_q(query)}&limit={int(limit)}")


# ------------------------------------------------------------- changing ----

@server.tool()
def new_workspace(title: str, home: str, country: str = "FR") -> dict:
    """Start a workspace (a project) for a home. The home is a SmartHome ID
    from cloud_homes(); only an edge not linked yet may use a draft name.
    The country chooses the norm (FR: NF C 15-100)."""
    return act(f"New workspace “{title}” for home {home}", "POST", "/api/workspaces",
               {"title": title, "home": home, "country": country})


@server.tool()
def cloud_homes() -> dict:
    """The person's homes on digitalhome.cloud (SmartHome ID, address label,
    country), which a new workspace must name. linked=false: the edge is not
    linked yet, and a workspace can only be a draft for a local name."""
    return _get("/api/cloud-homes")


@server.tool()
def set_workspace(workspace: str, title: str = "", status: str = "") -> dict:
    """Rename a workspace, or set its status: active, quoted, done, archived."""
    return act(f"Update workspace {workspace}", "POST", _ws(workspace), _clean(title=title, status=status))


@server.tool()
def add_board(workspace: str, label: str, rows: int = 1, modules_per_row: int = 13) -> dict:
    """A distribution board with rows × modules per row (18 mm modules)."""
    return act(f"Add board “{label}” ({rows} × {modules_per_row} modules)", "POST",
               _ws(workspace) + "/boards", {"label": label, "rows": rows, "modules_per_row": modules_per_row})


@server.tool()
def set_board(workspace: str, board: str, rows: int = 0, modules_per_row: int = 0) -> dict:
    """Resize a board."""
    return act(f"Resize board {board}", "POST", _ws(workspace) + f"/boards/{_q(board)}",
               _clean(rows=rows or None, modules_per_row=modules_per_row or None))


@server.tool()
def add_rcd(workspace: str, board: str, label: str, rated_current: float = 40,
            sensitivity_ma: float = 30, rcd_type: str = "A") -> dict:
    """A residual-current device (2 modules) on a board: rating in A,
    sensitivity in mA, type AC, A, F or B."""
    return act(f"Add RCD “{label}” {rated_current:g} A {sensitivity_ma:g} mA type {rcd_type}", "POST",
               _ws(workspace) + "/rcds", {"board": board, "label": label, "rated_current": rated_current,
                                          "sensitivity_ma": sensitivity_ma, "rcd_type": rcd_type})


@server.tool()
def add_device(workspace: str, board: str, kind: str, label: str,
               rated_current: float = 0, modules: int = 0) -> dict:
    """Another board device: contactor (e.g. day/night for the water heater),
    surge_protector, or breaker (e.g. the 2 A control circuit)."""
    return act(f"Add {kind.replace('_', ' ')} “{label}”", "POST", _ws(workspace) + "/devices",
               _clean(board=board, kind=kind, label=label, rated_current=rated_current or None,
                      modules=modules or None))


@server.tool()
def add_circuit(workspace: str, rcd: str, label: str, circuit_type: str, rated_current: float,
                cross_section: float, points: int = 0, appliance: str = "") -> dict:
    """A circuit and its own breaker below an RCD. circuit_type: lighting,
    socket, cooking, water_heater, heating, floor_heating, ev_charger,
    dedicated (then say the appliance: washing_machine, dishwasher, dryer,
    oven, heat_pump …). Rating in A, section in mm², points if known."""
    return act(f"Add circuit “{label}” {rated_current:g} A {cross_section:g} mm²", "POST",
               _ws(workspace) + "/circuits",
               _clean(rcd=rcd, label=label, circuit_type=circuit_type, rated_current=rated_current,
                      cross_section=cross_section, points=points or None, appliance=appliance))


@server.tool()
def move_circuit(workspace: str, circuit: str, rcd: str) -> dict:
    """Put a circuit below another RCD."""
    return act(f"Move circuit {circuit} to RCD {rcd}", "POST",
               _ws(workspace) + f"/circuits/{_q(circuit)}/move", {"rcd": rcd})


@server.tool()
def add_room(workspace: str, label: str, level: str = "") -> dict:
    """A room, optionally on a level (ground floor, first floor …)."""
    return act(f"Add room “{label}”", "POST", _ws(workspace) + "/rooms", _clean(label=label, level=level))


@server.tool()
def add_point(workspace: str, circuit: str, kind: str, label: str, room: str = "") -> dict:
    """A point on a circuit (socket, light, switch, appliance, outlet), in a room."""
    return act(f"Add {kind} “{label}”", "POST", _ws(workspace) + "/points",
               _clean(circuit=circuit, kind=kind, label=label, room=room))


@server.tool()
def place(workspace: str, item: str, room: str) -> dict:
    """Say which room an item is in."""
    return act(f"Place {item} in {room}", "POST", _ws(workspace) + f"/items/{_q(item)}/place", {"room": room})


@server.tool()
def rename(workspace: str, item: str, label: str) -> dict:
    """Give an item a new label."""
    return act(f"Rename {item} to “{label}”", "POST", _ws(workspace) + f"/items/{_q(item)}/rename",
               {"label": label})


@server.tool()
def set_reference(workspace: str, item: str, partner: str, reference: str) -> dict:
    """The partner article for an item (a board, RCD, breaker, device or
    point), so the BOM can price it. Find it with partner_search()."""
    return act(f"Use {partner} {reference} for {item}", "POST",
               _ws(workspace) + f"/items/{_q(item)}/reference", {"partner": partner, "reference": reference})


@server.tool()
def remove(workspace: str, item: str) -> dict:
    """Remove an item. A circuit takes its breaker and points with it; an RCD
    or a board is refused while something still hangs on it."""
    return act(f"Remove {item}", "DELETE", _ws(workspace) + f"/items/{_q(item)}", {})


def main() -> int:
    ap = argparse.ArgumentParser(prog="digitalhome-pro-edge-mcp",
                                 description=__doc__.strip().splitlines()[0])
    ap.add_argument("--url", help="web server base URL (overrides --port)")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--no-autostart", action="store_true",
                    help="fail rather than start a web server that is not running")
    args = ap.parse_args()
    web.configure(port=args.port, url=args.url, autostart=not args.no_autostart)
    web.log(f"serving MCP over stdio, web server at {web.BASE}")
    web.start_heartbeat()
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
