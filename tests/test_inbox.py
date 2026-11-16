# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""The inbox: files given to the chat, kinds detected from content."""

import io
import shutil
import zipfile

import pytest

from digitalhome_pro_edge import inbox as ib
from digitalhome_pro_edge import partners as pt


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("DHPRO_EDGE_EDGE_DATA", str(tmp_path / "data"))
    pt.add_partner("shop-b", "Shop B", "distributor", ["csv", "bmecat"])
    yield


CSV = b"reference;description;price\nX-1;RCD 40 A type A;48,50\nX-2;Breaker 16 A;6,10\n"
BMECAT = (b'<?xml version="1.0"?><BMECAT version="2005"><T_NEW_CATALOG><PRODUCT><SUPPLIER_PID>B-1</SUPPLIER_PID>'
          b'<PRODUCT_DETAILS><DESCRIPTION_SHORT>Contactor 2P</DESCRIPTION_SHORT></PRODUCT_DETAILS></PRODUCT>'
          b'</T_NEW_CATALOG></BMECAT>')


def _xlsx(rows):
    buf = io.BytesIO()
    strings = sorted({c for r in rows for c in r})
    idx = {s: i for i, s in enumerate(strings)}
    sheet = "".join("<row>" + "".join(f'<c r="{chr(65 + j)}{i + 1}" t="s"><v>{idx[c]}</v></c>' for j, c in enumerate(r))
                    + "</row>" for i, r in enumerate(rows))
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/sharedStrings.xml", f"<sst {ns}>" + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{sheet}</sheetData></worksheet>")
    return buf.getvalue()


def test_kinds_come_from_content_not_the_name():
    assert ib.add("prices.txt", CSV)["kind"] == "csv"
    assert ib.add("export.xml", BMECAT)["kind"] == "bmecat"
    assert ib.add("model.data", b"@prefix dhc: <https://digitalhome.cloud/ontology#> .\n")["kind"] == "turtle"
    assert ib.add("notes", b"Kitchen: oven, hob, two double sockets.")["kind"] == "text"
    assert ib.add("blob.bin", b"\x00\x01\x02\x03")["kind"] == "unknown"
    wb = ib.add("list.xlsx", _xlsx([["reference", "description", "price"], ["W-1", "Socket", "3,20"]]))
    assert wb["kind"] == "xlsx" and "1 looks like an article" in wb["note"]


def test_files_are_private_and_read_in_slices():
    m = ib.add("long.txt", ("word " * 10000).encode())
    d = ib._root() / m["id"]
    assert (d.stat().st_mode & 0o777) == 0o700 and ((d / "file").stat().st_mode & 0o777) == 0o600
    got = ib.read(m["id"], 0, 100)
    assert len(got["text"]) == 100 and got["more"] is True
    assert ib.read(m["id"], got["length"] - 5, 100)["more"] is False
    assert [f["id"] for f in ib.files()] == [m["id"]]
    ib.remove(m["id"])
    assert ib.files() == []


def test_bad_ids_never_reach_the_disk():
    with pytest.raises(ValueError):
        ib.read("../partners")


def test_import_to_partner_from_csv_and_workbook():
    got = ib.import_partner(ib.add("p.csv", CSV)["id"], "shop-b")
    assert got["articles"] == 2 and got["format"] == "csv"
    wb = ib.add("w.xlsx", _xlsx([["reference", "description", "price"], ["W-1", "Socket", "3,20"]]))
    assert ib.import_partner(wb["id"], "shop-b")["articles"] == 1
    assert pt.price("shop-b", "W-1")["price"] == "3.20"
    with pytest.raises(ValueError):
        ib.import_partner(ib.add("n.txt", b"just words here")["id"], "shop-b")


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="poppler-utils not installed")
def test_a_pdf_quote_is_recognised(tmp_path):
    # the smallest PDF that pdftotext reads: one page, one line of text
    text = b"BT /F1 12 Tf 72 720 Td (DEVIS electricite tableau) Tj ET"
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(text) + text + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    m = ib.add("scan.pdf", out)
    assert m["kind"] == "quote"
    assert "DEVIS" in ib.read(m["id"])["text"]
