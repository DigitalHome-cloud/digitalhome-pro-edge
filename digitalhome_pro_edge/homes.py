# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
homes.py — the homes this edge may design for, from digitalhome.cloud.

A home's SmartHome ID is made in the cloud (the Portal creates the home and
its owners); the edge does not invent one. A linked edge asks the cloud,
POST /edge/v1/homes, for the homes of the person who linked it, and a new
workspace must name one of them.

An edge that is not linked yet may still start a draft for a local name, so
work can begin before the home exists in the cloud; the page and the chat say
it is a draft. Answers are cached for a minute per connection (stage, prod
…): the page polls, and switching the current connection shows that cloud's
homes at once.
"""

from __future__ import annotations

import time
from typing import Dict, List

from .edge import cloud

_TTL = 60.0
_cache: Dict[str, object] = {"at": 0.0, "value": None, "profile": None}


def cloud_homes(refresh: bool = False) -> Dict:
    """{linked, homes: [{smartHomeId, label, city, postalCode, country, isDemo, linked}], why}."""
    now = time.monotonic()
    profile = cloud.active_profile()
    if (not refresh and _cache["value"] is not None and _cache["profile"] == profile
            and now - float(_cache["at"]) < _TTL):
        return _cache["value"]  # type: ignore[return-value]
    try:
        got = cloud.call("homes", {})
        value = {"linked": True, "homes": list(got.get("homes") or []), "why": ""}
        value["connection"] = profile
    except cloud.NotLinked:
        value = {"linked": False, "homes": [],
                 "why": "This edge is not linked to digitalhome.cloud: link it to choose one of your homes."}
    except cloud.CloudError as e:
        why = ("The connected cloud does not list homes yet." if getattr(e, "status", 0) == 404
               else f"digitalhome.cloud did not answer: {e}")
        value = {"linked": True, "homes": [], "why": why, "unavailable": True}
    value.setdefault("connection", profile)
    _cache.update(at=now, value=value, profile=profile)
    return value


def check(home: str) -> None:
    """Refuse a home the linked cloud does not know; allow a draft name only
    when the edge is not linked (or the cloud cannot list homes yet)."""
    got = cloud_homes()
    if not got["linked"] or got.get("unavailable"):
        return
    ids: List[str] = [h.get("smartHomeId", "") for h in got["homes"]]
    if home not in ids:
        known = ", ".join(f"{h.get('smartHomeId')} ({h.get('label')})" for h in got["homes"]) or "none yet"
        raise ValueError(f"{home} is not one of your homes on digitalhome.cloud ({known}); "
                         "create the home in the Portal first")
