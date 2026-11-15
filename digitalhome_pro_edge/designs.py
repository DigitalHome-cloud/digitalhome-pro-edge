# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
designs.py — a home's workspaces and the design each one holds (ADR-0001).

A *home* (the tenant, a SmartHome ID once linked) has one or more
*workspaces*: active projects such as "new switchboard" or "kitchen
extension". Each workspace is one A-Box, kept by edge.knowledge (one Turtle
file, written only through change(), so the structural shapes in
edge/ontology/shapes refuse a broken file). Whether a design meets a norm is
answered by report(): the norm shapes in edge/ontology/cbox plus a few rules
the shapes cannot express (how many RCDs, how full the board is). A design
that breaks a norm is saved and reported, never refused.

Instance IRIs follow the Designer's scheme so the cloud can read them:
https://digitalhome.cloud/instance/{home}/{type}/{id}. Ids are minted, never
derived from a label.
"""

from __future__ import annotations

import re
import secrets
import string
from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from rdflib import RDF, RDFS, Graph, Literal, Namespace, URIRef
from rdflib.namespace import XSD

from .edge import knowledge as kn
from .edge import settings

DHC = Namespace("https://digitalhome.cloud/ontology#")
DHP = Namespace("https://digitalhome.cloud/pro#")
REC = Namespace("https://w3id.org/rec#")
SH = Namespace("http://www.w3.org/ns/shacl#")
INSTANCE = "https://digitalhome.cloud/instance/"

# what a person or Claude says → the T-Box's circuit type
CIRCUIT_TYPES = {
    "lighting": "CircuitType_Lighting",
    "socket": "CircuitType_Socket",
    "cooking": "CircuitType_Cooking",
    "water_heater": "CircuitType_WaterHeater",
    "heating": "CircuitType_Heating",
    "floor_heating": "CircuitType_FloorHeating",
    "ev_charger": "CircuitType_IRVE",
    "dedicated": "CircuitType_DedicatedAppliance",
}
# appliances on a dedicated circuit that need an RCD of type A (or F, B)
TYPE_A_APPLIANCES = {"washing_machine", "dishwasher", "dryer", "hob", "oven", "heat_pump", "ev_charger"}
TYPE_A_CIRCUITS = {"cooking", "ev_charger"}

# devices that sit on a board, with the modules (18 mm) they usually take
DEVICES = {
    "breaker": (DHC.ProtectionDevice, 1),
    "contactor": (DHC.Contactor, 1),
    "surge_protector": (DHC.SurgeProtector, 2),
}
RCD_MODULES = 2
POINT_KINDS = {"socket", "light", "switch", "appliance", "outlet"}
STATUSES = ("active", "quoted", "done", "archived")
RESERVE = Decimal("0.20")       # NF C 15-100: about 20 % free space on a board


class NotFound(LookupError):
    pass


def _mint(prefix: str) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return prefix + "-" + "".join(secrets.choice(alphabet) for _ in range(8))


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    s = s if s and s[0].isalpha() else f"w-{s}".rstrip("-")
    return s[:30].rstrip("-") or "w"


def _iri(home: str, kind: str, ident: str) -> URIRef:
    return URIRef(f"{INSTANCE}{home}/{kind}/{ident}")


def _local(iri: URIRef) -> str:
    return str(iri).rsplit("/", 1)[-1]


def _dec(x: Any) -> Literal:
    return Literal(Decimal(str(x)), datatype=XSD.decimal)


def _int(x: Any) -> Literal:
    return Literal(int(x), datatype=XSD.integer)


class Designs:
    """The workspaces of this edge and the design in each."""

    def __init__(self, kb: Optional[kn.KnowledgeBase] = None):
        self.kb = kb or kn.KnowledgeBase()

    # ------------------------------------------------------------ workspaces

    def _workspace_node(self, g: Graph) -> Optional[URIRef]:
        return next(iter(g.subjects(RDF.type, DHP.Workspace)), None)

    def _home(self, g: Graph) -> str:
        ws = self._workspace_node(g)
        if ws is None:
            raise NotFound("no such workspace")
        return str(g.value(ws, DHP.home))

    def workspaces(self) -> List[Dict]:
        out = []
        for name in self.kb.graphs():
            g = self.kb.load(name)
            ws = self._workspace_node(g)
            if ws is None:
                continue
            out.append({
                "workspace": name,
                "title": str(g.value(ws, RDFS.label)),
                "home": str(g.value(ws, DHP.home)),
                "status": str(g.value(ws, DHP.status)),
                "country": str(g.value(ws, DHP.country) or ""),
                "boards": len(set(g.subjects(RDF.type, DHC.DistributionBoard))),
                "circuits": len(set(g.subjects(RDF.type, DHC.Circuit))),
            })
        return sorted(out, key=lambda w: (w["home"], w["title"].lower()))

    def homes(self) -> List[Dict]:
        by_home: Dict[str, List[Dict]] = defaultdict(list)
        for w in self.workspaces():
            by_home[w["home"]].append(w)
        return [{"home": h, "workspaces": ws} for h, ws in sorted(by_home.items())]

    def new_workspace(self, title: str, home: str, country: str = "FR") -> Dict:
        title = (title or "").strip()
        home = (home or "").strip()
        if not title or not home:
            raise ValueError("a workspace needs a title and a home")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", home):
            raise ValueError("a home is its SmartHome ID or a short local name: letters, digits, - and _")
        existing = set(self.kb.graphs())
        name = _slug(title)
        while name in existing:
            name = f"{_slug(title)[:24]}-{secrets.token_hex(2)}"
        node = _iri(home, "workspace", name)

        def apply(g: Graph) -> None:
            g.add((node, RDF.type, DHP.Workspace))
            g.add((node, RDFS.label, Literal(title)))
            g.add((node, DHP.home, Literal(home)))
            g.add((node, DHP.status, Literal("active")))
            g.add((node, DHP.country, Literal(country.upper())))
            if country.upper() == "FR":
                g.add((node, DHC.governedBy, DHC.Norm_NFC15100))
        self.kb.change(name, apply)
        return {"workspace": name, "title": title, "home": home}

    def set_workspace(self, ws: str, title: Optional[str] = None, status: Optional[str] = None) -> Dict:
        if status is not None and status not in STATUSES:
            raise ValueError(f"status is one of {', '.join(STATUSES)}")

        def apply(g: Graph) -> None:
            node = self._workspace_node(g)
            if node is None:
                raise NotFound("no such workspace")
            if title:
                g.set((node, RDFS.label, Literal(title.strip())))
            if status:
                g.set((node, DHP.status, Literal(status)))
        self._change(ws, apply)
        return {"workspace": ws}

    # ---------------------------------------------------------------- design

    def _change(self, ws: str, apply) -> Any:
        if ws not in self.kb.graphs() or self._workspace_node(self.kb.load(ws)) is None:
            raise NotFound(f"no workspace {ws}")
        return self.kb.change(ws, apply)

    def _find(self, g: Graph, ident: str, *classes: URIRef) -> URIRef:
        for s in set(g.subjects(RDF.type, None)):
            if _local(s) == ident and (not classes or any((s, RDF.type, c) in g for c in classes)):
                return s
        raise NotFound(f"no {ident} in this workspace")

    def add_board(self, ws: str, label: str, rows: int = 1, modules_per_row: int = 13) -> Dict:
        ident = _mint("board")

        def apply(g: Graph) -> None:
            n = _iri(self._home(g), "board", ident)
            g.add((n, RDF.type, DHC.DistributionBoard))
            g.add((n, RDFS.label, Literal(label)))
            g.add((n, DHP.rows, _int(rows)))
            g.add((n, DHP.modulesPerRow, _int(modules_per_row)))
        self._change(ws, apply)
        return {"id": ident}

    def set_board(self, ws: str, board: str, rows: Optional[int] = None,
                  modules_per_row: Optional[int] = None) -> Dict:
        def apply(g: Graph) -> None:
            n = self._find(g, board, DHC.DistributionBoard)
            if rows is not None:
                g.set((n, DHP.rows, _int(rows)))
            if modules_per_row is not None:
                g.set((n, DHP.modulesPerRow, _int(modules_per_row)))
        self._change(ws, apply)
        return {"id": board}

    def add_rcd(self, ws: str, board: str, label: str, rated_current: float = 40,
                sensitivity_ma: float = 30, rcd_type: str = "A") -> Dict:
        ident = _mint("rcd")

        def apply(g: Graph) -> None:
            b = self._find(g, board, DHC.DistributionBoard)
            n = _iri(self._home(g), "rcd", ident)
            g.add((n, RDF.type, DHC.RCD))
            g.add((n, RDFS.label, Literal(label)))
            g.add((n, DHC.ratedCurrent, _dec(rated_current)))
            g.add((n, DHC.sensitivityMA, _dec(sensitivity_ma)))
            g.add((n, DHC.rcdType, Literal(rcd_type.upper())))
            g.add((n, DHP.onBoard, b))
            g.add((n, DHP.modules, _int(RCD_MODULES)))
        self._change(ws, apply)
        return {"id": ident}

    def add_device(self, ws: str, board: str, kind: str, label: str,
                   rated_current: Optional[float] = None, modules: Optional[int] = None) -> Dict:
        """A board device that is not a circuit's own breaker: a contactor, a
        surge protector, the breaker of a control circuit."""
        if kind not in DEVICES:
            raise ValueError(f"kind is one of {', '.join(DEVICES)}")
        cls, default_modules = DEVICES[kind]
        ident = _mint(kind.split("_")[0])

        def apply(g: Graph) -> None:
            b = self._find(g, board, DHC.DistributionBoard)
            n = _iri(self._home(g), kind, ident)
            g.add((n, RDF.type, cls))
            g.add((n, RDFS.label, Literal(label)))
            g.add((n, DHP.onBoard, b))
            g.add((n, DHP.modules, _int(modules or default_modules)))
            if rated_current is not None:
                g.add((n, DHC.ratedCurrent, _dec(rated_current)))
        self._change(ws, apply)
        return {"id": ident}

    def add_circuit(self, ws: str, rcd: str, label: str, circuit_type: str, rated_current: float,
                    cross_section: float, points: int = 0, appliance: str = "",
                    dedicated: Optional[bool] = None) -> Dict:
        """A circuit and its own breaker (1 module), below an RCD."""
        if circuit_type not in CIRCUIT_TYPES:
            raise ValueError(f"circuit_type is one of {', '.join(CIRCUIT_TYPES)}")
        ident = _mint("circuit")

        def apply(g: Graph) -> None:
            r = self._find(g, rcd, DHC.RCD)
            home = self._home(g)
            board = g.value(r, DHP.onBoard)
            c = _iri(home, "circuit", ident)
            brk = _iri(home, "breaker", ident.replace("circuit", "brk"))
            g.add((brk, RDF.type, DHC.ProtectionDevice))
            g.add((brk, RDFS.label, Literal(f"{label} — {rated_current:g} A")))
            g.add((brk, DHC.ratedCurrent, _dec(rated_current)))
            g.add((brk, DHP.onBoard, board))
            g.add((brk, DHP.modules, _int(1)))
            g.add((c, RDF.type, DHC.Circuit))
            g.add((c, RDFS.label, Literal(label)))
            g.add((c, DHC.hasCircuitType, DHC[CIRCUIT_TYPES[circuit_type]]))
            g.add((c, DHC.governedBy, DHC.Norm_NFC15100))
            g.add((c, DHC.ratedCurrent, _dec(rated_current)))
            g.add((c, DHC.crossSection, _dec(cross_section)))
            g.add((c, DHC.phase, _int(1)))
            g.add((c, DHC.dedicated, Literal(bool(dedicated) if dedicated is not None
                                             else circuit_type not in ("lighting", "socket"))))
            if points:
                g.add((c, DHC.maxPoints, _int(points)))
            if appliance:
                g.add((c, DHP.appliance, Literal(appliance)))
            g.add((c, DHC.hasProtection, brk))
            g.add((c, DHC.hasProtection, r))
        self._change(ws, apply)
        return {"id": ident}

    def move_circuit(self, ws: str, circuit: str, rcd: str) -> Dict:
        def apply(g: Graph) -> None:
            c = self._find(g, circuit, DHC.Circuit)
            r = self._find(g, rcd, DHC.RCD)
            for old in [p for p in g.objects(c, DHC.hasProtection) if (p, RDF.type, DHC.RCD) in g]:
                g.remove((c, DHC.hasProtection, old))
            g.add((c, DHC.hasProtection, r))
            for brk in self._breakers(g, c):
                g.set((brk, DHP.onBoard, g.value(r, DHP.onBoard)))
        self._change(ws, apply)
        return {"id": circuit}

    def add_room(self, ws: str, label: str, level: str = "") -> Dict:
        ident = _mint("room")

        def apply(g: Graph) -> None:
            n = _iri(self._home(g), "room", ident)
            g.add((n, RDF.type, REC.Room))
            g.add((n, RDFS.label, Literal(label)))
            if level:
                g.add((n, DHP.level, Literal(level)))
        self._change(ws, apply)
        return {"id": ident}

    def add_point(self, ws: str, circuit: str, kind: str, label: str, room: str = "") -> Dict:
        """A socket, light, switch or appliance outlet on a circuit, in a room.
        The circuit's number of points follows the points it has."""
        if kind not in POINT_KINDS:
            raise ValueError(f"kind is one of {', '.join(sorted(POINT_KINDS))}")
        ident = _mint("point")

        def apply(g: Graph) -> None:
            c = self._find(g, circuit, DHC.Circuit)
            n = _iri(self._home(g), "point", ident)
            g.add((n, RDF.type, DHP.Point))
            g.add((n, RDFS.label, Literal(label)))
            g.add((n, DHP.kind, Literal(kind)))
            g.add((n, DHP.onCircuit, c))
            if room:
                g.add((n, REC.locatedIn, self._find(g, room, REC.Room)))
            self._count_points(g, c)
        self._change(ws, apply)
        return {"id": ident}

    def place(self, ws: str, item: str, room: str) -> Dict:
        def apply(g: Graph) -> None:
            n = self._find(g, item)
            g.set((n, REC.locatedIn, self._find(g, room, REC.Room)))
        self._change(ws, apply)
        return {"id": item}

    def rename(self, ws: str, item: str, label: str) -> Dict:
        if not (label or "").strip():
            raise ValueError("a label cannot be empty")

        def apply(g: Graph) -> None:
            g.set((self._find(g, item), RDFS.label, Literal(label.strip())))
        self._change(ws, apply)
        return {"id": item}

    def set_reference(self, ws: str, item: str, partner: str, reference: str) -> Dict:
        """The manufacturer's or distributor's article for an item, e.g.
        partner "schneider", reference "A9…". The BOM prices it (partners.py)."""
        def apply(g: Graph) -> None:
            n = self._find(g, item)
            g.set((n, DHP.partner, Literal(partner.strip().lower())))
            g.set((n, DHP.reference, Literal(reference.strip())))
        self._change(ws, apply)
        return {"id": item}

    def remove(self, ws: str, item: str) -> Dict:
        """An item, and what cannot exist without it: a circuit takes its
        breaker and points; an RCD or board refuses while circuits hang on it."""
        removed: List[str] = []

        def drop(g: Graph, n: URIRef) -> None:
            g.remove((n, None, None))
            g.remove((None, None, n))
            removed.append(_local(n))

        def apply(g: Graph) -> None:
            n = self._find(g, item)
            if (n, RDF.type, DHP.Workspace) in g:
                raise ValueError("a workspace is archived, not removed")
            if (n, RDF.type, DHC.RCD) in g and any(g.subjects(DHC.hasProtection, n)):
                raise ValueError("move or remove the circuits on this RCD first")
            if (n, RDF.type, DHC.DistributionBoard) in g and any(g.subjects(DHP.onBoard, n)):
                raise ValueError("remove the devices on this board first")
            if (n, RDF.type, DHC.Circuit) in g:
                for brk in self._breakers(g, n):
                    drop(g, brk)
                for p in list(g.subjects(DHP.onCircuit, n)):
                    drop(g, p)
            circuits = list(g.objects(n, DHP.onCircuit))    # a point's circuit recounts
            drop(g, n)
            for c in circuits:
                self._count_points(g, c)
        self._change(ws, apply)
        return {"removed": removed}

    # ------------------------------------------------------------ reading

    def _breakers(self, g: Graph, circuit: URIRef) -> List[URIRef]:
        return [p for p in g.objects(circuit, DHC.hasProtection) if (p, RDF.type, DHC.ProtectionDevice) in g]

    def _rcd(self, g: Graph, circuit: URIRef) -> Optional[URIRef]:
        return next((p for p in g.objects(circuit, DHC.hasProtection) if (p, RDF.type, DHC.RCD) in g), None)

    def _count_points(self, g: Graph, circuit: URIRef) -> None:
        n = len(set(g.subjects(DHP.onCircuit, circuit)))
        if n:
            g.set((circuit, DHC.maxPoints, _int(n)))

    def _type_key(self, g: Graph, circuit: URIRef) -> str:
        t = g.value(circuit, DHC.hasCircuitType)
        back = {v: k for k, v in CIRCUIT_TYPES.items()}
        return back.get(_local(t).split("#")[-1] if t else "", "") or str(t).rsplit("#", 1)[-1]

    def _num(self, g: Graph, n: URIRef, p: URIRef) -> Optional[float]:
        v = g.value(n, p)
        return float(v) if v is not None else None

    def design(self, ws: str) -> Dict:
        """The whole design as plain data: boards → RCDs → circuits → points,
        the devices on each board, the rooms and what is placed in them."""
        g = self.kb.load(ws)
        node = self._workspace_node(g)
        if node is None:
            raise NotFound(f"no workspace {ws}")

        def item(n: URIRef) -> Dict:
            d = {"id": _local(n), "label": str(g.value(n, RDFS.label) or "")}
            ref = g.value(n, DHP.reference)
            if ref is not None:
                d["partner"], d["reference"] = str(g.value(n, DHP.partner) or ""), str(ref)
            room = g.value(n, REC.locatedIn)
            if room is not None:
                d["room"] = _local(room)
            return d

        boards = []
        for b in sorted(set(g.subjects(RDF.type, DHC.DistributionBoard)), key=str):
            on = set(g.subjects(DHP.onBoard, b))
            rcds = []
            for r in sorted((x for x in on if (x, RDF.type, DHC.RCD) in g), key=str):
                circuits = []
                for c in sorted(set(g.subjects(DHC.hasProtection, r)), key=lambda c: str(g.value(c, RDFS.label))):
                    circuits.append({**item(c),
                                     "type": self._type_key(g, c),
                                     "rated_current": self._num(g, c, DHC.ratedCurrent),
                                     "cross_section": self._num(g, c, DHC.crossSection),
                                     "points": int(g.value(c, DHC.maxPoints) or 0),
                                     "appliance": str(g.value(c, DHP.appliance) or ""),
                                     "breakers": [item(x) for x in self._breakers(g, c)],
                                     "point_list": [{**item(p), "kind": str(g.value(p, DHP.kind))}
                                                    for p in sorted(g.subjects(DHP.onCircuit, c), key=str)]})
                rcds.append({**item(r), "rated_current": self._num(g, r, DHC.ratedCurrent),
                             "sensitivity_ma": self._num(g, r, DHC.sensitivityMA),
                             "rcd_type": str(g.value(r, DHC.rcdType)), "circuits": circuits})
            devices = []
            for d in sorted(on, key=str):
                if (d, RDF.type, DHC.RCD) in g:
                    continue
                kind = next((k for k, (cls, _) in DEVICES.items() if (d, RDF.type, cls) in g), "device")
                own = any((c, DHC.hasProtection, d) in g for c in g.subjects(RDF.type, DHC.Circuit))
                if not own:
                    devices.append({**item(d), "kind": kind, "rated_current": self._num(g, d, DHC.ratedCurrent),
                                    "modules": int(g.value(d, DHP.modules) or 1)})
            boards.append({**item(b), "rows": int(g.value(b, DHP.rows)),
                           "modules_per_row": int(g.value(b, DHP.modulesPerRow)),
                           "modules_used": sum(int(g.value(x, DHP.modules) or 0) for x in on),
                           "rcds": rcds, "devices": devices})
        rooms = [{**item(r), "level": str(g.value(r, DHP.level) or ""),
                  "items": sorted(_local(x) for x in g.subjects(REC.locatedIn, r))}
                 for r in sorted(set(g.subjects(RDF.type, REC.Room)), key=lambda r: str(g.value(r, RDFS.label)))]
        return {"workspace": ws, "title": str(g.value(node, RDFS.label)), "home": str(g.value(node, DHP.home)),
                "status": str(g.value(node, DHP.status)), "country": str(g.value(node, DHP.country) or ""),
                "boards": boards, "rooms": rooms}

    def export(self, ws: str) -> str:
        g = self.kb.load(ws)
        if self._workspace_node(g) is None:
            raise NotFound(f"no workspace {ws}")
        g.bind("dhc", DHC)
        g.bind("dhp", DHP)
        g.bind("rec", REC)
        return g.serialize(format="turtle")

    # ------------------------------------------------------------- report

    def report(self, ws: str, lang: str = "en") -> Dict:
        """What in this design breaks a rule, in sentences: the norm shapes
        (advisory) and the board rules the shapes cannot express."""
        g = self.kb.load(ws)
        if self._workspace_node(g) is None:
            raise NotFound(f"no workspace {ws}")
        findings = self._norm_findings(g, lang) + self._board_findings(g, lang)
        return {"workspace": ws, "conforms": not any(f["severity"] == "violation" for f in findings),
                "findings": findings}

    def _norm_findings(self, g: Graph, lang: str) -> List[Dict]:
        shapes, tbox = _norm_graphs()
        if not len(shapes):
            return []
        from pyshacl import validate as shacl
        data = Graph()
        for t in g:
            data.add(t)
        for t in tbox:                       # the norms and circuit types the shapes name
            data.add(t)
        _, report, _ = shacl(data, shacl_graph=shapes, inference="none")
        out, seen = [], set()
        for r in report.subjects(RDF.type, SH.ValidationResult):
            focus = report.value(r, SH.focusNode)
            if (focus, None, None) not in g:
                continue                     # about the T-Box, not this design
            source = report.value(r, SH.sourceShape)
            msgs = _in_lang({m for m in report.objects(r, SH.resultMessage)})
            texts = [msgs.get(lang) or msgs.get("en")] if (msgs.get(lang) or msgs.get("en")) and \
                report.value(r, SH.sourceConstraintComponent) != SH.OrConstraintComponent else []
            if not texts:
                # an sh:or names no reason: find the branch conditions this node breaks
                texts = _or_reasons(shapes, source, g, focus, lang) or [self._shape_label(shapes, source, lang)]
            for text in texts:
                if (str(focus), text) in seen:
                    continue
                seen.add((str(focus), text))
                rule = str(source).rsplit("#", 1)[-1] if isinstance(source, URIRef) else "norm"
                out.append({"severity": "violation", "rule": rule, "item": _local(focus),
                            "label": str(g.value(focus, RDFS.label) or ""), "message": text})
        return out

    def _shape_label(self, shapes: Graph, shape: Any, lang: str) -> str:
        labels = {l.language or "": str(l) for l in shapes.objects(shape, RDFS.label)} if shape is not None else {}
        name = labels.get(lang) or labels.get("en") or "a norm rule"
        return {"fr": f"Ne respecte pas : {name}", "de": f"Verletzt: {name}"}.get(lang, f"Breaks: {name}")

    def _board_findings(self, g: Graph, lang: str) -> List[Dict]:
        t = _texts(lang)
        out: List[Dict] = []
        country = str(g.value(self._workspace_node(g), DHP.country) or "")
        circuits = set(g.subjects(RDF.type, DHC.Circuit))
        rcds = set(g.subjects(RDF.type, DHC.RCD))

        def add(sev: str, rule: str, node: Optional[URIRef], key: str, **kw) -> None:
            out.append({"severity": sev, "rule": rule, "item": _local(node) if node is not None else "",
                        "label": str(g.value(node, RDFS.label) or "") if node is not None else "",
                        "message": t[key].format(**kw)})

        if country == "FR" and circuits:
            thirty = [r for r in rcds if (self._num(g, r, DHC.sensitivityMA) or 999) <= 30]
            if len(thirty) < 2:
                add("violation", "rcd-count", None, "rcd_count", n=len(thirty))
        for r in rcds:
            n = len(set(g.subjects(DHC.hasProtection, r)))
            if n > 8:
                add("violation", "rcd-circuits", r, "rcd_circuits", n=n)
        for c in circuits:
            r = self._rcd(g, c)
            if r is None:
                add("violation", "circuit-rcd", c, "circuit_rcd")
                continue
            needs_a = (self._type_key(g, c) in TYPE_A_CIRCUITS
                       or str(g.value(c, DHP.appliance) or "") in TYPE_A_APPLIANCES)
            if needs_a and str(g.value(r, DHC.rcdType)) == "AC":
                add("violation", "rcd-type-a", c, "rcd_type_a", rcd=str(g.value(r, RDFS.label)))
        for b in set(g.subjects(RDF.type, DHC.DistributionBoard)):
            cap = int(g.value(b, DHP.rows)) * int(g.value(b, DHP.modulesPerRow))
            used = sum(int(g.value(x, DHP.modules) or 0) for x in g.subjects(DHP.onBoard, b))
            if used > cap:
                add("violation", "board-full", b, "board_over", used=used, cap=cap)
            elif cap and Decimal(cap - used) / cap < RESERVE:
                add("warning", "board-reserve", b, "board_reserve", used=used, cap=cap,
                    free=cap - used, need=int((RESERVE * cap).to_integral_value(rounding="ROUND_CEILING")))
        return out

    # ---------------------------------------------------------------- BOM

    def bom(self, ws: str) -> List[Dict]:
        """What to buy, counted: one line per kind of device and rating, with
        the modules it takes and the partner reference when one is set."""
        g = self.kb.load(ws)
        if self._workspace_node(g) is None:
            raise NotFound(f"no workspace {ws}")
        lines: Counter = Counter()
        modules: Dict[tuple, int] = {}
        for b in set(g.subjects(RDF.type, DHC.DistributionBoard)):
            r, m = int(g.value(b, DHP.rows)), int(g.value(b, DHP.modulesPerRow))
            key = ("board", f"{r} × {m} modules", "", str(g.value(b, DHP.partner) or ""), str(g.value(b, DHP.reference) or ""))
            lines[key] += 1
            modules[key] = 0
            for x in g.subjects(DHP.onBoard, b):
                if (x, RDF.type, DHC.RCD) in g:
                    desc = f"RCD {self._num(g, x, DHC.ratedCurrent):g} A {self._num(g, x, DHC.sensitivityMA):g} mA type {g.value(x, DHC.rcdType)}"
                    kind = "rcd"
                else:
                    kind = next((k for k, (cls, _) in DEVICES.items() if (x, RDF.type, cls) in g), "device")
                    rc = self._num(g, x, DHC.ratedCurrent)
                    desc = f"{kind.replace('_', ' ')}" + (f" {rc:g} A" if rc is not None else "")
                key = (kind, desc, "", str(g.value(x, DHP.partner) or ""), str(g.value(x, DHP.reference) or ""))
                lines[key] += 1
                modules[key] = int(g.value(x, DHP.modules) or 0)
        for p in g.subjects(RDF.type, DHP.Point):
            key = ("point", str(g.value(p, DHP.kind)), "", str(g.value(p, DHP.partner) or ""), str(g.value(p, DHP.reference) or ""))
            lines[key] += 1
            modules[key] = 0
        order = {"board": 0, "rcd": 1, "breaker": 2, "contactor": 3, "surge_protector": 4, "device": 5, "point": 6}
        return [{"kind": k[0], "description": k[1], "quantity": q, "modules_each": modules[k],
                 "partner": k[3], "reference": k[4]}
                for k, q in sorted(lines.items(), key=lambda kv: (order.get(kv[0][0], 9), kv[0][1]))]


_NORMS: Dict[str, Graph] = {}


def _norm_graphs():
    """The advisory norm shapes (cbox/) and the T-Box they refer to (tbox/)."""
    if "shapes" not in _NORMS:
        shapes, tbox = Graph(), Graph()
        for folder, graph in (("cbox", shapes), ("tbox", tbox)):
            d = settings.ONTOLOGY / folder
            for p in sorted(d.glob("*.ttl")) if d.is_dir() else []:
                graph.parse(p, format="turtle")
        _NORMS["shapes"], _NORMS["tbox"] = shapes, tbox
    return _NORMS["shapes"], _NORMS["tbox"]


def _in_lang(literals) -> Dict[str, str]:
    return {(getattr(m, "language", None) or ""): str(m) for m in literals}


def _or_reasons(shapes: Graph, shape: Any, g: Graph, focus: URIRef, lang: str) -> List[str]:
    """The messages of the property conditions inside a shape's sh:or that
    this node breaks. The norm shapes guard each rule with an sh:or whose
    first branches say "not this kind of circuit"; the last branch holds the
    conditions with their messages."""
    from rdflib.collection import Collection
    reasons: List[str] = []
    for lst in shapes.objects(shape, SH["or"]):
        for branch in Collection(shapes, lst):
            for prop in shapes.objects(branch, SH.property):
                path = shapes.value(prop, SH.path)
                msgs = _in_lang(shapes.objects(prop, SH.message))
                if not msgs or path is None:
                    continue
                values = list(g.objects(focus, path))
                if _breaks(shapes, prop, values):
                    reasons.append(msgs.get(lang) or msgs.get("en") or next(iter(msgs.values())))
    return reasons


def _breaks(shapes: Graph, prop: Any, values: list) -> bool:
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    for v in values:
        x = num(v)
        lo, hi = shapes.value(prop, SH.minInclusive), shapes.value(prop, SH.maxInclusive)
        if x is not None and lo is not None and x < float(lo):
            return True
        if x is not None and hi is not None and x > float(hi):
            return True
    has = shapes.value(prop, SH.hasValue)
    if has is not None and has not in values:
        return True
    lo_count = shapes.value(prop, SH.minCount)
    return lo_count is not None and len(values) < int(lo_count)


def _texts(lang: str) -> Dict[str, str]:
    t = {
        "en": {
            "rcd_count": "NF C 15-100 asks for at least two 30 mA RCDs; this design has {n}. With one, a fault on any circuit cuts the whole home.",
            "rcd_circuits": "{n} circuits on this RCD; NF C 15-100 allows at most 8.",
            "circuit_rcd": "This circuit is not below any RCD.",
            "rcd_type_a": "This circuit needs an RCD of type A (or F, B); “{rcd}” is type AC.",
            "board_over": "The devices take {used} modules, the board has {cap}.",
            "board_reserve": "{used} of {cap} modules used, {free} free: about 20 % ({need}) should stay free for later circuits.",
        },
        "fr": {
            "rcd_count": "La NF C 15-100 demande au moins deux interrupteurs différentiels 30 mA ; ce projet en a {n}. Avec un seul, un défaut sur n'importe quel circuit coupe toute l'installation.",
            "rcd_circuits": "{n} circuits sur ce différentiel ; la NF C 15-100 en autorise 8 au plus.",
            "circuit_rcd": "Ce circuit n'est protégé par aucun différentiel.",
            "rcd_type_a": "Ce circuit demande un différentiel de type A (ou F, B) ; « {rcd} » est de type AC.",
            "board_over": "Les appareils occupent {used} modules, le tableau en a {cap}.",
            "board_reserve": "{used} modules occupés sur {cap}, {free} libres : environ 20 % ({need}) doivent rester libres pour les extensions.",
        },
        "de": {
            "rcd_count": "Die NF C 15-100 verlangt mindestens zwei FI-Schutzschalter 30 mA; dieser Entwurf hat {n}. Mit einem schaltet ein Fehler in irgendeinem Stromkreis das ganze Haus ab.",
            "rcd_circuits": "{n} Stromkreise an diesem FI; die NF C 15-100 erlaubt höchstens 8.",
            "circuit_rcd": "Dieser Stromkreis hängt an keinem FI.",
            "rcd_type_a": "Dieser Stromkreis braucht einen FI Typ A (oder F, B); „{rcd}“ ist Typ AC.",
            "board_over": "Die Geräte belegen {used} Teilungseinheiten, der Verteiler hat {cap}.",
            "board_reserve": "{used} von {cap} Teilungseinheiten belegt, {free} frei: etwa 20 % ({need}) sollten für spätere Stromkreise frei bleiben.",
        },
    }
    return t.get(lang, t["en"])
