# Porting Guide: building a new machine plugin on hpc-agent-core

This guide is for an agent (or human) bootstrapping a new HPC MCP plugin —
a Claude Code / Codex plugin that lets an agent submit and monitor batch
jobs, manage files, and search documentation for a specific supercomputer.
It assumes **no other context**: you do not need to have seen any existing
machine repo to follow this. Read it in full before writing any code.

Copy this file verbatim into your new repo's root as `PORTING.md`. Do not
edit `hpc-agent-core` itself — you have no write access to it (see §0).

## 0. The mental model

`hpc-agent-core` (a PyPI package: `pip install hpc-agent-core`) is the
shared, generic runtime: SSH execution, PSI/J-style job data models, Slurm
and Grid Engine scheduler backends, a documentation search pipeline, health
checks, and MCP serving glue. **Your new repo is a thin "skin"** around it:
your own machine's facts (a config JSON, a hand-written guide), a small
amount of Python that wires those facts into `hpc-agent-core`'s generic
pieces, skills, and packaging.

Two hard rules:

1. **You cannot modify `hpc-agent-core`.** Every customization must be
   reachable from your own repo: passing config/constructor arguments,
   subclassing a class it exposes, or — if genuinely nothing fits — simply
   not using a given `hpc-agent-core` module and writing your own equivalent
   in your repo. If you think you need to edit `hpc-agent-core` itself,
   you've misunderstood something; re-read the "Extending this" note in the
   relevant module's docstring.
2. **Prefer clarity over cleverness.** A little redundant, machine-specific
   code in your own repo is fine and expected — you are one of several
   machines built this way, and a small duplicated block that's easy to
   read beats a clever abstraction that isn't. Don't force every difference
   through a generic mechanism if a straightforward override reads better.

## 1. Learn the target machine before writing anything

Answer these from the machine's real, official documentation (see §3 for
how to turn that into your guide) and, if you have SSH access already, by
actually running commands on the login node — a "zero-code smoke path"
(`ssh <host> sinfo`, `sacct --version` or a real `sacct` call, `module
avail`, a real GPU allocation test) is a cheap way to confirm your
assumptions *before* writing a line of port code, not after.

- **Scheduler**: Slurm or Grid Engine? (Only these two have a ready-made
  backend in `hpc-agent-core` today — see §6. Something else needs its own
  `SchedulerBackend` subclass in your repo, reusing `compute.base`'s helpers.)
- **Accounting** (Slurm only): does `sacct`/`sacctmgr` actually work, or is
  accounting disabled (`accounting_storage/none`)? Test with a real `sacct`
  call, not just `sacct --version` (the binary can exist and still be
  configured off).
- **GPU request dialect** (Slurm only) — two *independent* questions, both
  must be answered separately:
  - Which flag: `--gpus=N` (a job-total count) or `--gres=gpu:N` (untyped)?
  - Does Slurm derive node count from the GPU count (so `--nodes` can be
    omitted), or must `--nodes` always be set explicitly? Do not assume
    these two questions have a shared answer — a real machine in this
    family uses the `--gpus=N` flag but always sets `--nodes` explicitly,
    which is *not* the combination you'd get by picking one "style".
  - Single GPU vendor, or more than one (needing a different container
    flag, e.g. `--nv` vs `--rocm`, chosen by partition)?
  - Any partitions that need **no** GPU flag at all (e.g. a unified
    CPU+GPU superchip where the GPU is simply always present)?
- **Grid Engine specifics** (if applicable): is there one real queue with
  node selection done via a host pin (`-l hostname=<host>`) because naming
  a host directly as a queue is rejected? What parallel environment(s)
  (`-pe`) exist? Does `$SGE_HGR_gpu` (or equivalent) need translating to
  `CUDA_VISIBLE_DEVICES` yourself, or is GPU isolation automatic?
- **Storage**: tiers (home/group/scratch), paths, quotas, which are
  node-local vs shared, auto-purge policies.
- **Software environment**: Lmod/environment-modules? Spack? Containers
  only? Conda/venv only? This shapes your guide and skills, not your code.
- **Login mechanics**: SSH hostname, how a new key gets registered (a web
  portal? emailing an admin? self-service?).
- **Account/project**: is `--account` mandatory, optional with a
  machine-side default, or unused entirely?
- **Connection quirks** (rare): does this machine need a different
  `remotemanager.Computer` option than the shared default (login-shell
  template, bash submitter, `python3`)? Check
  `hpc_agent_core.config.COMPUTER_OPTION_NAMES` for the full set (shell,
  timeout, keyfile, landing_dir, transport, ...) if so.

## 2. Write your own guide — never point at a live external site

`hpc-agent-core`'s documentation-search pipeline (`rag/ingest.py`) only ever
chunks a **local, hand-written guide file** — it will never git-clone or
fetch a remote docs site for you, and you shouldn't build a mechanism that
does either. A past port that pointed its ingest step at "always re-fetch
the live official site" broke silently when that site moved domains and
was restructured, with nothing to catch it.

Read the machine's real official documentation, then **write your own
guide, in your own words** — a plain-language orientation for someone
driving the machine through the agent, not a paraphrase or copy of the
vendor manual. Deliberately omit:
- generic HPC/Linux background (what a batch scheduler is, what SSH is),
- anything the agent can query live instead of memorizing (`sinfo`,
  `module avail`, current queue occupancy, your billing balance).

Keep it to the stable facts that shape how a job gets described: hardware
shape, the scheduler dialect from §1, storage tiers and quotas, the module/
software story, common failure modes and their fixes. Save it as
`data/<machine>_guide.md` in your package (see §4's layout).

If the official site later changes, re-sync by re-reading it and editing
your guide by hand — a deliberate, occasional, human-reviewed step — not by
building an automatic re-fetch.

## 3. Decide whether to cite a URL in search results

If the official docs site is genuinely stable and worth pointing users at,
your guide's search results can cite it (`docs_cite_url` in `configure()`,
see §5). If it's unreliable, moved recently, or you're not confident it'll
still be there next month, **leave `docs_cite_url` blank** (the default) —
search results simply won't mention a URL, and nothing in your plugin
should invent one to send a user to.

## 4. Repository layout

```
your-machine-agent/                 # top-level repo
  .claude-plugin/                    # Claude Code marketplace manifest
  .agents/plugins/                   # Codex marketplace manifest
  plugins/<machine>/
    .claude-plugin/                    # Claude Code plugin manifest
    .codex-plugin/                     # Codex plugin manifest
    .mcp.json                          # launches your two MCP servers (see §7)
    skills/
      <machine>-configuring/SKILL.md
      <machine>-submitting-jobs/SKILL.md
      <machine>-monitoring-jobs/SKILL.md
      <machine>-reference/SKILL.md
      <machine>-demo/SKILL.md
  server/
    pyproject.toml                     # depends on hpc-agent-core, pinned (see §9)
    <machine>_mcp/
      __init__.py                        # empty
      config.py                          # §5
      compute.py                         # §6 — constructs your SchedulerBackend
      hpc_server.py                      # §7 — the IRI-grouped tool surface
      docs_server.py                     # §7 — thin wrapper over hpc_agent_core.docs_server
      doctor.py                          # §7 — thin wrapper over hpc_agent_core.doctor
      serving.py or entry points in pyproject.toml
      data/
        <machine>_config.json              # static facts: partitions, storage, modules
        <machine>_guide.md                  # §2
        docs_index/                          # generated — see §8
    tests/
      smoke.py                             # §9
  README.md                            # user-facing overview
  AGENTS.md                            # design rules + cluster facts + repo map
  IRI_CHECKLIST.md                     # per-endpoint coverage decisions
```

## 5. Wire up `config.py`

Your `config.py` registers your machine's settings with `hpc-agent-core`
once, at import time, before any other `hpc_agent_core` module is used:

```python
# server/<machine>_mcp/config.py
from hpc_agent_core import config as _core

_core.configure(
    env_prefix="MYMACHINE",             # -> MYMACHINE_HOST, MYMACHINE_CONFIG, MYMACHINE_EMBED_API_KEY
    default_host="mymachine",            # ssh.host fallback: an alias in ~/.ssh/config, or user@hostname
    package="mymachine_mcp",             # must match this package's actual name
    embed_base_url="http://llm.ai.r-ccs.riken.jp:11434/v1",  # shared RIKEN endpoint, or your own
    embed_model="bge-m3:567m",
    docs_cite_url="",                    # leave blank unless you decided otherwise in §3
    # computer_defaults={"shell": "zsh"},   # only if §1's "connection quirks" applies
)

# Re-export what the rest of your package expects to import from here —
# these are just the registered functions/values, kept for readability:
ssh_host = _core.ssh_host
embed_api_key = _core.embed_api_key
CONFIG_PATH = _core.config_path()
DATA_DIR = _core.data_dir()


import json
from functools import lru_cache


@lru_cache(maxsize=1)
def load_cluster_config() -> dict:
    """Your machine's static facts (partitions, modules, storage) —
    bundled package data, not the user's config file."""
    with open(DATA_DIR / "mymachine_config.json") as f:
        return json.load(f)
```

Settings resolve environment variable > the user's `~/.<env_prefix.lower()>
/config.json` > the default you gave `configure()`. You never need to
implement this resolution yourself.

## 6. Wire up `compute.py`

Construct one of `hpc-agent-core`'s two ready-made backends with the
answers from §1, or subclass `SchedulerBackend` yourself if neither fits.
**Match the nearest real precedent below rather than inventing your own
combination from scratch** — every combination shown here is verified
against a real machine, not guessed:

| Machine shape | Backend construction |
|---|---|
| Slurm, accounting on, job-total `--gpus=N`, single GPU vendor, Slurm derives node count | `SlurmBackend(has_accounting=True, gpu_request_style="gpus_total")` |
| Slurm, accounting on, untyped `--gres=gpu:N`, dual GPU vendor, `--nodes` always explicit | `SlurmBackend(has_accounting=True, gpu_request_style="gres", gpu_vendor_map={"h200": "--nv", "mi300x": "--rocm"})` |
| Slurm, accounting on, job-total `--gpus=N` **but** `--nodes` always explicit, some partitions need no GPU flag at all | `SlurmBackend(has_accounting=True, gpu_request_style="gpus_total", nodes_always_explicit=True, no_gpu_flag_prefixes=frozenset({"qc-gh200", "ng-dgx-m"}))` |
| Slurm, accounting **off** (a small/lab-scale machine), untyped `--gres=gpu:N` | `SlurmBackend(has_accounting=False, gpu_request_style="gres")` — note: this path degrades `get_recent_statuses` to "current live queue only" (no multi-day history is possible without accounting) and is less battle-tested than the accounting-on paths; verify it against a real submitted job before trusting it, not just `doctor` passing. |
| Grid Engine, one real queue, some queue-like names are actually host pins | `GridEngineBackend(default_queue="all.q", host_pins={"nodeA", "nodeB"}, queue_aliases={"gpu"})` |

Example:

```python
# server/<machine>_mcp/compute.py
from hpc_agent_core.compute.slurm import SlurmBackend

backend = SlurmBackend(
    has_accounting=True,
    gpu_request_style="gpus_total",
    jobs_dir="agent/jobs",   # the default; only override if you have a reason to
)

# hpc_server.py calls these:
submit = backend.submit
get_statuses = backend.get_statuses
get_recent_statuses = backend.get_recent_statuses
cancel = backend.cancel
render_script = backend.render_script
```

If your dialect genuinely doesn't fit any row above, don't force it —
subclass `SchedulerBackend` (`hpc_agent_core.compute.base`) directly in
your own repo, reusing `duration_to_hms`, `to_epoch`, `parse_exit_code`,
and `render_body` from that module. This is a normal, expected outcome for
an unusual machine, not a sign something is missing from core.

## 7. Wire up the MCP servers

**`docs_server.py`** and **`doctor.py`** are thin — the generic work already
lives in `hpc-agent-core`:

```python
# server/<machine>_mcp/docs_server.py
from mcp.server.fastmcp import FastMCP
from hpc_agent_core.docs_server import build
from hpc_agent_core.serving import serve
from mymachine_mcp import config  # noqa: F401 -- registers via configure()

mcp = FastMCP("mymachine-docs")
build(mcp)

def main():
    serve(mcp)

if __name__ == "__main__":
    main()
```

```python
# server/<machine>_mcp/doctor.py
import sys
from mymachine_mcp import config  # noqa: F401 -- registers via configure()
from hpc_agent_core.doctor import main as _core_main

def main() -> int:
    return _core_main(scheduler_probe="sinfo --version", scheduler_name="slurm")
    # Grid Engine machines: scheduler_probe="qstat -help", scheduler_name="GE"
    # (or whatever your qstat actually prints — check it live first)

if __name__ == "__main__":
    sys.exit(main())
```

**`hpc_server.py`** is the one piece `hpc-agent-core` doesn't provide a
generic version of yet — you write the actual MCP tool surface, grouped
around the IRI Facility API (submit/status/cancel, filesystem operations,
facility/resource info). It's mostly a thin pass-through to `compute.py`
and `hpc_agent_core.middleware`:

```python
# server/<machine>_mcp/hpc_server.py (excerpt — extend with the full
# fs_* set: fs_ls, fs_stat, fs_view, fs_head, fs_tail, fs_mkdir, fs_upload,
# fs_download, fs_checksum, fs_cp, fs_mv, fs_chmod, fs_chown, fs_symlink,
# fs_compress, fs_extract — each a one-line call into hpc_agent_core.middleware)
from mcp.server.fastmcp import FastMCP
from hpc_agent_core.middleware import run_command, quote_path
from hpc_agent_core.models import Job, JobSpec
from hpc_agent_core.serving import serve
from mymachine_mcp import compute, config

mcp = FastMCP("mymachine-hpc")


@mcp.tool()
def get_facility() -> dict:
    """Static facility facts: partitions, modules, storage. (IRI: GET /facility)"""
    return config.load_cluster_config()


@mcp.tool()
def submit_job(spec: JobSpec) -> dict:
    """Submit a job. Show the user the spec before submitting unless they
    asked to just run it (mirrors run_command_on_cluster's rule below)."""
    return compute.submit(spec)


@mcp.tool()
def get_job_status(job_id: str) -> Job:
    jobs = compute.get_statuses([job_id])
    if not jobs:
        raise ValueError(f"Job {job_id} not found")
    return jobs[0]


@mcp.tool()
def get_job_statuses(job_ids: list[str]) -> list[Job]:
    return compute.get_statuses(job_ids) if job_ids else compute.get_recent_statuses()


@mcp.tool()
def cancel_job(job_id: str) -> Job | str:
    return compute.cancel(job_id)


@mcp.tool()
def run_command_on_cluster(command: str) -> str:
    """Run an arbitrary shell command on the login node (extension — not an
    IRI endpoint). Before calling this, show the user the exact command (or
    script) and a one-line explanation of what it does, then call it —
    skip the preview only if the user explicitly asked to just run
    something. Do not run heavy computation on the login node — submit a
    job instead."""
    return run_command(command)


def main():
    serve(mcp)

if __name__ == "__main__":
    main()
```

Group the rest of your tools (`get_resources`, `get_resource`,
`get_projects`/`get_project` if the machine has real accounting to query,
`update_job`, every `fs_*` operation) the same way — each is a short
function calling into `compute.py` or `hpc_agent_core.middleware`. Mark any
tool with no IRI counterpart (like `run_command_on_cluster` above) as an
explicit extension in your `IRI_CHECKLIST.md`.

## 8. Build the docs index

```bash
cd server
python -c "from mymachine_mcp import config"   # sanity: configure() runs without error
python -m hpc_agent_core.rag.ingest             # writes data/docs_index/chunks.json (+ embeddings.npy if a key is configured)
```

Commit `chunks.json` (and `embeddings.npy` if produced) as package data.
Make sure your `pyproject.toml`'s `package-data` includes your guide's
file extension (e.g. `"data/*.md"`) — a past port shipped a guide that
silently never installed because this glob was missing; `doctor` (§9)
would have caught it.

## 9. Validate before calling the port done

```bash
cd server
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m mymachine_mcp.doctor        # config, ssh+scheduler, guide bundled, docs index, embedding
.venv/bin/python tests/smoke.py                 # read-only MCP stdio test
.venv/bin/python tests/smoke.py --job           # + submits a real tiny job
```

**A passing `doctor` and passing read-only smoke test are not proof the
port works.** Real precedent: a machine that looked fine on every check
still had its job-status logic completely broken, because the check that
would have caught it (an actual submitted job) was the one nobody ran.
Submit at least one real job — ideally one requesting a GPU if the machine
has any — and confirm you can see it queue, run, and complete through the
agent before considering this port finished.

Pin `hpc-agent-core` in your `server/pyproject.toml`:

```toml
dependencies = [
    "hpc-agent-core>=0.2,<0.3",
    "mcp",
]
```

(Check the current released version and pin a compatible range — don't
leave it unpinned; a future core release could otherwise change what your
users install with no warning.)

## 10. Invariants that must hold, no exceptions

- **The MCP server must never fail to start.** Missing or malformed config
  is a *tool-call-time* error with a clear message (e.g. "run the
  configuring skill"), never a startup crash. Nothing above module scope in
  your `config.py`/`compute.py`/`hpc_server.py` should touch the network or
  read the config file eagerly — `hpc_agent_core.middleware.get_frontend()`
  is already lazy; don't defeat that by, say, calling it at import time.
- **Bias agent-created files into one visible directory.** Job working
  directories, staged uploads, and scratch/demo files should default under
  `~/agent/` (the default `jobs_dir="agent/jobs"` already does this for job
  scripts) — not scattered loose in `$HOME`, and not hidden in a dotfile
  directory either. This is a bias, not a restriction: honor any explicit
  path the user gives.
- **Show before you run.** Before `submit_job` or `run_command_on_cluster`
  actually executes something, show the user what's about to run (the
  JobSpec, or the exact command/script) and a brief explanation, unless
  they've explicitly said to just run it.
- **Never invent a documentation URL.** If `docs_cite_url` is blank (see
  §3), search results carry no URL — don't add one back in in a skill or
  tool description.

## 11. Write your skills, README, AGENTS.md, IRI_CHECKLIST.md

- **Skills** (`<machine>-configuring`, `-submitting-jobs`, `-monitoring-jobs`,
  `-reference`, `-demo`): each documents one user-facing workflow in plain
  language, referencing the tools from §7 and the facts from your guide.
  Machine-prefix the skill names so multiple plugins can be installed at
  once without collisions.
- **README.md**: user-facing — what the machine is, how to configure
  (`~/.<machine>/config.json`), how to install the plugin, how to verify
  (`doctor`).
- **AGENTS.md**: agent-facing — the design rules from this guide
  (no-write-access to core, clarity over cleverness, the §10 invariants),
  the cluster facts from §1, and a repository map.
- **IRI_CHECKLIST.md**: which IRI Facility API endpoints you implemented,
  deferred, or extended beyond the spec, and why — this is genuinely
  machine-specific (an endpoint sensible on one machine may not apply to
  another) and does not move into `hpc-agent-core`.
