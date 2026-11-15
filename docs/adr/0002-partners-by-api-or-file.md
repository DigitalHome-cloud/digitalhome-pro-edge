# ADR-0002: Partners by API or by file; the partner list is private

**Status:** accepted · **Date:** 2026-11-15

## Context

A design becomes a quote when its bill of materials has articles and prices.
Manufacturers, distributors and wholesalers offer that very differently: a
few have partner APIs behind an account and OAuth credentials; most deliver
data exchange files — BMEcat with ETIM classes, FAB-DIS, Datanorm — or can
export a price list. Which partners someone works with, and on what terms,
is their business: it does not belong in a public repository.

## Decision

1. **The partner list is private data, not code.** Each entry — id, name,
   kind, the formats it delivers, its API connector if any — is kept with the
   API credentials in one place, chosen on the page: **this computer** (the
   data folder, 0700/0600) or the **connected digitalhome.cloud instance**
   (edge API `/edge/v1/partners/…`, for every edge of the same home). Moving
   between the two copies everything over and clears the old place.
2. **The code knows only how to talk to partners:** the API **connectors**
   (the first follows Schneider Electric's published Product Catalog v2 spec,
   OAuth2 client credentials; its net-price path is configurable because that
   spec is behind the partner login) and the **file formats** (BMEcat 1.2 and
   2005 with the ETIM class, Datanorm 4 article records, CSV price lists with
   French, German or English column names).
3. Each partner uses a channel: **api** when it has a connector and
   credentials, else **file** when one was imported, else **none**.
4. A design item carries a **partner and reference**; the BOM is priced from
   the channel in use, and every unpriced line says why.
5. **Imported files and prices stay on this computer.** Credentials are
   entered on the page only. The chat may propose adding a partner to the
   list; file imports, credentials and where the list is kept are not in its
   allowed calls, and no tool returns a credential.

## Consequences

- darkfactory's edge API has no `/edge/v1/partners` yet. Until it does,
  choosing "in the connected cloud" is refused with that reason and nothing
  moves. The cloud side must store credentials encrypted and hand them only to
  the home's own edges.
- Tests and examples use invented partners; only connector code names a
  manufacturer.
- FAB-DIS (an Excel workbook) and ELBRIDGE baskets are not read yet; both fit
  the same model when a partner needs them.
- The API connector is tested against the published spec, not a live account.
