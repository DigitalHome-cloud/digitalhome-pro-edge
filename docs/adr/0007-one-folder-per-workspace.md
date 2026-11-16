# ADR-0007: One folder per workspace

**Status:** accepted · **Date:** 2026-11-15 · Amends ADR-0001 (where a design is kept) and ADR-0004 (where a file given to the chat is kept) · Amended by ADR-0008 (ids are minted, not made from the title)

## Context

A workspace (an active project: a new board, a kitchen extension) was one file
among others: the edge layer's knowledge base kept every A-Box in
`<data>/abox/<workspace>.ttl`, and every file given to the chat went into
one shared `<data>/inbox/`. Everything that belongs to one project should sit
in one place, so that it can be found, copied or archived as a folder. In a
checkout, `<data>` is `mydocs/`.

## Decision

1. **The layout:**

   ```
   <data>/<workspace>/design.ttl       the workspace's A-Box (its design)
   <data>/<workspace>/files/<id>/      files given to the chat while it is open
   <data>/inbox/<id>/                  files given with no workspace open
   <data>/partners/…                   partners and marketplace catalogues, shared
   <data>/.sync/<connection>/…         the cloud sync bases
   ```

   A workspace's id is its folder name and never changes. Its **display name**
   (the title) can change at any time: the design header's **Rename**, or
   `set_workspace(title=…)` in the API and MCP. `abox`, `inbox`, `partners` and
   `files` are never workspace ids.

2. **No edit of the edge layer.** `edge/knowledge.py` belongs to
   template-dlab5-edge. `designs.WorkspaceKB` subclasses its `KnowledgeBase`
   and only changes where a graph lives (`_path`, `graphs`). Validation on
   every change, one writer at a time and the sync bases (`kb.dir/.sync`) stay
   the edge layer's. At start, `app.main` binds `kn.KnowledgeBase` to
   `WorkspaceKB`. The edge layer's routes and first start build a
   `KnowledgeBase()` when they are called, so the cloud sync of A-Boxes uses
   the same folders. The binding is done in `main`, not on import, so the
   template's own tests keep their layout.

3. **Migration on start.** `designs.migrate_layout()` moves
   `abox/<workspace>.ttl` to `<workspace>/design.ttl` and `abox/.sync/` to
   `.sync/`. It never overwrites: a clash is left where it is and logged.
   Running it again changes nothing.

4. **Files follow the open workspace.** `inbox.add` stores a file under
   the workspace the page has open (`selection`), else in the shared inbox. A
   file is found by its id in either place. The Files tab lists the open
   workspace's files and the shared ones, and says where each is kept.

## Consequences

- A workspace can be archived or handed over by copying its folder.
- An upstream KnowledgeBase that changes `_path`/`graphs` would need a look
  here. The tests in `tests/test_workspace_layout.py` show it.
- Files given before this change stay in the shared inbox.
