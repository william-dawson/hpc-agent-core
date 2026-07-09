# hpc-agent-core

Shared runtime for the HPC MCP agent family — the Claude Code / Codex
plugins that let an agent submit and monitor Slurm/Grid Engine jobs, manage
files, and search documentation on a supercomputer (Rikyu, HOKUSAI
BigWaterfall2, Octopus, R-CCS Cloud, TSUBAME4, and others).

Each of those plugins used to be a full copy-pasted fork of the same
template. This package extracts the parts that were already generic in
practice — SSH middleware, PSI/J-style job models, scheduler backends, the
docs RAG pipeline, health checks (`doctor`), and the MCP serving glue — so a
machine repo becomes a thin "skin": its own `<machine>_config.json`, a
hand-written guide, skills, and packaging, depending on this package for
everything else.

See [`PLAN.md`](../PLAN.md) in the `merge_computers` workspace for the full
design rationale and migration plan. This repo implements that plan's Phase
1 (extract the generic modules) — it is **not yet** a drop-in replacement
for any machine repo's server code; nothing currently depends on it yet.

## What's here (Phase 1)

- `config.py` — generic env/file/default settings resolution. A machine's
  own `config.py` calls `hpc_agent_core.config.configure(...)` once to
  register its SSH default, embedding endpoint, docs source, and (optionally)
  any `remotemanager.Computer` option it needs to differ from the shared
  defaults (`computer_defaults={...}` — see `COMPUTER_OPTION_NAMES` for the
  full supported set: shell, timeout, keyfile, landing_dir, transport, ...).
  A machine sets these once in its own repo; the end user never has to.
- `middleware.py` — the SSH execution layer (base64 payloads, login shell,
  clean error surfacing). Never touches config or the network above module
  scope — the MCP server must never fail to start just because config is
  missing (see PORTING.md's invariant in every machine repo).
- `models.py` — PSI/J-style `JobSpec`/`ResourceSpec`/`JobAttributes`/`Job`/
  `JobState`, with no per-machine defaults baked in. Also `Scheduler` (an
  optional hint field for a machine that composes more than one
  `SchedulerBackend`) and `map_ge_state` for Grid Engine.
- `compute/base.py` — the `SchedulerBackend` ABC and scheduler-neutral
  script-body rendering (env vars, container wrapping, launcher prefix).
- `compute/slurm.py` — a config-driven Slurm backend: `has_accounting`
  (sacct vs. squeue+scontrol), `gpu_request_style` (`"gpus_total"` vs.
  `"gres"`) and the *independent* `nodes_always_explicit` (whether Slurm
  derives node count from the GPU count, or `--nodes` is always emitted —
  these two don't always move together, see `PHASE4_AUDIT.md` §1.1),
  `no_gpu_flag_prefixes` (partitions needing no GPU flag at all, e.g. a
  unified CPU+GPU superchip), and `gpu_vendor_map` (container GPU flag by
  partition prefix). Verified against Rikyu's, Octopus's, *and*
  RCCS-Cloud's actual rendered scripts. The `has_accounting=False` path
  (Banyan/Dgx1-style) is implemented from the porting knowledge-transfer
  reports and passes a mocked end-to-end test, but **is not yet verified
  against a real no-accounting cluster** — see the module docstring before
  trusting it on a live machine.
- `compute/gridengine.py` — a Grid Engine backend (qsub/qstat/qacct/qdel),
  promoted from shinobulab-cell-cluster-mcp (the only GE machine so far) and
  verified to reproduce its exact rendered scripts. `host_pins`/
  `queue_aliases`/`default_queue` generalize its host-pinning quirk into
  config, since it's a plausible shape for other small GE clusters, not a
  one-off. Live-tested as part of shinobulab-cell-cluster-mcp; **not yet
  re-verified from this promoted copy against a real cluster**.
- `rag/` — embedding client, BM25 + vector docs index, and an ingest
  pipeline that only ever chunks a bundled local guide (never clones a
  remote docs site — see the module docstring for why).
- `docs_server.py`, `doctor.py`, `serving.py` — generic FastMCP docs server,
  health checks, and CLI entry point.

## What's deliberately not here yet

- `hpc_server.py` (the IRI-grouped Slurm/filesystem tool surface) and a
  `machine_profile.py` that turns `<machine>_config.json` into config-driven
  scheduler dispatch — a machine currently wires a `SlurmBackend`/
  `GridEngineBackend` by hand in its own `compute.py`; that's a deliberate
  choice (PLAN.md §2a/§2b), not a placeholder for a missing feature.
- Repointing any machine repo at this package as a dependency.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
```

No machine repo depends on this yet, so there isn't a meaningful smoke test
to run standalone — validate changes against a machine repo once one is
repointed here.
