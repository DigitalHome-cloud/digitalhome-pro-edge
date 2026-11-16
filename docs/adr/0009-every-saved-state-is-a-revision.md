# ADR-0009: Every saved state of a design is a revision; a baseline never moves

**Status:** accepted · **Date:** 2026-11-16 · Amends ADR-0007 (what a workspace folder holds)

## Context

A workspace's `design.ttl` is overwritten on every change. That was enough
for a new board drawn from nothing. The first real job is a modernisation:
a 1986 board, surveyed from photos and the owner's answers, that is still
the live installation. The survey must be kept exactly as it was taken while
the design moves on, and the quote must say what changed since then.

A survey also says things a new design never does:
- a circuit's rating or cable section is unknown;
- a circuit is protected by a fuse, not by a breaker;
- the only residual-current device is the supplier's sealed main breaker
  (500 mA);
- some devices have not been identified.

A design that needed all of these values could only hold the survey with
guessed values.

## Decision

1. **One revision per change.**
   - Every save that changes the graph also writes the whole design to
     `mydocs/<ws>/revisions/r0001.ttl, r0002.ttl …`. It adds one line to
     `log.jsonl`: `{n, at, by, via, summary}`.
   - A save that changes nothing writes no revision.
   - A design saved before history was kept becomes r1 on its first change.
   - `by` is the account that runs the edge. `via` is the page, the chat (a
     confirmed proposal), an agent (MCP) or the edge itself.
   - This is done in `designs.WorkspaceKB`, the subclass the tool owns. The
     layer's `edge/knowledge.py` is unchanged.
2. **Tags name revisions; a frozen tag is a baseline.**
   - `tags.json` maps a name to a revision.
   - An ordinary tag can be moved or removed.
   - A frozen tag cannot be moved or removed, by anyone, through any route.
3. **History is never rewritten.** Restoring revision n makes a new revision
   with n's content, noted "restored rN". Nothing is ever pruned: a design
   is a few kB.
4. **Comparing works statement by statement, grouped by the node.** A
   compare lists the nodes added and removed. For each changed node it gives
   every property's values before and after. The page (History), the API
   (`/revisions`, `/diff`, `/tag`, `/restore`), the MCP tools and the chat
   all use the same code.
5. **A design can hold an as-is survey.**
   - A circuit may leave out its type, rating and section. It is then
     `dhp:toVerify true`, never given a guessed value.
   - A circuit may sit straight on a board, below no RCD.
   - Its own protection can be a fuse (`dhp:protectionKind`).
   - The supply's main breaker is a device (`main_breaker`, with its
     sensitivity). It is not an RCD, so it never counts as the 30 mA
     protection the norm asks for.
   - `unidentified` is a device seen but not yet known.
   - `dhc:builtUnder` records the edition the installation was built under,
     as evidence and not as a verdict. That includes NF C 15-100:1976 and
     :1991, which are T-Box editions without shapes.
6. **What a survey left open is unchecked, never compliant.** SHACL checks
   only the values that are present, so a missing rating passes every rule.
   The report adds an `unchecked` finding for each to-verify item, and a
   design with one does not conform.

## Consequences

- The first baseline is "As-is 1986 (baseline)" of the T3 workspace, which
  stays on the edge with its files. Revisions are not synced to the cloud
  yet. When they are, the cloud gets the same layout or an ADR saying
  otherwise.
- The norm shapes now get decimals in their shortest form
  (`designs._for_shapes`). rdflib reads the Turtle `32.0` back as "32.0",
  and the EV-charging guards compare `"32"^^xsd:decimal` as a term, so
  those rules had never run on a saved design. This is the same fix as in
  the cloud's template validator (core ADR 0017).
- A frozen tag is not a lock: the design keeps changing after it. A
  baseline is a point to compare with and restore from, not a branch.
