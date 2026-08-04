# hpc-agent-core

Shared runtime behind the RIKEN family of HPC agent plugins — Claude Code /
Codex plugins that let an agent submit and monitor jobs, manage files, and
search documentation on a supercomputer over SSH.

Used by:

- [Rikyu-Agent](https://github.com/RIKEN-RCCS/Rikyu-Agent) — Rikyu (GB200, Slurm)
- [Hokusai-Agent](https://github.com/RIKEN-RCCS/Hokusai-Agent) — HOKUSAI BigWaterfall2 (Slurm)
- [RCCS-CloudAgent](https://github.com/RIKEN-RCCS/RCCS-CloudAgent) — R-CCS Cloud (Slurm, heterogeneous hardware)
- and several other machine repos — see [`PORTING.md`](PORTING.md) for the full list and how they're built

## Building a new agent for a new cluster? Read `PORTING.md`.

**[`PORTING.md`](PORTING.md) is the complete porting guide** — what facts to
gather about a machine, how to wire up `config.py`/`compute.py`, what the MCP
tool surface should look like, and how to validate a port before calling it
done. If you're an agent (or a person) about to build a new machine repo on
top of this package, start there, not here.

## What's here

- `config.py` — settings resolution (env var > config file > default).
- `middleware.py` — the SSH execution layer; the only thing that talks to the
  cluster.
- `models.py` — PSI/J-style job models (`JobSpec`, `ResourceSpec`, `Job`, ...).
- `compute/slurm.py`, `compute/gridengine.py` — config-driven scheduler
  backends (script rendering, submit/status/cancel).
- `rag/` — the docs-search pipeline: BM25 keyword search, with optional
  vector embeddings, over a machine's bundled guide.
- `docs_server.py`, `doctor.py`, `serving.py`, `mcp_server.py` — the generic
  MCP plumbing. A machine repo mostly just supplies its own facts, guide, and
  tool surface on top of these.
- `client.py` — the public, notebook/script-facing MCP client (`connect()`,
  `HpcClient`, on-disk caching). For distilling exploratory agent work into a
  reproducible notebook that calls a machine's real tool surface directly,
  instead of a hand-copied SSH script. See the module docstring for the
  three caching modes (`live`/`lazy`/`replay`).
- `testing.py` — smoke-test-only plumbing (`Summary`, tiers, billing gate)
  for each machine repo's `tests/smoke.py`; re-exports `call`/`payload` from
  `client.py` rather than duplicating them.

## Tool surface: the IRI Facility API

Each machine's MCP tool surface is meant to mirror the [IRI Facility
API](https://api.alcf.anl.gov/openapi.json) (the DOE standard this family
targets — not vendored here; fetch it fresh when checking coverage). See
[`IRI_CHECKLIST.md`](IRI_CHECKLIST.md) for how that spec's capability groups
map onto what this package provides versus what a machine repo still has to
write itself. Coverage *verdicts* (implemented/deferred/why) are
machine-specific and live in each machine repo's own `IRI_CHECKLIST.md`, not
here.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
```

No machine repo depends on an unreleased local copy of this package, so
there isn't a meaningful smoke test to run standalone — validate changes
against a real machine repo (`tests/smoke.py`) before releasing.

## License

AGPL-3.0-or-later — see [LICENSE](LICENSE).
