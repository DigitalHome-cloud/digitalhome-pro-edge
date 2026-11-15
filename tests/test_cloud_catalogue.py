# SPDX-License-Identifier: GPL-3.0-or-later
"""The digitalhome.cloud catalogue on this edge, both ways (ADR-0005), with the
cloud answered here. Models and partners are invented."""

from __future__ import annotations

import pytest

from digitalhome_pro_edge import app as web
from digitalhome_pro_edge import catalogue as cat
from digitalhome_pro_edge import cloud_catalogue as cc
from digitalhome_pro_edge import partners as pt
from digitalhome_pro_edge.core import version
from digitalhome_pro_edge.edge import cloud

M1 = {"modelNumber": "TEST-SW-1", "brand": "Maker", "deviceType": "Switch actuator", "region": "EU",
      "standards": ["EN 60669"], "hasActorCapability": True, "voltageV": 230, "updatedAt": "2026-11-15T10:00:00.000Z"}
M2 = {"modelNumber": "TEST-TH-2", "brand": "Other", "deviceType": "Thermostat", "description": "Wall thermostat",
      "region": "DE, FR", "updatedAt": "2026-11-15T10:00:00.000Z"}


class Cloud:
    """Answers cloud.call like /edge/v1/catalogue[/put] would."""

    def __init__(self):
        self.calls, self.pages, self.put, self.profile = [], [], None, "stage"

    def __call__(self, path, body, profile=None):
        self.calls.append((path, body))
        if path == "catalogue":
            return self.pages.pop(0)
        if isinstance(self.put, Exception):
            raise self.put
        return {"model": dict(body["model"], updatedAt="2026-11-15T11:00:00.000Z"), "created": True}


@pytest.fixture
def fake(tmp_path, monkeypatch):
    monkeypatch.setenv("DHPRO_EDGE_EDGE_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("DHPRO_EDGE_EDGE_STATE", str(tmp_path / "cloud.json"))
    c = Cloud()
    monkeypatch.setattr(cloud, "call", c)
    monkeypatch.setattr(cloud, "active_profile", lambda: c.profile)
    return c


def test_first_sync_is_full_and_pages(fake):
    fake.pages = [{"models": [M1], "cursor": "abc", "now": "2026-11-15T12:00:00.000Z"},
                  {"models": [M2], "cursor": None, "now": "2026-11-15T12:00:05.000Z"}]
    got = cc.sync()
    assert got == {"profile": "stage", "full": True, "changed": 2, "models": 2}
    assert fake.calls == [("catalogue", {}), ("catalogue", {"cursor": "abc"})]
    assert cc.state()["since"] == "2026-11-15T12:00:00.000Z"       # the first page's `now`
    art = cat.article(cc.PARTNER, "TEST-TH-2")
    assert art["label"] == "Wall thermostat" and art["usable_in"] == ["DE", "FR"]
    assert cat.article(cc.PARTNER, "TEST-SW-1")["conforms_to"] == ["EN 60669"]
    assert [m["reference"] for m in cc.models("thermo")] == ["TEST-TH-2"]


def test_next_sync_asks_since_and_keeps_the_rest(fake):
    fake.pages = [{"models": [M1, M2], "cursor": None, "now": "T1"}]
    cc.sync()
    fake.pages = [{"models": [dict(M1, region="FR")], "cursor": None, "now": "T2"}]
    got = cc.sync()
    assert fake.calls[-1] == ("catalogue", {"since": "T1"}) and got["full"] is False
    assert got["models"] == 2 and cat.article(cc.PARTNER, "TEST-SW-1")["usable_in"] == ["FR"]


def test_another_connection_starts_over(fake):
    fake.pages = [{"models": [M1, M2], "cursor": None, "now": "T1"}]
    cc.sync()
    fake.profile = "prod"
    fake.pages = [{"models": [M2], "cursor": None, "now": "T9"}]
    got = cc.sync()
    assert fake.calls[-1] == ("catalogue", {}) and got == {"profile": "prod", "full": True, "changed": 1, "models": 1}


def test_an_old_cloud_says_so(fake):
    fake.pages = []
    def gone(path, body, profile=None):
        raise cloud.CloudError("not found", status=404)
    cloud.call = gone
    with pytest.raises(ValueError, match="no catalogue for edges"):
        cc.sync()


def test_publish_sends_the_article_without_a_price(fake):
    pt.add_partner("shop-b", "Shop B", "distributor", ["csv"])
    pt.import_file("shop-b", "csv", "Référence;Désignation;Prix\nTEST-RCD-40;RCD 40 A 30 mA;61,50\n".encode())
    cat.set_article("shop-b", "TEST-RCD-40", usable_in=["FR"], conforms_to=["EN 61008"])
    got = cc.publish("shop-b", "TEST-RCD-40", brand="Maker", device_type="RCD", category="FACILITIES_APPLIANCES")
    sent = fake.calls[-1][1]["model"]
    assert sent == {"modelNumber": "TEST-RCD-40", "brand": "Maker", "deviceType": "RCD", "description": "RCD 40 A 30 mA",
                    "region": "FR", "standards": ["EN 61008"], "category": "FACILITIES_APPLIANCES"}
    assert got["created"] is True and cat.article(cc.PARTNER, "TEST-RCD-40")["usable_in"] == ["FR"]


def test_publish_refusals(fake):
    pt.add_partner("shop-b", "Shop B", "distributor", ["csv"])
    pt.import_file("shop-b", "csv", "Référence;Désignation;Prix\nTEST-X;Thing;1\n".encode())
    with pytest.raises(ValueError, match="brand and a device type"):
        cc.publish("shop-b", "TEST-X", brand="Maker")
    with pytest.raises(ValueError, match="category"):
        cc.publish("shop-b", "TEST-X", brand="Maker", device_type="T", category="TOASTERS")
    with pytest.raises(ValueError, match="no article"):
        cc.publish("shop-b", "NOPE", brand="Maker", device_type="T")
    fake.put = cloud.CloudError("forbidden", status=403, code="not_allowed")
    with pytest.raises(PermissionError, match="catalogue admin"):
        cc.publish("shop-b", "TEST-X", brand="Maker", device_type="T")
    with pytest.raises(ValueError, match="reserved|synced cloud catalogue"):
        pt.add_partner(cc.PARTNER, "x")


def test_routes(fake, monkeypatch):
    monkeypatch.setattr(version, "UPDATE_CHECK", False)
    monkeypatch.setattr(web, "_designs", None)
    web.app.config["TESTING"] = True
    c = web.app.test_client()
    assert c.get("/api/cloud-catalogue").get_json()["models"] == []
    fake.pages = [{"models": [M1], "cursor": None, "now": "T1"}]
    assert c.post("/api/cloud-catalogue/sync", json={}).get_json()["models"] == 1
    got = c.get("/api/cloud-catalogue?q=maker").get_json()
    assert got["state"]["profile"] == "stage" and got["models"][0]["reference"] == "TEST-SW-1"
    assert c.get(f"/api/partners/{cc.PARTNER}/catalogue.ttl").status_code == 200
    pt.add_partner("shop-b", "Shop B", "distributor", ["csv"])
    pt.import_file("shop-b", "csv", "Référence;Désignation;Prix\nTEST-X;Thing;1\n".encode())
    fake.put = cloud.CloudError("forbidden", status=403)
    r = c.post("/api/cloud-catalogue/publish", json={"partner": "shop-b", "reference": "TEST-X", "brand": "M", "device_type": "T"})
    assert r.status_code == 403
    fake.put = cloud.NotLinked("not linked")
    assert c.post("/api/cloud-catalogue/publish", json={"partner": "shop-b", "reference": "TEST-X",
                                                         "brand": "M", "device_type": "T"}).status_code == 409
    fake.put = cloud.CloudError("bad gateway", status=500)
    assert c.post("/api/cloud-catalogue/publish", json={"partner": "shop-b", "reference": "TEST-X",
                                                         "brand": "M", "device_type": "T"}).status_code == 502
