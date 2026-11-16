# ADR-0008: A workspace belongs to one home on one instance

**Status:** accepted · **Date:** 2026-11-16 · Amends ADR-0007 (how a workspace id is made)

## Context

A home is made in the Portal: that is where its SmartHome ID, its owners and
its address come from. The pro edge designs for homes, so a workspace must
name one. Two gaps:

- An edge can be linked to several clouds at once (`edge/cloud.py`: stage,
  prod, a sandbox), and the same SmartHome ID can exist on more than one
  (`FR-DEMO`). A workspace only recorded `dhp:home`, not which cloud.
- An edge that was not linked could start a *draft* for a name it made up.
  Such a home exists nowhere else, and nobody else can see the work.

The id was also made from the first title (`mydocs/new-switchboard/`), so
after a rename the folder and the title said different things.

## Decision

1. **Workspace 1..* → 1 home on 1 instance.** A workspace records
   `dhp:home` (the SmartHome ID) and `dhp:instance` (the connection's name,
   e.g. `stage`, `prod`). The same ID on two instances is two homes.
2. **Linked only.** `POST /api/workspaces` (and the `new_workspace` tool)
   takes a `connection`, default the current one, and refuses unless that
   connection is linked and `POST /edge/v1/homes` on it lists the home. The
   cloud only lists homes the person may access, so the edge never decides
   that itself. No drafts.
3. **Minted ids.** A new workspace's id is `ws-` and eight letters or digits.
   It is its folder name (ADR-0007) and never changes; Rename changes only
   the title.
4. **Attach.** A workspace with no instance (made before this, perhaps for a
   draft name) is listed as *not attached*. `attach_workspace` (route
   `POST /api/workspaces/<ws>/attach`) gives it a home on a connection after
   the same checks. Every design IRI names its home
   (`https://digitalhome.cloud/instance/<home>/…`), so attach rewrites them
   in the same change, and the structural shapes check the result.

## Consequences

- Existing folders keep their ids; only new workspaces get minted ones.
- The page shows the instance beside each home, links a home to the Portal
  only when it is on the current connection, and offers Attach for an old
  workspace.
- The marketplace stays platform-wide: it is not tied to a workspace's home.
- Syncing a workspace's design to the cloud is not part of this: the DHC edge
  API has no tenant/space route yet (`edge/sync.py` syncs per space).
