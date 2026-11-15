# digitalhome-pro-edge

**v0.1.0** · GPL-3.0 · [releases](https://github.com/DigitalHome-cloud/digitalhome-pro-edge/releases)

**digitalhome.pro** — design a home's electrical installation by talking to
Claude. A home has one or more **workspaces**, each an active project (a new
switchboard, a kitchen) holding one design: boards → RCDs → circuits →
points in rooms. Claude proposes every change and you confirm it; the page
shows the board, a **report** against NF C 15-100, the **materials**, and
prints **QR labels** for the board. Product data and prices come from each
**partner** by API or by an imported file (BMEcat, Datanorm, CSV) and stay on
this computer. The **digitalhome.cloud device catalogue** syncs in as partner
`digitalhome-cloud`, and a catalogue admin can publish a checked article back
to it (Partners tab; ADR-0005).

It is the DigitalHome.Cloud edge for designers and installers; running a home
is [digitalhome-devops-edge](https://github.com/DigitalHome-cloud/digitalhome-devops-edge).
Decisions: [`docs/adr/`](docs/adr/). The edge layer: [`docs/edge.md`](docs/edge.md).

- Ontology: `scripts/sync-ontology.sh` copies `dhc-core.ttl` and the norm
  shapes from a darkfactory checkout.
- Nothing real belongs in this repository: no customers, quotes, prices or
  credentials. Examples and tests use invented homes.

## Use it

```bash
./run.sh                 # http://127.0.0.1:8773 (run.cmd or run.ps1 on Windows)
./run.sh --port 9000     # somewhere else
./run.sh --stop          # shut it down
```

The first run creates `.venv` and installs the requirements. Any other option
goes straight to the app, e.g. `./run.sh --no-update-check`.

The header has **About**, which shows the installed version, checks github.com
for a newer one and links to the repository. On a pip or pipx install it can
**update itself**: it runs pip against the latest tag, shows what pip said, and
restarts into the new version only if that worked. From a source checkout it
tells you to `git pull` instead. The check is one request for a text file. It
sends nothing about you, is cached for six hours, and is skipped silently when
there is no network. `--no-update-check` turns it off. **Restart** and **Stop**
are only accepted from this machine.

Notes live in two folders: `mydocs/` for your own, which git
ignores and which follows the working directory, and the samples that ship
inside the package. A save goes back to the folder the note came from.

## Installing without a clone

**A release tarball**: needs neither git nor pip.

```bash
curl -L https://github.com/DigitalHome-cloud/digitalhome-pro-edge/archive/refs/tags/v0.1.0.tar.gz | tar xz
cd digitalhome-pro-edge-0.1.0
./run.sh
```

**Or install it**, with no source tree to keep:

```bash
pipx install git+https://github.com/DigitalHome-cloud/digitalhome-pro-edge@v0.1.0
digitalhome-pro-edge-web                 # the page
digitalhome-pro-edge summarise note.json # the command line
digitalhome-pro-edge-mcp                 # the MCP server, for agents
digitalhome-pro-edge-skill --install     # the agent skill, into ~/.claude/skills
```

Every command has a `python3 -m` twin that needs nothing on PATH:

| command | the same thing as a module |
|---|---|
| `digitalhome-pro-edge` | `python3 -m digitalhome_pro_edge.engine` |
| `digitalhome-pro-edge-web` | `python3 -m digitalhome_pro_edge.app` |
| `digitalhome-pro-edge-mcp` | `python3 -m digitalhome_pro_edge.mcp_server` |
| `digitalhome-pro-edge-skill` | `python3 -m digitalhome_pro_edge.core.skill_install` |

## Updating an install

**From the page:** *About → Update and restart*.

**From the command line**, name the new tag. `--upgrade` alone will not move a
pinned tag:

```bash
pip install --upgrade git+https://github.com/DigitalHome-cloud/digitalhome-pro-edge@v0.1.0
pipx install --force git+https://github.com/DigitalHome-cloud/digitalhome-pro-edge@v0.1.0
```

If you copied the skill with `--install`, refresh it afterwards:
`digitalhome-pro-edge-skill --install --force`.

## For agents

**As a Claude Code plugin** you get the skill and the MCP server in one step:

```
/plugin marketplace add ERP-LAB-5/python-tool-template
/plugin install digitalhome-pro-edge@erp-lab-5
```

On first use the plugin installs the version it pins into its own venv under
`~/.local/share/dlab5-tools/digitalhome-pro-edge/` and runs the MCP server from there.
It needs `python3` on PATH.

**From a checkout**, `.mcp.json` registers the MCP server for this repository.

**For any other agent, press Agent** in the header. It writes the JSON for
Claude Code, VS Code (GitHub Copilot), Cursor or Claude Desktop with the real
paths already filled in — each client keeps the same server under a slightly
different key, in a different file — and either copies it or writes the file
for you, keeping any other servers already registered there. The panel also
shows whether an agent is currently working on this server.

MCP itself is the standard, so the server is written once and every client
speaks to it unchanged; only that small config file differs between them. What
no page can do is *start* one: a stdio server is spawned by its client, lives on
that client's pipes and dies with it, so there is nothing to start or stop from
the browser.

The MCP server starts the web server if it is not running, and both work on the
same files, so an agent's save shows up for the person at the browser.

[**The skill**](digitalhome_pro_edge/skill/SKILL.md) ships inside the package.
`digitalhome-pro-edge-skill --install` copies it to `~/.claude/skills` for agents
that don't use the plugin, and `--install --for vscode` writes it as
`.github/copilot-instructions.md` instead (`--for cursor` for Cursor's rules
folder). A checkout has identical copies in
`.claude/skills/digitalhome-pro-edge/` and `plugin/skills/digitalhome-pro-edge/`. They are
real files rather than symlinks, because symlinks don't survive a clone on
Windows. `digitalhome-pro-edge-skill --check` confirms they are in step, and
`--sync` rewrites them from the packaged copy.

## Development

```bash
./test.sh                # the suite, with ROS 2's PYTHONPATH kept out of it
```

This repository was generated from
[ERP-LAB-5/python-tool-template](https://github.com/ERP-LAB-5/python-tool-template).
`digitalhome_pro_edge/core/`, the launchers, `test.sh`, `tests/test_core.py`,
`scripts/release.py` and `plugin/bin/launch_mcp.py` belong to the template. Take its fixes with
`copier update` rather than editing them here. Everything else belongs to this tool.

Releasing:

```bash
python3 scripts/release.py 0.2.0 -F notes.txt --push
```

It bumps `VERSION` everywhere it appears, updates this README's pins, syncs the
skill copies, commits, tags, pushes, and creates the GitHub release.

## Licence

GPL-3.0-or-later. © 2026 D-LAB-5 — *Twin. Experiment. Automate.*
See [LICENSE](LICENSE).
