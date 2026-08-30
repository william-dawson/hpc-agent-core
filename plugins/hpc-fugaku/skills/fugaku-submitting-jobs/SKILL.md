---
name: fugaku-submitting-jobs
description: Use when the user wants to run, submit, or launch a job on Fugaku. Covers partition/queue selection, JobSpec construction, submission, and known gotchas specific to this facility.
user-invocable: true
---

# Submitting jobs on Fugaku

Every tool call in this skill uses `facility="fugaku"`.

Fugaku is **A64FX (Arm SVE) and has no GPUs** — never set `resources.gpus`
or `resources.gpu_cores_per_process`; both are rejected outright.

## Workflow

1. **Choose a PJM resource group** for `attributes.queue_name` — there is
   no default, deliberately, because which groups an account may use
   differs per project. `small` (1–384 nodes, up to 72h), `large` (385+
   nodes, up to 24h), `int` (interactive), `f-pt` (priority, see below), or
   a `spot-*` low-priority variant. Confirm the real min/max/default for
   this account with
   `run_command_on_cluster(facility="fugaku", command="pjacl --rg small")`.
2. **Every job needs a project group.** Set `attributes.account`
   explicitly, or rely on `defaults.group` in the config file (or
   `FUGAKU_GROUP`) — `submit_job` raises a clear error if neither
   is set. The shared `fugaku` group **cannot submit jobs**. If the
   resolved group is `trial` (the "Startup Project" every new account
   gets), only the `spot-*` resource groups work — `small`/`large`/`int`
   are rejected. Check `run_command_on_cluster(facility="fugaku",
   command="id")` for the account's real project groups before assuming
   `small` is available.
3. **Set `resources.node_count`.** For MPI work also set
   `resources.processes_per_node` (renders as PJM's
   `--mpi "max-proc-per-node=N"`) or `resources.process_count` for a total
   rank count. An `mpiexec -n <N>` launcher is added automatically whenever
   more than one task is requested — don't add it yourself unless you need
   non-default `mpiexec` flags (set `launcher` explicitly to override).
4. **Declare second-layer storage.** If the job touches anything outside
   `$HOME` — a group data volume, or Spack — set
   `attributes.custom_attributes["gfscache_volume"]` (e.g. `"/vol0004"`)
   or rely on the configured default. Without it `pjsub` rejects the job.

   **Declare exactly one volume.** A comma-separated value such as
   `/vol0002,/vol0004` is accepted by `pjsub` at submission, queues
   normally, and then fails the pre-execution gate check minutes later:
   state `ERR`, `REASON : GATE CHECK`, **no output file and no exit code**.
   That silent, delayed failure is why it is worth catching — `submit_job`
   now rejects a comma-containing value up front.

   Verified live across eight jobs, varying one thing at a time: every job
   carrying the comma value failed (at 5 *and* 10 minute elapse limits, so
   wall time is irrelevant), and every job with a single volume or none
   ran to completion (at 5, 6, 9 and 10 minutes). The `small-s5` sub-group
   that appears in `pjstat -s` is a red herring — successful jobs run in
   it too.

   The correct syntax for declaring **more than one** volume is not
   documented in the bundled guide or in `pjsub --help`; both only ever
   show a single `/vol000N`. Ask RIKEN rather than guessing a separator.
5. **Leave `stdout_path`/`stderr_path` unset** — PJM has no flag for
   redirecting them. Output always lands at `<name>.<job_id>.out`/`.err` in
   the submission directory. Set `spec.directory` if you want it elsewhere.

## Jobs run from the group data area, not `$HOME`

Point `directory` at something under `/vol0n0m/data/<groupname>/` for
every job. Home (`/home/<user>`) is a 20 GiB per-user area meant for
code and scripts; the group data area carries ~5 TiB per group and is
the intended job-execution space. Large outputs (matrix files, result
archives) can exhaust the home quota mid-run. `pjsub`'s submit-time
directory check also prefers the data area — the plugin passes
`--no-check-directory` automatically, so running from home *works*.
That is not the same as right.

Read the concrete path live instead of guessing the volume number:
`accountd -E` on the login node lists the account's project groups,
their `/vol0X0X/data/<group>/` paths, and quota usage.

## The standard A64FX layout

4 ranks per node (`processes_per_node: 4`) with 12 OpenMP threads per rank
(`OMP_NUM_THREADS=12` in `environment`), fully using the 48 cores per node.

## LLIO is mandatory at scale — big jobs get killed without it

Above ~7,000 nodes (~28,000 ranks), common-file handling is **not
optional**. Fugaku's own guidance is that one shared file opened by that
many processes slows I/O or takes the SIO down, and site admins kill jobs
that skip `llio_transfer` — even just for the executable, which every
rank opens at startup along with its `NEEDED` libraries. Apply this whole
checklist whenever `node_count × processes_per_node` reaches ~28,000, whenever
one file is opened by all ranks at that scale, and as good practice well
below it.

1. **Transfer every shared, read-only file in `pre_launch`, before
   `mpiexec` and before anything opens it:** the executable, every input
   file all ranks read, and any shared library resolving to `/home` or
   `/vol000N` (find them with `readelf -d <exe> | grep NEEDED` plus
   RPATH/RUNPATH; system libs under `/opt/FJSVxtclanga` and `/lib64` live
   on the compute-node image — not user disk — and need no transfer).
   `llio_transfer <path>...` copies the file to every assigned SIO; ranks
   keep using the same path. Rules: read-only files only — **never
   transfer a file the job also writes** (writes through the cache path
   fail; e.g. Nekir reads `<Name>.DensAlp.mtx` as the SCF guess and
   overwrites it at job end — exclude it) — ≤16,384 files per job,
   ≤1,024 open simultaneously, no file locking, auto-deleted at job end
   (`--purge` frees cache mid-job), never modify a source file during the
   job. Also exclude pure outputs and inputs the program never reads.
2. **Budget the ~87 GiB first-layer SSD per node:**
   `cache = 87 GiB − localtmp − sharedtmp` (the cache must stay ≥128 MiB
   or `pjsub` rejects the job). Common files occupy **full copies per SIO
   node**; ordinary outputs are **striped** (`stripe-count`, default/max
   24). `sharedtmp-size=80Gi` leaves only ~7 GiB for cache — too little
   once big inputs are transferred; size it so the cache fits the transfer
   list plus the job's striped-write peak (e.g. `sharedtmp-size=40Gi` for
   ~15 GiB of common files plus multi-GB per-SIO write stripes).
3. **Express `--llio` via the `custom_attributes` pass-through:**
   `{"llio": "sharedtmp-size=40Gi,perf"}` renders
   `#PJM --llio sharedtmp-size=40Gi,perf`; comma-separate several options
   in one value. Options: `localtmp-size`, `sharedtmp-size`,
   `sio-read-cache` (default on), `stripe-count` (default/max 24),
   `async-close` (default **off** — keep it: synchronous close guarantees
   `close()` flushes to FEFS; `on` risks losing unflushed data when the
   job is elapse-killed or a node dies), `perf[,perf-path=]` (LLIO
   counters), `uncompleted-fileinfo-path=` (files still unflushed at job
   end). Writes under `/vol000N` flush through the cache on close by
   default; an elapse kill mid-write deletes the cache and unwritten
   files are listed on stderr — leave write-tail margin in `elapse`.

JobSpec fragment for a ~32k-rank run (8192 nodes × 4 ranks):

```json
"resources": {"node_count": 8192, "processes_per_node": 4},
"attributes": {
  "queue_name": "f-pt", "account": "<groupname>",
  "custom_attributes": {"gfscache_volume": "/vol0004",
                        "llio": "sharedtmp-size=40Gi,perf"}
},
"pre_launch": "cp input.inp INPUT && llio_transfer INPUT <name>.Geom \
<name>.Basis <name>.NucRepl <name>.Overlap.mtx <name>.HCore.mtx <abs>/prog.exe"
```

Whole directories of modules use the wrapper
`/home/system/tool/dir_transfer [-l logdir] dir...`. Source: Fugaku User
Guide §8 "Layered storage" (§8.3 cache of second-layer storage, §8.3.5
`llio_transfer`, §8.6 high-parallel-job I/O limits).

## f-pt costs Fugaku Points

**`f-pt` is a priority queue that consumes Fugaku Points — it is not
free.** Confirm with the user before using it, and check the selected
project's remaining balance with `get_project_allocations(facility="fugaku",
project_id="<group>")`. Use it only for deliberate fast-turnaround
validation; revert to `small` for production runs.

Use `small` with a short `elapse` for validation jobs.

## Universal rules (apply on every facility, not just this one)

- `submit_job(facility="fugaku", spec=spec)` — **show the user the spec
  (or a plain-language description of it) before submitting, unless
  they've explicitly said to just run it.** No exceptions for this call.
- The returned `{"job_id": ..., "script_path": ...}` — the rendered script
  is kept on the cluster; `fs_view(facility="fugaku", path=script_path)`
  to inspect exactly what was submitted.
- If a partition/queue/GPU choice isn't given or obvious, check
  `get_resources(facility="fugaku")` (live occupancy) and
  `get_facility(facility="fugaku")` (static limits) — don't guess.
- Don't run heavy computation on the login node — submit a job instead.
- Stage anything the cluster needs (source trees, inputs, uploads, run
  directories) under `~/agent/work/<descriptive-name>/`, never in the
  home-directory root. `~/agent/` is the agent's visible scratch area —
  `~/agent/jobs` already holds every submitted script — and the home
  root stays the user's own.
- Don't guess facility-specific details not covered by the notes above —
  use `search_docs(facility="fugaku", query=...)` on the `hpc-docs`
  server. It searches a bundled guide, not a live site — never invent a URL
  to send the user to.
- Don't call `cancel_job` without confirming with the user first.
