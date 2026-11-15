# ADR-0004: Files are given to the chat, which decides what they are for

**Status:** accepted · **Date:** 2026-11-15

## Context

People arrive with files: a wholesaler's price list, a manufacturer's BMEcat,
a Datanorm export, a spreadsheet, a supplier's quote as PDF, a Turtle model.
A form per format would be a second design tool beside the chat. The design is
the chat plus the ontologies (ADR-0001); a file is one more input to it.

## Decision

1. **An inbox.** A file dropped on the page's Files tab is kept privately in
   `<data>/inbox/<id>/` (0700, files 0600) and becomes the chat's selection.
2. **Kind from content, not name.** `inbox.detect` recognises BMEcat,
   Datanorm, article tables (CSV and XLSX, the latter read with the standard
   library), Turtle, JSON, PDFs and PDFs that read like a quote, and notes what
   it found ("a BMEcat catalogue, 412 articles").
3. **The chat reads and decides.** `inbox()` and `read_file()` (text in slices;
   a PDF via `pdftotext`) are read tools. Articles go to a partner through
   `import_file_to_partner()`, a proposal that runs `partners.import_file`, so
   ADR-0002 and ADR-0003 apply unchanged. Anything else — a quote, a plan, a
   description — becomes design changes the chat proposes tool by tool, saying
   which facts came from the file.
4. Nothing in the inbox leaves the computer.

## Consequences

- A new kind of file usually needs no new code: the chat reads its text. A new
  *bulk* format (FAB-DIS) still needs a parser in `partners.py`.
- Reading a PDF needs poppler's `pdftotext`; without it the file is kept and
  the chat says it cannot read it.
- A long file costs chat context; `read_file` returns 20 000 characters at a
  time and says whether there is more.
