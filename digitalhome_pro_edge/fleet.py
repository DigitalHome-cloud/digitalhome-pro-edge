# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
fleet.py — what the Portal's Fleet page knows about this edge
(darkfactory ADR 0020: two kinds of edge).

A pro edge is never linked to one home: it works for the homes of the
person who linked it, one workspace per home. So it tells each linked
connection two things in a telemetry report:

- edge_kind "pro";
- homes: the homeIds (h-…, minted and meaningless) of the homes its
  workspaces on that connection are attached to. Never a SmartHome ID,
  a title, an address or anything of the design.

The cloud keeps the list and shows a person only those of the homes they
may use. Reports go at start, a little after a workspace is made or
attached, and every six hours; one that fails is tried at the next.
"""

from __future__ import annotations

import threading
from typing import Callable, Dict, List, Optional

EDGE_KIND = "pro"
EVERY_S = 6 * 3600
SETTLE_S = 3.0

_wake = threading.Event()
_started = False
_lock = threading.Lock()
last: Dict[str, Dict] = {}          # per connection: what was sent, or why not


def homes_by_connection(workspaces: List[Dict], cloud_homes: Callable[[str], List[Dict]],
                        linked: List[str]) -> Dict[str, List[str]]:
    """For each linked connection, the homeIds of the homes its workspaces
    are attached to, sorted. cloud_homes(profile) is the connection's list
    of homes ({smartHomeId, homeId}); a workspace whose home it does not
    list is left out (the cloud could not resolve it either)."""
    out: Dict[str, List[str]] = {}
    for name in linked:
        wanted = {w["home"] for w in workspaces if w.get("instance") == name and w.get("home")}
        if not wanted:
            out[name] = []
            continue
        ids = {str(h.get("homeId") or "") for h in cloud_homes(name) if h.get("smartHomeId") in wanted}
        out[name] = sorted(i for i in ids if i.startswith("h-"))
    return out


def report(designs, cloud, homes_mod) -> Dict[str, Dict]:
    """Send the kind and the homes to every linked connection now."""
    linked = cloud.linked_profiles()

    def listed(name: str) -> List[Dict]:
        return homes_mod.cloud_homes(refresh=True, profile=name).get("homes") or []

    result: Dict[str, Dict] = {}
    for name in linked:
        try:
            ids = homes_by_connection(designs.workspaces(), listed, [name])[name]
            cloud.telemetry("delta", {"edge_kind": EDGE_KIND, "homes": ids}, profile=name)
            result[name] = {"sent": len(ids)}
        except Exception as e:  # not reachable, token lapsed …: the next report tries again
            result[name] = {"error": str(e)[:200]}
    with _lock:
        last.clear()
        last.update(result)
    return result


def soon() -> None:
    """Report a little later (a workspace was made or attached)."""
    _wake.set()


def start(get_designs: Callable[[], object], cloud, homes_mod,
          every_s: float = EVERY_S, settle_s: float = SETTLE_S) -> Optional[threading.Thread]:
    """The background reporter: once now, after each soon(), every six hours."""
    global _started
    if _started:
        return None
    _started = True

    def loop() -> None:
        import time
        while True:
            report(get_designs(), cloud, homes_mod)
            _wake.wait(timeout=every_s)
            if _wake.is_set():
                time.sleep(settle_s)  # several changes in a row: one report
                _wake.clear()

    t = threading.Thread(target=loop, name="fleet-report", daemon=True)
    t.start()
    return t
