# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
catalogue.py — a partner's articles as Turtle, linked to the norms they may
be used under (ADR-0003).

One graph per partner, <data>/partners/<id>.catalogue.ttl:

    <https://digitalhome.cloud/catalogue/<partner>/<reference>>
        a dhp:Article ;
        dhp:partner "<partner>" ; dhp:reference "A9R…" ; rdfs:label "…" ;
        dhp:ean "…" ; dhp:etimClass "EC…" ;
        dhp:usableIn "EU" , "FR" ;            # markets it is sold and approved for
        dhp:approvedFor dhc:Norm_NFC15100 ;   # installation norms it is listed under
        dhp:conformsTo "EN 61008-1" .         # product standards it meets

An article is usable under a norm when it is approved for that norm, or its
markets include the norm's country (dhc:normCountry), or "EU" and the
country is in the EU. An article that says nothing is "unknown", not "no".

Prices are NOT here: they are commercial and stay in the private items file
(partners.py). The catalogue holds product facts, which a partner publishes.
"""

from __future__ import annotations

import os
import urllib.parse
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from rdflib import RDF, RDFS, Graph, Literal, Namespace, URIRef

from .edge import knowledge as kn
from .edge import settings

DHC = Namespace("https://digitalhome.cloud/ontology#")
DHP = Namespace("https://digitalhome.cloud/pro#")
# Articles are named as in the digitalhome.cloud marketplace (ADR-0006), so a
# partner's catalogue and its seller's graph there are the same statements.
BASE = "https://digitalhome.cloud/id/market/"
OLD_BASE = "https://digitalhome.cloud/catalogue/"           # before ADR-0006; rewritten on load
EU = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT",
      "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}


def _path(partner: str) -> Path:
    d = kn.data_dir() / "partners"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d / f"{partner}.catalogue.ttl"


def article_iri(partner: str, reference: str) -> URIRef:
    return URIRef(BASE + urllib.parse.quote(partner, safe="") + "/" + urllib.parse.quote(reference.strip(), safe=""))


def load(partner: str) -> Graph:
    g = Graph()
    p = _path(partner)
    if p.exists():
        g.parse(p, format="turtle")
        old = [t for t in g if str(t[0]).startswith(OLD_BASE)]
        if old:
            for s, pr, o in old:
                g.remove((s, pr, o))
                g.add((URIRef(BASE + str(s)[len(OLD_BASE):]), pr, o))
            _save(partner, g)
    return g


def _save(partner: str, g: Graph) -> None:
    g.bind("dhp", DHP)
    g.bind("dhc", DHC)
    p = _path(partner)
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(g.serialize(format="turtle").encode())
    os.replace(tmp, p)


def _norm(token: str) -> Optional[URIRef]:
    """'nfc15100', 'NF C 15-100' or 'Norm_NFC15100' → dhc:Norm_NFC15100."""
    t = "".join(ch for ch in token.upper() if ch.isalnum())
    if t.startswith("NORM"):
        t = t[4:]
    return DHC[f"Norm_{t}"] if t else None


def _split(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in str(value).replace("|", ",").replace(";", ",").split(",") if v.strip()]


def write_articles(partner: str, items: Iterable[Dict], markets: Iterable[str] = ()) -> int:
    """Put a file's articles into the partner's catalogue. An item's own
    norms/markets/standards win; otherwise the partner's default markets
    apply. Facts already stated about an article are kept."""
    g = load(partner)
    default = [m.upper() for m in markets]
    n = 0
    for it in items:
        ref = (it.get("reference") or "").strip()
        if not ref:
            continue
        a = article_iri(partner, ref)
        g.add((a, RDF.type, DHP.Article))
        g.set((a, DHP.partner, Literal(partner)))
        g.set((a, DHP.reference, Literal(ref)))
        if it.get("description"):
            g.set((a, RDFS.label, Literal(it["description"])))
        for key, prop in (("ean", DHP.ean), ("etim", DHP.etimClass)):
            if it.get(key):
                g.set((a, prop, Literal(it[key])))
        own = _split(it.get("markets") or it.get("region"))
        for m in own or ([] if (a, DHP.usableIn, None) in g else default):
            g.add((a, DHP.usableIn, Literal(m.upper())))
        for nm in _split(it.get("norms")):
            iri = _norm(nm)
            if iri is not None:
                g.add((a, DHP.approvedFor, iri))
        for st in _split(it.get("standards")):
            g.add((a, DHP.conformsTo, Literal(st)))
        n += 1
    _save(partner, g)
    return n


def set_article(partner: str, reference: str, usable_in: Optional[List[str]] = None,
                approved_for: Optional[List[str]] = None, conforms_to: Optional[List[str]] = None,
                label: str = "") -> Dict:
    """State (replace) where an article may be used. Lists that are None are
    left as they are; an empty list clears that fact."""
    g = load(partner)
    a = article_iri(partner, reference)
    g.add((a, RDF.type, DHP.Article))
    g.set((a, DHP.partner, Literal(partner)))
    g.set((a, DHP.reference, Literal(reference.strip())))
    if label:
        g.set((a, RDFS.label, Literal(label)))
    if usable_in is not None:
        g.remove((a, DHP.usableIn, None))
        for m in usable_in:
            g.add((a, DHP.usableIn, Literal(m.strip().upper())))
    if approved_for is not None:
        g.remove((a, DHP.approvedFor, None))
        for nm in approved_for:
            iri = _norm(nm)
            if iri is None:
                raise ValueError(f"not a norm: {nm}")
            g.add((a, DHP.approvedFor, iri))
    if conforms_to is not None:
        g.remove((a, DHP.conformsTo, None))
        for st in conforms_to:
            g.add((a, DHP.conformsTo, Literal(st.strip())))
    _save(partner, g)
    return article(partner, reference) or {}


def article(partner: str, reference: str) -> Optional[Dict]:
    g = load(partner)
    a = article_iri(partner, reference)
    if (a, RDF.type, DHP.Article) not in g:
        return None
    return {"partner": partner, "reference": str(g.value(a, DHP.reference)),
            "label": str(g.value(a, RDFS.label) or ""),
            "usable_in": sorted(str(x) for x in g.objects(a, DHP.usableIn)),
            "approved_for": sorted(str(x).rsplit("#", 1)[-1] for x in g.objects(a, DHP.approvedFor)),
            "conforms_to": sorted(str(x) for x in g.objects(a, DHP.conformsTo))}


def _norm_country(norm: URIRef) -> str:
    tbox = Graph()
    d = Path(settings.ONTOLOGY) / "tbox"
    for p in sorted(d.glob("*.ttl")) if d.is_dir() else []:
        tbox.parse(p, format="turtle")
    return str(tbox.value(norm, DHC.normCountry) or "")


_COUNTRY: Dict[str, str] = {}


def norm_country(norm: URIRef) -> str:
    key = str(norm)
    if key not in _COUNTRY:
        _COUNTRY[key] = _norm_country(norm)
    return _COUNTRY[key]


def usable(partner: str, reference: str, norm: Optional[URIRef], country: str = "") -> Dict:
    """Whether an article may be used under a norm (or in a country):
    {status: yes | no | unknown, why}."""
    art = article(partner, reference)
    if art is None:
        return {"status": "unknown", "why": "not in the partner's catalogue"}
    country = (country or (norm_country(norm) if norm is not None else "")).upper()
    norm_id = str(norm).rsplit("#", 1)[-1] if norm is not None else ""
    if norm_id and norm_id in art["approved_for"]:
        return {"status": "yes", "why": f"approved for {norm_id}"}
    markets = set(art["usable_in"])
    if country and country in markets:
        return {"status": "yes", "why": f"sold for {country}"}
    if country in EU and "EU" in markets:
        return {"status": "yes", "why": "sold for the EU"}
    if not markets and not art["approved_for"]:
        return {"status": "unknown", "why": "the catalogue says nothing about where it may be used"}
    where = ", ".join(sorted(markets) + art["approved_for"])
    return {"status": "no", "why": f"limited to {where}"}


def turtle(partner: str) -> str:
    g = load(partner)
    g.bind("dhp", DHP)
    g.bind("dhc", DHC)
    return g.serialize(format="turtle")
