# SPDX-License-Identifier: GPL-3.0-or-later
"""
settings.py — what makes this edge yours. THE TOOL OWNS THIS FILE: the edge
layer writes it once and never again (`copier update` leaves it alone).

Everything else in edge/ belongs to the layer and is replaced on update, so
put product decisions here, not there.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Tuple

# -- who this edge is ----------------------------------------------------------

TOOL = "digitalhome-pro-edge"
PACKAGE = "digitalhome_pro_edge"
TITLE = "digitalhome.pro"
KIND = "human"                 # human | iot | robot
CLOUD_NAME = "DigitalHome.Cloud"          # "the Mediathek", "DigitalHome" …
TENANT_NOUN = "home"        # what people call a tenant here
SPACE_NOUN = "workspace"          # … and a space
ENV = "DHPRO_EDGE"                 # DHPRO_EDGE_EDGE_STATE, DHPRO_EDGE_CHAT_CONFIRM …

# The client id and scope this edge asks for when it pairs (DH-SPEC-100).
CLIENT_ID = TOOL
SCOPE = "edge.link edge.telemetry graphs.write"

# -- knowledge (the A-Boxes, ADR-0007 in the cloud) ---------------------------

# Copy the cloud's packages/ontology here (tbox/*.ttl, shapes/*.ttl): this
# edge validates a merged A-Box with the same shapes the cloud does.
ONTOLOGY = Path(__file__).resolve().parent / "ontology"

# Facts a thing has at most one of. Two different values from two sides are
# a CONFLICT the person resolves, instead of both being kept.
_DHC = "https://digitalhome.cloud/ontology#"
_DHP = "https://digitalhome.cloud/pro#"
SINGLE_VALUED: List[str] = [
    "https://schema.org/name",
    "http://www.w3.org/2000/01/rdf-schema#label",
    _DHP + "status", _DHP + "rows", _DHP + "modulesPerRow", _DHP + "onBoard", _DHP + "onCircuit",
    _DHP + "reference", _DHC + "ratedCurrent", _DHC + "crossSection", _DHC + "sensitivityMA",
    _DHC + "rcdType", _DHC + "maxPoints", _DHC + "hasCircuitType",
    "https://w3id.org/rec#locatedIn",
]
# Facts that are single per LANGUAGE (one label per language).
PER_LANGUAGE: List[str] = [
    "http://www.w3.org/2004/02/skos/core#prefLabel",
]

# -- the chat (a local Claude Code with only this edge's MCP tools) -----------

# What a proposal from the chat may run on this edge's own API: (method, path
# regex). Nothing else can be proposed. Add the tool's own routes here.
CHAT_ALLOWED: List[Tuple[str, str]] = [
    ("POST", r"/api/jobs/[\w-]{1,40}/cancel"),
    ("POST", r"/api/cloud/link"),
    ("POST", r"/api/cloud/use"),
    ("POST", r"/api/knowledge/sync"),
    # designs (app.py): a workspace and everything in its design
    ("POST", r"/api/workspaces"),
    ("POST", r"/api/workspaces/[a-z][a-z0-9-]{0,39}"),
    ("POST", r"/api/workspaces/[a-z][a-z0-9-]{0,39}/(boards|rcds|devices|circuits|rooms|points)"),
    ("POST", r"/api/workspaces/[a-z][a-z0-9-]{0,39}/boards/[a-z]+-[a-z0-9]{8}"),
    ("POST", r"/api/workspaces/[a-z][a-z0-9-]{0,39}/circuits/circuit-[a-z0-9]{8}/move"),
    ("POST", r"/api/workspaces/[a-z][a-z0-9-]{0,39}/items/[a-z]+-[a-z0-9]{8}/(place|rename|reference)"),
    ("DELETE", r"/api/workspaces/[a-z][a-z0-9-]{0,39}/items/[a-z]+-[a-z0-9]{8}"),
    # never here: partner file imports and credentials, which come from the page only
]

CHAT_SYSTEM = """You are the chat of {title}, an edge of {cloud} where an
electrician or a home owner designs the electrical installation of a home
with you. Use the {tool} tools; do not guess numbers. Be brief and concrete,
and answer in the language the person writes in (the page is in {{lang}}).

A home has one or more workspaces: active projects such as a new
switchboard or a kitchen. Each holds one design: boards (rows × 18 mm
modules) → RCDs → circuits, each with its own breaker → points in rooms.
Build it with the tools, one step at a time; ids come back from design().

The norm is NF C 15-100 for France. Know its essentials: at least two 30 mA
RCDs, at most 8 circuits per RCD, type A for cooking, washing machine and EV
charging; lighting ≤ 16 A and 8 points in 1.5 mm²; sockets 16 A in 1.5 mm²
(≤ 8) or 20 A in 2.5 mm² (≤ 12); cooking 32 A in 6 mm²; water heater 20 A in
2.5 mm², usually on a day/night contactor with a 2 A control breaker; about
20 % of a board's modules free. After a change, call report() and say what
it finds; a design that breaks the norm is saved and shown, never refused.

When someone brings a quote (devis), model what it offers in one workspace,
report it, and propose a better design in another, with the reasons.

Changes are proposals: a tool that changes something answers "proposed". The
person sees a Confirm button for it. Never say a change is done before they
have confirmed. Prices and partner credentials are private: never ask for a
credential in the chat; partner files and API access are set up on the page.""".format(
    title=TITLE, cloud=CLOUD_NAME, tool=TOOL, tenant=TENANT_NOUN)

# Optional, for a tool whose page lets the person choose items to talk about.
# CHAT_SELECTION() returns a string that changes when the selection does (a
# file name, a hash), or None; the chat then tells Claude once that there is
# a new selection, in these words. Give Claude a tool of your own that reads
# the items (the Mediathek's is selection()).
def CHAT_SELECTION():
    from .. import selection
    return selection.key()


CHAT_SELECTION_NOTICE = ("[The person opened something else on the page. Call selection() "
                         "before answering: it names the workspace and item now open.]")

# Openings of messages the page writes itself, never a conversation's title
# in the history (the person's first own words are).
CHAT_TITLE_SKIP: List[str] = []

# -- first start ---------------------------------------------------------------

# Steps a new edge runs once (at start, and again after linking) until each
# has worked: fetch models, pull what the cloud already knows … Each is
# (name, needed() -> bool, run(progress, cancelled) -> dict). The layer adds
# "home knowledge" (every space's A-Box) itself.
FIRST_START: List[Tuple[str, Callable[[], bool], Callable[..., Dict]]] = []
