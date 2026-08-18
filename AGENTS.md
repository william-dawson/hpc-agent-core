# AGENTS.md

Read [`PORTING.md`](PORTING.md) before making changes here — it's the
canonical guide for onboarding a new facility. This file covers design
rules and repo facts that apply across the whole repo, not the porting
procedure itself.

## What this repo is

One Claude Code / Codex plugin (`plugins/hpc/`), one MCP server process,
every onboarded HPC facility reachable through one generic, facility-
parametrized tool surface.

**This lives on the `unified-hub` branch of
`william-dawson/hpc-agent-core`.** It is the unified form of what `main`
does per machine: `main` publishes a PyPI library that one-repo-per-machine
plugins (`Rikyu-Agent`, `Hokusai-Agent`, `RCCS-CloudAgent`, `Fugaku-Agent`,
...) each depend on, while this branch absorbs the engine and every machine
into a single repo and a single server. Those per-machine repos are
untouched by this branch and continue to work.

Two consequences worth knowing before you change anything here:

- The `hpc_agent_core` package on this branch is **not** API-compatible
  with the one `main` publishes — every entry point takes a `facility`
  argument. Don't port a change between them by copying; re-derive it.
- Anything installed from this branch shadows the PyPI `hpc-agent-core` if
  both are in one environment. The plugin's `.mcp.json` uses
  `uv tool run --from git+...@unified-hub`, which is isolated, so this only
  matters if you hand-install both into the same venv.

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
                        Each facility's skill_notes/ holds its real,
                        hand-written skill content (see PORTING.md §7).
hpc_mcp/                The unified server entry points; importing this
                        package registers every facility.
plugins/hpc/            The Claude Code / Codex plugin: .mcp.json, skills/
                        (one real generated skill per facility+workflow,
                        plus the shared hpc-facilities discovery skill).
templates/skills/       Shared per-workflow skill templates (the mechanics
                        every facility has identically) — not per-facility.
scripts/                render_facility_tables.py (facility table codegen)
                        and render_skills.py (per-facility skill codegen).
tests/live_smoke.py     Live, facility-agnostic smoke test.
```

## Facilities onboarded so far

<!-- FACILITY_TABLE:START -->
| slug | facility | scheduler | description |
|---|---|---|---|
| `fugaku` | Fugaku | pjm | 158,976-node A64FX (Arm SVE) system, Fujitsu PJM scheduler, no GPUs; a project group is mandatory on every job. |
| `hokusai` | HOKUSAI BigWaterfall2 (HBW2) | slurm | CPU-first Slurm cluster (312-node MPC, large-memory, H100 GPU subsystems); a project account is mandatory on every job. |
| `rccs-cloud` | R-CCS Cloud | slurm | Heterogeneous ~20-partition cluster (CPU/NVIDIA/AMD/Intel GPU), Slurm with accounting. |
| `rikyu` | RIKYU (RIKEN AI4S / GB200) | slurm | RIKEN AI4S GB200 GPU cluster, Slurm with accounting, job-total GPU request. |
<!-- FACILITY_TABLE:END -->

## Tool coverage

See [`IRI_CHECKLIST.md`](IRI_CHECKLIST.md) — one checklist for the whole
repo (not per-facility), since every facility shares the same tool set.
