# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
labels.py — printable labels for a design, for full-sheet A4 sticker paper
(297 × 210 mm, one adhesive sheet per page, cut by hand along the lines).

Two layouts:

  grid   QR labels, 70 × 37 mm, 3 × 8 = 24 per sheet: one per RCD, circuit
         and device, each QR opening the item on this edge
  strip  board strips, on the sheet in landscape: one strip per row of each
         board, every device as wide as the modules it takes (17.5 mm per DIN
         module by default), to stick above the devices on the board itself;
         a row longer than 281 mm is cut into pieces stuck end to end

`skip` leaves the first cells of the first sheet empty, so a sheet whose
top was already used can go through the printer again.

The pattern is digitalhome-devops-edge's panel cards (webapp Codes.js): the
browser prints the page (window.print, @page A4, no margins); there is no
printer driver here. QR codes are SVG from segno (pure Python). Print at
100 % ("actual size"), not "fit to page", or the cut lines will not match.
"""

from __future__ import annotations

import html
import urllib.parse
from typing import Dict, List

import segno

PAGE_W, PAGE_H = 210.0, 297.0          # A4 portrait, mm
MARGIN = 8.0                           # what most printers cannot print
GRID = {"w": 70.0, "h": 37.0, "cols": 3, "rows": 8}
STRIP_H = 15.0                         # height of a board strip, mm
MODULE_MM = 17.5                       # one DIN module


def link(base_url: str, workspace: str, item: str) -> str:
    return f"{base_url.rstrip('/')}/#w={urllib.parse.quote(workspace)}&i={urllib.parse.quote(item)}"


def qr_svg(data: str) -> str:
    return segno.make(data, error="m").svg_inline(scale=3, border=1)


def board_labels(design: Dict) -> List[Dict]:
    """The labels of every board, in board order: each RCD, then the
    circuits below it (their own breaker), then the other devices."""
    out: List[Dict] = []
    for b in design["boards"]:
        for r in b["rcds"]:
            out.append({"board": b["label"], "board_id": b["id"], "item": r["id"], "kind": "rcd", "modules": 2,
                        "title": r["label"], "short": f"{r['sensitivity_ma']:g} mA {r['rcd_type']}",
                        "detail": f"{r['rated_current']:g} A · {r['sensitivity_ma']:g} mA · type {r['rcd_type']}"})
            for c in r["circuits"]:
                out.append({"board": b["label"], "board_id": b["id"], "item": c["id"], "kind": "circuit", "modules": 1,
                            "title": c["label"], "short": f"{c['rated_current']:g} A",
                            "detail": f"{c['rated_current']:g} A · {c['cross_section']:g} mm² · {r['label']}"})
        for d in b["devices"]:
            rc = d.get("rated_current")
            out.append({"board": b["label"], "board_id": b["id"], "item": d["id"], "kind": d["kind"],
                        "modules": d.get("modules", 1), "title": d["label"],
                        "short": f"{rc:g} A" if rc is not None else "",
                        "detail": f"{rc:g} A" if rc is not None else d["kind"].replace("_", " ")})
    return out


def strips(design: Dict, module_mm: float = MODULE_MM, max_mm: float = PAGE_H - 2 * MARGIN) -> List[Dict]:
    """One strip per board row: the devices in board order, wrapped at the
    row's module count. A row longer than the sheet is cut into pieces that
    are stuck end to end."""
    out = []
    for s in _rows(design, module_mm):
        width = s["modules"] * module_mm
        if width <= max_mm:
            out.append({**s, "width": width, "part": ""})
            continue
        piece, w, k = [], 0.0, 1
        for c in s["cells"]:
            if w + c["width"] > max_mm and piece:
                out.append({**s, "cells": piece, "width": w, "part": f" ({k})"})
                piece, w, k = [], 0.0, k + 1
            piece.append(c)
            w += c["width"]
        rest = s["modules"] * module_mm - sum(c["width"] for c in s["cells"])
        out.append({**s, "cells": piece, "width": w + rest, "part": f" ({k})"})
    return out


def _rows(design: Dict, module_mm: float) -> List[Dict]:
    out = []
    labels = board_labels(design)
    for b in design["boards"]:
        row, used, n = [], 0, 1
        for lab in (x for x in labels if x["board_id"] == b["id"]):
            m = max(1, int(lab["modules"]))
            if used + m > b["modules_per_row"] and row:
                out.append({"board": b["label"], "row": n, "cells": row, "modules": b["modules_per_row"]})
                row, used, n = [], 0, n + 1
            row.append({**lab, "width": m * module_mm})
            used += m
        if row:
            out.append({"board": b["label"], "row": n, "cells": row, "modules": b["modules_per_row"]})
    return out


def _page(title: str, body: str, controls: str, extra_css: str = "", landscape: bool = False) -> str:
    w, h = (PAGE_H, PAGE_W) if landscape else (PAGE_W, PAGE_H)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Labels — {title}</title>
<style>
 @page {{ size: A4 {"landscape" if landscape else "portrait"}; margin: 0; }}
 * {{ box-sizing: border-box; }}
 body {{ margin: 0; font: 12px system-ui, sans-serif; color: #111; background: #ddd; }}
 .bar {{ padding: 10px 16px; background: #fff; border-bottom: 1px solid #bbb; display: flex; gap: 10px;
        align-items: center; flex-wrap: wrap; position: sticky; top: 0; }}
 .bar form {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
 .bar input[type=number] {{ width: 60px; }}
 .sheet {{ width: {w}mm; height: {h}mm; background: #fff; margin: 10mm auto; position: relative;
          padding: {MARGIN}mm; overflow: hidden; page-break-after: always; break-after: page; }}
 .sheet:last-child {{ page-break-after: auto; break-after: auto; }}
 {extra_css}
 @media print {{ body {{ background: #fff; }} .bar {{ display: none; }} .sheet {{ margin: 0; }} }}
</style></head><body>
<div class="bar">{controls}</div>
{body}
</body></html>"""


def _controls(layout: str, skip: int, module_mm: float, count: int, sheets: int) -> str:
    sel = lambda v: " selected" if v == layout else ""  # noqa: E731
    return (f'<form method="get"><b>A4 sticker sheet, 297 × 210 mm</b>'
            f'<select name="layout"><option value="grid"{sel("grid")}>QR labels 70 × 37 mm</option>'
            f'<option value="strip"{sel("strip")}>Board strips</option></select>'
            f'<label>skip <input type="number" name="skip" min="0" max="23" value="{skip}"></label>'
            f'<label>module <input type="number" name="module" min="9" max="27" step="0.5" value="{module_mm:g}"> mm</label>'
            f'<button>Show</button></form>'
            f'<button onclick="window.print()">Print</button>'
            f'<span>{count} labels on {sheets} sheet{"s" if sheets != 1 else ""} · print at 100 %, not “fit to page”</span>')


def sheet(design: Dict, base_url: str, layout: str = "grid", skip: int = 0, module_mm: float = MODULE_MM) -> str:
    """The printable A4 sheets as a standalone HTML page."""
    title = html.escape(design["title"])
    skip = max(0, int(skip))
    module_mm = float(module_mm)
    if layout == "strip":
        return _strip_sheets(design, title, skip, module_mm)
    per = GRID["cols"] * GRID["rows"]
    cells = [None] * min(skip, per - 1) + board_labels(design)
    pages = [cells[i:i + per] for i in range(0, len(cells), per)] or [[]]
    out = []
    for page in pages:
        divs = []
        for lab in page:
            if lab is None:
                divs.append('<div class="lbl used"></div>')
                continue
            url = link(base_url, design["workspace"], lab["item"])
            divs.append('<div class="lbl">'
                        f'<div class="qr">{qr_svg(url)}</div>'
                        f'<div class="txt"><b>{html.escape(lab["title"])}</b>'
                        f'<span>{html.escape(lab["detail"])}</span>'
                        f'<small>{html.escape(lab["board"])}</small></div></div>')
        out.append(f'<section class="sheet"><div class="grid">{"".join(divs)}</div></section>')
    css = f""".grid {{ display: grid; grid-template-columns: repeat({GRID['cols']}, {GRID['w']}mm);
   grid-auto-rows: {GRID['h']}mm; justify-content: center; }}
 .lbl {{ display: flex; gap: 3mm; align-items: center; padding: 3mm; border: 0.2mm dashed #999; overflow: hidden; }}
 .lbl.used {{ border-color: #eee; }}
 .qr svg {{ width: 24mm; height: 24mm; display: block; }}
 .txt {{ display: flex; flex-direction: column; gap: 1mm; min-width: 0; }}
 .txt b {{ font-size: 11pt; line-height: 1.1; }} .txt span {{ font-size: 8pt; }} .txt small {{ color: #555; font-size: 7pt; }}"""
    n = len(cells) - min(skip, per - 1)
    return _page(title, "".join(out), _controls("grid", skip, module_mm, n, len(pages)), css)


def _strip_sheets(design: Dict, title: str, skip: int, module_mm: float) -> str:
    rows = strips(design, module_mm)
    usable = PAGE_W - 2 * MARGIN                         # landscape: the sheet's height is 210 mm
    per = int(usable // (STRIP_H + 4))                  # strips per sheet, 4 mm between them
    blanks = [None] * min(skip, per - 1)
    items = blanks + rows
    pages = [items[i:i + per] for i in range(0, len(items), per)] or [[]]
    out = []
    for page in pages:
        strips_html = []
        for s in page:
            if s is None:
                strips_html.append('<div class="strip used"></div>')
                continue
            cells = "".join(
                f'<div class="cell" style="width:{c["width"]}mm"><b>{html.escape(c["title"])}</b>'
                f'<span>{html.escape(c["short"])}</span></div>' for c in s["cells"])
            free = s["width"] - sum(c["width"] for c in s["cells"])
            if free > 0.1:
                cells += f'<div class="cell free" style="width:{free}mm"></div>'
            strips_html.append(f'<div class="strip"><small>{html.escape(s["board"])} · row {s["row"]}{s["part"]}</small>'
                               f'<div class="cells" style="width:{s["width"]}mm">{cells}</div></div>')
        out.append(f'<section class="sheet">{"".join(strips_html)}</section>')
    css = f""".strip {{ height: {STRIP_H + 4}mm; }}
 .strip small {{ display: block; font-size: 6pt; color: #666; height: 3mm; }}
 .strip.used {{ border-bottom: 0.2mm dashed #eee; }}
 .cells {{ display: flex; height: {STRIP_H}mm; border: 0.2mm solid #333; }}
 .cell {{ flex: none; border-right: 0.2mm solid #333; padding: 0.6mm; overflow: hidden; display: flex;
         flex-direction: column; justify-content: space-between; text-align: center; }}
 .cell:last-child {{ border-right: 0; }}
 .cell b {{ font-size: 6.5pt; line-height: 1.05; word-break: break-word; }}
 .cell span {{ font-size: 7pt; font-weight: 600; }}
 .cell.free {{ background: repeating-linear-gradient(45deg, #fff, #fff 1mm, #f1f1f1 1mm, #f1f1f1 2mm); }}"""
    return _page(title, "".join(out), _controls("strip", skip, module_mm, len(rows), len(pages)), css, landscape=True)
