# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
inbox.py — files given to the chat (ADR-0004).

A person drops a file on the page — a partner's price list, a BMEcat
catalogue, a supplier's quote as PDF, a spreadsheet, a Turtle design — and
the chat reads it and decides what it is for: articles for a partner, or the
facts of a design, which it then proposes tool by tool like anything else.
The design is the chat plus the ontologies; a file is one more input to it.

Each file is kept privately, <data>/inbox/<id>/ (0700, files 0600), with
meta.json: name, size, the kind detected from its content (not its name
alone), and a short note of what was found. Text is extracted on demand:

  csv, txt, json, xml, ttl   as text
  pdf                        pdftotext (poppler), when installed
  xlsx                       read with the standard library (zip + XML)

Nothing here sends a file anywhere. Importing articles goes through
partners.import_file, so the partner rules (registered partner, private
items file, catalogue graph) apply unchanged.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

from . import partners as pt
from .edge import knowledge as kn

MAX_BYTES = 64 * 1024 * 1024
TEXT_LIMIT = 20000               # characters returned per read
KINDS = ("bmecat", "datanorm", "csv", "xlsx", "turtle", "json", "pdf", "quote", "text", "unknown")
_ID = re.compile(r"^in-[0-9a-f]{10}$")


def _root() -> Path:
    d = kn.data_dir() / "inbox"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def _dir(fid: str) -> Path:
    if not _ID.match(fid or ""):
        raise ValueError(f"not a file id: {fid}")
    d = _root() / fid
    if not d.is_dir():
        from .designs import NotFound
        raise NotFound(f"no file {fid} in the inbox")
    return d


def _write(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


# ------------------------------------------------------------- reading ----

def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _pdf_text(path: Path) -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        raise ValueError("reading a PDF needs pdftotext (poppler-utils) on this computer")
    got = subprocess.run([exe, "-layout", "-enc", "UTF-8", str(path), "-"],
                         capture_output=True, timeout=60, check=False)
    if got.returncode != 0:
        raise ValueError("pdftotext could not read this PDF")
    return got.stdout.decode("utf-8", "replace")


def _col(ref: str) -> int:
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + ord(ch.upper()) - 64
    return n - 1


def xlsx_rows(data: bytes, limit: int = 100000) -> List[List[str]]:
    """The first sheet of a workbook, as rows of strings."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        shared: List[str] = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
        sheets = sorted(n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
        if not sheets:
            return []
        rows = []
        for r in ET.fromstring(z.read(sheets[0])).iter(f"{{{ns['m']}}}row"):
            row: List[str] = []
            for c in r.findall("m:c", ns):
                v = c.find("m:v", ns)
                if c.get("t") == "inlineStr":
                    text = "".join(t.text or "" for t in c.iter(f"{{{ns['m']}}}t"))
                elif v is None:
                    text = ""
                elif c.get("t") == "s":
                    text = shared[int(v.text)]
                else:
                    text = v.text or ""
                i = _col(c.get("r", ""))
                if i >= 0:
                    row.extend([""] * (i - len(row)))
                row.append(text)
            rows.append(row)
            if len(rows) >= limit:
                break
        return rows


def _xlsx_csv(data: bytes) -> bytes:
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    for row in xlsx_rows(data):
        w.writerow(row)
    return out.getvalue().encode()


def extract(path: Path, kind: str) -> str:
    data = path.read_bytes()
    if kind in ("pdf", "quote"):
        return _pdf_text(path)
    if kind == "xlsx":
        return _xlsx_csv(data).decode()
    return _decode(data)


# ----------------------------------------------------------- detecting ----

_QUOTE = re.compile(r"\b(devis|quote|quotation|angebot|kostenvoranschlag|offerte|proposition commerciale)\b", re.I)


def _n(k: int, one: str, many: str) -> str:
    return f"{k} {one if k == 1 else many}"


def detect(name: str, data: bytes, path: Optional[Path] = None) -> Dict:
    """What a file is, from its content: {kind, note}."""
    head = data[:4096]
    low = name.lower()
    if head.startswith(b"%PDF"):
        try:
            text = _pdf_text(path) if path else ""
        except (ValueError, subprocess.TimeoutExpired):
            return {"kind": "pdf", "note": "a PDF; its text could not be read here"}
        if _QUOTE.search(text[:5000]):
            return {"kind": "quote", "note": "a PDF that reads like a quote"}
        return {"kind": "pdf", "note": f"a PDF, {len(text.split())} words of text"}
    if head.startswith(b"PK") and (low.endswith(".xlsx") or b"xl/" in data[:2000]):
        try:
            rows = xlsx_rows(data, limit=2000)
        except (zipfile.BadZipFile, ET.ParseError, KeyError):
            return {"kind": "unknown", "note": "a zip archive, not a readable workbook"}
        items = pt.parse_csv(_xlsx_csv(data)) if rows else []
        return {"kind": "xlsx", "note": f"a workbook, {_n(len(rows), 'row', 'rows')}" +
                (", 1 looks like an article" if len(items) == 1 else
                 f", {len(items)} look like articles" if items else "")}
    text = _decode(head)
    stripped = text.lstrip()
    if stripped.startswith("<") and re.search(r"<\s*BMECAT\b", text, re.I):
        return {"kind": "bmecat", "note": f"a BMEcat catalogue, {_n(len(pt.parse_bmecat(data)), 'article', 'articles')}"}
    if low.endswith((".ttl", ".turtle")) or re.match(r"(@prefix|PREFIX)\s", stripped):
        return {"kind": "turtle", "note": "Turtle: a model graph"}
    if stripped[:1] in "{[":
        try:
            json.loads(_decode(data))
            return {"kind": "json", "note": "JSON"}
        except ValueError:
            pass
    if re.match(r"^[VA][; ]", stripped) or low.endswith((".001", ".dat", ".dnr")):
        items = pt.parse_datanorm(data)
        if items:
            return {"kind": "datanorm", "note": f"a Datanorm file, {_n(len(items), 'article', 'articles')}"}
    items = pt.parse_csv(data) if b";" in head or b"," in head or b"\t" in head else []
    if items:
        return {"kind": "csv", "note": "a table, " + ("1 row looks like an article" if len(items) == 1 else f"{len(items)} rows look like articles")}
    if stripped.startswith("<"):
        return {"kind": "text", "note": "XML"}
    if b"\x00" in head:
        return {"kind": "unknown", "note": "a binary file this edge cannot read"}
    return {"kind": "text", "note": f"text, {len(text.split())} words at the start"}


# ------------------------------------------------------------- the box ----

def add(name: str, data: bytes) -> Dict:
    if not data:
        raise ValueError("the file is empty")
    if len(data) > MAX_BYTES:
        raise ValueError(f"files up to {MAX_BYTES // (1024 * 1024)} MB")
    name = Path(name or "file").name[:200] or "file"
    fid = "in-" + secrets.token_hex(5)
    d = _root() / fid
    d.mkdir(mode=0o700)
    raw = d / "file"
    _write(raw, data)
    found = detect(name, data, raw)
    meta = {"id": fid, "name": name, "size": len(data), "added": int(time.time()), **found}
    _write(d / "meta.json", json.dumps(meta, ensure_ascii=False).encode())
    return meta


def files() -> List[Dict]:
    out = []
    for d in _root().iterdir():
        m = d / "meta.json"
        if _ID.match(d.name) and m.exists():
            out.append(json.loads(m.read_text()))
    return sorted(out, key=lambda m: -m["added"])


def meta(fid: str) -> Dict:
    return json.loads((_dir(fid) / "meta.json").read_text())


def read(fid: str, offset: int = 0, limit: int = TEXT_LIMIT) -> Dict:
    """A slice of the file's text, so a long file is read in parts."""
    m = meta(fid)
    if m["kind"] == "unknown":
        raise ValueError(f"{m['name']}: {m['note']}")
    text = extract(_dir(fid) / "file", m["kind"])
    offset = max(0, int(offset))
    limit = max(1, min(int(limit), TEXT_LIMIT))
    return {**m, "offset": offset, "length": len(text), "text": text[offset:offset + limit],
            "more": offset + limit < len(text)}


def remove(fid: str) -> Dict:
    shutil.rmtree(_dir(fid))
    return {"removed": fid}


_FORMAT = {"bmecat": "bmecat", "datanorm": "datanorm", "csv": "csv", "xlsx": "csv"}


def import_partner(fid: str, partner: str, fmt: str = "") -> Dict:
    """Import a file's articles for a registered partner."""
    m = meta(fid)
    fmt = fmt or _FORMAT.get(m["kind"], "")
    if fmt not in pt.PARSERS:
        raise ValueError(f"{m['name']} is {m['note']}; articles come from {', '.join(pt.FORMATS)} or a workbook")
    data = (_dir(fid) / "file").read_bytes()
    if m["kind"] == "xlsx":
        data = _xlsx_csv(data)
    got = pt.import_file(partner, fmt, data, m["name"])
    return {**got, "file": fid}
