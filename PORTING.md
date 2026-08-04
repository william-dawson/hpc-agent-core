# Porting Guide: building a new machine plugin on hpc-agent-core

This guide is for an agent (or human) bootstrapping a new HPC MCP plugin —
a Claude Code / Codex plugin that lets an agent submit and monitor batch
jobs, manage files, and search documentation for a specific supercomputer.
It assumes **no other context**: you do not need to have seen any existing
machine repo to follow this. Read it in full before writing any code.

**Do not create a `PORTING.md` file in your new repo at all — not even a
stub or a link file.** Earlier versions of this guide said to copy it
verbatim, then later said to leave a one-line stub file behind instead;
both were mistakes for the same reason: any file in your repo named
`PORTING.md` is a second place this guide can appear to live, and it drifts
(a hardcoded version number in an earlier revision of this file went stale
within the same day it was written — a copy or a stub is that same failure
mode at a smaller scale, just less bad). The canonical copy lives at exactly
one URL, permanently:
<https://github.com/william-dawson/hpc-agent-core/blob/main/PORTING.md>.
Reference that URL directly from **`AGENTS.md`** (required — see §11) and
optionally once from `README.md`; do not put it in a file of its own. Keep
only what's genuinely specific to your machine in your own repo (cluster
facts, decisions made under uncertainty, a repo map). Do not edit
`hpc-agent-core` itself — you have no write access to it (see §0).

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
      # (no serving.py needed — each server's main() is exposed as a
      #  console-script entry point in pyproject.toml; see §7's last part)
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

Settings resolve environment variable > the user's config file > the
default you gave `configure()`. The config file itself lives at
`~/.hpc-agent/<env_prefix.lower()>.json` (one common directory shared by
every machine's plugin, one file each) — `hpc-agent-core` also still reads
the older per-machine `~/.<env_prefix.lower()>/config.json` location if
that's the only one that exists, so nobody who already configured a plugin
before this convention existed has to redo anything. You never need to
implement this resolution yourself, and your skills/README should point
users at the common `~/.hpc-agent/<slug>.json` location, not a per-machine
dotdir.

`ssh.host` also accepts `"localhost"` (or a `127.*` address) for running
directly on the cluster's own front-end/login node with no SSH at all —
remotemanager's `URL.is_local` already routes that case to a bare local
shell, and `get_frontend()` is deliberately uncached specifically so a
config file edit (e.g. switching to/from `"localhost"`) takes effect on
the next tool call, not just after a full server restart. No middleware
change is needed in your own repo for this to work. Your `<machine>-configuring`
skill should offer `"localhost"` as an SSH-setup option and skip the usual
`ssh -o BatchMode=yes` probe for it (there's nothing to probe). The routing
mechanism itself is verified (a bare local shell exec with zero `ssh`
subprocess involved, confirmed end to end against this package's own dev
machine) — what's **not** verified is exercising it against a real cluster
front-end with real scheduler binaries present. Confirm that specifically
before telling users to rely on it for actual job submission.

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
from mymachine_mcp import config  # noqa: F401 -- registers via configure().
# Import this even though nothing below calls it directly: SlurmBackend's
# constructor doesn't need config yet, but this module must not depend on
# being imported *after* config by whoever imports it (e.g. `import
# mymachine_mcp.compute` in isolation, in a test or a REPL, would otherwise
# crash the first time anything here actually talks to the cluster).

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
get_live_resources = backend.get_live_resources   # raises NotImplementedError if your backend doesn't support it
```

If your dialect genuinely doesn't fit any row above, don't force it —
subclass `SchedulerBackend` (`hpc_agent_core.compute.base`) directly in
your own repo, reusing `duration_to_hms`, `to_epoch`, `parse_exit_code`,
and `render_body` from that module. This is a normal, expected outcome for
an unusual machine, not a sign something is missing from core.

## 7. Wire up the MCP servers

**`docs_server.py`** and **`doctor.py`** are thin — the generic work already
lives in `hpc-agent-core`. Always import `MCPServer` from
`hpc_agent_core.mcp_server`, never from `mcp` directly, and don't add `"mcp"`
to your own `pyproject.toml` — `hpc-agent-core` is the only package that
depends on the MCP SDK. It renamed its own server class once already (2.0.0,
`FastMCP` → `MCPServer`, no deprecation window); routing every machine repo
through one re-export means a future rename is a one-file fix in core
instead of a fix in every machine repo:

```python
# server/<machine>_mcp/docs_server.py
from hpc_agent_core.mcp_server import MCPServer
from hpc_agent_core.docs_server import build
from hpc_agent_core.serving import serve
from mymachine_mcp import config  # noqa: F401 -- registers via configure()

mcp = MCPServer("mymachine-docs")
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

If your scheduler has no single --version-style command whose output
identifies it by name (PJM and Bridge don't; several of their commands need
to simply exist instead), don't force one — write your own `main()` that
composes a small local SSH-connectivity check with
`hpc_agent_core.doctor.check_commands_on_path(names, label)` instead of
`check_ssh()`. See Irene's or Fugaku's `doctor.py` for the pattern; this is
exactly the "write a local replacement for the one check_* that doesn't
fit" case §7's docstring already describes.

**`hpc_server.py`** is the one piece `hpc-agent-core` doesn't provide a
generic version of yet — you write the actual MCP tool surface, grouped
around the IRI Facility API (submit/status/cancel, filesystem operations,
facility/resource info). It's mostly a thin pass-through to `compute.py`
and `hpc_agent_core.middleware`:

```python
# server/<machine>_mcp/hpc_server.py (excerpt — extend with the full
# fs_* set: fs_ls, fs_stat, fs_view, fs_head, fs_tail, fs_mkdir, fs_upload,
# fs_download, fs_checksum, fs_cp, fs_mv, fs_chmod, fs_chown, fs_symlink,
# fs_compress, fs_extract — each a one-line call into hpc_agent_core.middleware.
# fs_grep/fs_glob (see below) are optional — add them if your users would
# want to search cluster-side files without a full download first.)
from hpc_agent_core.mcp_server import MCPServer
from hpc_agent_core.middleware import run_command, quote_path
from hpc_agent_core.models import Job, JobSpec
from hpc_agent_core.serving import serve
from mymachine_mcp import compute, config

mcp = MCPServer("mymachine-hpc")


@mcp.tool()
def get_facility() -> dict:
    """Static facility facts: partitions, modules, storage. (IRI: GET /facility)"""
    return config.load_cluster_config()


@mcp.tool()
def get_resources() -> list[dict]:
    """Live per-partition node occupancy — "will a job start soon", as
    opposed to get_facility's static hardware description. Backed by
    compute.py's SchedulerBackend, not by mymachine_config.json — don't
    reimplement this as static config data (an easy mistake: a machine
    built without live cluster access once did exactly this, and it's a
    real functionality gap, not just a style difference). (IRI: GET /resources)
    """
    return compute.get_live_resources()


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

### Optional: `fs_grep` / `fs_glob` — remote search, without a download first

`hpc_agent_core.middleware.grep_files()`/`glob_files()` are remote
analogues of a local Grep/Glob tool — "find where this string appears" or
"find files matching this pattern" on the cluster, without a full
`fs_download` round trip first. Wiring them up is the same one-line-wrapper
shape as any other `fs_*` tool:

```python
@mcp.tool()
def fs_grep(pattern: str, path: str = ".", glob: str | None = None,
            case_insensitive: bool = False) -> str:
    """Search file contents on the cluster recursively for a regex — remote
    equivalent of a local Grep. Skips binary files and common VCS/dependency
    directories. Returns "path:line:text" per match; empty string means no
    matches (not an error). (Extension — no IRI counterpart.)
    """
    return middleware.grep_files(pattern, path, glob=glob, case_insensitive=case_insensitive)


@mcp.tool()
def fs_glob(pattern: str, path: str = ".") -> str:
    """Find files under `path` matching a glob pattern (** for recursive) —
    remote equivalent of a local Glob. Empty string means no matches.
    (Extension — no IRI counterpart.)
    """
    return middleware.glob_files(pattern, path)
```

Two things worth knowing before you add these, not because the wrapper
hides anything, but because they're easy to get wrong if you reimplement
them yourself: `grep_files` treats "no matches" (grep's exit 1) as a normal
empty result, not an error — only a real failure (bad regex, unreadable
path) raises. And `glob_files`'s pattern can't be `shlex.quote()`'d the way
every other path argument in this family is — quoting it would suppress
the shell's own glob expansion, which is the whole point — so it's checked
against a character allowlist instead, rejecting anything that isn't
legitimate glob syntax before it ever reaches a remote shell.

Optional, not required — a machine repo opts in by adding these two tools
(or skips them entirely) independent of everything else in this guide.

**Expose each server as a console-script entry point, then point `.mcp.json`
at those scripts *run from your git remote*.** This is the part that makes
the plugin installable by an end user who has never cloned your repo, and
it is the step both of the first clean-room ports got wrong — don't skip it.

In `server/pyproject.toml`, name the two servers (and the doctor) as
entry points. Use the family convention: `<machine>-hpc-mcp`,
`<machine>-docs-mcp`, `<machine>-doctor`:

```toml
[project.scripts]
mymachine-hpc-mcp = "mymachine_mcp.hpc_server:main"
mymachine-docs-mcp = "mymachine_mcp.docs_server:main"
mymachine-doctor = "mymachine_mcp.doctor:main"
```

Then in `plugins/<machine>/.mcp.json`, launch each server with
`uv tool run --from git+<your-remote>@main#subdirectory=server`, **not** a
bare command name:

```json
{
  "mcpServers": {
    "mymachine-hpc": {
      "command": "uv",
      "args": ["tool", "run", "--quiet", "--from",
               "git+https://github.com/<owner>/<repo>.git@main#subdirectory=server",
               "mymachine-hpc-mcp"],
      "env": {}
    },
    "mymachine-docs": {
      "command": "uv",
      "args": ["tool", "run", "--quiet", "--from",
               "git+https://github.com/<owner>/<repo>.git@main#subdirectory=server",
               "mymachine-docs-mcp"],
      "env": {}
    }
  }
}
```

Why not just `"command": "mymachine-hpc-mcp"`? A bare command name assumes
the script is already on the user's `PATH` — which is only true on *your*
dev machine after `pip install -e .`. A user installing the plugin from the
marketplace has never installed your package, so the bare command fails with
"command not found". The `uv tool run --from git+…` form makes `uv` fetch
your repo (pinned to `@main`), build the `server/` subdirectory, and run the
entry point in one step, with no prior install — that's what every shipped
plugin in this family does, and what lets "install the plugin" actually
work. (`uv tool run` also pulls `hpc-agent-core` and your other deps
transitively, so the pinned range from §9 is what governs which core version
the user gets.)

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
.venv/bin/python tests/smoke.py --offline       # offline tier: no SSH, no live cluster needed
.venv/bin/python tests/smoke.py                 # + the read-only tier against the live machine
.venv/bin/python tests/smoke.py --job           # + submits a real tiny job
```

### Write `smoke.py` as three tiers: offline, read-only, job

`hpc_agent_core.testing` provides the machine-agnostic plumbing —
`call()`/`payload()` (read a tool result correctly: raise on `is_error`,
prefer `structured_content`, unwrap the `{"result": ...}` wire convention),
`job_name()` (a run-scoped name so concurrent runs never collide), and
`Summary`/`run_tier()` (pass/fail/skip tracking with one final summary
line, skips named rather than folded silently into "passed"). Import these
rather than reimplementing them — an earlier `smoke.py` read every result
through raw text-truthiness, which quietly conflated "legitimately empty
result" with "call failed," and a stale-dependency bug (a repo pinned to a
range that no longer guaranteed the module it imported actually existed)
went undetected because nothing ever exercised import/registration without
also needing live SSH. The offline tier below exists specifically to catch
that class of bug without needing a cluster at all.

Everything else — which tools to check for, what a live call should
assert, the job spec shape — stays local to your `smoke.py`, including the
tier functions themselves and the top-level orchestration deciding what to
skip when. That orchestration is short (~15 lines) and differs enough
machine to machine (a Grid Engine machine's tiers look different from a
dual-scheduler one) that centralizing it would cost more in awkward
parameterization than it saves in duplication — unlike `call`/`payload`,
which are byte-for-byte identical everywhere. A minimal shape:

```python
# server/<machine>_mcp/tests/smoke.py (excerpt)
from hpc_agent_core.testing import Summary, call, confirm_billing_gate, job_name, payload, run_tier

async def check_hpc_server_offline(session) -> None:
    tools = await session.list_tools()
    # assert your required tool names are present
    submit_job_tool = next(t for t in tools.tools if t.name == "submit_job")
    # assert submit_job_tool.input_schema["$defs"] has the shapes you expect
    facility = await call(session, "get_facility", {})
    assert str(payload(facility)).strip()

async def check_hpc_server_live(session) -> None:
    resources = await call(session, "get_resources", {})
    # assert something live-only about the result — see the caution below

# ... _offline_tier() / _read_only_tier() / _job_tier() wrap these in a
# stdio ClientSession each; _run() calls run_tier() for each, skipping
# read-only/job per the rules: --offline given, or an earlier tier failed.
```

Make the read-only tier actually exercise the cluster, not just tool
registration. It should, over MCP stdio: list the tools on both servers,
call `search_docs`/`list_doc_sections` (no SSH — these belong in the
offline tier), **and make at least one live read-only scheduler round
trip** — `get_resources` (`sinfo`) plus `get_job_statuses([])`
(recent-jobs query) and a `run_command_on_cluster("hostname")`. Both early
clean-room ports wrote a read-only path that only called `get_facility`,
which reads bundled JSON and touches no SSH at all — so a green read-only
run "passed" without ever proving the machine was reachable.
`get_facility` proves nothing about connectivity; `get_resources` does.
(These are all read-only, so they're safe to run every time, unlike
`--job`.)

If your machine's compute is billed with no usage cap (or any other
consequence you don't want an accidental `--job` to trigger),
`confirm_billing_gate(args, reason=...)` returns a refusal message when
`--job` was given without a matching `--confirm-billing` flag — check it
before constructing any client, so refusal never touches SSH. This is
optional; a machine with no such concern just doesn't call it.

**Even so, a passing `doctor` and passing read-only smoke test are not proof
the port works.** Real precedent: a machine that looked fine on every check
still had its job-status logic completely broken, because the check that
would have caught it (an actual submitted job) was the one nobody ran.
Submit at least one real job — ideally one requesting a GPU if the machine
has any — and confirm you can see it queue, run, and complete through the
agent before considering this port finished.

Add `hpc-agent-core` as a dependency in your `server/pyproject.toml`, pinned
to the **exact** version you actually tested against —
`hpc-agent-core==X.Y.Z` — not a range and not left unpinned. A range like
`>=X.Y,<X.(Y+1)` still lets a routine core release (even an additive one,
like a new module your repo doesn't use) change what a fresh install
resolves to without you ever deciding that; an exact pin means nothing
changes for your users until you bump it yourself, on purpose, after
verifying against the new version. Check `pip index versions
hpc-agent-core` (or the PyPI project page) for whatever is actually current
*right now* — don't hardcode a version number from this guide, since it
will go stale the moment a new `hpc-agent-core` ships. When you do bump the
pin later, treat it like any other dependency upgrade: verify your own
`tests/smoke.py` (see §9) against the new version before committing to it,
even if the core changelog claims the release is backward compatible.

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
  they've explicitly said to just run it. **This applies only to those two
  consequential tools — not to every tool call in a skill.** A real port's
  `-demo` skill once wrote "explain each step to the user before running
  it" as a blanket rule for its whole walkthrough (including read-only
  steps like `get_facility`/`get_resources`), and an agent following that
  skill read it as "produce the explanation, then stop" rather than
  "narrate as you go" — the demo described itself instead of running. Don't
  generalize this invariant beyond submit/run; see §11's demo-skill
  guidance for the wording that avoids this.
- **Never invent a documentation URL.** If `docs_cite_url` is blank (see
  §3), search results carry no URL — don't add one back in in a skill or
  tool description.

## 11. Write your skills, README, AGENTS.md, IRI_CHECKLIST.md

- **Skills** (`<machine>-configuring`, `-submitting-jobs`, `-monitoring-jobs`,
  `-reference`, `-demo`): each documents one user-facing workflow in plain
  language, referencing the tools from §7 and the facts from your guide.
  Machine-prefix the skill names so multiple plugins can be installed at
  once without collisions. Give each skill's frontmatter `user-invocable: true`
  so it's callable as a slash command.

  **`-demo` specifically must be written so an agent actually executes it,
  not just reads it back.** Use this exact pattern — imperative, numbered
  steps, and "pause *after* each step," never "explain *before* running
  it" (see §10's note on why that phrasing backfires):

  ```markdown
  Run each step in order — actually call the tools, don't just describe
  the plan. Present results as a readable narrative, not raw JSON dumps.
  Pause after each step and show the output before moving on.

  ## Step 1 — <name>

  Call `<tool>`. <what to show/point out>.

  ## Step 2 — <name>
  ...
  ```

  Every step should read as a direct command ("Call `get_resources`"), not
  a description of what could happen. Only the step that actually submits
  a job needs the show-before-you-run framing from §10, and even there,
  phrase it as "tell the user you'll submit X, then call `submit_job`" —
  an instruction to act, not a pause point.
- **README.md**: user-facing, and short. It has an intro paragraph followed
  by exactly four sections, in this order — **don't add others** (see the
  "don't add" list below):

  1. **A one-paragraph intro** — what the machine is, one line on what the
     plugin does (submit/monitor jobs, manage files, search docs), and one
     line naming this as a thin skin over `hpc-agent-core` with a link to
     it.
  2. **Configure** — the config file at `~/.hpc-agent/<machine>.json` (the
     common location — see §5), the one or two keys it actually needs (at
     minimum `ssh.host`; add `embedding.api_key` if docs search matters),
     what each env var override is, a one-line mention that `ssh.host`
     also accepts `"localhost"` for running directly on the machine's own
     front-end with no SSH (see §5), and a one-line mention that your
     `<machine>-configuring` skill walks through this interactively.
  3. **Install** — this is the part both of the first ports got wrong by
     inventing a dev-mode `pip install -e .` writeup instead: use this exact
     shape, adjusting only the machine name, org/repo, and script names:

     ```markdown
     ## Install

     ### Prerequisite: uv

     The plugin starts its MCP servers with `uv tool run` from this
     repository's `main` branch, so [`uv`](https://docs.astral.sh/uv/) must
     be installed and on your `PATH` before Claude Code or Codex starts the
     plugin:

     ```bash
     brew install uv        # or: curl -LsSf https://astral.sh/uv/install.sh | sh
     ```

     Restart Claude Code or Codex after installing uv so the plugin process
     inherits the updated `PATH`.

     ### Claude Code

     ```
     /plugin marketplace add <org>/<repo>
     /plugin install <machine>@<machine>-marketplace
     /reload-plugins
     ```

     ### Codex

     ```
     codex plugin marketplace add <org>/<repo>
     ```

     Then open `/plugins`, install `<machine>`, start a new thread, and run
     `/<machine>-demo` to verify the connection end-to-end.

     ### Manual (any MCP-compatible client)

     Both options below only register the MCP servers — copy
     `plugins/<machine>/skills/` into wherever your client loads skills
     from too (this varies by client, so don't go into depth here).

     #### Option A — Using Hatch!

     [Hatch!](https://github.com/CrackingShells/Hatch) registers MCP servers
     on any supported host from a single command. Install it once, then
     configure both servers — replace `<host>` with your target platform
     (`claude-code`, `codex`, `cursor`, `vscode`, `claude-desktop`, `kiro`,
     `gemini`, `lmstudio`, or any other
     [supported host](https://github.com/CrackingShells/Hatch#supported-mcp-hosts)):

     ```bash
     pip install hatch-xclam

     hatch mcp configure <machine>-hpc --host <host> \
       --command uv \
       --args "tool run --quiet --from git+https://github.com/<org>/<repo>.git@main#subdirectory=server <machine>-hpc-mcp"

     hatch mcp configure <machine>-docs --host <host> \
       --command uv \
       --args "tool run --quiet --from git+https://github.com/<org>/<repo>.git@main#subdirectory=server <machine>-docs-mcp"
     ```

     To replicate the same configuration to additional hosts:

     ```bash
     hatch mcp sync --from-host <host> --to-host cursor,vscode
     ```

     #### Option B — Edit `.mcp.json` directly

     Create or edit `.mcp.json` in your project root, pointing at the same
     `uv tool run --from git+https://github.com/<org>/<repo>.git@main#subdirectory=server`
     invocation your own `plugins/<machine>/.mcp.json` uses (see §7) for
     both the `-hpc-mcp` and `-docs-mcp` entry points.
     ```

     Keep both options — three ports in a row have quietly dropped the Hatch
     option while rewriting this section (it's easy to do since Option B
     alone "looks complete"), even though it was already an established
     family convention before hpc-agent-core existed. Don't drop it again.

     No other install path belongs in the README — not a local
     `pip install -e .`/`pipx install` writeup (that's for *you*, developing
     the plugin, not for someone installing it; it belongs in Development,
     below, not Install) and not a console-script table (the scripts are an
     implementation detail behind the `.mcp.json` entries above; a user
     never types their names directly).
  4. **Verify** — one command:

     ```bash
     uv tool run --quiet --from git+https://github.com/<org>/<repo>.git@main#subdirectory=server <machine>-doctor
     ```

     plus a one-line note on what a passing/partial result looks like (e.g.
     "all lines should read ✓ except possibly embedding, which falls back to
     keyword search off the RIKEN network — not blocking").
  5. **Development** (for contributors to *this* repo, not end users) — use
     `uv run`, not a hand-rolled venv (your own `server/run.sh` already
     auto-detects `uv`; keep the README consistent with it):

     ```bash
     cd server
     uv run python -m <machine>_mcp.doctor
     uv run python tests/smoke.py
     uv run python tests/smoke.py --job
     ```

     plus the one-liner for rebuilding the docs index after editing the
     guide: `uv run python -m hpc_agent_core.rag.ingest`.

  **Do not add** a "What's here" repo-tree section, a "What the plugin can
  do"/tool-list section, or a "<Machine> quick facts" cluster-summary
  section. All three showed up in the first ports' READMEs and all three
  are dead weight: the repo layout is self-evident from browsing GitHub, the
  tool list is enumerable from `list_tools` and documented per-tool in
  `hpc_server.py`'s docstrings, and cluster facts belong in exactly one
  place — the guide (`data/<machine>_guide.md`) — not copied into a second
  file where they will drift the next time the guide is corrected.
- **AGENTS.md**: agent-facing — the design rules from this guide
  (no-write-access to core, clarity over cleverness, the §10 invariants),
  the cluster facts from §1, and a repository map. **Must open with a line
  pointing at the canonical guide** — "Read
  [hpc-agent-core's `PORTING.md`](https://github.com/william-dawson/hpc-agent-core/blob/main/PORTING.md)
  before making changes here" or equivalent — since no `PORTING.md` file
  exists in this repo (see the top of this guide).
- **IRI_CHECKLIST.md**: which IRI Facility API endpoints you implemented,
  deferred, or extended beyond the spec, and why — this is genuinely
  machine-specific (an endpoint sensible on one machine may not apply to
  another) and does not move into `hpc-agent-core`. See
  [`hpc-agent-core`'s own `IRI_CHECKLIST.md`](https://github.com/william-dawson/hpc-agent-core/blob/main/IRI_CHECKLIST.md)
  first — it maps each IRI capability group onto the primitive this package
  already gives you (`SchedulerBackend.submit()`, `middleware.run_command`,
  ...), so your own checklist only needs to record the machine-specific
  verdict, not rediscover what's already handled.

## 12. Reproducible notebooks (optional, recommended)

An interactive agent session is great for exploring, but its record — a chat
transcript, done out of order, with dead ends — isn't something a co-author
or a future you can re-run to check a result still holds. `hpc_agent_core.client`
exists to distill that kind of session into a linear Jupyter notebook that
calls the *same* MCP tool surface the agent used, not a hand-copied SSH/rsync
script. That matters beyond tidiness: a hand-copied script is a second,
unaudited implementation of talking to the cluster, and second implementations
drift silently (a genuine `middleware.py` bug shipped for a while specifically
in the untested rsync path — see its git history). A notebook built on
`hpc_agent_core.client` exercises the exact code already covered by your own
`tests/smoke.py`, so a regression there breaks the notebook too, instead of
living unnoticed in a script nobody else runs.

`connect_sync()` (or the async `connect()`, for concurrent/already-async use)
opens an MCP stdio session and returns an `HpcClient`/`SyncHpcClient` that
exposes every tool as a plain method — `hpc.submit_job(spec=spec)`, no
`await`, no manual `__aenter__`/`__aexit__` spread across cells. `dev_params()`
launches your `python -m <machine>_mcp.hpc_server` for local development;
`pinned_params()` launches the exact `uv tool run --from git+...@<ref>`
invocation your own `.mcp.json` uses, pinned to a tag/commit — pin it, don't
leave it on `main`, or a notebook that reproduced a result in January silently
reproduces something else by June.

Three caching modes, chosen once when connecting — see `client.py`'s module
docstring and `HpcClient.wait_for_job`/`fs_download` docstrings for the full
contract, including why polling and file downloads each need bespoke (not
generic per-call) caching:

- `mode="live"` — always hits the real cluster.
- `mode="lazy"` — cache-first, falls back to live on a miss. What you iterate
  on a notebook with.
- `mode="replay"` — cache-only, no SSH attempted at all. What you ship: commit
  the cache directory (`examples/.hpc_cache/<name>/`) alongside the notebook
  so `mode="replay"` reproduces the whole narrative — including the actual
  bytes of any downloaded file, not just a "verified: true" claim — for
  someone with no cluster account at all.

**The one discipline that actually matters here: every cell output committed
to the notebook, and every file in the committed cache directory, must come
from really executing the cells against the real cluster — never authored,
never guessed, never "this is obviously what it would print."** Two bugs in
this exact machinery were caught only because of that discipline, not
in-principle review of the code:

- The first cut of `fs_download`'s caching stored only metadata (checksum,
  byte count), not the file's actual bytes — so a `mode="replay"` run from a
  fresh clone would have reported a successful, verified download while the
  file silently never got written. Invisible until an actual `mode="replay"`
  run from an isolated directory with no prior live connection was tried.
- The first cut of `connect_sync` scheduled each call as an independent
  asyncio Task via `run_coroutine_threadsafe`. Fine against a mocked session;
  against the real MCP stdio transport it raised `RuntimeError: Attempted to
  exit cancel scope in a different task than it was entered in`, because
  `anyio`'s cancel scopes are task-affine. A mocked test never exercises
  `anyio` at all, so only a real subprocess connection caught it.

Neither bug was reachable by reasoning about the code — both needed an actual
live run to surface. Hold your own machine's notebook to the same bar: run it
for real (`mode="live"`, from a clean checkout) before committing its cache
directory, the same way §9 insists on an actual submitted job, not just a
passing `doctor`.

Repo convention: `examples/<name>.ipynb` plus the committed
`examples/.hpc_cache/<name>/` recording (JSON metadata + `.blob` files for
any cached downloads); add the notebook's own runtime-generated output
directory (e.g. `examples/downloads/`) to `.gitignore` — that's regenerated
by running the notebook, not part of the recording.

Document this for the agent as one more skill in §11's set —
`<machine>-reproducing` — covering when to reach for this (the user asks to
make a result reproducible or shareable, or you've just finished a chunk of
exploratory tool use worth preserving).

**The skill file must be self-contained — inline the code pattern
(`connect_sync`/`dev_params`/`pinned_params`, the mode discipline) directly
in the skill's own text.** Do not tell the agent to go read your `examples/`
notebook as a reference: that file only exists in *your own* repo checkout.
An agent running from an actually-installed plugin (the normal case — no
local git clone, `uv tool run` fetches and runs the server from an ephemeral
env) has no local copy of it to find. The first cut of this skill for
RCCS-CloudAgent got exactly this wrong — pointed at `examples/
reproduction_demo.ipynb` "in this repo" — and a live test caught the actual
failure mode: the agent, unable to resolve that reference, searched the
filesystem, found an unrelated local dev checkout that happened to exist on
the same machine, and ran a probe script against *that* checkout's venv
instead of using its own already-installed MCP tools. Worked by pure
proximity accident on a laptop that had both the plugin and the dev repo;
would have failed outright — or worse, silently done something equally
wrong — anywhere else. Explicitly tell the skill: don't go looking for a
local checkout of this plugin or of `hpc-agent-core`; if one happens to
exist on disk, it isn't part of the installation. Explicitly tell it, too,
that `hpc_agent_core.client` code belongs *inside the notebook being
written*, never something to shell out to during the agent's own
exploration — that work already goes through the normal MCP tool calls it
has.

This needs `hpc_agent_core.client`, added in `hpc-agent-core` 0.5.0 — bump
your pin (see §9's note on bumping pins deliberately) if you ported before
then.
