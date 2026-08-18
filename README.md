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
| `hokusai` | HOKUSAI BigWaterfall2 (HBW2) | slurm | CPU-first Slurm cluster (312-node MPC, large-memory, H100 GPU subsystems); a project account is mandatory on every job. |
| `rccs-cloud` | R-CCS Cloud | slurm | Heterogeneous ~20-partition cluster (CPU/NVIDIA/AMD/Intel GPU), Slurm with accounting. |
| `rikyu` | RIKYU (RIKEN AI4S / GB200) | slurm | RIKEN AI4S GB200 GPU cluster, Slurm with accounting, job-total GPU request. |
<!-- FACILITY_TABLE:END -->

## Adding a new facility? Read `PORTING.md`.

**[`PORTING.md`](PORTING.md) is the complete porting guide.** Porting a new
machine means opening a PR against *this* repo that adds one
`facilities/<slug>/` directory — no new repo, no new plugin. Start there if
you're about to onboard a facility.

## What's here

- `hpc_agent_core/` — the generic engine: `config.py` (the facility
  registry), `middleware.py` (the SSH execution layer — the only thing that
  talks to a cluster), `models.py` (PSI/J-style job models), `compute/`
  (config-driven Slurm/Grid-Engine scheduler backends), `rag/` (the
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
  (configuring, submitting-jobs, monitoring-jobs, demo, reproducing).
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
