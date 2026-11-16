# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
homes.py — the homes this edge may design for, from digitalhome.cloud.

A home's SmartHome ID is made in the cloud (the Portal creates the home and
its owners); the edge does not invent one. A linked edge asks the cloud,
POST /edge/v1/homes, for the homes of the person who linked it, and a new
workspace must name one of them.

A workspace belongs to one home on one instance (ADR-0008): the connection
(stage, prod …) it was made on, and a SmartHome ID that connection lists. An
edge that is not linked cannot start one. Answers are cached for a minute per
connection: the page polls, and switching the current connection shows that
cloud's homes at once.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from .edge import cloud

_TTL = 60.0
_cache: Dict[str, Tuple[float, Dict]] = {}       # connection → (when, answer)


def reset() -> None:
    _cache.clear()


def cloud_homes(refresh: bool = False, profile: Optional[str] = None) -> Dict:
    """{linked, homes: [{smartHomeId, label, city, postalCode, country, isDemo, linked}],
    why, connection, site} for one connection (default: the current one)."""
    now = time.monotonic()
    profile = profile or cloud.active_profile()
    hit = _cache.get(profile)
    if not refresh and hit is not None and now - hit[0] < _TTL:
        return hit[1]
    try:
        got = cloud.call("homes", {}, profile=profile)
        value = {"linked": True, "homes": list(got.get("homes") or []), "why": ""}
    except cloud.NotLinked:
        value = {"linked": False, "homes": [],
                 "why": "This edge is not linked to digitalhome.cloud: link it to choose one of your homes."}
    except cloud.CloudError as e:
        why = ("The connected cloud does not list homes yet." if getattr(e, "status", 0) == 404
               else f"digitalhome.cloud did not answer: {e}")
        value = {"linked": True, "homes": [], "why": why, "unavailable": True}
    value["connection"] = profile
    # the cloud's web site (the Portal), for links to a home: <site>/?home=<SmartHome ID>
    value["site"] = cloud.load_state(profile).get("site") if value["linked"] else None
    _cache[profile] = (now, value)
    return value


def check(home: str, profile: Optional[str] = None) -> str:
    """The connection a workspace for this home may be made on; refuses when
    the connection is not linked, cannot list homes, or does not list it."""
    got = cloud_homes(profile=profile)
    name = got["connection"]
    if not got["linked"]:
        raise ValueError(f"the {name} connection is not linked: link this edge to digitalhome.cloud first")
    if got.get("unavailable"):
        raise ValueError(f"cannot check the home on {name}: {got['why']}")
    ids: List[str] = [h.get("smartHomeId", "") for h in got["homes"]]
    if home not in ids:
        known = ", ".join(f"{h.get('smartHomeId')} ({h.get('label')})" for h in got["homes"]) or "none yet"
        raise ValueError(f"{home} is not one of your homes on {name} ({known}); "
                         "create the home in the Portal first")
    return name
