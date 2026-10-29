# hpc-agent-core

This project provides the core for developing an agent that can interact
with an HPC cluster. From your own personal computer, the agent will be able
to connect to the cluster, compile code, organize data, and submit jobs.
This agent should work with any standard harness that supports
mcp servers (claude code, codex, opencode, cline, etc).

https://github.com/user-attachments/assets/770e1f11-01c7-48f3-8c89-70efc3722e95

Used by:

- [Rikyu-Agent](https://github.com/RIKEN-RCCS/Rikyu-Agent) — Rikyu
- [Hokusai-Agent](https://github.com/RIKEN-RCCS/Hokusai-Agent) — HOKUSAI BigWaterfall2
- [RCCS-CloudAgent](https://github.com/RIKEN-RCCS/RCCS-CloudAgent) — R-CCS Cloud
- [Fugaku-Agent](https://github.com/RIKEN-RCCS/Fugaku-Agent) — Supercomputer Fugaku
- and several other machines across the globe.

## One server for every machine: HPC Rookery

The repositories above are one-per-machine: each is its own plugin, its own
MCP server, its own installation, all built on this package. That keeps each
machine's quirks in its own place, but an agent working across several of them
juggles several plugins and several tool namespaces at once.

[**HPC Rookery**](https://github.com/william-dawson/hpc-rookery) is the same
idea folded into one repository: one plugin, one MCP server, and every machine
reachable through a single tool surface, with an explicit `facility` slug on
every call. Nine machines live there today (Fugaku, HOKUSAI BigWaterfall2,
Miyabi, R-CCS Cloud and Rikyu validated against their real schedulers;
cell2026, Irene, Octopus and TSUBAME4.0 ported and passing the offline suite).
Porting a machine there means opening a pull request that adds one
`facilities/<slug>/` directory rather than bootstrapping a new repository.

Rookery grew out of this project and still carries a copy of this package, but
it is a **divergent fork, not a consumer**: every entry point there takes a
facility argument, so the two are not API-compatible and a change in one has to
be re-derived in the other rather than copied. Neither replaces the other —
pick the single-machine model here if you want one cluster in its own
self-contained repository, and Rookery if you want several clusters behind one
server.

## Building a new agent for a new cluster?

This project is an exercise in Specification Driven Development. As we know,
clusters are not standardized. Each one offers a unique combination of hardware
and software. Interactions with the cluster are also not standardized.
For example, two clusters may expose slurm as the job scheduler, yet the
way the queues are set up, the required arguments, the complementary commands
for things like budgeting, are all unique. In the age of traditional software
programming, the idea of exposing (and maintaining) a unified interface to 
clusters all over the world was extremely challenging. 

AI coding provides an alternative approach. Our goal in this project is to
develop a comprehensive **specification** for cluster interactions, such that
one can use vibe coding to automatically generate a new cluster agent.
That specification is in` hpc_agent_core/PORTING.md`. 

Imagine you want to port this agent approach to a new machine. You should 
follow these steps:
* Clone this repository
* Download the documentation related to your cluster
* Start up a coding agent and tell it "given the documentation about machine
X in in folder Y and the porting guide in folder `hpc_agent_core`, implement
a new agent for X"
The coding agent will make all the design decisions and implement all the
cluster specific code.

If you would rather add your machine to the unified server than stand up a
repository for it, HPC Rookery takes the same approach with its own porting
guide: point your agent at that repository's `PORTING.md` instead, and it adds
a single `facilities/<slug>/` directory.

### Tool surface: the IRI Facility API

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
