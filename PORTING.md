# Porting Guide: onboarding a new facility onto hpc-agent-hub

This guide is for an agent (or human) adding a new HPC facility to this
repo's unified MCP server — the multi-facility plugin that lets an agent
submit and monitor batch jobs, manage files, and search documentation for
every onboarded supercomputer through one process. It assumes **no other
context**: you do not need to have seen any other facility's directory to
follow this. Read it in full before writing any code.

**Porting a facility means opening a PR against this repo, not creating a
new repo.** There is exactly one repo, one plugin, one MCP server for every
facility. Your PR adds one `facilities/<slug>/` directory; nothing else in
this repo should need to change (the server auto-discovers every facility
directory — see §5).

## 0. The mental model

`hpc_agent_core/` is the shared, generic engine: SSH execution, PSI/J-style
job data models, Slurm and Grid Engine scheduler backends, a documentation
search pipeline, health checks, and MCP serving glue. `hpc_mcp/` is the
**one, already-written, generic MCP tool surface** — every tool
(`submit_job`, `get_resources`, `fs_ls`, ...) already exists and takes a
`facility` slug as its first argument. **You do not write a tool surface.**
Your job is entirely contained in one new `facilities/<slug>/` directory:
your facility's facts (a config JSON, a hand-written guide), and a small
amount of Python that registers those facts and constructs a scheduler
backend.

Two hard rules:

1. **Everything you need lives in your own `facilities/<slug>/` directory.**
   You may read `hpc_agent_core/` and `hpc_mcp/` freely, but a genuine
   customization is expressed by what you pass into
   `config.register_facility(...)` and which `SchedulerBackend` subclass
   (and hook overrides) you construct — never by editing those shared
   files. If you think you need to edit them, re-read the relevant module's
   docstring; you've likely misunderstood an extension point.
2. **Prefer clarity over cleverness.** A little facility-specific code in
   your own `facility.py` is fine and expected — you are one of several
   facilities built this way, and a small, easy-to-read override beats a
   clever generic mechanism that isn't.

## 1. Learn the target machine before writing anything

Answer these from the machine's real, official documentation (see §2 for
how to turn that into your guide) and, if you have SSH access already, by
actually running commands on the login node — a "zero-code smoke path"
(`ssh <host> sinfo`, `sacct --version` or a real `sacct` call, `module
avail`, a real GPU allocation test) is a cheap way to confirm your
assumptions *before* writing a line of port code, not after.

- **Scheduler**: Slurm or Grid Engine? (Only these two have a ready-made
  backend today — see §6. Something else needs its own `SchedulerBackend`
  subclass, reusing `compute.base`'s helpers.)
- **Accounting** (Slurm only): does `sacct`/`sacctmgr` actually work, or is
  accounting disabled (`accounting_storage/none`)? Test with a real `sacct`
  call, not just `sacct --version` (the binary can exist and still be
  configured off).
- **GPU request dialect** (Slurm only) — two *independent* questions, both
  must be answered separately:
  - Which flag: `--gpus=N` (a job-total count) or `--gres=gpu:N` (untyped)?
  - Does Slurm derive node count from the GPU count (so `--nodes` can be
    omitted), or must `--nodes` always be set explicitly? Do not assume
    these two questions have a shared answer — a real onboarded facility
    uses the `--gpus=N` flag but always sets `--nodes` explicitly, which is
    *not* the combination you'd get by picking one "style".
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
  only? Conda/venv only? This shapes your guide, not your code.
- **Login mechanics**: SSH hostname, how a new key gets registered (a web
  portal? emailing an admin? self-service?).
- **Account/project**: is `--account` mandatory, optional with a
  machine-side default, or unused entirely?
- **Connection quirks** (rare): does this facility need a different
  `remotemanager.Computer` option than the shared default (login-shell
  template, bash submitter, `python3`)? Check
  `hpc_agent_core.config.COMPUTER_OPTION_NAMES` for the full set (shell,
  timeout, keyfile, landing_dir, transport, ...) if so.
- **Sensible default queue?** Does this facility have exactly one partition
  (or one obviously-correct default) that `submit_job` should fill in when
  the caller leaves `queue_name` blank, or does it have several
  partition families with no safe default (see §6's `default_queue_name`
  hook)?

## 2. Write your own guide — never point at a live external site

The docs-search pipeline (`rag/ingest.py`) only ever chunks a **local,
hand-written guide file** — it will never git-clone or fetch a remote docs
site for you, and you shouldn't build a mechanism that does either. A past
port that pointed its ingest step at "always re-fetch the live official
site" broke silently when that site moved domains and was restructured,
with nothing to catch it.

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
`facilities/<slug>/data/<slug>_guide.md`.

If the official site later changes, re-sync by re-reading it and editing
your guide by hand — a deliberate, occasional, human-reviewed step — not by
building an automatic re-fetch.

## 3. Decide whether to cite a URL in search results

If the official docs site is genuinely stable and worth pointing users at,
your guide's search results can cite it (`docs_cite_url` in
`register_facility()`, see §5). If it's unreliable, moved recently, or
you're not confident it'll still be there next month, **leave
`docs_cite_url` blank** (the default) — search results simply won't mention
a URL, and nothing in your plugin should invent one to send a user to.

## 4. Directory layout

```
facilities/<slug>/               # e.g. facilities/rikyu/ — the ONLY directory your PR adds
  __init__.py                      # empty — makes this a Python package
  facility.py                      # §5/§6 — registers config + scheduler backend
  facility.json                    # §7 — small manifest for the generated facility table
  data/
    <slug>_config.json               # static facts: partitions, storage, modules (see §7's facts_filename)
    <slug>_guide.md                  # §2
    docs_index/                      # generated — see §8
```

Note: `<slug>` uses hyphens where natural (`rccs-cloud`); the *directory*
name must be a valid Python identifier, so use underscores there
(`facilities/rccs_cloud/`) while the registered `slug` string keeps the
hyphen — see `facilities/rccs_cloud/facility.py` for a real example of this
split.

Nothing outside `facilities/<slug>/` needs to change. `hpc_mcp/__init__.py`
auto-imports every `facilities/*/facility.py` it finds — that's what
"registering" your facility means, and it's how a new facility PR avoids
touching any shared file.

## 5. Wire up `facility.py` — config registration

```python
# facilities/<slug>/facility.py
from pathlib import Path

from hpc_agent_core import config

FACILITY = config.register_facility(
    slug="mymachine",                 # the string every tool's `facility` argument expects
    display_name="My Machine (Site)",
    description="One-line summary shown by get_facilities() and rendered "
                 "into the facility table.",
    default_host="mymachine",          # ssh.host fallback: a ~/.ssh/config alias, or user@hostname
    data_dir=Path(__file__).parent / "data",
    embed_base_url="http://llm.ai.r-ccs.riken.jp:11434/v1",  # shared RIKEN endpoint, or your own
    embed_model="bge-m3:567m",
    docs_cite_url="",                  # leave blank unless you decided otherwise in §3
    # facts_filename="mymachine_config.json",   # default: "<slug>_config.json" — override
    #                                              only if reusing a differently-named file
    # docs_filename="mymachine_guide.md",       # default: "<slug>_guide.md" — same idea
    # computer_defaults={"shell": "zsh"},       # only if §1's "connection quirks" applies
)
```

Settings resolve environment variable > the user's config file > the
default you gave `register_facility()`. The config file itself lives at
`~/.hpc-agent/<slug-with-underscores>.json` (one common directory shared by
every facility). `ssh.host` also accepts `"localhost"` (or a `127.*`
address) for running directly on the cluster's own front-end/login node
with no SSH at all — `middleware.get_frontend()` is deliberately uncached
specifically so a config file edit (e.g. switching to/from `"localhost"`)
takes effect on the next tool call, not just after a full server restart.
Your `hpc-configuring` skill guidance already covers this generically —
you don't need facility-specific configuring skill text at all.

## 6. Wire up `facility.py` — the scheduler backend

Construct one of the two ready-made backends with the answers from §1, or
subclass `SchedulerBackend` yourself if neither fits. **Match the nearest
real precedent below rather than inventing your own combination from
scratch** — every combination shown here is verified against a real
facility, not guessed:

| Facility shape | Backend construction |
|---|---|
| Slurm, accounting on, job-total `--gpus=N`, single GPU vendor, Slurm derives node count | `SlurmBackend(facility=SLUG, has_accounting=True, gpu_request_style="gpus_total")` |
| Slurm, accounting on, untyped `--gres=gpu:N`, dual GPU vendor, `--nodes` always explicit | `SlurmBackend(facility=SLUG, has_accounting=True, gpu_request_style="gres", gpu_vendor_map={"h200": "--nv", "mi300x": "--rocm"})` |
| Slurm, accounting on, job-total `--gpus=N` **but** `--nodes` always explicit, some partitions need no GPU flag at all | `SlurmBackend(facility=SLUG, has_accounting=True, gpu_request_style="gpus_total", nodes_always_explicit=True, no_gpu_flag_prefixes=frozenset({"qc-gh200", "ng-dgx-m"}))` — see `facilities/rccs_cloud/facility.py` |
| Slurm, accounting **off** (a small/lab-scale machine), untyped `--gres=gpu:N` | `SlurmBackend(facility=SLUG, has_accounting=False, gpu_request_style="gres")` — note: this path degrades `get_recent_statuses` to "current live queue only" and is less battle-tested; verify against a real submitted job, not just `doctor` passing |
| Grid Engine, one real queue, some queue-like names are actually host pins | `GridEngineBackend(facility=SLUG, default_queue="all.q", host_pins={"nodeA", "nodeB"}, queue_aliases={"gpu"})` |

Complete example, including the two optional hooks the generic `submit_job`
tool calls (see `facilities/rikyu/facility.py` for the real version this is
based on):

```python
# facilities/<slug>/facility.py, continued
from hpc_agent_core.compute.slurm import SlurmBackend
from hpc_agent_core.models import JobSpec
from facilities.registry import register_backend

SLUG = "mymachine"


class MyMachineBackend(SlurmBackend):
    def default_queue_name(self) -> str | None:
        """Return a partition name to fill in when the caller leaves
        queue_name blank, or None if there's no single sensible default
        (the base class already returns None — override only if your
        facility genuinely has one obvious default, like a single
        partition)."""
        return "gpu"  # or: return None

    def validate_spec(self, spec: JobSpec) -> None:
        """Raise ValueError for a facility-specific constraint the
        scheduler itself would only reject confusingly. No-op (inherited)
        if you have nothing to check."""
        # e.g. a fixed set of allowed per-job GPU counts — see Rikyu's real
        # validate_spec for the pattern.


BACKEND = MyMachineBackend(
    facility=SLUG,
    has_accounting=True,
    gpu_request_style="gpus_total",
)
register_backend(SLUG, BACKEND)
```

If your dialect genuinely doesn't fit any row above, don't force it —
subclass `SchedulerBackend` (`hpc_agent_core.compute.base`) directly,
reusing `duration_to_hms`, `to_epoch`, `parse_exit_code`, and `render_body`
from that module. This is a normal, expected outcome for an unusual
facility, not a sign something is missing.

If you need a machine-specific tweak to the *rendered script itself* (not
covered by any constructor knob), override `render_script` the way
`facilities/rccs_cloud/facility.py`'s `CloudSlurmBackend` does (injecting
`source /etc/profile` before the job body) — call the base class's
`_header()`/`render_body()` helpers and add your one extra line, rather
than reimplementing script rendering from scratch.

## 7. The facility manifest — `facility.json`

A small, separate file the facility-table generator reads (not read by the
running server at all — that's `register_facility()`'s job):

```json
{
  "slug": "mymachine",
  "display_name": "My Machine (Site)",
  "description": "One-line summary — keep this in sync with facility.py's register_facility() call.",
  "scheduler": "slurm"
}
```

After adding or editing this file, regenerate the tables it feeds:

```bash
python scripts/render_facility_tables.py
```

This rewrites the block between the `FACILITY_TABLE:START` /
`FACILITY_TABLE:END` HTML-comment marker pair in every file that has one
(README.md, AGENTS.md, the `hpc-reference` skill) — commit the result. CI
runs the same script with `--check` and fails the PR if you forgot.

(Note for anyone editing *this* file: don't write the two markers next to
each other as a literal matched HTML-comment pair anywhere in this
document, including in a code block — `render_facility_tables.py` finds
marker pairs by scanning every file's raw text, this file included, and
would silently rewrite whatever sits between them.)

## 8. Build the docs index

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m hpc_mcp.ingest mymachine
```

This writes `facilities/mymachine/data/docs_index/chunks.json` (+
`embeddings.npy` if an embedding key is configured for that facility).
Commit both.

## 9. Validate before calling the port done

```bash
.venv/bin/python -m hpc_mcp.doctor mymachine    # config, ssh+scheduler, guide bundled, docs index, embedding
.venv/bin/python tests/live_smoke.py            # read-only tier against every registered facility (live SSH)
.venv/bin/python tests/live_smoke.py --job      # + submits a real tiny job on rikyu — extend this
                                                 #   script to also cover your new facility's job tier
```

`tests/live_smoke.py` is deliberately short and machine-agnostic already —
it iterates `get_facilities()` for the read-only tier, so your new facility
is exercised automatically the moment it's registered; you don't need to
add facility-specific code there for read-only checks. If you're adding the
job-submission tier for your facility, follow the existing `--job` block's
shape (submit, poll `get_job_status` to a terminal state, read output via
`fs_tail`) rather than inventing a different pattern.

**Even so, a passing `doctor` and passing read-only smoke test are not
proof the port works.** Submit at least one real job — ideally one
requesting a GPU if the facility has any — and confirm you can see it
queue, run, and complete through the agent before considering this port
finished.

## 10. Invariants that must hold, no exceptions

- **The MCP server must never fail to start.** Missing or malformed config
  for one facility is a *tool-call-time* error with a clear message for
  that facility only (e.g. "facility 'mymachine' is not configured — run
  the configuring skill"), never a startup crash, and never something that
  prevents other, correctly-configured facilities from working. Nothing
  above module scope in your `facility.py` should touch the network or read
  the config file eagerly.
- **An unknown facility slug fails loudly, listing valid slugs.** Don't
  catch or reinterpret `config.get_facility`'s / `facilities.registry
  .get_backend`'s `ValueError` — let it surface as the tool error.
- **Bias agent-created files into one visible directory.** Job working
  directories, staged uploads, and scratch/demo files default under
  `~/agent/` (the default `jobs_dir="agent/jobs"` already does this) — not
  scattered loose in `$HOME`, and not hidden in a dotfile directory either.
  This is a bias, not a restriction: honor any explicit path the user gives.
- **Show before you run.** Before `submit_job` or `run_command_on_cluster`
  actually executes something, show the user what's about to run (the
  JobSpec, or the exact command/script) and a brief explanation, unless
  they've explicitly said to just run it. This applies only to those two
  consequential tools, not to every tool call — see `hpc-demo`'s skill text
  for the exact wording that keeps this from over-generalizing into "narrate
  everything, including read-only calls."
- **Never invent a documentation URL.** If `docs_cite_url` is blank (see
  §3), search results carry no URL — don't add one back in anywhere.

## 11. What you do *not* need to write

Because the tool surface, skills, README, and IRI checklist are already
generic and facility-parametrized, a facility PR does **not** touch:

- `hpc_mcp/hpc_server.py` / `docs_server.py` / `doctor.py` — already handle
  every registered facility generically.
- `plugins/hpc/skills/*` — already facility-generic; the one
  facility-specific content (the table of what's onboarded) is generated,
  not hand-written (§7).
- `README.md`'s prose, `IRI_CHECKLIST.md`, `AGENTS.md` — edit only if your
  facility exposes something genuinely new the checklist doesn't cover yet
  (e.g. a scheduler with no `has_accounting`-style project listing).

If you find yourself wanting to write a new skill file, a new tool, or a
new server entry point just for your facility, stop — that's almost always
a sign the thing you need is actually a `SchedulerBackend` hook (§6) or a
`register_facility()` parameter (§5), not a new file.

## 12. Reproducible notebooks

`hpc_agent_core.client` (used by the `hpc-reproducing` skill — see
`plugins/hpc/skills/hpc-reproducing/SKILL.md` for the full, self-contained
procedure) needs nothing facility-specific from you: `pinned_params(...)`
points at this one repo regardless of which facility a given notebook
targets, and every call in the notebook passes `facility="mymachine"`
explicitly like any other tool call. Nothing to add here for a new
facility.
