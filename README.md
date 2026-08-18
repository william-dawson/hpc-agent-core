# hpc-agent-hub

One Claude Code / Codex plugin, one MCP server process, every onboarded
supercomputer reachable through one generic tool surface. An agent submits
and monitors jobs, manages files, and searches documentation on any
registered facility by passing its slug on every call — `submit_job(facility
="rikyu", ...)`, `search_docs(facility="rccs-cloud", ...)`.

This supersedes the earlier "one repo per machine, all pinning a shared
[hpc-agent-core](https://github.com/william-dawson/hpc-agent-core) library"
model: instead of N separate repos/plugins/processes, every facility lives
in this one repo and this one process.

<!-- FACILITY_TABLE:START -->
| slug | facility | scheduler | description |
|---|---|---|---|
| `fugaku` | Fugaku | pjm | 158,976-node A64FX (Arm SVE) system, Fujitsu PJM scheduler, no GPUs; a project group is mandatory on every job. |
| `hokusai` | HOKUSAI BigWaterfall2 (HBW2) | slurm | CPU-first Slurm cluster (312-node MPC, large-memory, H100 GPU subsystems); a project account is mandatory on every job. |
| `rccs-cloud` | R-CCS Cloud | slurm | Heterogeneous ~20-partition cluster (CPU/NVIDIA/AMD/Intel GPU), Slurm with accounting. |
| `rikyu` | RIKYU (RIKEN AI4S / GB200) | slurm | RIKEN AI4S GB200 GPU cluster, Slurm with accounting, job-total GPU request. |
<!-- FACILITY_TABLE:END -->

## Install

### Prerequisite: uv

The plugin starts its MCP servers with `uv tool run` from this repository's
`main` branch, so [`uv`](https://docs.astral.sh/uv/) must be installed and
on your `PATH` before Claude Code or Codex starts the plugin:

```bash
brew install uv        # or: curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart Claude Code or Codex afterwards so the plugin process inherits the
updated `PATH`.

### Claude Code

```
/plugin marketplace add william-dawson/hpc-agent-hub
/plugin install hpc@hpc-marketplace
/reload-plugins
```

### Codex

```
codex plugin marketplace add william-dawson/hpc-agent-hub
```

Then open `/plugins`, install `hpc`, start a new thread, and run
`/<facility>-demo` (e.g. `/rikyu-demo`) to verify end to end.

### Manual (any MCP-compatible client)

Both options below only register the MCP servers — copy
`plugins/hpc/skills/` into wherever your client loads skills from too (this
varies by client).

#### Option A — Using Hatch!

[Hatch!](https://github.com/CrackingShells/Hatch) registers MCP servers on
any supported host from a single command. Install it once, then configure
both servers — replace `<host>` with your target platform (`claude-code`,
`codex`, `cursor`, `vscode`, `claude-desktop`, `kiro`, `gemini`,
`lmstudio`, or any other
[supported host](https://github.com/CrackingShells/Hatch#supported-mcp-hosts)):

```bash
pip install hatch-xclam

hatch mcp configure hpc --host <host> \
  --command uv \
  --args "tool run --quiet --from git+https://github.com/william-dawson/hpc-agent-hub.git@main hpc-mcp"

hatch mcp configure hpc-docs --host <host> \
  --command uv \
  --args "tool run --quiet --from git+https://github.com/william-dawson/hpc-agent-hub.git@main hpc-docs-mcp"
```

To replicate the same configuration to additional hosts:

```bash
hatch mcp sync --from-host <host> --to-host cursor,vscode
```

#### Option B — Edit `.mcp.json` directly

Create or edit `.mcp.json` in your project root, using the same two entries
as [`plugins/hpc/.mcp.json`](plugins/hpc/.mcp.json).

## Configure

Each facility has its own settings file at
`~/.hpc-agent/<slug>.json` — one file per machine, all in one directory.
The minimum is an SSH host:

```json
{
  "ssh": {"host": "rikyu"}
}
```

- `ssh.host` is a `~/.ssh/config` alias, a `user@hostname`, or
  `"localhost"` if the agent runs directly on that cluster's own front-end
  node (no SSH at all). `<SLUG>_HOST` overrides the file.
- Some facilities need more — HBW2 requires a project account
  (`"defaults": {"account": "..."}`), for instance. **You don't have to
  look this up:** every tool call that can't reach a facility returns that
  machine's complete setup directions, including the exact JSON to write.
- For semantic documentation search, add
  `"embedding": {"api_key": "..."}` (or set `<SLUG>_EMBED_API_KEY` /
  the shared `RCCS_EMBED_API_KEY`). Without a key — or off the RIKEN
  network — docs search falls back to BM25 keyword matching over the same
  content, so it still works.

The `<slug>-configuring` skill (e.g. `/rikyu-configuring`) walks through
this interactively and can write the file for you.

## Verify

```bash
uv tool run --quiet --from git+https://github.com/william-dawson/hpc-agent-hub.git@main hpc-doctor
```

Checks every registered facility (pass a slug to check just one). All lines
should read `✓` except possibly embedding, which falls back to keyword
search outside RIKEN's network — not blocking.

## Adding a new facility? Read `PORTING.md`.

**[`PORTING.md`](PORTING.md) is the complete porting guide.** Porting a new
machine means opening a PR against *this* repo that adds one
`facilities/<slug>/` directory — no new repo, no new plugin. Start there if
you're about to onboard a facility.

## What's here

- `hpc_agent_core/` — the generic engine: `config.py` (the facility
  registry), `middleware.py` (the SSH execution layer — the only thing that
  talks to a cluster), `models.py` (PSI/J-style job models), `compute/`
  (config-driven Slurm and Grid-Engine backends; a facility whose
  scheduler is neither brings its own — see `facilities/fugaku/`), `rag/` (the
  docs-search pipeline), `docs_server.py`, `doctor.py`, `serving.py`,
  `mcp_server.py`.
- `facilities/<slug>/` — one directory per onboarded machine: `facility.py`
  (registers the facility + its scheduler backend), `facility.json` (the
  small manifest the table above is rendered from), `data/` (the facts
  JSON, the hand-written guide, the pre-built docs index), `skill_notes/`
  (real, facility-specific how-to — GPU dialect, module tables, MPI
  gotchas, failure modes — dropped into that facility's generated skills).
- `hpc_mcp/` — the unified server entry points (`hpc_server.py`,
  `docs_server.py`, `doctor.py`, `ingest.py`) — importing `hpc_mcp` itself
  registers every facility under `facilities/`.
- `plugins/hpc/` — the Claude Code / Codex plugin: one `.mcp.json`, one
  `skills/` tree with **real, distinct skill files per facility**
  (`rikyu-submitting-jobs`, `rccs-cloud-submitting-jobs`, ...), generated
  from a shared template (the genuinely universal mechanics) plus that
  facility's own `skill_notes/` (the cluster-specific knowhow) — not one
  generic skill shared by every machine. One small `hpc-facilities` skill
  (not generated per facility) is the discovery entry point.
- `templates/skills/*.md.tmpl` — one shared template per workflow
  (configuring, submitting-jobs, monitoring-jobs, reference, demo,
  reproducing).
- `scripts/render_facility_tables.py` — regenerates the table above (and
  anywhere else marked `FACILITY_TABLE:START`/`END`) from
  `facilities/*/facility.json`.
- `scripts/render_skills.py` — regenerates every `plugins/hpc/skills/
  <slug>-<workflow>/SKILL.md` from `templates/skills/*.md.tmpl` +
  `facilities/*/skill_notes/*.md`. `.github/workflows/ci.yml` runs both
  generators with `--check` so a PR that adds/edits a facility without
  re-running them fails.

## Tool surface: the IRI Facility API

The MCP tool surface mirrors the [IRI Facility
API](https://api.alcf.anl.gov/openapi.json) (the DOE standard this family
targets — not vendored here; fetch it fresh when checking coverage). See
[`IRI_CHECKLIST.md`](IRI_CHECKLIST.md) for coverage. One checklist for the
whole repo, not one per facility — coverage is uniform by construction
(every facility shares the same generic tool set).

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e .

.venv/bin/python tests/conformance.py            # offline; every facility, no SSH needed
.venv/bin/python -m hpc_mcp.doctor               # health check, every registered facility
.venv/bin/python -m hpc_mcp.doctor rikyu          # just one facility
.venv/bin/python tests/live_smoke.py              # live, read-only, every facility
.venv/bin/python tests/live_smoke.py --job rikyu  # + submits a real tiny job there — run when
                                                   #   touching compute/, middleware.py, models.py

python scripts/render_facility_tables.py          # after editing any facility.json
python scripts/render_skills.py                   # after editing any skill_notes/*.md
```

## License

AGPL-3.0-or-later — see [LICENSE](LICENSE).
