# ADR-0003: A partner's articles say which norms they may be used under

**Status:** accepted · **Date:** 2026-11-15

## Context

A design picks articles from partners (ADR-0002). Some articles are sold all
over Europe (an RCD to EN 61008-1); others belong to one country's practice:
a French-pattern socket, a Belgian one, a device listed for NF C 15-100 only.
A design under one norm must not quietly use an article made for another.

## Decision

1. Each partner has a **catalogue graph**, `<data>/partners/<id>.catalogue.ttl`
   (0600): `dhp:Article` nodes with the product facts a partner publishes —
   reference, label, EAN, ETIM class — and three facts about where it may be
   used: `dhp:usableIn` (a market: "EU", "FR", "BE" …), `dhp:approvedFor`
   (an installation norm, `dhc:Norm_NFC15100`) and `dhp:conformsTo` (product
   standards, "EN 61008-1").
2. It is filled on import, from a file's own `norms`, `markets`/`region` and
   `standards` columns, else from the partner's default `markets`; and by hand
   or by the chat from a datasheet (`set_article_norms`, a proposal).
3. **Usable** = approved for the norm, or sold for the norm's country
   (`dhc:normCountry` in the T-Box), or sold for the EU and the country is in
   it. An article that says nothing is **unknown**, not refused.
4. `report()` warns (`article-norm`) when an item's article is *not* usable
   under the workspace's norm. It is a finding, like the norm shapes, never a
   refusal.
5. **Prices are not in the catalogue.** They are commercial and stay in the
   private items file; the catalogue holds facts a partner publishes and could
   one day be shared.

## Consequences

- The same design can be checked against two partners' ranges, and a switch to
  another country's norm shows at once which articles no longer fit.
- "Unknown" is common until partners' files carry market data; the report
  stays quiet about it rather than flooding a design with warnings.
- The catalogue's IRIs (`https://digitalhome.cloud/catalogue/<partner>/<ref>`)
  are minted on the edge; when the cloud keeps catalogues, it must keep them.
