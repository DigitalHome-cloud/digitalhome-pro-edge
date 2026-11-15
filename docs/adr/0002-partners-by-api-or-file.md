# ADR-0002: Partners by API or by file, whichever they offer

**Status:** accepted · **Date:** 2026-11-15

## Context

A design becomes a quote when its bill of materials has articles and prices.
Manufacturers and distributors offer that very differently (researched
2026-11-15):

- **Schneider Electric** has partner APIs (Product Catalog v2 with ETIM 10,
  Net Price, Availability, Stock, Order Entry) behind a partner account and
  OAuth2 client credentials.
- **Hager** offers no public API; its catalogue comes as BMEcat files with
  ETIM classes.
- **French distribution** exchanges FAB-DIS files; **German wholesalers**
  Datanorm files and IDS Connect; most distributors can export a price list.
- **ELBRIDGE 2.0** sends a configurator's BOM to a wholesaler's shop as a
  basket.

## Decision

1. Each partner is a **source** with a channel: **api** when this edge has
   credentials for it, else **file** when one was imported, else **none**.
   `partners.capability()` says which is in use and what is possible.
2. Formats read now: **BMEcat** (1.2 and 2005, with the ETIM class),
   **Datanorm 4** article records, and **CSV** price lists (French, German or
   English column names, decimal comma or point). The Schneider client follows
   the published catalogue spec; its net-price path is configurable because
   that spec is behind the partner login, and it is not called until set.
3. A design item carries a **partner and reference** (`dhp:partner`,
   `dhp:reference`); the BOM is priced from the channel in use, and every
   unpriced line says why.
4. **Commercial data stays on the PC.** Imported files and credentials live
   in the edge's data folder (0700/0600), never in the repository, never in an
   export. Credentials are entered on the page only: neither the import nor
   the credentials route is in the chat's allowed calls, and no tool returns
   a credential.

## Consequences

- FAB-DIS (an Excel workbook) and ELBRIDGE are not read yet; both fit the same
  source model when a partner needs them.
- The Schneider client is unit-tested against the spec, not against a live
  account. The first real partner account will tell whether the response
  parsing holds.
- Matching a template item to an article by ETIM class (rather than by a
  chosen reference) belongs with the templates and model homes (slice 2).
