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

## This branch must never publish to PyPI

`main` of this same repository publishes the `hpc-agent-core` library on a
released tag. **This branch must not.** It is a divergent fork of that
engine, and publishing it would either create a confusing second package or
— far worse — ship an API-incompatible `hpc_agent_core` to everyone
depending on the real one.

Three things keep that true; leave all three alone:

- there is **no publish workflow on this branch** (`main` has one; this
  branch deliberately does not — don't copy it over);
- `.github/workflows/ci.yml` grants only `contents: write`. PyPI trusted
  publishing requires `id-token: write`, so no step in this workflow can
  authenticate to PyPI even if one were added;
- the package is named `hpc-agent-hub`, so it could not overwrite
  `hpc-agent-core` in any case.

`main`'s publish workflow triggers on `release: published` and is unaffected
by anything on this branch — pushing here cannot fire it.

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
### Live-tested facilities

These integrations have been exercised against their real scheduler.

| slug | facility | scheduler | description |
|---|---|---|---|
| `fugaku` | Fugaku | pjm | 158,976-node A64FX (Arm SVE) system, Fujitsu PJM scheduler, no GPUs; a project group is mandatory on every job. |
| `hokusai` | HOKUSAI BigWaterfall2 (HBW2) | slurm | CPU-first Slurm cluster (312-node MPC, large-memory, H100 GPU subsystems); a project account is mandatory on every job. |
| `miyabi` | Miyabi (JCAHPC) | pbs | JCAHPC CPU/GH200 system with PBS Professional, full-GPU and MIG queues; reached over a multiplexed SSH connection the user authenticates once with a one-time code. |
| `rccs-cloud` | R-CCS Cloud | slurm | Heterogeneous ~20-partition cluster (CPU/NVIDIA/AMD/Intel GPU), Slurm with accounting. |
| `rikyu` | RIKYU (RIKEN AI4S / GB200) | slurm | RIKEN AI4S GB200 GPU cluster, Slurm with accounting, job-total GPU request. |

### Awaiting live validation

These ports register and pass the offline test suite, but have not yet
completed an end-to-end check against the current live system.

| slug | facility | scheduler | description |
|---|---|---|---|
| `cell2026` | cell2026 (Shinobu Lab) | gridengine + slurm | Dual-scheduler GPU cluster: Grid Engine on helix/kinase with managed RTX A4000s and durable qacct, plus no-accounting Slurm on beta/serine with unmanaged RTX 4000 Ada/RTX 5090 GPUs. |
| `irene` | Irene (CEA TGCC) | bridge | CEA TGCC CPU-first system with AMD Rome, large-memory, and NVIDIA GPU partitions, accessed through the Bridge #MSUB/ccc_* scheduler interface. |
| `octopus` | Octopus (RIKEN R-CCS) | slurm | Four-node, dual-vendor GPU cluster: three NVIDIA H200 nodes and one AMD MI300X node, Slurm accounting, and vendor-specific container passthrough. |
| `tsubame` | TSUBAME4.0 (Science Tokyo) | gridengine | Science Tokyo's GPU-first H100 system, scheduled by Altair Grid Engine using fixed resource-type slices and TSUBAME group points. |
<!-- FACILITY_TABLE:END -->

## Outstanding code-review work

Resolve these findings before committing the current facility integrations:

- **P1 — CELL2026 cancellation must fail closed when scheduler lookup is
  uncertain.** `Cell2026Backend._is_not_found()` currently treats an
  `UNKNOWN` result without queue metadata as an authoritative miss, but the
  underlying Slurm and Grid Engine backends also return that shape when a
  command or connection fails. For an unregistered job ID, do not cancel on
  the scheduler that answered if the other lookup failed or was inconclusive.
  Require two authoritative lookup results or an explicit scheduler, and add
  conformance coverage for the failure/one-hit case.
- **P1 — constrain Miyabi PBS directive arguments.** Validate `queue_name`
  against the exact known queue set and restrict the PBS project group to its
  documented identifier syntax before rendering. Values such as
  `debug-c -l place=excl` currently pass the prefix check and inject an extra
  PBS option into the `#PBS -q` line. Cover malicious/invalid queue and account
  strings in the offline tests. Validate or safely render output paths with
  spaces as well.
- **P2 — make the CELL2026 doctor honor `CELL2026_GE_BIN`.** Runtime Grid
  Engine commands use the configured AGE binary prefix, while
  `check_scheduler()` probes only bare command names. A correctly configured
  installation must not fail doctor merely because AGE is outside `PATH`.
- **P2 — extract Miyabi's actual PBS working directory.** `qstat -f` exposes
  it inside `Variable_List` as `PBS_O_WORKDIR=...`; do not publish the complete
  comma-separated variable list as `meta_data.workdir`. Add parser and live
  smoke coverage so output discovery uses the real directory.
- **P2 — reject TSUBAME's `prior` subscription queue in trial mode.** No group
  means the constrained free trial, whereas `prior` is the subscription queue.
  Require an account/group when `queue_name="prior"` and test that combination.

After fixing these, rerun `tests/conformance.py`, `tests/notebook_client.py`,
both generated-output checks, `git diff --check`, and the wheel-data check.

## Tool coverage

See [`IRI_CHECKLIST.md`](IRI_CHECKLIST.md) — one checklist for the whole
repo (not per-facility), since every facility shares the same tool set.
