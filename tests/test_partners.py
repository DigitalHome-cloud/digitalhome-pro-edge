# SPDX-License-Identifier: GPL-3.0-or-later
"""Partners: each by API or by file. Articles and prices here are invented."""

from __future__ import annotations

import io
import json

import pytest

from digitalhome_pro_edge import designs as dz
from digitalhome_pro_edge import partners as pt
from digitalhome_pro_edge.edge import knowledge as kn

BMECAT = b"""<?xml version="1.0" encoding="UTF-8"?>
<BMECAT version="2005" xmlns="http://www.bmecat.org/bmecat/2005">
 <HEADER><CATALOG><CURRENCY>EUR</CURRENCY></CATALOG></HEADER>
 <T_NEW_CATALOG>
  <PRODUCT><SUPPLIER_PID>TEST-RCD-40A</SUPPLIER_PID>
   <PRODUCT_DETAILS><DESCRIPTION_SHORT>RCD 2P 40 A 30 mA type A</DESCRIPTION_SHORT>
    <INTERNATIONAL_PID type="gtin">0000000000017</INTERNATIONAL_PID></PRODUCT_DETAILS>
   <PRODUCT_FEATURES><REFERENCE_FEATURE_SYSTEM_NAME>ETIM-10.0</REFERENCE_FEATURE_SYSTEM_NAME>
    <REFERENCE_FEATURE_GROUP_ID>EC999001</REFERENCE_FEATURE_GROUP_ID></PRODUCT_FEATURES>
   <PRODUCT_PRICE_DETAILS><PRODUCT_PRICE price_type="net_list"><PRICE_AMOUNT>61.50</PRICE_AMOUNT>
    <PRICE_CURRENCY>EUR</PRICE_CURRENCY></PRODUCT_PRICE></PRODUCT_PRICE_DETAILS>
  </PRODUCT>
  <PRODUCT><SUPPLIER_PID>TEST-MCB-16A</SUPPLIER_PID>
   <PRODUCT_DETAILS><DESCRIPTION_SHORT>MCB 1P+N 16 A</DESCRIPTION_SHORT></PRODUCT_DETAILS>
   <PRODUCT_PRICE_DETAILS><PRODUCT_PRICE><PRICE_AMOUNT>9.80</PRICE_AMOUNT></PRODUCT_PRICE></PRODUCT_PRICE_DETAILS>
  </PRODUCT>
 </T_NEW_CATALOG>
</BMECAT>"""

CSV = "Référence;Désignation;Prix\nTEST-BOARD-2R;Coffret 2 rangées 26 modules;48,90\nTEST-KM-20;Contacteur jour/nuit 20 A;1.234,50\n".encode()

DATANORM = "A;N;TEST-DN-1;00;Leitungsschutzschalter;B16 1P+N;1;0;Stk;0000985;;;\nB;N;TEST-DN-1;x\n".encode("cp850")


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("DHPRO_EDGE_EDGE_DATA", str(tmp_path / "data"))
    return tmp_path


def test_bmecat_with_etim_and_prices():
    got = pt.import_file("hager", "bmecat", BMECAT, "catalogue.xml")
    assert got == {"partner": "hager", "format": "bmecat", "articles": 2, "priced": 2}
    rcd = pt.search("hager", "rcd 40")[0]
    assert rcd["etim"] == "EC999001" and rcd["ean"] == "0000000000017" and rcd["price"] == "61.50"


def test_csv_with_french_columns_and_decimal_comma():
    pt.import_file("distributor", "csv", CSV)
    assert pt.price("distributor", "TEST-BOARD-2R")["price"] == "48.90"
    assert pt.price("distributor", "test-km-20")["price"] == "1234.50"


def test_datanorm_article_records():
    pt.import_file("wholesaler-de", "datanorm", DATANORM)
    got = pt.search("wholesaler-de", "B16")
    assert got[0]["reference"] == "TEST-DN-1" and got[0]["price"] == "9.85"


def test_capability_prefers_api_then_file():
    assert pt.capability("schneider")["use"] == "none"
    pt.import_file("schneider", "csv", CSV)
    assert pt.capability("schneider")["use"] == "file"
    pt.set_credentials("schneider", {"client_id": "x", "client_secret": "y", "supplier_id": "1", "customer_id": "2"})
    cap = pt.capability("schneider")
    assert cap["use"] == "api" and cap["api_configured"]
    assert "client_secret" not in json.dumps(pt.capabilities())
    pt.forget_credentials("schneider")
    assert pt.capability("schneider")["use"] == "file"


def test_hager_has_no_api():
    with pytest.raises(ValueError):
        pt.set_credentials("hager", {"client_id": "x"})


def test_private_files_are_owner_only(data):
    pt.import_file("distributor", "csv", CSV)
    d = data / "data" / "partners"
    assert oct(d.stat().st_mode & 0o777) == "0o700"
    assert all(oct(p.stat().st_mode & 0o777) == "0o600" for p in d.iterdir())


def test_schneider_client_follows_the_catalogue_spec():
    calls = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout=0):
        calls.append(req)
        if req.full_url.endswith("/token"):
            return Resp(b'{"access_token": "t", "expires_in": 3600}')
        return Resp(b'{"products": []}')

    c = pt.SchneiderClient({"client_id": "a", "client_secret": "b", "supplier_id": "S", "customer_id": "C"}, opener)
    c.catalogue("TEST-REF")
    url = calls[1].full_url
    assert url.startswith("https://api.se.com/v2/reference-data/product/product-catalog/products?")
    assert "product-reference=TEST-REF" in url and "supplierid=S" in url and "customerid=C" in url
    assert calls[1].headers["Authorization"] == "Bearer t"
    assert c.net_price("TEST-REF") is None          # no net-price path configured: never guessed


def test_bom_is_priced_where_a_reference_is_set(tmp_path):
    pt.import_file("hager", "bmecat", BMECAT)
    d = dz.Designs(kn.KnowledgeBase(tmp_path / "abox"))
    w = d.new_workspace("W", "demo-house")["workspace"]
    b = d.add_board(w, "B", 1, 13)["id"]
    r = d.add_rcd(w, b, "R", 40, 30, "A")["id"]
    d.set_reference(w, r, "hager", "TEST-RCD-40A")
    priced = pt.price_bom(d.bom(w))
    rcd = next(l for l in priced["lines"] if l["kind"] == "rcd")
    assert rcd["unit_price"] == "61.50" and rcd["source"] == "file:bmecat"
    assert not priced["complete"] and priced["total"] == "61.50"
