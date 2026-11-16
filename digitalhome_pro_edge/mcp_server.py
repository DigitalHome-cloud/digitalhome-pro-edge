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
from typing import Dict, Optional

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

from .edge.mcp_tools import act, add_edge_tools, confirm_in_panel  # edge layer
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
def market_sellers() -> dict:
    """The sellers of the digitalhome.cloud marketplace (manufacturers,
    distributors, wholesalers, and digitalhome-cloud, the platform's curated
    catalogue): their catalogue version and size, whether each is a partner
    here (subscribed), when it was last synced, and whether the person who
    linked this edge may edit it (mayEdit). A subscribed seller is a partner
    with the same id: use it like any partner."""
    return _get("/api/market")


@server.tool()
def subscribe_to_seller(seller: str) -> dict:
    """Propose taking a marketplace seller as a partner here, and syncing its
    catalogue once."""
    return act(f"Subscribe to {seller} in the digitalhome.cloud marketplace", "POST",
               "/api/market/subscribe", {"seller": seller})


@server.tool()
def sync_with_market(partner: str, resolve: Optional[Dict[str, str]] = None) -> dict:
    """Propose syncing a partner's catalogue with its marketplace seller:
    changes on both sides are merged statement by statement. If the result
    lists conflicts (one fact, two values), ask the person and propose again
    with `resolve`: {conflict key: "mine" | "theirs"}. Changes made here are
    pushed only when the person who linked this edge is the seller's editor;
    otherwise they stay on this edge. Prices never leave."""
    return act(f"Sync {partner} with the marketplace", "POST", "/api/market/sync",
               _clean(partner=partner, resolve=resolve))


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
def new_workspace(title: str, home: str, country: str = "FR", connection: str = "") -> dict:
    """Start a workspace (a project) for a home. The home is a SmartHome ID
    from cloud_homes(); the edge must be linked, and the workspace belongs to
    that home on that connection (stage, prod …; default the current one).
    The country chooses the norm (FR: NF C 15-100, BE: RGIE); another
    country gets no norm checks."""
    return act(f"New workspace “{title}” for home {home}", "POST", "/api/workspaces",
               _clean(title=title, home=home, country=country, connection=connection))


@server.tool()
def attach_workspace(workspace: str, home: str, connection: str = "") -> dict:
    """Give a workspace its home on a connection: one listed as not attached
    (made before workspaces had an instance, or for a draft name). The
    design's identifiers are moved to that home."""
    return act(f"Attach workspace {workspace} to home {home}", "POST", f"{_ws(workspace)}/attach",
               _clean(home=home, connection=connection))


@server.tool()
def cloud_homes(connection: str = "") -> dict:
    """The person's homes on digitalhome.cloud for one connection (default the
    current one): SmartHome ID, address label, country. A new workspace must
    name one of them. linked=false: link the edge first."""
    return _get("/api/cloud-homes" + (f"?connection={_q(connection)}" if connection else ""))


@server.tool()
def set_workspace(workspace: str, title: str = "", status: str = "", built_under: str = "",
                  supply: str = "") -> dict:
    """Rename a workspace (its title; the id and folder stay), set its
    status (active, quoted, done, archived), record the norm edition the
    existing installation was built under, e.g. nfc15100-1977 (evidence for
    the report, not a verdict; only when the date of the work is known), or
    its supply system: 1N~230V (single phase), 3N~400V (three phase with
    neutral), 3~230V (three phase without neutral, older Belgian homes)."""
    return act(f"Update workspace {workspace}" + (f": supply {supply}" if supply else ""), "POST", _ws(workspace),
               _clean(title=title, status=status, built_under=built_under, supply=supply))


@server.tool()
def add_board(workspace: str, label: str, rows: int = 1, modules_per_row: int = 13) -> dict:
    """A distribution board with rows × modules per row (18 mm modules)."""
    return act(f"Add board “{label}” ({rows} × {modules_per_row} modules)", "POST",
               _ws(workspace) + "/boards", {"label": label, "rows": rows, "modules_per_row": modules_per_row})


@server.tool()
def set_board(workspace: str, board: str, rows: int = 0, modules_per_row: int = 0, built_under: str = "") -> dict:
    """Resize a board, or record the norm edition it was built under (e.g. nfc15100-1977)."""
    return act(f"Update board {board}", "POST", _ws(workspace) + f"/boards/{_q(board)}",
               _clean(rows=rows or None, modules_per_row=modules_per_row or None, built_under=built_under))


@server.tool()
def add_rcd(workspace: str, board: str, label: str, rated_current: float = 40,
            sensitivity_ma: float = 30, rcd_type: str = "A", to_verify: bool = False, poles: int = 2) -> dict:
    """A residual-current device on a board: rating in A, sensitivity in mA,
    type AC, A, F or B, poles 2 or 4 (as many modules). to_verify=True when
    a survey could not read, or a quote does not state, its rating or type:
    pass rated_current=0 and rcd_type="" for what is unknown, never a guess."""
    body = {"board": board, "label": label, "sensitivity_ma": sensitivity_ma, "to_verify": bool(to_verify),
            "rated_current": rated_current or None, "rcd_type": rcd_type or None, "poles": poles}
    what = f"{rated_current:g} A" if rated_current else "? A"
    return act(f"Add RCD “{label}” {what} {sensitivity_ma:g} mA type {rcd_type or '?'}", "POST", _ws(workspace) + "/rcds", body)


@server.tool()
def set_position(workspace: str, item: str, row: int = 0, slot: int = 0) -> dict:
    """Where an item sits on its board, as read on site: row (1 = top) and
    the module it starts at in that row (1 = left). item: an RCD, a device
    or a circuit (its breaker). row=0 clears it. The board strips follow it."""
    body = {"item": item, "row": row, "slot": slot} if row else {"item": item}
    return act(f"Place {item}" + (f" at row {row}, slot {slot}" if row else " nowhere"), "POST",
               _ws(workspace) + "/position", body)


@server.tool()
def label_draft(workspace: str) -> dict:
    """The labels as they would print, with what to look at first: per label
    its text, short line, pictogram, phase, module numbers and warnings
    (too_long, no_rating, to_verify, no_phase, duplicate, position); the
    cable labels (id, cable, length); the wizard's print settings."""
    return _get(_ws(workspace) + "/labels")


@server.tool()
def set_label(workspace: str, item: str, text: Optional[str] = None, short: Optional[str] = None,
              symbol: Optional[str] = None) -> dict:
    """What an item's label says instead of the design's: text (the name, at
    most 60 characters), short (the rating line, at most 20), symbol (a
    pictogram id from symbols()). Leave one out to keep it; "" goes back to
    the design's. The design's own label (rename) stays as it is."""
    body = {k: v for k, v in (("text", text), ("short", short), ("symbol", symbol)) if v is not None}
    what = ", ".join(f"{k} “{v}”" if v else f"{k} back to the design's" for k, v in body.items())
    return act(f"Label of {item}: {what}", "POST", _ws(workspace) + f"/items/{_q(item)}/label", body)


@server.tool()
def symbols() -> list:
    """The pictograms a label can carry: id and name."""
    from . import symbols as sy
    return sy.ALL


@server.tool()
def set_phase(workspace: str, item: str, phase: str = "") -> dict:
    """The phase a circuit, RCD or device is connected to (IEC 60445 names):
    L1, L2, L3 or L1L2L3 on 3N~400V; L1L2, L2L3, L3L1 or L1L2L3 on 3~230V. A
    circuit below a 2-pole RCD is on the RCD's phase unless it has its own.
    "" clears it. Only what was read on site, or a phase_plan() line the
    person agrees with; never a guess presented as read."""
    return act(f"Put {item} on {phase or 'no phase'}", "POST", _ws(workspace) + f"/items/{_q(item)}/phase",
               {"phase": phase})


@server.tool()
def phase_plan(workspace: str) -> dict:
    """A balanced split of the circuits over the phases, as a suggestion (it
    changes nothing): what is set stays, the rest is spread by rated
    current, a 2-pole RCD's circuits together. Propose each line with
    set_phase() only if the person wants the split."""
    return _get(_ws(workspace) + "/phase-plan")


@server.tool()
def add_device(workspace: str, board: str, kind: str, label: str,
               rated_current: float = 0, modules: int = -1, sensitivity_ma: float = 0,
               to_verify: bool = False) -> dict:
    """Another board device: contactor (e.g. day/night for the water heater),
    surge_protector, breaker or fuse (e.g. the 2 A control circuit),
    main_breaker (the supply's own, e.g. Enedis 500 mA 45 A: give
    sensitivity_ma; it takes no modules), bell_transformer, or unidentified
    (seen in a survey, not known yet). modules: leave out for the usual width."""
    return act(f"Add {kind.replace('_', ' ')} “{label}”", "POST", _ws(workspace) + "/devices",
               _clean(board=board, kind=kind, label=label, rated_current=rated_current or None,
                      modules=modules if modules >= 0 else None, sensitivity_ma=sensitivity_ma or None,
                      to_verify=to_verify or None))


@server.tool()
def add_circuit(workspace: str, label: str, rcd: str = "", circuit_type: str = "",
                rated_current: float = 0, cross_section: float = 0, points: int = 0, appliance: str = "",
                board: str = "", protection: str = "breaker", to_verify: bool = False, poles: int = 1,
                modules: int = 0) -> dict:
    """A circuit and its own breaker (or fuse) below an RCD. circuit_type:
    lighting, socket, cooking, water_heater, heating, floor_heating,
    ev_charger, dedicated (then say the appliance: washing_machine,
    dishwasher, dryer, oven, heat_pump …). Rating in A, section in mm²,
    points if known.

    Surveying an existing (old) board: give `board` instead of `rcd` when the
    circuit is below no RCD, protection="fuse" for a fuse holder, and leave
    out what was not read (type, rating, section): the circuit is then marked
    to verify. Never guess a value.

    poles: of the circuit's own breaker, 1 to 3 (as many modules). On a
    Belgian 3 × 230 V supply a single-phase circuit's breaker has 2 poles,
    a three-phase one (a hob) 3. modules: only for a compact breaker
    narrower than one module per pole (a 2-pole breaker in 1 module)."""
    what = " ".join(x for x in (f"{rated_current:g} A" if rated_current else "",
                                f"{cross_section:g} mm²" if cross_section else "") if x) or "to verify"
    return act(f"Add circuit “{label}” {what}", "POST", _ws(workspace) + "/circuits",
               _clean(rcd=rcd, board=board, label=label, circuit_type=circuit_type,
                      rated_current=rated_current or None, cross_section=cross_section or None,
                      points=points or None, appliance=appliance,
                      protection=protection if protection != "breaker" else None, to_verify=to_verify or None,
                      poles=poles if poles != 1 else None, modules=modules or None))


@server.tool()
def move_circuit(workspace: str, circuit: str, rcd: str, protection: str = "") -> dict:
    """Put a circuit below another RCD (its breaker or fuse moves to that
    RCD's board). protection="breaker" when a fuse holder is replaced by a
    breaker, as in a new board; its rating stays as it was."""
    body = {"rcd": rcd, **({"protection": protection} if protection else {})}
    return act(f"Move circuit {circuit} to RCD {rcd}" + (f" as a {protection}" if protection else ""), "POST",
               _ws(workspace) + f"/circuits/{_q(circuit)}/move", body)


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


# ------------------------------------------------------------- history ----
# Every saved state of a design is a numbered revision (ADR-0009).

@server.tool()
def revisions(workspace: str) -> list:
    """Every saved state of the design, newest first: number, when, who,
    through what (page, chat, mcp), a one-line summary, and its tags. A
    frozen tag is a baseline (e.g. the as-is installation)."""
    return _get(_ws(workspace) + "/revisions")


@server.tool()
def diff(workspace: str, from_revision: str, to_revision: str = "latest") -> dict:
    """What changed between two revisions (numbers or tag names, e.g. the
    baseline "As-is 1986" and "latest"): nodes added, removed, and changed
    with each property's values before and after."""
    return _get(_ws(workspace) + "/diff?" + urllib.parse.urlencode({"from": from_revision, "to": to_revision}))


@server.tool()
def tag_revision(workspace: str, revision: int, name: str, frozen: bool = False) -> dict:
    """Name a revision. frozen=True makes it a baseline that never moves —
    only for the installation as surveyed, or as delivered."""
    return act(f"Tag revision {revision} of {workspace} \"{name}\"" + (" (baseline)" if frozen else ""), "POST",
               _ws(workspace) + f"/revisions/{int(revision)}/tag", {"name": name, "frozen": bool(frozen)})


@server.tool()
def restore(workspace: str, revision: int) -> dict:
    """Make the design what it was at a revision. History is kept: this adds
    a new revision with that content."""
    return act(f"Restore {workspace} to revision {revision}", "POST",
               _ws(workspace) + f"/revisions/{int(revision)}/restore", {})


# ---- the home's configurations and vault in the cloud (ADR-0010) ----------

@server.tool()
def configuration(workspace: str) -> dict:
    """The home's configurations in the cloud: the live version, every
    version before it (live, superseded, legacy), the planning options; and
    what this workspace is linked to (basedOn, option)."""
    return _get(_ws(workspace) + "/configuration")


@server.tool()
def create_option(workspace: str, label: str, based_on: str = "") -> dict:
    """A planning option in the cloud for the home, based on a version
    (default: the live one); this workspace becomes its checkout."""
    return act(f"Create planning option “{label}” for {workspace}", "POST",
               _ws(workspace) + "/configuration/option", {"label": label, "based_on": based_on})


@server.tool()
def pull_option(workspace: str, option: str = "") -> dict:
    """Replace this workspace's design with the option's graph in the cloud
    (a new revision; the old one stays in the history)."""
    return act(f"Pull {option or 'the option'} into {workspace}", "POST",
               _ws(workspace) + "/configuration/pull", {"option": option} if option else {})


@server.tool()
def push_option(workspace: str) -> dict:
    """Save this workspace's design as its option's next version in the
    cloud. A conflict means someone saved since: pull first."""
    return act(f"Push {workspace} to its planning option", "POST", _ws(workspace) + "/configuration/push", {})


def _person_only(what: str, method: str, path: str, body: dict | None = None) -> dict:
    """Publishing a first live configuration and promoting an option cannot
    be undone: only a person does them. In the chat panel this proposes;
    elsewhere it points to the page."""
    if confirm_in_panel():
        return act(what, method, path, body or {})
    return {"status": "not done", "why": f"{what} is a person's act: do it on the page (History → Cloud), "
            "or propose it in the edge's chat panel."}


@server.tool()
def publish_first_live(workspace: str) -> dict:
    """Propose that this workspace's design (e.g. the as-is survey) becomes
    the home's first live configuration, <homeId>-0001-0000."""
    return _person_only(f"Publish {workspace} as the home's first live configuration", "POST",
                        _ws(workspace) + "/configuration/publish")


@server.tool()
def promote_option(workspace: str) -> dict:
    """Propose that this workspace's option becomes the home's live
    configuration (the next major; the current one becomes legacy). Only
    when the work is done and delivered."""
    return _person_only(f"Promote the option of {workspace} to live", "POST", _ws(workspace) + "/configuration/promote")


@server.tool()
def withdraw_version(workspace: str, version: str = "") -> dict:
    """Propose taking back a live major that changed nothing (an option
    promoted unchanged). The cloud refuses any version that changed
    something; the one before it becomes live again."""
    return _person_only(f"Withdraw {version or 'the live version'} of {workspace}", "POST",
                        _ws(workspace) + "/configuration/withdraw", {"version": version} if version else {})


@server.tool()
def tag_vault_items(workspace: str, add: list[str] | None = None, remove: list[str] | None = None,
                    items: list[str] | None = None) -> dict:
    """Tag vault items with the configuration versions they document (one
    photo may show several): add / remove version or option ids, or the
    short form "0001-0000". items: names or SHA-256s; none means all."""
    return act(f"Tag {len(items) if items else 'every'} vault item(s) of {workspace}", "POST",
               _ws(workspace) + "/vault/tag", {"items": items or [], "add": add or [], "remove": remove or []})


@server.tool()
def vault(workspace: str, config_version: str = "") -> dict:
    """The home's vault: photos and documents, each with the configuration
    versions or options it documents (its tags); config_version filters."""
    return _get(_ws(workspace) + "/vault" + (f"?configVersion={_q(config_version)}" if config_version else ""))


@server.tool()
def upload_to_vault(workspace: str, config_version: str = "", names: list[str] | None = None,
                    dry_run: bool = True) -> dict:
    """The workspace's files (files/) to the home's vault, each once.
    dry_run=True (default) says what would go up; then call again with
    dry_run=False. Photos can show private details: only the home's owners
    see the vault, but ask before uploading a person's files."""
    body = {"config_version": config_version, "names": names or [], "dry_run": dry_run}
    if dry_run:
        web.ensure_server()
        return web.call("POST", _ws(workspace) + "/vault/upload", body)
    return act(f"Upload {len(names) if names else 'the'} files of {workspace} to the home's vault", "POST",
               _ws(workspace) + "/vault/upload", body)


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
