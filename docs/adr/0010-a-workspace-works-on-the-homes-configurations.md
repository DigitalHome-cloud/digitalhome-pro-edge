# ADR-0010: A workspace works on the home's configurations in the cloud

**Status:** accepted · **Date:** 2026-11-16 · Builds on ADR-0008 and ADR-0009

## Context

digitalhome.cloud now keeps, per home, one live configuration, the versions
before it and planning options, and a vault of photos and documents
(darkfactory ADRs 0018 and 0019). Everything there is keyed on the home's
meaningless `homeId`, not on its SmartHome ID. Until now a workspace's
design and files lived only on the edge.

## Decision

1. **A workspace links to the home's configurations** through its
   workspace node:
   - `dhp:homeId`, taken from `/edge/v1/homes` once and then kept;
   - `dhp:basedOn`, the version the work started from;
   - `dhp:option` and `dhp:optionVersion`, the planning option this
     workspace is a checkout of, and the option version it last pulled or
     pushed.
2. **What goes to the cloud is the design without the workspace node.**
   The title, status, connection and link stay on the edge.
3. **Operations** (`configs.py`, page, MCP, chat):
   - **publish** a survey or a first design as `<homeId>-0001-0000`;
   - **create** an option, based on the live version by default;
   - **pull** an option (a new revision noted "pulled …");
   - **push** to an option, with the cloud's version check. A conflict
     says to pull first;
   - **promote** the option to the next major.
4. **Publishing and promoting are a person's act.** They cannot be undone.
   - The page asks twice.
   - The chat and an agent in the chat panel can only propose them.
   - An agent outside the panel is pointed to the page.
5. **The edge's revisions stay its working history (ADR-0009).** The
   revision that became a version is tagged with the version's id, frozen.
6. **Files go to the home's vault**, from the workspace's `files/`:
   - a dry run comes first, and every file is sent once (by SHA-256);
   - each file is grouped under the option this workspace checks out, else
     its `basedOn`, unless a version is named;
   - its path in `files/` is kept as its caption;
   - the files also stay on the edge;
   - there are no thumbnails until Pillow is a dependency.

## Consequences

- The T3 of the first job is the home's `-0001-0000`. Its modernisation is
  option `p01`, and the survey package is in the vault under `-0001-0000`.
- Instance IRIs still name the SmartHome ID (`instance/{home}/…`, the
  Designer's scheme). Moving them to the homeId is a separate decision
  shared with the Designer.
