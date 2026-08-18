# hpc-agent-hub

This project lets an agent work on *every* HPC cluster you have access to,
through one plugin and one server. From your own personal computer, the
agent can connect to any of them, compile code, organize data, and submit
jobs. It should work with any standard harness that supports mcp servers
(claude code, codex, opencode, cline, etc).

https://github.com/user-attachments/assets/770e1f11-01c7-48f3-8c89-70efc3722e95

This is the unified form of [`hpc-agent-core`](https://github.com/william-dawson/hpc-agent-core).
Instead of one repository and one plugin per machine, every cluster lives
here as a `facilities/<name>/` directory, and every tool takes the machine
name as its first argument — `submit_job(facility="rikyu", ...)`,
`search_docs(facility="fugaku", ...)`. The agent asks `get_facilities()`
when it doesn't already know which machine you mean.

Clusters currently onboarded:

<!-- FACILITY_TABLE:START -->
| slug | facility | scheduler | description |
|---|---|---|---|
| `fugaku` | Fugaku | pjm | 158,976-node A64FX (Arm SVE) system, Fujitsu PJM scheduler, no GPUs; a project group is mandatory on every job. |
| `hokusai` | HOKUSAI BigWaterfall2 (HBW2) | slurm | CPU-first Slurm cluster (312-node MPC, large-memory, H100 GPU subsystems); a project account is mandatory on every job. |
| `rccs-cloud` | R-CCS Cloud | slurm | Heterogeneous ~20-partition cluster (CPU/NVIDIA/AMD/Intel GPU), Slurm with accounting. |
| `rikyu` | RIKYU (RIKEN AI4S / GB200) | slurm | RIKEN AI4S GB200 GPU cluster, Slurm with accounting, job-total GPU request. |
<!-- FACILITY_TABLE:END -->

## Install

Clone this repository, then tell your coding agent:

> Install the skill files and mcp servers of this repository.

That is the whole installation. The agent will register the two mcp servers
(`hpc-mcp` and `hpc-docs-mcp`) with whatever harness you are running, and
copy the skills into wherever that harness loads them from.

## Configure

Each cluster has its own settings file at `~/.hpc-agent/<name>.json` — one
file per machine, all in one directory. The minimum is an ssh host:

```json
{
  "ssh": {"host": "rikyu"}
}
```

- `ssh.host` is a `~/.ssh/config` alias, a `user@hostname`, or
  `"localhost"` if the agent is running directly on that cluster's own
  front-end node (no ssh at all). `RIKYU_HOST` overrides the file.
- Some machines need more. Fugaku requires a project group on every job,
  HOKUSAI requires a project account. **You don't have to look any of this
  up**: any tool call that can't reach a cluster replies with that
  machine's own setup instructions, including the exact json to write and
  where to get an ssh key registered.
- For documentation search, add `"embedding": {"api_key": "..."}`. Without
  a key — or off the RIKEN network — docs search falls back to keyword
  matching over the same content, so it still works.

You can also just ask the agent to do it: every cluster has a
`<name>-configuring` skill that walks through this and writes the file for
you.

Then check everything is reachable. The simplest way is to ask the agent
to run the doctor, but you can also run it yourself without installing
anything:

```bash
uv tool run --from git+https://github.com/william-dawson/hpc-agent-core.git@unified-hub hpc-doctor
```

Every line should read `✓`, except possibly the embedding endpoint — that
one falls back to keyword search and is not blocking. Add a cluster name to
check just that one.

## Adding a cluster you have access to?

This project is an exercise in Specification Driven Development. As we
know, clusters are not standardized. Each one offers a unique combination
of hardware and software. Interactions with the cluster are also not
standardized. For example, two clusters may expose slurm as the job
scheduler, yet the way the queues are set up, the required arguments, the
complementary commands for things like budgeting, are all unique. And some
machines are not slurm at all — Fugaku runs Fujitsu's PJM, with a
different command for every operation.

AI coding provides an alternative approach. Our goal is a comprehensive
**specification** for cluster interactions, such that one can use vibe
coding to automatically generate support for a new cluster. That
specification is [`PORTING.md`](PORTING.md).

Imagine you want to add a machine. You should follow these steps:
* Clone this repository
* Download the documentation related to your cluster
* Start up a coding agent and tell it "given the documentation about
machine X in folder Y and the porting guide `PORTING.md`, add X to this
repository"

The coding agent will make all the design decisions and implement all the
cluster specific code. It adds exactly one `facilities/<name>/` directory:
the machine's facts, a guide written in its own words, the code that
teaches the shared scheduler backend that machine's dialect, and the skill
notes that turn hard-won operational knowledge — which mpi launcher
actually works, which queue silently rejects a job an hour later — into
something the agent knows before it makes the mistake.

Nothing else in the repository needs to change, which is what makes it
possible for several people to add different machines at the same time.
When you are happy with it, open a pull request.

### Tool surface: the IRI Facility API

The mcp tool surface mirrors the [IRI Facility
API](https://api.alcf.anl.gov/openapi.json) (the DOE standard this family
targets — not vendored here; fetch it fresh when checking coverage).
[`IRI_CHECKLIST.md`](IRI_CHECKLIST.md) records what is implemented, what
deviates and why, and what is deliberately left out. Because there is one
tool surface shared by every cluster, those verdicts are real and
repo-wide rather than a per-machine template.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e .

.venv/bin/python tests/conformance.py             # offline, every cluster
.venv/bin/python tests/live_smoke.py              # read-only, needs ssh
.venv/bin/python tests/live_smoke.py --job rikyu  # + submits a real job
```

Some files are generated from each cluster's `facility.json` and
`skill_notes/` — the cluster table above, and one skill file per cluster
per workflow. **You don't have to run anything for this**: CI regenerates
them on your pull request and commits the result back to your branch. Run
them yourself if you'd rather read the output first:

```bash
python scripts/render_facility_tables.py   # after editing facility.json
python scripts/render_skills.py            # after editing skill_notes/
```

## License

AGPL-3.0-or-later — see [LICENSE](LICENSE).
