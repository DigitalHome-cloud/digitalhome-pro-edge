# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
cloud_catalogue.py — the device catalogue of digitalhome.cloud on this edge,
both ways (ADR-0005).

The cloud keeps one admin-curated catalogue of device models (the Portal's
Catalog). This edge keeps a copy as the catalogue of a reserved partner,
`digitalhome-cloud`, beside the partners' own catalogues, so a design can name
`digitalhome-cloud` + a model number like any article, and the norms rules
(catalogue.usable) apply unchanged:

    sync()      POST /edge/v1/catalogue: models changed since the last sync
                (everything the first time, or when the connection changed),
                page by page, into <data>/partners/digitalhome-cloud.catalogue.ttl.
    publish()   POST /edge/v1/catalogue/put: one article of a partner's
                catalogue as a cloud model. The cloud allows it only while the
                person who linked this edge is a catalogue admin (dhc-admins
                with an authenticator app). Prices never go: they are not in
                the catalogue graphs at all (partners.py keeps them).

The copy is read-only here: it changes only by a sync or by a publish's answer.
"""

from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional

from rdflib import RDF, RDFS, Literal

from . import catalogue as cat
from .edge import cloud
from .edge import knowledge as kn

PARTNER = "digitalhome-cloud"
PAGES = 200                                   # a guard: 200 pages of 200 models
CATEGORIES = ["COMPUTING_IT", "CONTROLLERS_AUTOMATION", "FACILITIES_APPLIANCES",
              "MEDIA_COMMUNICATION", "SECURITY_MONITORING"]
POWER = ["FIXED", "SOCKET", "BATTERY", "ACCU"]
# facts of a model kept on the article, beside dhp:reference / rdfs:label / usableIn / conformsTo
FACTS = {"brand": "brand", "deviceType": "deviceType", "category": "category", "powerSource": "powerSource",
         "voltageV": "voltageV", "currentA": "currentA", "powerW": "powerW", "updatedAt": "cloudUpdated"}
FLAGS = ["hasActorCapability", "hasSensorCapability", "hasControllerCapability", "hasIOTCapability"]


def _state_path():
    d = kn.data_dir() / "partners"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d / f"{PARTNER}.sync.json"


def state() -> Dict:
    """{profile, since, synced_at, models} of the last sync; {} before the first."""
    try:
        return json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return {}


def _save_state(s: Dict) -> None:
    p = _state_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1))
    os.chmod(tmp, 0o600)
    tmp.replace(p)


def _region(model: Dict) -> List[str]:
    r = str(model.get("region") or "").strip().upper()
    return [x for x in (t.strip() for t in r.replace(";", ",").split(",")) if x]


def _put(g, model: Dict) -> None:
    ref = str(model.get("modelNumber") or "").strip()
    if not ref:
        return
    a = cat.article_iri(PARTNER, ref)
    g.remove((a, None, None))                  # the cloud's answer is the whole truth for a model
    g.add((a, RDF.type, cat.DHP.Article))
    g.add((a, cat.DHP.partner, Literal(PARTNER)))
    g.add((a, cat.DHP.reference, Literal(ref)))
    label = model.get("description") or " ".join(str(model.get(k) or "") for k in ("brand", "deviceType")).strip()
    if label:
        g.add((a, RDFS.label, Literal(label)))
    for key, prop in FACTS.items():
        if model.get(key) not in (None, ""):
            g.add((a, cat.DHP[prop], Literal(model[key])))
    for flag in FLAGS:
        if model.get(flag):
            g.add((a, cat.DHP.capability, Literal(flag[3:-10].lower())))   # actor, sensor, controller, iot
    for m in _region(model):
        g.add((a, cat.DHP.usableIn, Literal(m)))
    for st in model.get("standards") or []:
        g.add((a, cat.DHP.conformsTo, Literal(str(st))))
    for c in model.get("compatibleClasses") or []:
        g.add((a, cat.DHP.compatibleClass, Literal(str(c))))


def sync(full: bool = False) -> Dict:
    """Pull the models changed since the last sync of this connection (all of
    them when `full`, the first time, or after the connection changed)."""
    profile = cloud.active_profile()
    last = state()
    full = full or not last.get("since") or last.get("profile") != profile
    g = cat.Graph() if full else cat.load(PARTNER)
    body: Dict = {} if full else {"since": last["since"]}
    seen, now = 0, None
    for _ in range(PAGES):
        try:
            got = cloud.call("catalogue", body, profile)
        except cloud.CloudError as e:
            if e.status == 404:
                raise ValueError("the connected cloud has no catalogue for edges yet (/edge/v1/catalogue)") from e
            raise
        now = now or got.get("now")
        for m in got.get("models") or []:
            _put(g, m)
            seen += 1
        if not got.get("cursor"):
            break
        body = dict(body, cursor=got["cursor"])
    else:
        raise cloud.CloudError("the cloud catalogue did not end after 200 pages; try a full sync later")
    cat._save(PARTNER, g)
    total = len(set(g.subjects(RDF.type, cat.DHP.Article)))
    _save_state({"profile": profile, "since": now, "synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "models": total, "full": full})
    return {"profile": profile, "full": full, "changed": seen, "models": total}


def models(query: str = "", limit: int = 50) -> List[Dict]:
    """The synced models, filtered by text (model number, label, brand, type)."""
    g = cat.load(PARTNER)
    q = (query or "").strip().lower()
    out = []
    for a in g.subjects(RDF.type, cat.DHP.Article):
        row = {"reference": str(g.value(a, cat.DHP.reference) or ""), "label": str(g.value(a, RDFS.label) or ""),
               "brand": str(g.value(a, cat.DHP.brand) or ""), "deviceType": str(g.value(a, cat.DHP.deviceType) or ""),
               "category": str(g.value(a, cat.DHP.category) or ""),
               "usable_in": sorted(str(x) for x in g.objects(a, cat.DHP.usableIn)),
               "conforms_to": sorted(str(x) for x in g.objects(a, cat.DHP.conformsTo))}
        if q and q not in " ".join([row["reference"], row["label"], row["brand"], row["deviceType"]]).lower():
            continue
        out.append(row)
    out.sort(key=lambda r: (r["brand"].lower(), r["reference"].lower()))
    return out[: max(1, min(int(limit), 500))]


def model_for(partner: str, reference: str, brand: str = "", device_type: str = "", category: str = "",
              description: str = "", power_source: str = "") -> Dict:
    """What publish() would send for a partner's article: its facts, plus what
    the catalogue needs and an article does not say (brand, device type)."""
    if partner == PARTNER:
        raise ValueError("that article came from digitalhome.cloud already")
    art = cat.article(partner, reference)
    if art is None:
        raise ValueError(f"{partner} has no article {reference} in its catalogue")
    model: Dict = {"modelNumber": art["reference"], "brand": (brand or "").strip(),
                   "deviceType": (device_type or "").strip()}
    if not model["brand"] or not model["deviceType"]:
        raise ValueError("a cloud model needs a brand and a device type (e.g. “Hager”, “RCD”)")
    text = (description or art.get("label") or "").strip()
    if text:
        model["description"] = text[:1000]
    markets = art.get("usable_in") or []
    if markets:
        model["region"] = "EU" if "EU" in markets else ",".join(markets)[:20]
    if art.get("conforms_to"):
        model["standards"] = art["conforms_to"][:20]
    if category:
        if category not in CATEGORIES:
            raise ValueError(f"category: one of {', '.join(CATEGORIES)}")
        model["category"] = category
    if power_source:
        if power_source not in POWER:
            raise ValueError(f"power source: one of {', '.join(POWER)}")
        model["powerSource"] = power_source
    return model


def publish(partner: str, reference: str, **facts) -> Dict:
    """Send one article to the cloud catalogue; the answer goes into the copy here."""
    model = model_for(partner, reference, **facts)
    try:
        got = cloud.call("catalogue/put", {"model": model})
    except cloud.CloudError as e:
        if e.status == 403:
            raise PermissionError("digitalhome.cloud accepts catalogue entries only from an edge linked by a "
                                  "catalogue admin (dhc-admins, with an authenticator app)") from e
        if e.status == 400:
            raise ValueError(f"digitalhome.cloud refused it: {e.payload.get('description') or e.code}") from e
        if e.status == 404:
            raise ValueError("the connected cloud has no catalogue for edges yet (/edge/v1/catalogue)") from e
        raise
    g = cat.load(PARTNER)
    _put(g, got.get("model") or {})
    cat._save(PARTNER, g)
    return {"model": got.get("model") or {}, "created": bool(got.get("created"))}
