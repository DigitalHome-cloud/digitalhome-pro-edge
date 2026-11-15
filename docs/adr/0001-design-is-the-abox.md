# ADR-0001: The design is the A-Box; the agent edits it

**Status:** accepted · **Date:** 2026-11-15

## Context

In the darkfactory Designer, a home's electrical installation is designed
with Blockly: blocks generated from the T-Box, saved as a Turtle A-Box. The
knowledge that matters sits in the example designs (French flat types T1–T4
after the Hager NF C 15-100 guide, a VDI panel, real boards) and in the norm
shapes. Claude can already write such an A-Box from a description; the block
editor is what stands between a person and the design. We move from
"Blockly-coded" to "vibe-coded".

## Decision

1. **A home has workspaces.** The tenant is a home (its SmartHome ID once
   linked); a workspace is an active project in it — a new switchboard, a
   kitchen — and holds one design. A workspace is one A-Box (one space of the
   D-LAB-5 edge layer), so it syncs, validates and links like any space.
2. **The design is the A-Box**, in the Designer's own IRI scheme
   (`https://digitalhome.cloud/instance/{home}/{type}/{id}`) and vocabulary
   (`dhc:DistributionBoard`, `dhc:RCD`, `dhc:Circuit`, `dhc:hasProtection` …),
   so the cloud reads what the edge writes. Ids are minted. What the T-Box has
   no word for yet (board size in modules, a device's place on a board, a
   point on a circuit, the workspace itself) is in a small edge vocabulary,
   `dhp:` (`https://digitalhome.cloud/pro#`), to be moved upstream.
3. **Claude edits it through MCP tools; the person confirms each change.**
   Every changing tool goes through `act()`, so in the chat panel it is a
   proposal with a Confirm button, limited to `CHAT_ALLOWED`. The page shows
   the result. Blockly is not ported.
4. **Two kinds of shapes.** *Structural* shapes (`edge/ontology/shapes/`)
   refuse a save: a board without a size, an RCD of an unknown type, a circuit
   without a breaker is not a design. *Norm* shapes (`edge/ontology/cbox/`,
   copied from darkfactory) are advisory: a design that breaks NF C 15-100 is
   saved, and `report()` says what is wrong, in the person's language. The
   rules the shapes cannot express — at least two 30 mA RCDs, at most eight
   circuits per RCD, type A where the appliance needs it, about 20 % free
   modules — are checked in `designs.py`.
5. **The Designer keeps working.** Retiring Blockly in the cloud is a later
   decision, once the edge has replaced it in practice.

## Consequences

- A quote can be modelled as a workspace and reported on, and a counter-
  proposal built in another workspace of the same home: that is the first
  use, and it needs no block editor.
- Structural shapes and `dhp:` live in this repository for now. When the
  Designer writes the same structure they move to darkfactory
  `repos/core/schema`, and `scripts/sync-ontology.sh` copies them like the rest.
- The norm shapes' `sh:or` guards report no reason of their own; `report()`
  finds the failed condition inside the guard and shows its message. A shape
  written differently may need the same care.
- One link to the cloud is one home (the layer's tenant). An installer with
  many homes links once per home until the cloud's edge API knows otherwise.
- Real homes, quotes and prices never enter this repository: examples and
  tests use invented ones.
