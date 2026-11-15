# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
partners.py — manufacturers, distributors and wholesalers as sources of
product data and prices, through whichever channel each one offers
(ADR-0002):

  api   a partner API, when this edge has credentials for it
  file  a data exchange file someone imported: BMEcat with ETIM, Datanorm 4,
        or a CSV price list (any distributor's export)

WHO the partners are is private: the register (each partner's id, name,
kind, formats and API connector) and the API credentials are kept either on
this computer or in the connected digitalhome.cloud instance, never in the
repository. The code only knows the CONNECTORS — how to talk to a partner
API — and the FILE FORMATS it reads.

Imported files (articles and net prices) stay on this computer, in the data
folder (0700/0600). Credentials never pass through the chat or MCP.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .edge import cloud
from .edge import knowledge as kn

FORMATS = ("csv", "bmecat", "datanorm")
KINDS = ("manufacturer", "distributor", "wholesaler")
_ID = re.compile(r"[a-z][a-z0-9-]{0,39}")


class NotConfigured(Exception):
    pass


def _dir() -> Path:
    d = kn.data_dir() / "partners"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(d, 0o700)
    return d


def _write(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.replace(tmp, path)


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _check(partner: str) -> str:
    partner = (partner or "").strip().lower()
    if not _ID.fullmatch(partner):
        raise ValueError("a partner is lowercase letters, digits and -")
    return partner


def _price(text) -> Optional[str]:
    if text is None:
        return None
    t = str(text).strip().replace(" ", "").replace(" ", "")
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    else:
        t = t.replace(",", ".")
    try:
        return str(Decimal(t))
    except InvalidOperation:
        return None


# ------------------------------------------------------------- the files ----

def parse_csv(data: bytes) -> List[Dict]:
    """A price list as CSV (; or ,): columns named reference/ref/article,
    description, price, and optionally ean, etim, currency, unit."""
    text = data.decode("utf-8-sig", errors="replace")
    dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t")
    rows = csv.DictReader(io.StringIO(text), dialect=dialect)
    names = {"reference": ("reference", "ref", "article", "artikelnummer", "référence", "refciale"),
             "description": ("description", "designation", "désignation", "libelle", "libellé", "kurztext"),
             "price": ("price", "prix", "preis", "net", "tarif", "tarifd"),
             "ean": ("ean", "gtin"), "etim": ("etim", "etim_class", "class"),
             "currency": ("currency", "devise", "währung"), "unit": ("unit", "unité", "einheit"),
             "norms": ("norms", "norm", "normes", "norme", "normen"),
             "markets": ("markets", "market", "region", "marchés", "märkte", "pays", "country"),
             "standards": ("standards", "standard", "conformité", "konformität")}
    out = []
    for row in rows:
        low = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        item = {key: next((low[c] for c in cands if low.get(c)), "") for key, cands in names.items()}
        if not item["reference"]:
            continue
        item["price"] = _price(item["price"])
        item["currency"] = item["currency"] or "EUR"
        out.append(item)
    return out


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first(el: ET.Element, *names: str) -> Optional[ET.Element]:
    for d in el.iter():
        if _local(d.tag) in names:
            return d
    return None


def parse_bmecat(data: bytes) -> List[Dict]:
    """BMEcat 1.2 (ARTICLE / SUPPLIER_AID) or 2005 (PRODUCT / SUPPLIER_PID),
    with the ETIM class from the feature system, when there is one."""
    root = ET.fromstring(data)
    currency_el = _first(root, "CURRENCY")
    currency = currency_el.text.strip() if currency_el is not None and currency_el.text else "EUR"
    out = []
    for el in root.iter():
        if _local(el.tag) not in ("ARTICLE", "PRODUCT"):
            continue
        ref = _first(el, "SUPPLIER_AID", "SUPPLIER_PID")
        if ref is None or not (ref.text or "").strip():
            continue
        desc = _first(el, "DESCRIPTION_SHORT")
        ean = _first(el, "EAN")
        if ean is None:
            ean = next((d for d in el.iter() if _local(d.tag) == "INTERNATIONAL_PID"
                        and d.get("type", "").lower() in ("gtin", "ean")), None)
        etim = ""
        for feats in el.iter():
            if _local(feats.tag) in ("ARTICLE_FEATURES", "PRODUCT_FEATURES"):
                system = _first(feats, "REFERENCE_FEATURE_SYSTEM_NAME")
                group = _first(feats, "REFERENCE_FEATURE_GROUP_ID")
                if system is not None and (system.text or "").upper().startswith("ETIM") and group is not None:
                    etim = (group.text or "").strip()
                    break
        amount = _first(el, "PRICE_AMOUNT")
        cur = _first(el, "PRICE_CURRENCY")
        out.append({"reference": ref.text.strip(),
                    "description": (desc.text or "").strip() if desc is not None else "",
                    "ean": (ean.text or "").strip() if ean is not None else "",
                    "etim": etim, "unit": "",
                    "price": _price(amount.text) if amount is not None else None,
                    "currency": (cur.text.strip() if cur is not None and cur.text else currency)})
    return out


def parse_datanorm(data: bytes) -> List[Dict]:
    """Datanorm 4 article records ("A;…"): reference, two short texts, price
    unit and the price in cents. Other record types are skipped."""
    text = data.decode("cp850", errors="replace")
    out = []
    for line in text.splitlines():
        f = line.split(";")
        if len(f) < 10 or f[0] != "A":
            continue
        # A;Satzkennzeichen;Artikelnummer;Textkennzeichen;Kurztext1;Kurztext2;
        # Preiskennzeichen;Preiseinheit;Mengeneinheit;Preis;…
        try:
            per = {"0": 1, "1": 10, "2": 100, "3": 1000}.get(f[7].strip(), 1)
            price = Decimal(f[9].strip() or "0") / 100 / per
        except InvalidOperation:
            price = None
        out.append({"reference": f[2].strip(), "description": " ".join(x.strip() for x in f[4:6] if x.strip()),
                    "ean": "", "etim": "", "unit": f[8].strip(),
                    "price": str(price) if price is not None else None, "currency": "EUR"})
    return out


PARSERS = {"csv": parse_csv, "bmecat": parse_bmecat, "datanorm": parse_datanorm}


def import_file(pid: str, fmt: str, data: bytes, name: str = "") -> Dict:
    pid = _check(pid)
    if partner(pid) is None:
        raise ValueError(f"{pid} is not in the partner list")
    if fmt not in PARSERS:
        raise ValueError(f"format is one of {', '.join(FORMATS)}")
    items = PARSERS[fmt](data)
    if not items:
        raise ValueError(f"no articles found in this {fmt} file")
    _write(_dir() / f"{pid}.items.json",
           {"partner": pid, "format": fmt, "file": name, "imported": int(time.time()), "items": items})
    from . import catalogue
    catalogue.write_articles(pid, items, partner(pid).get("markets") or [])
    return {"partner": pid, "format": fmt, "articles": len(items),
            "priced": sum(1 for i in items if i.get("price"))}


def _items(partner: str) -> Optional[Dict]:
    return _read(_dir() / f"{_check(partner)}.items.json", None)


# --------------------------------------------- the private store ----
#
# The register and the credentials live in ONE place, chosen on the page:
# "local" (the data folder) or "cloud" (the connected digitalhome.cloud
# instance, through the edge API: /edge/v1/partners/…). The cloud keeps them
# for the home, so a second edge of the same home sees the same partners.

def _store_path() -> Path:
    return _dir() / "store.json"


def store() -> Dict:
    got = _read(_store_path(), {})
    return {"where": got.get("where", "local"), "profile": got.get("profile", "")}


def set_store(where: str, profile: str = "") -> Dict:
    """Move the register and credentials to `where` (local or cloud). What is
    stored at the old place is copied over first, then removed there."""
    if where not in ("local", "cloud"):
        raise ValueError("where is local or cloud")
    old = store()
    if old["where"] == where and old.get("profile", "") == profile:
        return old
    register, creds = _get_register(), {p["id"]: _get_credentials(p["id"]) for p in _get_register()}
    _write(_store_path(), {"where": where, "profile": profile})
    try:
        _put_register(register)
        for pid, values in creds.items():
            if values:
                _put_credentials(pid, values)
    except Exception:
        _write(_store_path(), old)               # the new place refused: stay where we were
        raise
    if old["where"] == "local":
        for p in _dir().glob("*.credentials.json"):
            p.unlink()
        _store_file("register").unlink(missing_ok=True)
    else:                                        # clear the cloud copy, so nothing lingers there
        new = store()
        _write(_store_path(), old)
        try:
            for pid in creds:
                _put_credentials(pid, None)
            _put_register([])
        finally:
            _write(_store_path(), new)
    return store()


def _store_file(name: str) -> Path:
    return _dir() / f"{name}.json"


def _cloud(path: str, body: Dict) -> Dict:
    try:
        return cloud.call(f"partners/{path}", body, store()["profile"] or None)
    except cloud.CloudError as e:
        if e.status == 404:
            raise ValueError("the connected cloud does not keep partner data yet "
                             "(it needs /edge/v1/partners); keep it on this computer for now") from e
        raise


def _get_register() -> List[Dict]:
    if store()["where"] == "cloud":
        return list(_cloud("get", {}).get("partners") or [])
    return list(_read(_store_file("register"), []))


def _put_register(register: List[Dict]) -> None:
    if store()["where"] == "cloud":
        _cloud("put", {"partners": register})
    else:
        _write(_store_file("register"), register)


def _cred_path(partner: str) -> Path:
    return _dir() / f"{_check(partner)}.credentials.json"


def _get_credentials(partner: str) -> Optional[Dict]:
    if store()["where"] == "cloud":
        return _cloud("credentials/get", {"partner": partner}).get("values") or None
    return _read(_cred_path(partner), None)


def _put_credentials(partner: str, values: Optional[Dict]) -> None:
    if store()["where"] == "cloud":
        _cloud("credentials/put", {"partner": partner, "values": values})
    elif values is None:
        _cred_path(partner).unlink(missing_ok=True)
    else:
        _write(_cred_path(partner), values)


def register() -> List[Dict]:
    return sorted(_get_register(), key=lambda p: p["id"])


def partner(pid: str) -> Optional[Dict]:
    pid = _check(pid)
    return next((p for p in _get_register() if p["id"] == pid), None)


def add_partner(id: str, name: str, kind: str = "distributor", formats: Optional[List[str]] = None,  # noqa: A002
                api: str = "", note: str = "", markets: Optional[List[str]] = None) -> Dict:
    """Add or replace a partner in the private register."""
    pid = _check(id)
    if kind not in KINDS:
        raise ValueError(f"kind is one of {', '.join(KINDS)}")
    formats = [f for f in (formats or ["csv"]) if f]
    bad = [f for f in formats if f not in FORMATS]
    if bad:
        raise ValueError(f"unknown format {', '.join(bad)}; one of {', '.join(FORMATS)}")
    if api and api not in CONNECTORS:
        raise ValueError(f"no API connector {api}; one of {', '.join(CONNECTORS) or 'none'}")
    entry = {"id": pid, "name": (name or pid).strip(), "kind": kind, "formats": formats,
             "api": api, "note": (note or "").strip(),
             "markets": sorted({m.strip().upper() for m in (markets or []) if m.strip()})}
    reg = [p for p in _get_register() if p["id"] != pid] + [entry]
    _put_register(reg)
    return entry


def remove_partner(pid: str) -> Dict:
    pid = _check(pid)
    _put_register([p for p in _get_register() if p["id"] != pid])
    _put_credentials(pid, None)
    (_dir() / f"{pid}.items.json").unlink(missing_ok=True)
    (_dir() / f"{pid}.catalogue.ttl").unlink(missing_ok=True)
    return {"removed": pid}


def set_credentials(partner_id: str, values: Dict) -> Dict:
    """Store a partner API's credentials (from the page, never the chat)."""
    p = partner(partner_id)
    if p is None:
        raise ValueError(f"{partner_id} is not in the partner list")
    conn = CONNECTORS.get(p.get("api") or "")
    if conn is None:
        raise ValueError(f"{p['name']} has no API connector")
    keep = {k: str(v).strip() for k, v in values.items() if k in conn.FIELDS and str(v).strip()}
    missing = [k for k in conn.REQUIRED if k not in keep]
    if missing:
        raise ValueError("missing: " + ", ".join(missing))
    _put_credentials(p["id"], keep)
    return {"partner": p["id"], "configured": True, "where": store()["where"]}


def forget_credentials(partner_id: str) -> Dict:
    _put_credentials(_check(partner_id), None)
    return {"partner": partner_id, "configured": False}


# -------------------------------------------------------------- the APIs ----

class SchneiderClient:
    """Schneider Electric's partner APIs, OAuth2 client credentials.

    The catalogue endpoint follows the published spec (Product Catalog v2,
    api-explorer.se.com). The net-price path is configurable because its spec
    is behind the partner login; it is not called until it is set.
    """
    FIELDS = ("client_id", "client_secret", "supplier_id", "customer_id", "base_url",
              "token_url", "netprice_path")
    REQUIRED = ("client_id", "client_secret", "supplier_id", "customer_id")
    CATALOGUE = "/v2/reference-data/product/product-catalog/products"

    def __init__(self, cfg: Dict, opener=urllib.request.urlopen):
        self.cfg = cfg
        self.base = cfg.get("base_url") or "https://api.se.com"
        self.open = opener
        self._token: Optional[str] = None
        self._until = 0.0

    def token(self) -> str:
        if self._token and time.time() < self._until - 60:
            return self._token
        body = urllib.parse.urlencode({"grant_type": "client_credentials",
                                       "client_id": self.cfg["client_id"],
                                       "client_secret": self.cfg["client_secret"]}).encode()
        req = urllib.request.Request(self.cfg.get("token_url") or self.base + "/token", data=body,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with self.open(req, timeout=20) as r:
            got = json.load(r)
        self._token, self._until = got["access_token"], time.time() + float(got.get("expires_in", 600))
        return self._token

    def _get(self, path: str, query: Dict) -> Dict:
        url = self.base + path + "?" + urllib.parse.urlencode(query, doseq=True)
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token()}",
                                                   "Accept": "application/json"})
        with self.open(req, timeout=30) as r:
            return json.load(r)

    def catalogue(self, reference: str) -> Dict:
        return self._get(self.CATALOGUE, {
            "supplierid": self.cfg["supplier_id"], "supplierid-type": "specific",
            "customerid": self.cfg["customer_id"], "customerid-type": "specific",
            "product-reference": reference, "product-identifier": "commercialReference",
            "etim-version": "ETIM-10.0"})

    def net_price(self, reference: str) -> Optional[Dict]:
        path = self.cfg.get("netprice_path")
        if not path:
            return None
        got = self._get(path, {"customerid": self.cfg["customer_id"], "productReference": reference})
        amount = _find_number(got, ("netPrice", "net_price", "price", "amount"))
        return {"reference": reference, "price": amount, "currency": "EUR", "raw": got} if amount else None


def _find_number(data, keys: Iterable[str]) -> Optional[str]:
    if isinstance(data, dict):
        for k, v in data.items():
            if k in keys and _price(v if not isinstance(v, dict) else v.get("value")):
                return _price(v if not isinstance(v, dict) else v.get("value"))
        for v in data.values():
            got = _find_number(v, keys)
            if got:
                return got
    if isinstance(data, list):
        for v in data:
            got = _find_number(v, keys)
            if got:
                return got
    return None


# The API connectors this edge knows: how to talk to a partner API. Which
# partner uses one is in the private register.
CONNECTORS = {"schneider": SchneiderClient}


def client(partner_id: str):
    p = partner(partner_id)
    conn = CONNECTORS.get((p or {}).get("api") or "")
    cfg = _get_credentials(partner_id) if conn else None
    if not cfg:
        raise NotConfigured(f"no API credentials for {partner_id}")
    return conn(cfg)


# ------------------------------------------------------- what is in use ----

def capability(partner_id: str) -> Dict:
    p = partner(partner_id)
    if p is None:
        raise ValueError(f"{partner_id} is not in the partner list")
    has_api = bool(p.get("api")) and bool(_get_credentials(p["id"]))
    items = _items(p["id"])
    use = "api" if has_api else ("file" if items else "none")
    return {"partner": p["id"], "name": p["name"], "kind": p.get("kind", ""), "use": use,
            "api": p.get("api", ""), "api_configured": has_api, "formats": p.get("formats", ["csv"]),
            "markets": p.get("markets", []),
            "note": p.get("note", ""),
            "file": ({"format": items["format"], "name": items.get("file", ""), "articles": len(items["items"]),
                      "imported": items["imported"]} if items else None)}


def capabilities() -> Dict:
    return {"store": store(), "connectors": sorted(CONNECTORS), "formats": list(FORMATS),
            "partners": [capability(p["id"]) for p in register()]}


def search(partner: str, query: str, limit: int = 20) -> List[Dict]:
    """Articles of an imported file whose reference, description, EAN or
    ETIM class contain every word of the query."""
    items = _items(partner)
    if not items:
        return []
    words = [w.lower() for w in (query or "").split() if w]
    hits = []
    for it in items["items"]:
        hay = " ".join(str(it.get(k, "")) for k in ("reference", "description", "ean", "etim")).lower()
        if all(w in hay for w in words):
            hits.append(it)
            if len(hits) >= limit:
                break
    return hits


def price(partner: str, reference: str) -> Optional[Dict]:
    """A reference's price from the channel in use: the API, else the file."""
    cap = capability(partner)
    if cap["use"] == "api":
        try:
            got = client(partner).net_price(reference)
            if got:
                return {**{k: got[k] for k in ("reference", "price", "currency")}, "source": "api"}
        except (OSError, ValueError, KeyError, NotConfigured):
            pass
    items = _items(partner)
    for it in (items or {}).get("items", []):
        if it["reference"].replace(" ", "").lower() == reference.replace(" ", "").lower() and it.get("price"):
            return {"reference": it["reference"], "price": it["price"], "currency": it.get("currency", "EUR"),
                    "description": it.get("description", ""), "source": f"file:{items['format']}"}
    return None


def price_bom(lines: List[Dict]) -> Dict:
    """The BOM with a unit price and line total wherever a line has a partner
    reference that a source can price; the rest say why not."""
    total, priced = Decimal(0), []
    for line in lines:
        out = dict(line)
        if line.get("partner") and line.get("reference"):
            got = price(line["partner"], line["reference"])
            if got:
                unit = Decimal(got["price"])
                out.update(unit_price=str(unit), total=str(unit * line["quantity"]), source=got["source"],
                           currency=got["currency"])
                total += unit * line["quantity"]
            else:
                out["missing"] = "no price for this reference"
        else:
            out["missing"] = "no partner reference yet"
        priced.append(out)
    return {"lines": priced, "total": str(total),
            "complete": all("missing" not in l for l in priced)}
