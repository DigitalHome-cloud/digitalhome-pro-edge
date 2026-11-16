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

Two layouts:

  strip  board strips, on the sheet in landscape: one strip per board row,
         every module 17.5 mm wide by default, to stick under or over the
         row; a narrow device's name runs upwards, as on a handwritten strip;
         a row longer than the sheet is cut into pieces stuck end to end
  grid   QR labels, 70 × 37 mm, 3 × 8 = 24 per sheet: one per RCD, circuit
         and device, in board order, each QR opening the item on this edge

`skip` leaves the first cells (grid) or strips (strip) of the first sheet
empty, so a sheet whose top was already used can go through the printer
again.

The browser prints the page (window.print, @page A4, no margins); there is
no printer driver here. QR codes are SVG from segno (pure Python). Print at
100 % ("actual size"), not "fit to page", or the cut lines will not match.
"""

from __future__ import annotations

import html
import urllib.parse
from typing import Dict, List, Optional

import segno

PAGE_W, PAGE_H = 210.0, 297.0          # A4 portrait, mm
MARGIN = 8.0                           # what most printers cannot print
GRID = {"w": 70.0, "h": 37.0, "cols": 3, "rows": 8}
STRIP_H = 30.0                         # height of a board strip, mm
MODULE_MM = 17.5                       # one DIN module
STRIP_GAP = 5.0                        # between strips on a sheet: the caption and the cut


def link(base_url: str, workspace: str, item: str) -> str:
    return f"{base_url.rstrip('/')}/#w={urllib.parse.quote(workspace)}&i={urllib.parse.quote(item)}"


def qr_svg(data: str) -> str:
    return segno.make(data, error="m").svg_inline(scale=3, border=1)


def _n(v, unit: str) -> str:
    """A value with its unit, or "?" for one a survey has not read yet."""
    return f"{v:g} {unit}" if v is not None else f"? {unit}"


# ---------------------------------------------------------------- what is labelled

def board_labels(design: Dict) -> List[Dict]:
    """The labels of every board in the design's order: each RCD and the
    circuits below it (their own breaker), the circuits below no RCD, then
    the other devices. Each knows its width and, if read, its position."""
    out: List[Dict] = []

    def add(b: Dict, x: Dict, kind: str, modules: int, short: str, detail: str) -> None:
        out.append({"board": b["label"], "board_id": b["id"], "item": x["id"], "kind": kind,
                    "modules": max(1, int(modules or 1)), "title": x["label"], "short": short, "detail": detail,
                    "row": x.get("row"), "slot": x.get("slot"), "to_verify": bool(x.get("to_verify"))})

    def circuit(b: Dict, c: Dict, upstream: str) -> None:
        detail = f"{_n(c['rated_current'], 'A')} · {_n(c['cross_section'], 'mm²')}" + (f" · {upstream}" if upstream else "")
        add(b, c, "circuit", c.get("modules", 1), _n(c["rated_current"], "A"), detail)

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
            f'<option value="grid"{sel("grid")}>QR labels 70 × 37 mm</option></select>'
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


def sheet(design: Dict, base_url: str, layout: str = "strip", skip: int = 0, module_mm: float = MODULE_MM,
          height: Optional[float] = None) -> str:
    """The printable A4 sheets as a standalone HTML page."""
    title = html.escape(design["title"])
    skip = max(0, int(skip))
    module_mm = float(module_mm)
    height = float(height or STRIP_H)
    if layout == "strip":
        return _strip_sheets(design, title, skip, module_mm, height)
    return _grid_sheets(design, base_url, title, skip, module_mm, height)


def _grid_sheets(design: Dict, base_url: str, title: str, skip: int, module_mm: float, height: float) -> str:
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
            url = link(base_url, design["workspace"], lab["item"])
            where = numbers(lab)
            divs.append('<div class="lbl">'
                        f'<div class="qr">{qr_svg(url)}</div>'
                        f'<div class="txt"><b>{html.escape(lab["title"])}</b>'
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
 .qr svg {{ width: 24mm; height: 24mm; display: block; }}
 .txt {{ display: flex; flex-direction: column; gap: 1mm; min-width: 0; }}
 .txt b {{ font-size: 11pt; line-height: 1.1; }} .txt span {{ font-size: 8pt; }} .txt small {{ color: #555; font-size: 7pt; }}"""
    return _page(title, "".join(out), _controls("grid", skip, module_mm, height, len(labs), len(pages),
                                                _unplaced_note(design)), css)


def _cell_html(c: Dict, module_mm: float) -> str:
    where = numbers(c)
    if c.get("free"):
        nums = "".join(f'<i style="width:{module_mm}mm">{n}</i>'
                       for n in range(c["first"], c["last"] + 1)) if c.get("first") else ""
        return f'<div class="cell free" style="width:{c["width"]}mm"><div class="nums">{nums}</div></div>'
    narrow = c["modules"] == 1
    cls = "cell" + (" narrow" if narrow else "") + ("" if c["placed"] else " guess") + (f" k-{c['kind']}")
    mark = ('<em class="q" title="to verify">?</em>' if c["to_verify"] else "")
    pos = "" if c["placed"] else '<em class="pos">position?</em>'
    return (f'<div class="{cls}" style="width:{c["width"]}mm">'
            f'<div class="num">{where}{mark}</div>'
            f'<div class="name"><span>{html.escape(c["title"])}</span></div>'
            f'<div class="val">{html.escape(c["short"])}{pos}</div></div>')


def _strip_sheets(design: Dict, title: str, skip: int, module_mm: float, height: float) -> str:
    rows = strips(design, module_mm)
    usable = PAGE_W - 2 * MARGIN                         # landscape: the sheet's height is 210 mm
    per = max(1, int(usable // (height + STRIP_GAP)))
    items = [None] * min(skip, per - 1) + rows
    pages = [items[i:i + per] for i in range(0, len(items), per)] or [[]]
    out = []
    for page in pages:
        strips_html = []
        for s in page:
            if s is None:
                strips_html.append('<div class="strip used"></div>')
                continue
            where = "not on the board yet" if s["overflow"] else f"row {s['row']}{s['part']}"
            cells = "".join(_cell_html(c, module_mm) for c in s["cells"])
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
 .name span {{ font-size: 7.5pt; line-height: 1.1; overflow-wrap: anywhere; }}
 .narrow .name span {{ writing-mode: vertical-rl; transform: rotate(180deg); font-size: 7pt; max-height: 100%; }}
 .val {{ font: 700 7pt system-ui; display: flex; flex-direction: column; }}
 .val .pos {{ font: italic 5pt system-ui; color: #8a5a00; }}
 .guess {{ background: repeating-linear-gradient(135deg, #fff, #fff 2mm, #fbf3e4 2mm, #fbf3e4 4mm); }}
 .k-rcd {{ background: #eef4fb; }}
 .cell.free {{ padding: 0.7mm 0; background: repeating-linear-gradient(45deg, #fff, #fff 1mm, #f1f1f1 1mm, #f1f1f1 2mm); }}
 .free .nums {{ display: flex; }}
 .free .nums i {{ font: 600 6pt system-ui; color: #aaa; font-style: normal; text-align: center; flex: none; }}"""
    return _page(title, "".join(out), _controls("strip", skip, module_mm, height, len(rows), len(pages),
                                                _unplaced_note(design)), css, landscape=True)
