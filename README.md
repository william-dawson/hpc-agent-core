# hpc-agent-core

This project provides the core for developing an agent that can interact
with an HPC cluster. From your own personal computer, the agent will be able
to connect to the cluster, compile code, organize data, and submit jobs.
This agent should work with any standard harness that supports
mcp servers (claude code, codex, opencode, cline, etc).

Used by:

- [Rikyu-Agent](https://github.com/RIKEN-RCCS/Rikyu-Agent) — Rikyu
- [Hokusai-Agent](https://github.com/RIKEN-RCCS/Hokusai-Agent) — HOKUSAI BigWaterfall2
- [RCCS-CloudAgent](https://github.com/RIKEN-RCCS/RCCS-CloudAgent) — R-CCS Cloud
- [Fugaku-Agent](https://github.com/RIKEN-RCCS/Fugaku-Agent) — Supercomputer Fugaku
- and several other machines across the globe.

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
