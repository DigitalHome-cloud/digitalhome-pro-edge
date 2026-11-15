# SPDX-License-Identifier: GPL-3.0-or-later
"""Partners: a private list, each by API or by file. Partners, articles and
prices here are invented; only the API connector is real code."""

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
    pt.add_partner("maker-a", "Maker A", "manufacturer", ["bmecat", "csv"])
    pt.add_partner("maker-api", "Maker with an API", "manufacturer", ["csv"], api="schneider")
    pt.add_partner("shop-b", "Shop B", "distributor", ["csv"])
    pt.add_partner("whole-c", "Wholesaler C", "wholesaler", ["datanorm"])
    return tmp_path


def test_bmecat_with_etim_and_prices():
    got = pt.import_file("maker-a", "bmecat", BMECAT, "catalogue.xml")
    assert got == {"partner": "maker-a", "format": "bmecat", "articles": 2, "priced": 2}
    rcd = pt.search("maker-a", "rcd 40")[0]
    assert rcd["etim"] == "EC999001" and rcd["ean"] == "0000000000017" and rcd["price"] == "61.50"


def test_csv_with_french_columns_and_decimal_comma():
    pt.import_file("shop-b", "csv", CSV)
    assert pt.price("shop-b", "TEST-BOARD-2R")["price"] == "48.90"
    assert pt.price("shop-b", "test-km-20")["price"] == "1234.50"


def test_datanorm_article_records():
    pt.import_file("whole-c", "datanorm", DATANORM)
    got = pt.search("whole-c", "B16")
    assert got[0]["reference"] == "TEST-DN-1" and got[0]["price"] == "9.85"


def test_capability_prefers_api_then_file():
    assert pt.capability("maker-api")["use"] == "none"
    pt.import_file("maker-api", "csv", CSV)
    assert pt.capability("maker-api")["use"] == "file"
    pt.set_credentials("maker-api", {"client_id": "x", "client_secret": "y", "supplier_id": "1", "customer_id": "2"})
    cap = pt.capability("maker-api")
    assert cap["use"] == "api" and cap["api_configured"]
    assert "client_secret" not in json.dumps(pt.capabilities())
    pt.forget_credentials("maker-api")
    assert pt.capability("maker-api")["use"] == "file"


def test_a_partner_without_a_connector_takes_no_credentials():
    with pytest.raises(ValueError):
        pt.set_credentials("maker-a", {"client_id": "x"})


def test_the_list_is_private_data_not_code():
    assert not hasattr(pt, "PARTNERS")
    assert [p["id"] for p in pt.register()] == ["maker-a", "maker-api", "shop-b", "whole-c"]
    pt.remove_partner("shop-b")
    assert "shop-b" not in [p["id"] for p in pt.register()]
    with pytest.raises(ValueError):
        pt.import_file("nobody", "csv", CSV)
    with pytest.raises(ValueError):
        pt.add_partner("x", "X", api="no-such-connector")


def test_the_list_and_credentials_can_live_in_the_cloud(monkeypatch, data):
    cloud_side = {}

    def call(path, body, profile=None):
        if path == "partners/get":
            return {"partners": cloud_side.get("register", [])}
        if path == "partners/put":
            cloud_side["register"] = body["partners"]
            return {}
        if path == "partners/credentials/get":
            return {"values": cloud_side.get(("cred", body["partner"]))}
        if path == "partners/credentials/put":
            cloud_side[("cred", body["partner"])] = body["values"]
            return {}
        raise AssertionError(path)

    monkeypatch.setattr(pt.cloud, "call", call)
    pt.set_credentials("maker-api", {"client_id": "x", "client_secret": "y", "supplier_id": "1", "customer_id": "2"})
    pt.set_store("cloud")
    folder = data / "data" / "partners"
    assert not list(folder.glob("*.credentials.json")) and not (folder / "register.json").exists()
    assert [p["id"] for p in cloud_side["register"]][0] == "maker-a"
    assert cloud_side[("cred", "maker-api")]["client_secret"] == "y"
    assert pt.capability("maker-api")["use"] == "api"
    pt.set_store("local")
    assert cloud_side["register"] == [] and cloud_side[("cred", "maker-api")] is None
    assert pt.capability("maker-api")["api_configured"]


def test_a_cloud_without_partner_storage_is_refused_and_nothing_moves(monkeypatch):
    def call(path, body, profile=None):
        raise pt.cloud.CloudError("not found", 404)
    monkeypatch.setattr(pt.cloud, "call", call)
    with pytest.raises(ValueError, match="does not keep partner data"):
        pt.set_store("cloud")
    assert pt.store()["where"] == "local" and len(pt.register()) == 4


def test_private_files_are_owner_only(data):
    pt.import_file("shop-b", "csv", CSV)
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
    pt.import_file("maker-a", "bmecat", BMECAT)
    d = dz.Designs(kn.KnowledgeBase(tmp_path / "abox"))
    w = d.new_workspace("W", "demo-house")["workspace"]
    b = d.add_board(w, "B", 1, 13)["id"]
    r = d.add_rcd(w, b, "R", 40, 30, "A")["id"]
    d.set_reference(w, r, "maker-a", "TEST-RCD-40A")
    priced = pt.price_bom(d.bom(w))
    rcd = next(l for l in priced["lines"] if l["kind"] == "rcd")
    assert rcd["unit_price"] == "61.50" and rcd["source"] == "file:bmecat"
    assert not priced["complete"] and priced["total"] == "61.50"


def test_catalogue_links_articles_to_markets_and_norms(tmp_path):
    from digitalhome_pro_edge import catalogue as cat
    pt.add_partner("maker-eu", "Maker EU", "manufacturer", ["csv"], markets=["EU"])
    csv_eu = ("reference;description;price;norms;markets;standards\n"
              "EU-RCD;RCD 40 A type A;50;;;EN 61008-1\n"
              "FR-ONLY;Socket, French pattern;5;nfc15100;FR;NF C 61-314\n"
              "BE-ONLY;Socket, Belgian pattern;5;;BE;\n").encode()
    pt.import_file("maker-eu", "csv", csv_eu)
    nfc = cat.DHC.Norm_NFC15100
    assert cat.usable("maker-eu", "EU-RCD", nfc)["status"] == "yes"          # EU default → FR
    assert cat.usable("maker-eu", "FR-ONLY", nfc)["why"] == "approved for Norm_NFC15100"
    got = cat.usable("maker-eu", "BE-ONLY", nfc)
    assert got["status"] == "no" and "BE" in got["why"]
    assert cat.usable("maker-eu", "NOPE", nfc)["status"] == "unknown"
    art = cat.article("maker-eu", "EU-RCD")
    assert art["usable_in"] == ["EU"] and art["conforms_to"] == ["EN 61008-1"]
    ttl = cat.turtle("maker-eu")
    assert "dhp:approvedFor dhc:Norm_NFC15100" in ttl and "50" not in ttl.split("EU-RCD")[1][:200]

    d = dz.Designs(kn.KnowledgeBase(tmp_path / "abox"))
    w = d.new_workspace("W", "demo-house")["workspace"]
    b = d.add_board(w, "B", 2, 13)["id"]
    r = d.add_rcd(w, b, "R", 40, 30, "A")["id"]
    room = d.add_room(w, "Hall")["id"]
    c = d.add_circuit(w, r, "Sockets", "socket", 16, 1.5)["id"]
    p = d.add_point(w, c, "socket", "Hall socket", room)["id"]
    d.set_reference(w, p, "maker-eu", "BE-ONLY")
    found = [f for f in d.report(w)["findings"] if f["rule"] == "article-norm"]
    assert len(found) == 1 and "BE-ONLY" in found[0]["message"]
    cat.set_article("maker-eu", "BE-ONLY", usable_in=["BE", "FR"])
    assert not [f for f in d.report(w)["findings"] if f["rule"] == "article-norm"]


def test_prices_never_enter_the_catalogue():
    from digitalhome_pro_edge import catalogue as cat
    pt.import_file("shop-b", "csv", CSV)
    assert "48" not in cat.turtle("shop-b") and "price" not in cat.turtle("shop-b").lower()
