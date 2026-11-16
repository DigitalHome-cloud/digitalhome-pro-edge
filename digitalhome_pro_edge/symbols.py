# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
symbols.py — pictograms for the labels: what a circuit feeds, or what a
device is, legible at 6 mm on a 17.5 mm module.

Drawn here, one stroke weight on a 24 × 24 grid in currentColor, so they
print in black and take the label's colour on screen. They are our own
simple drawings, not the IEC 60617 symbols (which are for diagrams and
installation plans) and not a board maker's pictogram sheets.

default_for() picks one from what the design says (circuit type, appliance,
device kind); an item's dhp:symbol overrides it (designs.set_label).
"""

from __future__ import annotations

from typing import Dict, List, Optional

# id → (English name, SVG body inside the 24 × 24 viewBox)
_D: Dict[str, tuple] = {
    "lighting": ("Lighting", '<path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2V17h5v-1.1c0-.8.4-1.5 1-2A6 6 0 0 0 12 3z"/>'
                 '<path d="M9.5 20h5M10.5 22h3"/>'),
    "socket": ("Socket", '<circle cx="12" cy="12" r="9"/><circle cx="8.5" cy="12" r="1.3" fill="currentColor"/>'
               '<circle cx="15.5" cy="12" r="1.3" fill="currentColor"/><path d="M12 3v3.5M12 17.5V21"/>'),
    "hob": ("Hob, cooking", '<rect x="2.5" y="4" width="19" height="16" rx="2"/><circle cx="8" cy="9.5" r="2.6"/>'
            '<circle cx="16" cy="9.5" r="2.6"/><circle cx="8" cy="15.5" r="2"/><circle cx="16" cy="15.5" r="2"/>'),
    "oven": ("Oven", '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 8h18"/>'
             '<rect x="7" y="11" width="10" height="6.5" rx="1"/><path d="M6.5 5.5h.01M10 5.5h.01M17.5 5.5h-4"/>'),
    "water_heater": ("Water heater", '<rect x="6.5" y="2" width="11" height="17.5" rx="5.5"/>'
                     '<path d="M9.5 9.5q1.25-1.6 2.5 0t2.5 0M9.5 13.5q1.25-1.6 2.5 0t2.5 0M10 19.5V22M14 19.5V22"/>'),
    "washing_machine": ("Washing machine", '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M4 6.5h16"/>'
                        '<circle cx="12" cy="14" r="4.8"/><path d="M9.6 14.6q1.2 1 2.4 0t2.4 0M7 4.3h.01M10 4.3h.01"/>'),
    "dishwasher": ("Dishwasher", '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M4 7h16"/>'
                   '<path d="M7 18h10M8.5 18v-6M12 18v-7M15.5 18v-6M9 4.5h6"/>'),
    "dryer": ("Dryer", '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M4 6.5h16"/>'
              '<circle cx="12" cy="14" r="4.8"/><path d="M10.6 12.2q1.4.9 0 1.8t0 1.8M13.4 12.2q1.4.9 0 1.8t0 1.8"/>'),
    "fridge": ("Fridge, freezer", '<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M6 9.5h12M9 5v2M9 12.5v3"/>'),
    "heating": ("Heating", '<rect x="3" y="6.5" width="18" height="11.5" rx="1.5"/>'
                '<path d="M7.5 6.5V18M12 6.5V18M16.5 6.5V18M6 18v2.5M18 18v2.5"/>'),
    "floor_heating": ("Floor heating", '<path d="M4 17h13a2 2 0 0 0 0-4H7a2 2 0 0 1 0-4h13"/><path d="M2 21h20"/>'),
    "heat_pump": ("Heat pump", '<rect x="2.5" y="5" width="19" height="14" rx="2"/><circle cx="10" cy="12" r="4.5"/>'
                  '<path d="M10 7.5v9M5.5 12h9M18 8.5v7"/>'),
    "ev_charger": ("EV charger", '<rect x="4" y="3" width="10" height="18" rx="2"/>'
                   '<path d="M10 7l-3 5h4l-3 5M14 13h2.5a2 2 0 0 1 2 2v3.5a1.5 1.5 0 0 0 3 0V10l-2-2"/>'),
    "ventilation": ("Ventilation", '<circle cx="12" cy="12" r="9.5"/><circle cx="12" cy="12" r="1.4"/>'
                    '<path d="M12 10.6c0-3.6 1.6-5.6 4.3-5.4M13.3 12.6c3.2 1.8 4.2 4.3 2.6 6.4M10.7 12.6c-3.1 1.8-5.7 1.5-6.7-1"/>'),
    "shutters": ("Shutters", '<rect x="4" y="3" width="16" height="18" rx="1"/>'
                 '<path d="M4 6.5h16M4 9.5h16M4 12.5h16M12 15v4.5M10 17.5l2 2 2-2"/>'),
    "outdoor": ("Outdoor, garden", '<circle cx="12" cy="9" r="5.5"/><path d="M12 14.5V21M3 21h18M9.5 17.5 12 19"/>'),
    "garage": ("Garage", '<path d="M3 10.5 12 4l9 6.5V21H3z"/><path d="M7 21v-7.5h10V21M7 16h10M7 18.5h10"/>'),
    "bell": ("Bell", '<path d="M6 16.5h12l-1.5-2.2V10a4.5 4.5 0 0 0-9 0v4.3z"/><path d="M10.3 19a1.7 1.7 0 0 0 3.4 0M12 4V3"/>'),
    "network": ("Network, IT", '<rect x="9" y="2.5" width="6" height="5" rx="1"/><rect x="2.5" y="16.5" width="6" height="5" rx="1"/>'
                '<rect x="15.5" y="16.5" width="6" height="5" rx="1"/><path d="M12 7.5V12M5.5 12h13M5.5 12v4.5M18.5 12v4.5"/>'),
    "solar": ("PV, solar", '<path d="M3.5 14 6.5 4h14l-3 10z"/><path d="M5 9h14M11.2 4 9.4 14M15.8 4 14 14M11.5 14v4M8 20.5h7"/>'),
    "switch": ("Switch", '<rect x="4" y="4" width="16" height="16" rx="2.5"/><rect x="9" y="7.5" width="6" height="9" rx="1"/>'
               '<path d="M9 12h6"/>'),
    "outlet": ("Outlet, junction box", '<circle cx="12" cy="12" r="6.5"/><path d="M12 2v3.5M12 18.5V22M2 12h3.5M18.5 12H22"/>'
               '<path d="M9.5 12h5"/>'),
    "spare": ("Spare, reserve", '<rect x="3.5" y="5.5" width="17" height="13" rx="1.5" stroke-dasharray="2.2 2"/>'
              '<path d="M12 9v6M9 12h6"/>'),
    "unknown": ("Unknown, to verify", '<circle cx="12" cy="12" r="9.5"/>'
                '<path d="M9.4 9.4a2.7 2.7 0 1 1 3.9 2.4c-.8.4-1.3 1-1.3 1.8v.8"/><circle cx="12" cy="17" r=".8" fill="currentColor"/>'),
    "rcd": ("RCD", '<rect x="4" y="2.5" width="16" height="19" rx="2"/><ellipse cx="12" cy="12" rx="5.5" ry="2.6"/>'
            '<path d="M9.5 6.5v11M14.5 6.5v11"/>'),
    "breaker": ("Breaker", '<rect x="5" y="2.5" width="14" height="19" rx="2"/><rect x="9" y="7" width="6" height="10" rx="1"/>'
                '<path d="M9 11h6"/>'),
    "main_breaker": ("Main breaker", '<rect x="3" y="2.5" width="18" height="19" rx="2"/><rect x="8" y="7" width="8" height="10" rx="1"/>'
                     '<path d="M8 11h8M5.5 5h.01"/>'),
    "surge": ("Surge protector", '<rect x="4" y="2.5" width="16" height="19" rx="2"/><path d="M13 5.5 8.5 12.5h4l-1.5 6 4.5-7h-4z"/>'),
    "contactor": ("Contactor, timer", '<rect x="4" y="2.5" width="16" height="19" rx="2"/><circle cx="12" cy="12" r="5"/>'
                  '<path d="M12 9v3l2 1.5"/>'),
}

ALL: List[Dict[str, str]] = [{"id": k, "name": v[0]} for k, v in _D.items()]
IDS = frozenset(_D)

# what the design says → a symbol
_BY_TYPE = {"lighting": "lighting", "socket": "socket", "cooking": "hob", "water_heater": "water_heater",
            "heating": "heating", "floor_heating": "floor_heating", "ev_charger": "ev_charger"}
_BY_APPLIANCE = {"washing_machine": "washing_machine", "dishwasher": "dishwasher", "dryer": "dryer",
                 "hob": "hob", "oven": "oven", "cooker": "hob", "fridge": "fridge", "freezer": "fridge",
                 "heat_pump": "heat_pump", "ev_charger": "ev_charger", "water_heater": "water_heater",
                 "vmc": "ventilation", "ventilation": "ventilation", "shutters": "shutters", "boiler": "water_heater"}
_BY_DEVICE = {"rcd": "rcd", "breaker": "breaker", "fuse": "breaker", "main_breaker": "main_breaker",
              "surge_protector": "surge", "contactor": "contactor", "bell_transformer": "bell",
              "unidentified": "unknown"}


_BY_POINT = {"socket": "socket", "light": "lighting", "switch": "switch", "outlet": "outlet"}


def default_for(kind: str, circuit_type: str = "", appliance: str = "", point_kind: str = "") -> str:
    """The symbol a label gets when the person has not chosen one."""
    if kind == "point":
        return _BY_POINT.get(point_kind) or _BY_APPLIANCE.get(appliance) or _BY_TYPE.get(circuit_type) or "unknown"
    if kind == "circuit":
        return _BY_APPLIANCE.get(appliance) or _BY_TYPE.get(circuit_type) or ("socket" if circuit_type == "dedicated"
                                                                             else "unknown")
    return _BY_DEVICE.get(kind, "unknown")


def svg(ident: str, size: Optional[str] = None, title: bool = False) -> str:
    """The pictogram as inline SVG (unknown ids give "unknown")."""
    name, body = _D.get(ident, _D["unknown"])
    dim = f' width="{size}" height="{size}"' if size else ""
    t = f"<title>{name}</title>" if title else ""
    return (f'<svg class="sym" viewBox="0 0 24 24"{dim} fill="none" stroke="currentColor" stroke-width="1.6" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="{"false" if title else "true"}">{t}{body}</svg>')
