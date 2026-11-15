# ADR-0005: The digitalhome.cloud catalogue, both ways

**Status:** accepted · **Date:** 2026-11-15

## Context

digitalhome.cloud keeps one admin-curated catalogue of device models (the
Portal's Catalog, the `DeviceModel` table). A professional designs on this edge
with partners' catalogues (ADR-0002, ADR-0003). Without a link, the same model
is typed twice: once in the Portal, once in a partner file. Without a link the
other way, an article a professional has checked never reaches the catalogue
that homeowners and the Designer use.

## Decision

1. **A copy as a reserved partner.** `cloud_catalogue.sync()` pulls the cloud's
   models (`POST /edge/v1/catalogue`, device token, page by page) into the
   catalogue graph of partner `digitalhome-cloud`. A design names
   `digitalhome-cloud` + a model number like any article; the norms rules
   (`catalogue.usable`) apply unchanged. The id is reserved: no partner can
   be added under it. The copy is read-only here; `set_article` refuses it as
   it refuses any unregistered partner.
2. **Changes only, per connection.** The sync keeps the cloud's `now` and asks
   for models changed since then. It starts over (a full sync) the first time,
   on request, or when the current connection is another cloud than the last
   one, so stage and production models never mix.
3. **Publishing is one article, by a catalogue admin.** `publish()` sends one
   partner article as a model (`POST /edge/v1/catalogue/put`): reference →
   model number, label → description, markets → region, standards →
   standards, plus the brand and device type the person gives. Prices are not
   in the catalogue graphs (partners.py keeps them), so none can go. The cloud
   decides on every call whether the person who linked this edge may write:
   in `dhc-admins` with an authenticator app, the Portal's own rule. Anyone
   else gets 403, shown as such.
4. **The chat proposes, the person runs.** `cloud_catalogue()` is a read tool;
   `sync_cloud_catalogue()` and `publish_to_cloud_catalogue()` are proposals
   (`act`), and only these two calls are in `CHAT_ALLOWED`.

## Consequences

- One catalogue in the cloud, visible in every design on every linked edge.
- The edge needs the cloud's `/edge/v1/catalogue` routes (core, 2026-11-15); an
  older cloud answers 404, shown as "no catalogue for edges yet".
- Pictures stay the Portal's: S3 paths and thumbnails are not sent either way.
