# SPDX-License-Identifier: GPL-3.0-or-later
"""Partner catalogues synced with the digitalhome.cloud marketplace (ADR-0006),
with the cloud answered here like /edge/v1/market/*. Sellers, articles and
prices are invented."""

from __future__ import annotations

import pytest
from rdflib import Graph, Literal, URIRef

from digitalhome_pro_edge import app as web
from digitalhome_pro_edge import catalogue as cat
from digitalhome_pro_edge import market as mk
from digitalhome_pro_edge import partners as pt
from digitalhome_pro_edge.core import version
from digitalhome_pro_edge.edge import cloud

A = "https://digitalhome.cloud/id/market/maker-a/"
P = "https://digitalhome.cloud/pro#"
SEED = f"""@prefix dhp: <{P}> . @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<{A}TEST-RCD-40> a dhp:Article ; dhp:partner "maker-a" ; dhp:reference "TEST-RCD-40" ;
  rdfs:label "RCD 40 A 30 mA" ; dhp:brand "Maker" ; dhp:usableIn "FR" .
"""
CSV = "Référence;Désignation;Prix\nTEST-MCB-16;MCB 1P+N 16 A;9,80\n".encode()


class Market:
    """A marketplace with one seller, maker-a, answering like edgeMarket."""

    def __init__(self):
        self.version, self.ttl, self.may_edit = 1, SEED, False
        self.staged, self.puts, self.files, self.uploaded = {}, [], set(), []
        self.calls = []
        self.race = 0                       # commits to refuse with 409, as if someone saved first
        self.invalid = None

    def call(self, path, body, profile=None):
        self.calls.append(path)
        if path == "market/sellers":
            return {"sellers": [{"id": "maker-a", "name": "Maker A", "kind": "manufacturer", "version": self.version,
                                 "articles": 1, "mayEdit": self.may_edit}]}
        if body.get("name", body.get("seller")) != "maker-a":
            raise cloud.CloudError("no such seller", status=404)
        if path == "market/graphs/get":
            return {"name": "maker-a", "version": self.version, "url": f"fake://get/{self.version}"}
        if path == "market/graphs/put":
            if not self.may_edit:
                raise cloud.CloudError("not allowed", status=403)
            if body["baseVersion"] != self.version:
                raise cloud.CloudError("conflict", status=409)
            if not body.get("commit"):
                key = f"k{len(self.staged)}"
                return {"key": key, "url": f"fake://put/{key}", "headers": {"Content-Type": "text/turtle"}}
            if self.race:
                self.race -= 1
                self._someone_else_saves()
                raise cloud.CloudError("conflict", status=409)
            if self.invalid:
                raise cloud.CloudError("invalid", status=422, payload={"problems": self.invalid})
            self.ttl, self.version = self.staged.pop(body["key"]), self.version + 1
            self.puts.append(self.ttl)
            return {"version": self.version}
        if path == "market/uploads":
            out = []
            for f in body["files"]:
                name = f"{f['sha256']}.{f['ext']}"
                out.append({"name": name, "exists": True} if name in self.files else
                           {"name": name, "exists": False, "url": f"fake://file/{name}", "headers": {}})
            return {"files": out}
        raise AssertionError(path)

    def http(self, method, url, data=None, headers=None):
        if url.startswith("fake://get/"):
            return self.ttl.encode()
        if url.startswith("fake://put/"):
            self.staged[url.rsplit("/", 1)[1]] = data.decode()
            return b""
        if url.startswith("fake://file/"):
            name = url.rsplit("/", 1)[1]
            self.files.add(name)
            self.uploaded.append(name)
            return b""
        raise AssertionError(url)

    def _someone_else_saves(self):
        g = Graph().parse(data=self.ttl, format="turtle")
        g.add((URIRef(A + "TEST-RCD-40"), URIRef(P + "conformsTo"), Literal("EN 61008-1")))
        self.ttl, self.version = g.serialize(format="turtle"), self.version + 1

    def graph(self):
        return Graph().parse(data=self.ttl, format="turtle")


@pytest.fixture
def market(tmp_path, monkeypatch):
    monkeypatch.setenv("DHPRO_EDGE_EDGE_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("DHPRO_EDGE_EDGE_STATE", str(tmp_path / "cloud.json"))
    m = Market()
    monkeypatch.setattr(cloud, "call", m.call)
    monkeypatch.setattr(cloud, "active_profile", lambda: "stage")
    monkeypatch.setattr(mk, "_http", m.http)
    return m


def rcd(prop):
    return sorted(str(o) for o in cat.load("maker-a").objects(URIRef(A + "TEST-RCD-40"), URIRef(P + prop)))


def test_subscribe_pulls_the_sellers_catalogue(market):
    got = mk.subscribe("maker-a")
    assert got["status"] == "ok" and got["pulled"] > 0 and got["pushed"] == 0 and got["version"] == 1
    assert pt.partner("maker-a")["market"] is True
    assert cat.article("maker-a", "TEST-RCD-40")["usable_in"] == ["FR"]
    assert mk.sellers()[0]["subscribed"] is True and mk.state()["maker-a"]["version"] == 1


def test_an_editor_merges_both_sides_and_pushes_without_prices(market):
    market.may_edit = True
    mk.subscribe("maker-a")
    pt.import_file("maker-a", "csv", CSV)                         # a new article here, with a price
    cat.set_article("maker-a", "TEST-RCD-40", usable_in=["FR", "BE"])
    market._someone_else_saves()                                   # and a change in the cloud
    got = mk.sync("maker-a")
    assert got["status"] == "ok" and got["version"] == 3 and got["pushed"] > 0
    pushed = market.graph()
    assert (URIRef(A + "TEST-MCB-16"), URIRef(P + "reference"), Literal("TEST-MCB-16")) in pushed
    assert rcd("usableIn") == ["BE", "FR"] and rcd("conformsTo") == ["EN 61008-1"]
    assert "9.80" not in market.ttl and "price" not in market.ttl.lower()
    assert pt.price("maker-a", "TEST-MCB-16")["price"] == "9.80"  # still here, privately
    again = mk.sync("maker-a")
    assert again["pushed"] == 0 and len(market.puts) == 1        # nothing new: nothing sent


def test_one_fact_two_values_is_a_conflict_the_person_settles(market):
    market.may_edit = True
    mk.subscribe("maker-a")
    g = cat.load("maker-a")
    g.set((URIRef(A + "TEST-RCD-40"), URIRef(P + "brand"), Literal("Maker Pro")))
    cat._save("maker-a", g)
    theirs = market.graph()
    theirs.set((URIRef(A + "TEST-RCD-40"), URIRef(P + "brand"), Literal("Maker Inc")))
    market.ttl, market.version = theirs.serialize(format="turtle"), 2
    got = mk.sync("maker-a")
    assert got["status"] == "conflict"
    c = got["conflicts"][0]
    assert c["mine"] == ["Maker Pro"] and c["theirs"] == ["Maker Inc"]
    assert mk.sync("maker-a", {c["key"]: "mine"})["status"] == "ok"
    assert rcd("brand") == ["Maker Pro"] and "Maker Pro" in market.ttl


def test_without_edit_rights_changes_stay_here(market):
    mk.subscribe("maker-a")
    cat.set_article("maker-a", "TEST-RCD-40", usable_in=["FR", "BE"])
    got = mk.sync("maker-a")
    assert got["status"] == "ok" and got["local_only"] == 1 and not market.puts
    market._someone_else_saves()
    got = mk.sync("maker-a")
    assert rcd("usableIn") == ["BE", "FR"] and rcd("conformsTo") == ["EN 61008-1"] and got["local_only"] == 1


def test_a_save_that_lost_the_race_merges_again(market):
    market.may_edit = True
    mk.subscribe("maker-a")
    cat.set_article("maker-a", "TEST-RCD-40", usable_in=["FR", "BE"])
    market.race = 1
    got = mk.sync("maker-a")
    assert got["status"] == "ok" and rcd("conformsTo") == ["EN 61008-1"] and "BE" in market.ttl


def test_the_cloud_refuses_an_invalid_catalogue(market):
    market.may_edit = True
    mk.subscribe("maker-a")
    cat.set_article("maker-a", "TEST-RCD-40", usable_in=["FR", "BE"])
    market.invalid = ["TEST-RCD-40: a GTIN has 8 to 14 digits (dhp:ean)"]
    got = mk.sync("maker-a")
    assert got["status"] == "invalid" and "GTIN" in got["problems"][0]
    assert "maker-a" not in mk.state() or mk.state()["maker-a"]["version"] == 1    # nothing recorded as agreed


def test_files_go_up_once_by_hash(market):
    market.may_edit = True
    mk.subscribe("maker-a")
    got = mk.attach("maker-a", "TEST-RCD-40", b"%PDF-1.4 datasheet", "rcd.PDF")
    name = got["datasheet"]
    assert name.endswith(".pdf") and len(name) == 68 and mk.file_path(name).read_bytes().startswith(b"%PDF")
    mk.sync("maker-a")
    assert market.uploaded == [name] and rcd("datasheet") == [name]
    mk.attach("maker-a", "TEST-RCD-40", b"\x89PNG image", "front.png")
    mk.sync("maker-a")
    assert len(market.uploaded) == 2                               # the pdf was not sent again
    with pytest.raises(ValueError, match="image"):
        mk.attach("maker-a", "TEST-RCD-40", b"<html>", "x.html")
    assert mk.file_path("../cloud.json") is None


def test_old_local_catalogues_move_to_marketplace_names(market):
    pt.add_partner("shop-b", "Shop B", "distributor", ["csv"])
    old = cat._path("shop-b")
    old.write_text('<https://digitalhome.cloud/catalogue/shop-b/X%201> a <https://digitalhome.cloud/pro#Article> ; '
                   '<https://digitalhome.cloud/pro#reference> "X 1" .\n')
    assert cat.article("shop-b", "X 1")["reference"] == "X 1"
    assert "/id/market/shop-b/X%201" in old.read_text()


def test_routes(market, monkeypatch):
    monkeypatch.setattr(version, "UPDATE_CHECK", False)
    monkeypatch.setattr(web, "_designs", None)
    web.app.config["TESTING"] = True
    c = web.app.test_client()
    assert c.get("/api/market").get_json()["sellers"][0]["subscribed"] is False
    assert c.post("/api/market/subscribe", json={"seller": "maker-a"}).get_json()["status"] == "ok"
    assert c.post("/api/market/sync", json={"partner": "maker-a", "resolve": {"k": "both"}}).status_code == 400
    assert c.post("/api/market/sync", json={"partner": "nobody"}).status_code == 400
    r = c.post("/api/partners/maker-a/articles/file", data={"reference": "TEST-RCD-40",
                                                            "file": (__import__("io").BytesIO(b"%PDF x"), "d.pdf")})
    name = r.get_json()["datasheet"]
    assert c.get(f"/api/market/files/{name}").data == b"%PDF x"
    assert c.get("/api/market/files/nothing.pdf").status_code == 404
    cloud.call = lambda *a, **k: (_ for _ in ()).throw(cloud.NotLinked("default is not linked"))
    assert c.get("/api/market").status_code == 409
