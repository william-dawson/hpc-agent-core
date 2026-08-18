Fugaku is **A64FX (Arm SVE) and has no GPUs** — never set `resources.gpus`
or `resources.gpu_cores_per_process`; both are rejected outright.

## Workflow

1. **Choose a PJM resource group** for `attributes.queue_name` — there is
   no default, deliberately, because which groups an account may use
   differs per project. `small` (1–384 nodes, up to 72h), `large` (385+
   nodes, up to 24h), `int` (interactive), `f-pt` (priority, see below), or
   a `spot-*` low-priority variant. Confirm the real min/max/default for
   this account with
   `run_command_on_cluster(facility="{{SLUG}}", command="pjacl --rg small")`.
2. **Every job needs a project group.** Set `attributes.account`
   explicitly, or rely on `defaults.group` in the config file (or
   `{{ENV_PREFIX}}_GROUP`) — `submit_job` raises a clear error if neither
   is set. The shared `fugaku` group **cannot submit jobs**. If the
   resolved group is `trial` (the "Startup Project" every new account
   gets), only the `spot-*` resource groups work — `small`/`large`/`int`
   are rejected. Check `run_command_on_cluster(facility="{{SLUG}}",
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

   **Use a single volume.** A comma-separated list is accepted by `pjsub`
   at submission time but then fails the pre-execution gate check: the job
   is queued, never runs, and ends in PJM state `ERR` with
   `REASON : GATE CHECK` and no output file at all. Verified live — the
   same job with one volume, or with none, queued normally. If a user's
   configured `defaults.gfscache_volume` contains a comma, that is the
   first thing to suspect for an `ERR`/GATE CHECK job.
5. **Leave `stdout_path`/`stderr_path` unset** — PJM has no flag for
   redirecting them. Output always lands at `<name>.<job_id>.out`/`.err` in
   the submission directory. Set `spec.directory` if you want it elsewhere.

## The standard A64FX layout

4 ranks per node (`processes_per_node: 4`) with 12 OpenMP threads per rank
(`OMP_NUM_THREADS=12` in `environment`), fully using the 48 cores per node.

## f-pt costs Fugaku Points

**`f-pt` is a priority queue that consumes Fugaku Points — it is not
free.** Confirm with the user before using it, and check the remaining
balance with `run_command_on_cluster(facility="{{SLUG}}",
command="accountj_pt")`. Use it only for deliberate fast-turnaround
validation; revert to `small` for production runs.

Use `small` with a short `elapse` for validation jobs.
