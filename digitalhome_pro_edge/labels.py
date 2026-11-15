# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
labels.py — printable labels for a design: one per device on a board, in the
order they sit, each with a QR code that opens the item on this edge.

The pattern is digitalhome-devops-edge's panel cards (webapp Codes.js): the
browser prints the sheet (window.print, @media print); there is no printer
driver here. QR codes are SVG from segno (pure Python).
"""

from __future__ import annotations

import html
import urllib.parse
from typing import Dict, List

import segno


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
            out.append({"board": b["label"], "item": r["id"], "kind": "rcd",
                        "title": r["label"],
                        "detail": f"{r['rated_current']:g} A · {r['sensitivity_ma']:g} mA · type {r['rcd_type']}"})
            for c in r["circuits"]:
                out.append({"board": b["label"], "item": c["id"], "kind": "circuit", "title": c["label"],
                            "detail": f"{c['rated_current']:g} A · {c['cross_section']:g} mm² · {r['label']}"})
        for d in b["devices"]:
            rc = d.get("rated_current")
            out.append({"board": b["label"], "item": d["id"], "kind": d["kind"], "title": d["label"],
                        "detail": f"{rc:g} A" if rc is not None else d["kind"].replace("_", " ")})
    return out


def sheet(design: Dict, base_url: str) -> str:
    """The printable sheet as a standalone HTML page."""
    cards = []
    for lab in board_labels(design):
        url = link(base_url, design["workspace"], lab["item"])
        cards.append(
            '<div class="lbl">'
            f'<div class="qr">{qr_svg(url)}</div>'
            f'<div class="txt"><b>{html.escape(lab["title"])}</b>'
            f'<span>{html.escape(lab["detail"])}</span>'
            f'<small>{html.escape(lab["board"])}</small></div></div>')
    title = html.escape(design["title"])
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Labels — {title}</title>
<style>
 body{{font:12px system-ui,sans-serif;margin:16px;color:#111;background:#fff}}
 h1{{font-size:16px;margin:0 0 12px}} .bar{{margin-bottom:12px}}
 .sheet{{display:grid;grid-template-columns:repeat(auto-fill,minmax(62mm,1fr));gap:4mm}}
 .lbl{{display:flex;gap:3mm;align-items:center;border:1px dashed #999;padding:2mm;break-inside:avoid}}
 .qr svg{{width:20mm;height:20mm;display:block}}
 .txt{{display:flex;flex-direction:column;gap:1mm;min-width:0}}
 .txt b{{font-size:12px}} .txt span{{font-size:10px}} .txt small{{color:#555;font-size:9px}}
 @media print{{.bar{{display:none}} body{{margin:6mm}}}}
</style></head><body>
<h1>{title}</h1>
<div class="bar"><button onclick="window.print()">Print</button> {len(cards)} labels</div>
<div class="sheet">{''.join(cards)}</div>
</body></html>"""
