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
  register its SSH default, embedding endpoint, and docs source.
- `middleware.py` — the SSH execution layer (base64 payloads, login shell,
  clean error surfacing). Never touches config or the network above module
  scope — the MCP server must never fail to start just because config is
  missing (see PORTING.md's invariant in every machine repo).
- `models.py` — PSI/J-style `JobSpec`/`ResourceSpec`/`JobAttributes`/`Job`/
  `JobState`, with no per-machine defaults baked in.
- `compute/base.py` — the `SchedulerBackend` ABC and scheduler-neutral
  script-body rendering (env vars, container wrapping, launcher prefix).
- `compute/slurm.py` — a Slurm backend matching the Rikyu/HOKUSAI dialect
  (accounting on, job-total `--gpus=N`). **Not yet** the fully config-driven
  backend the plan describes (accounting on/off, `--gres` vs `--gpus`,
  GPU-vendor container flags) — that generalization is the next step.
- `rag/` — embedding client, BM25 + vector docs index, and an ingest
  pipeline that only ever chunks a bundled local guide (never clones a
  remote docs site — see the module docstring for why).
- `docs_server.py`, `doctor.py`, `serving.py` — generic FastMCP docs server,
  health checks, and CLI entry point.

## What's deliberately not here yet

- `hpc_server.py` (the IRI-grouped Slurm/filesystem tool surface) and a
  `machine_profile.py` that turns `<machine>_config.json` into config-driven
  scheduler dispatch — these need the `has_accounting` / `gpu_request_style`
  / `gpu_vendor_map` schema design worked out first.
- `compute/gridengine.py` — promoting shinobulab's Grid Engine backend.
- Repointing any machine repo at this package as a dependency.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
```

No machine repo depends on this yet, so there isn't a meaningful smoke test
to run standalone — validate changes against a machine repo once one is
repointed here.
