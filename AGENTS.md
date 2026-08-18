# AGENTS.md

Read [`PORTING.md`](PORTING.md) before making changes here — it's the
canonical guide for onboarding a new facility. This file covers design
rules and repo facts that apply across the whole repo, not the porting
procedure itself.

## What this repo is

One Claude Code / Codex plugin (`plugins/hpc/`), one MCP server process,
every onboarded HPC facility reachable through one generic, facility-
parametrized tool surface. This supersedes the earlier "one repo per
machine, all pinning a shared `hpc-agent-core` PyPI library" model
(`Rikyu-Agent`, `Hokusai-Agent`, `RCCS-CloudAgent`, ...) — those repos are
untouched by this project and continue to exist independently; this is a
fork of `hpc-agent-core`'s engine that absorbed multi-facility support into
itself, not a consumer of the PyPI package.

## Design rules

- **Every tool takes an explicit `facility` slug as its first argument.**
  There is no default facility, no "current" facility, no global state
  naming one. An agent must always know or discover (`get_facilities()`)
  which facility it's calling.
- **A facility PR touches exactly one directory: `facilities/<slug>/`.**
  See PORTING.md §11 for the full list of what a facility PR does *not*
  need to touch. If a change seems to require editing `hpc_agent_core/` or
  `hpc_mcp/`, that's a signal to reconsider the approach, not a green light
  to edit them — those files serve every facility at once.
- **Clarity over cleverness.** A little facility-specific code in one
  `facility.py` is fine — don't force every dialect difference through a
  maximally generic mechanism if a straightforward subclass override reads
  better (see `facilities/rccs_cloud/facility.py`'s `CloudSlurmBackend` for
  the pattern).
- **The MCP server must never fail to start.** Per-facility config is read
  lazily, at tool-call time, never at import time.
- **Never write to stdout in server code** — MCP stdio transport uses it
  for JSON-RPC; log to stderr only. `remotemanager`'s progress output is
  redirected by `middleware.py`.

## Repo map

```
hpc_agent_core/        The generic engine (SSH middleware, models, scheduler
                        backends, docs RAG, doctor, serving, the facility
                        registry in config.py).
facilities/             One directory per onboarded facility, plus
                        registry.py (facility slug -> SchedulerBackend).
hpc_mcp/                The unified server entry points; importing this
                        package registers every facility.
plugins/hpc/            The Claude Code / Codex plugin: .mcp.json, skills/.
scripts/                render_facility_tables.py — the facility-table
                        codegen (see PORTING.md §7).
tests/live_smoke.py     Live, facility-agnostic smoke test.
```

## Facilities onboarded so far

<!-- FACILITY_TABLE:START -->
| slug | facility | scheduler | description |
|---|---|---|---|
| `rccs-cloud` | R-CCS Cloud | slurm | Heterogeneous ~20-partition cluster (CPU/NVIDIA/AMD/Intel GPU), Slurm with accounting. |
| `rikyu` | RIKYU (RIKEN AI4S / GB200) | slurm | RIKEN AI4S GB200 GPU cluster, Slurm with accounting, job-total GPU request. |
<!-- FACILITY_TABLE:END -->

## Tool coverage

See [`IRI_CHECKLIST.md`](IRI_CHECKLIST.md) — one checklist for the whole
repo (not per-facility), since every facility shares the same tool set.
