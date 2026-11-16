# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
labels.py — printable labels for a design, for full-sheet A4 sticker paper
(297 × 210 mm, one adhesive sheet per page, cut by hand along the lines).

Everything follows the board as it is built: `layout()` puts each device at
the row and module where it sits (designs.position, read on site), numbers the
modules as the board does (1 … rows × modules per row, row by row), and
keeps the empty modules as blanks. A device whose position was not read
fills the first gap that fits and is marked "position?"; a board where
nothing is placed is laid out in the design's order (RCD, then its circuits).

Three layouts:

  strip  board strips, on the sheet in landscape: one strip per board row,
         every module 17.5 mm wide by default, to stick under or over the
         row; a narrow device's name runs upwards, as on a handwritten strip;
         a row longer than the sheet is cut into pieces stuck end to end.
         Each cell has its pictogram (symbols.py) and, on a three-phase
         supply, a bar with its phase in the IEC 60445 colours
  grid   QR labels, 70 × 37 mm, 3 × 8 = 24 per sheet: one per RCD, circuit
         and device, in board order
  tag    small QR stickers for the points (sockets, lights, switches,
         outlets) and the devices, to go inside a cover: a square code of
         15 to 25 mm and two short lines below it
  cable  wrap-around cable labels, two per circuit (the board end and the
         far end): the text fills the first half, the blank second half
         wraps over it around the cable. The length is 2 × π × the cable's
         outer diameter (estimated from its cores and section, IEC 62491
         asks for a label at both ends that reads without turning the cable)

A QR code opens the item's ID card in the Portal of the workspace's
connection: https://<portal>/id/?h=<homeId>&i=<item>. It carries the home's
minted homeId, never the SmartHome ID (which spells the address), and the
card shows nothing to anyone but the home's owners (ADR 0018, 0019). A
workspace not attached to a home on a linked connection gets no codes: a
link to this edge would be useless on a phone (it listens on this computer
only). The address is printed in small type under each code, so a sticker
put over it can be seen to point elsewhere.

What a label says comes from the design; designs.set_label overrides the
text, the short line and the pictogram of one item. The wizard on the page
(the Labels tab) keeps its format per workspace in label-settings.json.

`skip` leaves the first cells (grid) or strips (strip) of the first sheet
empty, so a sheet whose top was already used can go through the printer
again.

The browser prints the page (window.print, @page A4, no margins); there is
no printer driver here. QR codes are SVG from segno (pure Python). Print at
100 % ("actual size"), not "fit to page", or the cut lines will not match.
"""

from __future__ import annotations

import html
import json
import math
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

import segno

from . import symbols

PAGE_W, PAGE_H = 210.0, 297.0          # A4 portrait, mm
MARGIN = 8.0                           # what most printers cannot print
GRID = {"w": 70.0, "h": 37.0, "cols": 3, "rows": 8}
STRIP_H = 30.0                         # height of a board strip, mm
MODULE_MM = 17.5                       # one DIN module
STRIP_GAP = 5.0                        # between strips on a sheet: the caption and the cut
PT_MM = 0.3528                         # one typographic point
CHAR_EM = 0.55                         # an average character's width, in em

# IEC 60445: the colours of the line conductors
PHASE_COLOURS = {"L1": "#7b4a21", "L2": "#111111", "L3": "#8c8c8c"}

# Typical outer diameters (mm) of sheathed installation cable (NYM-J, R2V,
# XVB), by cores and section: enough to size a wrap label, not a datasheet.
CABLE_OD = {
    3: {1.5: 8.5, 2.5: 9.5, 4: 11.0, 6: 12.5, 10: 15.0, 16: 17.5},
    4: {1.5: 9.0, 2.5: 10.5, 4: 12.0, 6: 13.5, 10: 16.5, 16: 19.0},
    5: {1.5: 10.0, 2.5: 11.5, 4: 13.5, 6: 15.0, 10: 18.0, 16: 21.0},
}
CABLE_OVERLAP = 4.0                    # mm the blank half laps past the text

DEFAULTS: Dict[str, Any] = {
    "kind": "board",                   # board | cable | qr | tag
    "module_mm": MODULE_MM, "strip_h": STRIP_H, "font_pt": 7.5,
    "cable_h": 19.0, "cable_d": 0.0,   # 0: estimated per circuit
    "tag_mm": 20.0,                    # the QR of a small tag, square
    "show_symbol": True, "show_phase": True, "show_number": True,
    "skip": 0, "boards": [], "items": [],
}
_LAYOUT = {"board": "strip", "qr": "grid", "cable": "cable", "tag": "tag", "strip": "strip", "grid": "grid"}


def settings_path(folder: Path) -> Path:
    return Path(folder) / "label-settings.json"


def load_settings(folder: Path) -> Dict[str, Any]:
    try:
        own = json.loads(settings_path(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        own = {}
    return clean_settings({**DEFAULTS, **(own if isinstance(own, dict) else {})})


def clean_settings(s: Dict[str, Any]) -> Dict[str, Any]:
    """The settings, checked: numbers in range, kinds known, lists of ids."""
    out = dict(DEFAULTS)
    try:
        out["kind"] = s.get("kind") if s.get("kind") in ("board", "cable", "qr", "tag") else "board"
        for k, lo, hi in (("module_mm", 9, 27), ("strip_h", 10, 60), ("font_pt", 5, 14),
                          ("cable_h", 9, 40), ("cable_d", 0, 40), ("tag_mm", 12, 30)):
            v = float(s.get(k, DEFAULTS[k]))
            if not lo <= v <= hi:
                raise ValueError(f"{k} is {lo} to {hi}")
            out[k] = v
        out["skip"] = max(0, int(s.get("skip", 0)))
        for k in ("show_symbol", "show_phase", "show_number"):
            out[k] = bool(s.get(k, True))
        for k in ("boards", "items"):
            v = s.get(k) or []
            if not isinstance(v, list) or not all(isinstance(x, str) and len(x) < 60 for x in v):
                raise ValueError(f"{k} is a list of ids")
            out[k] = v
    except (TypeError, ValueError) as e:
        raise ValueError(str(e) or "bad label settings") from None
    return out


def save_settings(folder: Path, s: Dict[str, Any]) -> Dict[str, Any]:
    s = clean_settings({**load_settings(folder), **s})
    p = settings_path(folder)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1), encoding="utf-8")
    tmp.replace(p)
    return s


def card_url(site: str, home_id: str, item: str) -> str:
    """The item's ID card in the Portal."""
    q = urllib.parse.urlencode({"h": home_id, "i": item})
    return f"{site.rstrip('/')}/id/?{q}"


def _card(cards: Optional[Dict], item: str) -> str:
    return card_url(cards["site"], cards["home_id"], item) if cards else ""


def qr_svg(data: str) -> str:
    return segno.make(data, error="m").svg_inline(scale=3, border=1)


def _short_url(url: str) -> str:
    return url.split("://", 1)[-1]


def _n(v, unit: str) -> str:
    """A value with its unit, or "?" for one a survey has not read yet."""
    return f"{v:g} {unit}" if v is not None else f"? {unit}"


# ---------------------------------------------------------------- what is labelled

def board_labels(design: Dict) -> List[Dict]:
    """The labels of every board in the design's order: each RCD and the
    circuits below it (their own breaker), the circuits below no RCD, then
    the other devices. Each knows its width and, if read, its position."""
    out: List[Dict] = []

    def add(b: Dict, x: Dict, kind: str, modules: int, short: str, detail: str, **extra) -> None:
        out.append({"board": b["label"], "board_tag": b.get("label_short") or "", "board_id": b["id"],
                    "item": x["id"], "kind": kind, "modules": max(1, int(modules or 1)),
                    "title": x.get("label_text") or x["label"], "name": x["label"],
                    "short": x.get("label_short") or short, "detail": detail,
                    "symbol": x.get("symbol") or symbols.default_for(kind, x.get("type", ""), x.get("appliance", "")),
                    "symbol_set": bool(x.get("symbol")), "text_set": bool(x.get("label_text") or x.get("label_short")),
                    "label_text": x.get("label_text", ""), "label_short": x.get("label_short", ""), "derived_short": short,
                    "phase_own": x.get("phase_conductor", ""),
                    "phase": x.get("phase") or x.get("phase_conductor") or "",
                    "row": x.get("row"), "slot": x.get("slot"), "to_verify": bool(x.get("to_verify")), **extra})

    def circuit(b: Dict, c: Dict, upstream: str) -> None:
        detail = f"{_n(c['rated_current'], 'A')} · {_n(c['cross_section'], 'mm²')}" + (f" · {upstream}" if upstream else "")
        add(b, c, "circuit", c.get("modules", 1), _n(c["rated_current"], "A"), detail,
            rated_current=c.get("rated_current"), cross_section=c.get("cross_section"),
            three_phase=bool(c.get("three_phase")))

    for b in design["boards"]:
        for r in b["rcds"]:
            add(b, r, "rcd", r.get("modules", 2),
                f"{_n(r['sensitivity_ma'], 'mA')} {r['rcd_type'] or '?'}",
                f"{_n(r['rated_current'], 'A')} · {_n(r['sensitivity_ma'], 'mA')} · type {r['rcd_type'] or '?'}")
            for c in r["circuits"]:
                circuit(b, c, r["label"])
        for c in b.get("circuits", []):
            circuit(b, c, "")
        for d in b["devices"]:
            if not d.get("modules"):
                continue                                  # upstream of the board (a main breaker): no place on it
            rc = d.get("rated_current")
            add(b, d, d["kind"], d["modules"], f"{rc:g} A" if rc is not None else "",
                f"{rc:g} A" if rc is not None else d["kind"].replace("_", " "))
    return out


def point_labels(design: Dict) -> List[Dict]:
    """A label per point (socket, light, switch, appliance, outlet), with its
    room, and the board, module number and phase of the circuit that feeds
    it: what someone at the outlet needs to switch it off."""
    rooms = {r["id"]: r["label"] for r in design.get("rooms", [])}
    where = {c["item"]: c for b in layout(design) for r in b["rows"] for c in r["cells"] if not c.get("free")}
    out = []
    for b in design["boards"]:
        for c in [c for r in b["rcds"] for c in r["circuits"]] + b.get("circuits", []):
            cell = where.get(c["id"], {})
            for p in c.get("point_list", []):
                out.append({"board": b["label"], "board_tag": b.get("label_short") or "", "board_id": b["id"],
                            "item": p["id"], "kind": "point", "point_kind": p.get("kind", ""),
                            "title": p.get("label_text") or p["label"], "name": p["label"],
                            "short": p.get("label_short") or "", "label_text": p.get("label_text", ""),
                            "label_short": p.get("label_short", ""), "derived_short": "",
                            "symbol": p.get("symbol") or symbols.default_for("point", c.get("type", ""),
                                                                          c.get("appliance", ""), p.get("kind", "")),
                            "symbol_set": bool(p.get("symbol")),
                            "text_set": bool(p.get("label_text") or p.get("label_short")),
                            "room": rooms.get(p.get("room", ""), ""), "circuit": c["label"],
                            "circuit_item": c["id"], "number": numbers(cell) if cell else "",
                            "phase": c.get("phase") or c.get("phase_conductor") or "", "phase_own": "",
                            "to_verify": bool(c.get("to_verify")), "modules": 0})
    return out


def phase_text(phase: str) -> str:
    """ "L1", "L1-L2", "L1-L2-L3" """
    return "-".join(phase[i:i + 2] for i in range(0, len(phase), 2)) if phase else ""


def _three_phase(design: Dict) -> bool:
    return design.get("supply") in ("3N~400V", "3~230V")


def warnings(design: Dict, s: Optional[Dict] = None, cards: Optional[Dict] = None) -> List[Dict]:
    """What to look at before printing, per label: text that will not fit
    its cell at the chosen size, a rating not read, an item to verify, a
    phase missing on a three-phase supply, two labels that say the same."""
    s = clean_settings(s or {})
    out = []
    labs = [c for b in layout(design) for r in b["rows"] for c in r["cells"] if not c.get("free")]
    seen: Dict[tuple, str] = {}
    char = s["font_pt"] * PT_MM * CHAR_EM
    for c in labs:
        w: List[Dict] = []
        if c["modules"] == 1:            # upright text: the strip's height, less number, symbol and rating
            room = (s["strip_h"] - 4 - (6 if s["show_symbol"] else 0) - 3) / char
        else:
            room = 2 * (c["modules"] * s["module_mm"] - 1.5) / char      # two lines
        if len(c["title"]) > room:
            w.append({"code": "too_long", "text": f"“{c['title']}” is {len(c['title'])} characters; about "
                                                  f"{int(room)} fit at {s['font_pt']:g} pt"})
        if c["kind"] == "circuit" and c.get("rated_current") is None and not c["text_set"]:
            w.append({"code": "no_rating", "text": "rating not read: the label says “? A”"})
        if c["to_verify"]:
            w.append({"code": "to_verify", "text": "marked to verify on site"})
        if _three_phase(design) and c["kind"] in ("circuit", "rcd") and not c["phase"]:
            w.append({"code": "no_phase", "text": "no phase on a three-phase supply"})
        key = (c["board_id"], c["title"].strip().lower())
        if key in seen:
            w.append({"code": "duplicate", "text": "says the same as another label on this board"})
        seen[key] = c["item"]
        if c.get("first") is None or not c.get("placed"):
            w.append({"code": "position", "text": "position on the board not read"})
        out.append({"item": c["item"], "kind": c["kind"], "board": c["board"], "title": c["title"],
                    "card": _card(cards, c["item"]),
                    "name": c["name"], "short": c["short"], "symbol": c["symbol"], "symbol_set": c["symbol_set"],
                    "text_set": c["text_set"], "label_text": c["label_text"], "label_short": c["label_short"],
                    "derived_short": c["derived_short"], "phase": c["phase"], "phase_own": c["phase_own"],
                    "number": numbers(c), "modules": c["modules"],
                    "warnings": w})
    tag_chars = 2 * (s["tag_mm"] + 2) / (6 * PT_MM * CHAR_EM)
    for p in point_labels(design):
        w = []
        if len(p["title"]) > tag_chars:
            w.append({"code": "too_long", "text": f"“{p['title']}” is {len(p['title'])} characters; about "
                                                  f"{int(tag_chars)} fit on a {s['tag_mm']:g} mm tag"})
        if not p["room"]:
            w.append({"code": "no_room", "text": "no room"})
        out.append({"item": p["item"], "kind": "point", "board": p["board"], "title": p["title"], "name": p["name"],
                    "card": _card(cards, p["item"]), "short": p["short"], "symbol": p["symbol"],
                    "symbol_set": p["symbol_set"], "text_set": p["text_set"], "label_text": p["label_text"],
                    "label_short": p["label_short"], "derived_short": p["room"] or p["circuit"],
                    "phase": p["phase"], "phase_own": "", "number": p["number"], "modules": 0,
                    "point_kind": p["point_kind"], "room": p["room"], "circuit": p["circuit"], "warnings": w})
    return out


def layout(design: Dict) -> List[Dict]:
    """Every board as built: {board, board_id, per, rows: [{row, cells}]}.
    A cell is a device ({**label, start, width, first, last, placed}) or a
    run of empty modules ({free: True, start, width, first, last}); `start`
    counts from 1 in its row, `first`/`last` are the board's own module
    numbers. Devices that do not fit go to an extra row, marked overflow."""
    labels = board_labels(design)
    out = []
    for b in design["boards"]:
        per, nrows = int(b["modules_per_row"]), int(b["rows"])
        taken = [[None] * per for _ in range(nrows)]
        rows: List[List[Dict]] = [[] for _ in range(nrows)]
        mine = [x for x in labels if x["board_id"] == b["id"]]

        def put(r: int, s: int, lab: Dict, placed: bool) -> None:
            for k in range(s, s + lab["modules"]):
                taken[r][k] = lab["item"]
            rows[r].append({**lab, "start": s + 1, "width": lab["modules"], "placed": placed})

        def fits(r: int, s: int, w: int) -> bool:
            return s + w <= per and all(taken[r][k] is None for k in range(s, s + w))

        waiting = []
        for lab in mine:
            r, s = lab.get("row"), lab.get("slot")
            if r and s and 1 <= r <= nrows and fits(r - 1, s - 1, lab["modules"]):
                put(r - 1, s - 1, lab, True)
            else:
                waiting.append(lab)
        overflow: List[Dict] = []
        for lab in waiting:
            spot = next(((r, s) for r in range(nrows) for s in range(per) if fits(r, s, lab["modules"])), None)
            if spot:
                put(*spot, lab, False)
            else:
                overflow.append(lab)
        board_rows = []
        for r in range(nrows):
            cells = sorted(rows[r], key=lambda c: c["start"])
            filled: List[Dict] = []
            pos = 1
            for c in cells + [None]:
                end = c["start"] if c else per + 1
                if end > pos:
                    filled.append({"free": True, "start": pos, "width": end - pos})
                if c:
                    filled.append(c)
                    pos = c["start"] + c["width"]
            for c in filled:
                c["first"] = r * per + c["start"]
                c["last"] = c["first"] + c["width"] - 1
            board_rows.append({"row": r + 1, "cells": filled, "overflow": False})
        if overflow:
            cells, pos = [], 1
            for lab in overflow:
                cells.append({**lab, "start": pos, "width": lab["modules"], "placed": False,
                              "first": None, "last": None})
                pos += lab["modules"]
            board_rows.append({"row": nrows + 1, "cells": cells, "overflow": True})
        out.append({"board": b["label"], "board_id": b["id"], "per": per, "rows": board_rows})
    return out


def numbers(cell: Dict) -> str:
    """The board's module numbers of a cell: "7", "17–19", or "" off the board."""
    if not cell.get("first"):
        return ""
    return str(cell["first"]) if cell["first"] == cell["last"] else f"{cell['first']}–{cell['last']}"


def strips(design: Dict, module_mm: float = MODULE_MM, max_mm: float = PAGE_H - 2 * MARGIN) -> List[Dict]:
    """One strip per board row, every cell `width` mm wide; a row longer than
    the sheet is cut, between two cells, into pieces stuck end to end."""
    out = []
    for b in layout(design):
        for row in b["rows"]:
            cells = [{**c, "modules": c["width"], "width": c["width"] * module_mm} for c in row["cells"]]
            head = {"board": b["board"], "board_id": b["board_id"], "row": row["row"], "overflow": row["overflow"]}
            total = sum(c["width"] for c in cells)
            if total <= max_mm:
                out.append({**head, "cells": cells, "width": total, "part": ""})
                continue
            # a run of blanks may be cut anywhere: one cell per module
            cells = [y for c in cells for y in (
                [{**c, "modules": 1, "width": module_mm, "start": c["start"] + i,
                  "first": c["first"] + i if c.get("first") else None,
                  "last": c["first"] + i if c.get("first") else None} for i in range(c["modules"])]
                if c.get("free") else [c])]
            piece, w, k = [], 0.0, 1
            for c in cells:
                if w + c["width"] > max_mm and piece:
                    out.append({**head, "cells": piece, "width": w, "part": f" ({k})"})
                    piece, w, k = [], 0.0, k + 1
                piece.append(c)
                w += c["width"]
            out.append({**head, "cells": piece, "width": w, "part": f" ({k})"})
    return out


def cable_od(cores: int, section: Optional[float]) -> float:
    """The outer diameter, from the table, rounded up to the next listed section."""
    table = CABLE_OD.get(cores) or CABLE_OD[5 if cores > 5 else 3]
    if section is None:
        return table[2.5]
    for sec in sorted(table):
        if section <= sec:
            return table[sec]
    return table[max(table)]


def cable_labels(design: Dict, s: Optional[Dict] = None) -> List[Dict]:
    """Two wrap-around labels per circuit (board end, far end): the id that
    ties both ends together (the board and the circuit's module number), the
    name, the cable (cores G section, G: with a protective conductor) and
    the phase. length = 2 × (π × diameter) + overlap: the text on the first
    half, the blank half wraps over it."""
    s = clean_settings(s or {})
    three = _three_phase(design)
    out = []
    order = 0
    for b in layout(design):
        for row in b["rows"]:
            for c in row["cells"]:
                if c.get("free") or c["kind"] != "circuit":
                    continue
                order += 1
                if c.get("three_phase"):
                    cores = 4 if design.get("supply") == "3~230V" else 5
                else:
                    cores = 3
                sec = c.get("cross_section")
                d = s["cable_d"] or cable_od(cores, sec)
                text_len = round(math.pi * d + CABLE_OVERLAP / 2, 1)
                num = numbers(c) or f"#{order}"
                ident = f"{c['board_tag']} · {num}" if c["board_tag"] else num
                cable = f"{cores}G{sec:g}" if sec is not None else f"{cores}G?"
                for end in ("board", "load"):
                    out.append({"item": c["item"], "end": end, "id": ident, "title": c["title"], "cable": cable,
                                "rating": c["short"], "phase": phase_text(c["phase"]) if three else "",
                                "symbol": c["symbol"], "diameter": d, "text_len": text_len,
                                "length": round(2 * text_len, 1), "height": s["cable_h"]})
    return out


# ---------------------------------------------------------------- the page

def _page(title: str, body: str, controls: str, extra_css: str = "", landscape: bool = False) -> str:
    w, h = (PAGE_H, PAGE_W) if landscape else (PAGE_W, PAGE_H)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Labels — {title}</title>
<style>
 @page {{ size: A4 {"landscape" if landscape else "portrait"}; margin: 0; }}
 * {{ box-sizing: border-box; }}
 body {{ margin: 0; font: 12px system-ui, sans-serif; color: #111; background: #ddd; }}
 .bar {{ padding: 10px 16px; background: #fff; border-bottom: 1px solid #bbb; display: flex; gap: 10px;
        align-items: center; flex-wrap: wrap; position: sticky; top: 0; z-index: 1; }}
 .bar form {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
 .bar input[type=number] {{ width: 60px; }}
 .bar .warn {{ color: #8a5a00; }}
 .sheet {{ width: {w}mm; height: {h}mm; background: #fff; margin: 10mm auto; position: relative;
          padding: {MARGIN}mm; overflow: hidden; page-break-after: always; break-after: page; }}
 .sheet:last-child {{ page-break-after: auto; break-after: auto; }}
 {extra_css}
 @media print {{ body {{ background: #fff; }} .bar {{ display: none; }} .sheet {{ margin: 0; }} }}
</style></head><body>
<div class="bar">{controls}</div>
{body}
</body></html>"""


def _controls(layout_name: str, skip: int, module_mm: float, height: float, count: int, sheets: int,
              note: str = "") -> str:
    sel = lambda v: " selected" if v == layout_name else ""  # noqa: E731
    return (f'<form method="get"><b>A4 sticker sheet, 297 × 210 mm</b>'
            f'<select name="layout"><option value="strip"{sel("strip")}>Board strips</option>'
            f'<option value="grid"{sel("grid")}>QR labels 70 × 37 mm</option>'
            f'<option value="cable"{sel("cable")}>Cable labels</option>'
            f'<option value="tag"{sel("tag")}>Small QR tags</option></select>'
            f'<label>skip <input type="number" name="skip" min="0" max="23" value="{skip}"></label>'
            f'<label>module <input type="number" name="module" min="9" max="27" step="0.5" value="{module_mm:g}"> mm</label>'
            f'<label>strip <input type="number" name="height" min="10" max="60" step="1" value="{height:g}"> mm</label>'
            f'<button>Show</button></form>'
            f'<button onclick="window.print()">Print</button>'
            f'<span>{count} {"strips" if layout_name == "strip" else "labels"} on {sheets} sheet{"s" if sheets != 1 else ""}'
            f' · print at 100 %, not “fit to page”</span>'
            + (f'<span class="warn">{html.escape(note)}</span>' if note else ""))


def _unplaced_note(design: Dict) -> str:
    rows = [c for b in layout(design) for r in b["rows"] for c in r["cells"] if not c.get("free")]
    some = any(c["placed"] for c in rows)
    missing = sum(1 for c in rows if not c["placed"])
    if some and missing:
        return f"{missing} device(s) without a position read on site: marked “position?”"
    if not some and rows:
        return "No positions read yet: the strips follow the design's order, not the board"
    return ""


def _only(design: Dict, s: Dict) -> Dict:
    """The design with only the boards and items the wizard picked."""
    boards = [b for b in design["boards"] if not s["boards"] or b["id"] in s["boards"]]
    if not s["items"]:
        return {**design, "boards": boards}
    keep = set(s["items"])
    return {**design, "boards": [{**b, "rcds": [{**r, "circuits": [c for c in r["circuits"] if c["id"] in keep]}
                                               for r in b["rcds"]],
                                  "circuits": [c for c in b.get("circuits", []) if c["id"] in keep],
                                  "devices": [x for x in b["devices"] if x["id"] in keep]} for b in boards]}


def sheet(design: Dict, cards: Optional[Dict] = None, layout: str = "strip", skip: int = 0,
          module_mm: float = MODULE_MM, height: Optional[float] = None, settings: Optional[Dict] = None) -> str:
    """The printable A4 sheets as a standalone HTML page. `cards`: {site,
    home_id} for the QR codes, or None when the workspace has no home in the
    cloud (then no codes). `settings` (the wizard's, see DEFAULTS) wins over
    the loose arguments."""
    s = clean_settings({"module_mm": module_mm, "strip_h": height or STRIP_H, "skip": skip,
                        "kind": {"strip": "board", "grid": "qr"}.get(layout, layout), **(settings or {})})
    title = html.escape(design["title"])
    view = _only(design, s)
    kind = _LAYOUT[s["kind"]]
    if kind == "strip":
        return _strip_sheets(view, title, s)
    if kind == "cable":
        return _cable_sheets(view, title, s)
    if kind == "tag":
        return _tag_sheets(design, cards, title, s)
    return _grid_sheets(view, cards, title, s["skip"], s["module_mm"], s["strip_h"])


def _grid_sheets(design: Dict, cards: Optional[Dict], title: str, skip: int, module_mm: float, height: float) -> str:
    per = GRID["cols"] * GRID["rows"]
    labs = [c for b in layout(design) for r in b["rows"] for c in r["cells"] if not c.get("free")]
    cells = [None] * min(skip, per - 1) + labs
    pages = [cells[i:i + per] for i in range(0, len(cells), per)] or [[]]
    out = []
    for page in pages:
        divs = []
        for lab in page:
            if lab is None:
                divs.append('<div class="lbl used"></div>')
                continue
            url = _card(cards, lab["item"])
            where = numbers(lab)
            divs.append('<div class="lbl">'
                        + (f'<div class="qr">{qr_svg(url)}<i>{html.escape(_short_url(url))}</i></div>' if url else "")
                        + f'<div class="txt"><b>{html.escape(lab["title"])}</b>'
                        f'<span>{html.escape(lab["detail"])}</span>'
                        f'<small>{html.escape(lab["board"])}'
                        + (f' · {"№" if lab["placed"] else "≈ №"} {where}' if where else "")
                        + ('' if not lab["to_verify"] else ' · to verify')
                        + '</small></div></div>')
        out.append(f'<section class="sheet"><div class="grid">{"".join(divs)}</div></section>')
    css = f""".grid {{ display: grid; grid-template-columns: repeat({GRID['cols']}, {GRID['w']}mm);
   grid-auto-rows: {GRID['h']}mm; justify-content: center; }}
 .lbl {{ display: flex; gap: 3mm; align-items: center; padding: 3mm; border: 0.2mm dashed #999; overflow: hidden; }}
 .lbl.used {{ border-color: #eee; }}
 .qr {{ flex: none; width: 24mm; }} .qr svg {{ width: 24mm; height: 24mm; display: block; }}
 .qr i {{ display: block; font: 3.6pt system-ui; color: #555; font-style: normal; overflow-wrap: anywhere; line-height: 1.1; }}
 .txt {{ display: flex; flex-direction: column; gap: 1mm; min-width: 0; }}
 .txt b {{ font-size: 11pt; line-height: 1.1; }} .txt span {{ font-size: 8pt; }} .txt small {{ color: #555; font-size: 7pt; }}"""
    return _page(title, "".join(out), _controls("grid", skip, module_mm, height, len(labs), len(pages),
                                                _unplaced_note(design) if cards else NO_CARDS), css)


NO_CARDS = ("No QR codes: this workspace is not attached to a home on a linked connection, "
            "and a code must open the item's card in the Portal")


def _tag_sheets(design: Dict, cards: Optional[Dict], title: str, s: Dict) -> str:
    """Small QR tags, for inside the cover of a socket, a switch or a
    device: the code, two short lines, the address in small type."""
    picked = set(s["items"])
    tags = [p for p in point_labels(design) if not picked or p["item"] in picked]
    tags += [c for b in layout(design) for r in b["rows"] for c in r["cells"]
             if not c.get("free") and c["kind"] not in ("circuit", "rcd") and (not picked or c["item"] in picked)]
    q = s["tag_mm"]
    w, h = q + 4, q + 12
    usable_w, usable_h = PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN
    per = max(1, int(usable_w // w)) * max(1, int(usable_h // h))
    cells: List[Optional[Dict]] = [None] * min(s["skip"], per - 1) + tags
    pages = [cells[i:i + per] for i in range(0, len(cells), per)] or [[]]
    out = []
    for page in pages:
        divs = []
        for t in page:
            if t is None:
                divs.append('<div class="tag used"></div>')
                continue
            url = _card(cards, t["item"])
            line2 = " · ".join(x for x in (t.get("board_tag") or "", numbers(t) if t.get("first") else t.get("number", ""),
                                           phase_text(t.get("phase", "")) if _three_phase(design) else "") if x)
            divs.append('<div class="tag">'
                        + (f'<div class="code">{qr_svg(url)}</div><i>{html.escape(_short_url(url))}</i>' if url
                           else '<div class="code none">no code</div>')
                        + f'<b>{html.escape(t["title"])}</b><small>{html.escape(line2 or t.get("room", ""))}</small></div>')
        out.append(f'<section class="sheet"><div class="tags">{"".join(divs)}</div></section>')
    css = f""".tags {{ display: grid; grid-template-columns: repeat(auto-fill, {w}mm); grid-auto-rows: {h}mm; }}
 .tag {{ border: 0.2mm dashed #999; padding: 1mm 2mm; display: flex; flex-direction: column; align-items: center;
        overflow: hidden; text-align: center; }}
 .tag.used {{ border-color: #eee; }}
 .tag .code svg {{ width: {q}mm; height: {q}mm; display: block; }}
 .tag .none {{ width: {q}mm; height: {q}mm; display: flex; align-items: center; justify-content: center; color: #b00; font-size: 6pt; }}
 .tag i {{ font: 3.2pt system-ui; color: #555; font-style: normal; white-space: nowrap; overflow: hidden; max-width: 100%; }}
 .tag b {{ font-size: 6pt; line-height: 1.1; max-width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
 .tag small {{ font-size: 5pt; color: #333; }}"""
    return _page(title, "".join(out), _controls("tag", s["skip"], s["module_mm"], s["strip_h"], len(tags), len(pages),
                                                "" if cards else NO_CARDS), css)


def _phase_bar(phase: str) -> str:
    parts = [phase[i:i + 2] for i in range(0, len(phase), 2)]
    if not parts:
        return ""
    stops = "".join(f'<b style="background:{PHASE_COLOURS.get(p, "#555")}"></b>' for p in parts)
    return f'<div class="ph" title="{phase_text(phase)}"><span class="ph-c">{stops}</span><i>{phase_text(phase)}</i></div>'


def _cell_html(c: Dict, module_mm: float, s: Optional[Dict] = None, three: bool = False) -> str:
    s = s or DEFAULTS
    where = numbers(c) if s["show_number"] else ""
    if c.get("free"):
        nums = "".join(f'<i style="width:{module_mm}mm">{n}</i>'
                       for n in range(c["first"], c["last"] + 1)) if c.get("first") else ""
        return f'<div class="cell free" style="width:{c["width"]}mm"><div class="nums">{nums}</div></div>'
    narrow = c["modules"] == 1
    cls = "cell" + (" narrow" if narrow else "") + ("" if c["placed"] else " guess") + (f" k-{c['kind']}")
    mark = ('<em class="q" title="to verify">?</em>' if c["to_verify"] else "")
    pos = "" if c["placed"] else '<em class="pos">position?</em>'
    sym = f'<div class="sy">{symbols.svg(c.get("symbol", "unknown"))}</div>' if s["show_symbol"] else ""
    ph = _phase_bar(c.get("phase", "")) if three and s["show_phase"] else ""
    return (f'<div class="{cls}" style="width:{c["width"]}mm">'
            f'<div class="num">{where}{mark}</div>{sym}'
            f'<div class="name"><span>{html.escape(c["title"])}</span></div>'
            f'<div class="val">{html.escape(c["short"])}{pos}</div>{ph}</div>')


def _strip_sheets(design: Dict, title: str, s: Dict) -> str:
    skip, module_mm, height = s["skip"], s["module_mm"], s["strip_h"]
    three = _three_phase(design)
    rows = strips(design, module_mm)
    usable = PAGE_W - 2 * MARGIN                         # landscape: the sheet's height is 210 mm
    per = max(1, int(usable // (height + STRIP_GAP)))
    items = [None] * min(skip, per - 1) + rows
    pages = [items[i:i + per] for i in range(0, len(items), per)] or [[]]
    out = []
    opts = s
    for page in pages:
        strips_html = []
        for s in page:
            if s is None:
                strips_html.append('<div class="strip used"></div>')
                continue
            where = "not on the board yet" if s["overflow"] else f"row {s['row']}{s['part']}"
            cells = "".join(_cell_html(c, module_mm, opts, three) for c in s["cells"])
            strips_html.append(f'<div class="strip"><small>{html.escape(s["board"])} · {where}</small>'
                               f'<div class="cells" style="width:{s["width"]}mm">{cells}</div></div>')
        out.append(f'<section class="sheet">{"".join(strips_html)}</section>')
    css = f""".strip {{ height: {height + STRIP_GAP}mm; }}
 .strip small {{ display: block; font-size: 6pt; color: #666; height: {STRIP_GAP - 1}mm; line-height: {STRIP_GAP - 1}mm; }}
 .strip.used {{ border-bottom: 0.2mm dashed #eee; }}
 .cells {{ display: flex; height: {height}mm; border: 0.25mm solid #222; }}
 .cell {{ flex: none; border-right: 0.25mm solid #222; padding: 0.7mm 0.6mm; overflow: hidden; display: flex;
         flex-direction: column; text-align: center; gap: 0.5mm; }}
 .cell:last-child {{ border-right: 0; }}
 .num {{ font: 600 6pt system-ui; color: #444; position: relative; }}
 .num .q {{ position: absolute; right: 0; top: 0; font: 700 7pt system-ui; color: #b00; }}
 .name {{ flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center; overflow: hidden; }}
 .name span {{ font-size: {opts["font_pt"]:g}pt; line-height: 1.1; overflow-wrap: anywhere; }}
 .narrow .name span {{ writing-mode: vertical-rl; transform: rotate(180deg); font-size: {opts["font_pt"] - 0.5:g}pt; max-height: 100%; }}
 .sy {{ display: flex; justify-content: center; }} .sy svg {{ width: {min(6.0, module_mm - 3):g}mm; height: {min(6.0, module_mm - 3):g}mm; }}
 .ph {{ display: flex; align-items: center; gap: 0.6mm; justify-content: center; font: 600 5pt system-ui; }}
 .ph .ph-c {{ display: flex; height: 1.6mm; width: 5mm; }} .ph .ph-c b {{ flex: 1; }} .ph i {{ font-style: normal; }}
 .narrow .ph i {{ display: none; }} .narrow .ph .ph-c {{ width: 100%; }}
 .val {{ font: 700 7pt system-ui; display: flex; flex-direction: column; }}
 .val .pos {{ font: italic 5pt system-ui; color: #8a5a00; }}
 .guess {{ background: repeating-linear-gradient(135deg, #fff, #fff 2mm, #fbf3e4 2mm, #fbf3e4 4mm); }}
 .k-rcd {{ background: #eef4fb; }}
 .cell.free {{ padding: 0.7mm 0; background: repeating-linear-gradient(45deg, #fff, #fff 1mm, #f1f1f1 1mm, #f1f1f1 2mm); }}
 .free .nums {{ display: flex; }}
 .free .nums i {{ font: 600 6pt system-ui; color: #aaa; font-style: normal; text-align: center; flex: none; }}"""
    return _page(title, "".join(out), _controls("strip", skip, module_mm, height, len(rows), len(pages),
                                                _unplaced_note(design)), css, landscape=True)


def _cable_sheets(design: Dict, title: str, s: Dict) -> str:
    """Cable labels packed on A4 portrait, each boxed by its cut line; a
    dashed line marks the half where the blank part starts to wrap."""
    labs = cable_labels(design, s)
    usable_w, usable_h = PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN
    gap = 2.0
    pages: List[List[Optional[Dict]]] = [[]]
    x = y = 0.0
    row_h = 0.0
    for lab in [None] * s["skip"] + labs:
        w, h = (lab["length"], lab["height"]) if lab else (0.0, 0.0)
        if lab is None:
            pages[-1].append(None)
            continue
        if x + w > usable_w + 0.01:
            x, y = 0.0, y + row_h + gap
            row_h = 0.0
        if y + h > usable_h + 0.01:
            pages.append([])
            x = y = row_h = 0.0
        pages[-1].append(lab)
        x += w + gap
        row_h = max(row_h, h)
    out = []
    for page in pages:
        divs = []
        for lab in page:
            if lab is None:
                continue
            sym = symbols.svg(lab["symbol"]) if s["show_symbol"] else ""
            ph = f' · {lab["phase"]}' if lab["phase"] and s["show_phase"] else ""
            end = "→ board" if lab["end"] == "board" else "→ load"
            divs.append(f'<div class="cab" style="width:{lab["length"]}mm;height:{lab["height"]}mm">'
                        f'<div class="txt" style="width:{lab["text_len"]}mm">'
                        f'<div class="l1">{sym}<b>{html.escape(lab["id"])}</b><small>{end}</small></div>'
                        f'<div class="l2">{html.escape(lab["title"])}</div>'
                        f'<div class="l3">{html.escape(lab["cable"])} · {html.escape(lab["rating"])}{html.escape(ph)}</div>'
                        f'</div><div class="wrap" title="Ø {lab["diameter"]:g} mm: wraps over the text"></div></div>')
        out.append(f'<section class="sheet"><div class="cabs">{"".join(divs)}</div></section>')
    css = f""".cabs {{ display: flex; flex-wrap: wrap; gap: 2mm; align-content: flex-start; }}
 .cab {{ display: flex; border: 0.2mm dashed #999; flex: none; overflow: hidden; }}
 .cab .txt {{ flex: none; padding: 0.8mm 1.2mm; display: flex; flex-direction: column; justify-content: center;
             gap: 0.4mm; overflow: hidden; border-right: 0.2mm dashed #c33; font-size: {s["font_pt"]:g}pt; line-height: 1.1; }}
 .cab .l1 {{ display: flex; align-items: center; gap: 1mm; }} .cab .l1 svg {{ width: 3.6mm; height: 3.6mm; flex: none; }}
 .cab .l1 small {{ margin-left: auto; font-size: 5pt; color: #666; }}
 .cab .l2 {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
 .cab .l3 {{ font-size: {max(5.0, s["font_pt"] - 1.5):g}pt; color: #333; white-space: nowrap; }}
 .cab .wrap {{ flex: 1; }}"""
    note = "text on the left half; the right half wraps over it" + (" · the cable diameter is estimated per circuit"
                                                                   if not s["cable_d"] else "")
    return _page(title, "".join(out), _controls("cable", s["skip"], s["module_mm"], s["strip_h"], len(labs),
                                                len(pages), note), css)
