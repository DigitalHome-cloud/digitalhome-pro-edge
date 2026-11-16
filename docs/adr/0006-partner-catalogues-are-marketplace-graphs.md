# ADR-0006: Partner catalogues are graphs of the digitalhome.cloud marketplace

**Status:** accepted · **Date:** 2026-11-15 · Supersedes ADR-0005

## Context

ADR-0005 linked this edge to the cloud's device catalogue with routes of its
own: page through the `DeviceModel` table, write one model at a time. That is a
second sync mechanism beside the one the platform already has. The Mediathek
keeps its knowledge as one RDF graph per space with a version, and an edge
merges it three ways (template-dlab5-cloud ADR-0007). A catalogue is not a
home's either: it belongs to whoever sells the products. So the cloud turned
its catalogue into a **marketplace**: one catalogue graph per seller
(manufacturer, distributor, wholesaler, or `digitalhome-cloud`, the platform's
curated one), edited by that seller's editors (core, `schema/market/`,
`/edge/v1/market/*`).

## Decision

1. **A seller is a partner with the same id.** `market.subscribe(seller)` adds
   it to the private partner register (`market: true`), and its catalogue is
   the partner's graph, `<data>/partners/<id>.catalogue.ttl`. Designs, the
   norms rules (ADR-0003) and the materials list use it unchanged. Articles
   are named as in the marketplace, `https://digitalhome.cloud/id/market/<id>/<ref>`;
   older local catalogues are renamed when they are loaded.
2. **The Mediathek's merge.** `market.sync(partner)` uses the edge layer's
   `sync.merge` and `Base` against the version this edge and that connection
   last agreed on (`<data>/partners/.sync/<connection>/<id>.ttl`). One fact
   with two values (a brand, a label, a rating — `settings.SINGLE_VALUED`) is
   a conflict: nothing is written until the person picks "mine" or "theirs".
   A save that loses a race (409) merges again.
3. **Who may push is the cloud's answer.** When the person who linked this
   edge is the seller's editor (or a platform admin), with an authenticator
   app, the merged graph is pushed (two steps: a staging PUT, then a commit
   the cloud validates against the marketplace shapes; refusals come back as
   problems to show). Otherwise the sync only pulls, and what was added here
   stays on this edge (`local_only`), merged again on every sync.
4. **Files by content.** `attach()` keeps an image or datasheet by its SHA-256
   under `<data>/partners/files/` and names it on the article; a push uploads
   the ones the cloud lacks through hash-bound, write-once presigned PUTs.
5. **Prices never go.** They are not in the catalogue graphs (partners.py
   keeps them), and the marketplace shapes are closed, so a price could not
   be saved there anyway.
6. **The chat proposes.** `market_sellers()` reads; `subscribe_to_seller()`
   and `sync_with_market()` (with conflict choices) are proposals, the only
   market calls in `CHAT_ALLOWED`.

## Consequences

- One catalogue per seller across the platform; a professional's corrections
  reach it when they edit for that seller, and stay theirs otherwise.
- Needs the cloud's `/edge/v1/market/*` routes (core, 2026-11-15); an older
  cloud answers 404, shown as "no marketplace yet".
- `cloud_catalogue.py` and the `/api/cloud-catalogue*` routes are gone.
