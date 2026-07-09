"""SlurmBackend — config-driven across the dialects seen so far (PLAN.md §3a).

Independent knobs, each backed by real evidence from an existing or
documented port rather than guessed:

- has_accounting (bool): whether sacct/sacctmgr are available.
  * True  (Rikyu, Octopus, RCCS-Cloud): status comes from sacct;
    get_recent_statuses can look back by --starttime.
  * False (Banyan, Dgx1 — per the porting knowledge-transfer reports; not
    live-verified in this repo, see the warning below): status comes from
    squeue (live jobs) falling back to `scontrol show job` (jobs that just
    finished — Slurm keeps these for a short time, MinJobAge, after which
    they're simply gone; there is no longer-term history without sacct).
    get_recent_statuses degrades to "the current user's live queue" — no
    multi-day lookback is possible.
- gpu_request_style ("gpus_total" | "gres"): which flag requests GPUs.
  * "gpus_total" (Rikyu, HOKUSAI, RCCS-Cloud): --gpus=N is a job-wide count.
  * "gres" (Octopus, and per the KT reports, Banyan/Dgx1): --gres=gpu:N,
    untyped.
- nodes_always_explicit (bool | None): whether Slurm derives node count from
  the GPU count (so --nodes is only emitted when the caller overrides the
  default of 1) or --nodes is always emitted. **Independent of
  gpu_request_style** — this conflation was PHASE4_AUDIT.md §1.1's finding:
  RCCS-Cloud uses the "gpus_total" flag but always emits --nodes explicitly,
  a combination the two of these together (not one enum) are needed to
  express. Defaults to True for "gres", False for "gpus_total" when not
  given explicitly, matching every dialect seen so far without an override;
  RCCS-Cloud is the one machine that needs to override it.
- no_gpu_flag_prefixes (frozenset[str]): partition-name prefixes that get NO
  GPU flag at all, e.g. RCCS-Cloud's unified CPU+GPU superchip partitions
  ("qc-gh200", "ng-dgx-m") where the GPU is implicit and --gpus/--gres would
  be wrong to emit.
- gpu_vendor_map (dict[str, str]): partition-name-prefix -> container GPU
  flag, e.g. {"h200": "--nv", "mi300x": "--rocm"} for Octopus's dual-vendor
  cluster. Empty (the default) means single-vendor — every GPU job gets
  default_gpu_vendor_flag, no branching, matching Rikyu/HOKUSAI.

IMPORTANT — has_accounting=False is not live-verified here: it's implemented
directly from the Banyan-port knowledge-transfer report's specific command
recommendations (squeue/scontrol field names, the "no sacct read-back on
cancel" rule), but no no-accounting machine is repointed at this package yet.
Per the porting lessons ("doctor-green hid the real accounting gap"),
confirm this path against a real job on a no-accounting machine before
trusting it — don't assume doctor passing is enough.

Extending further: machine repos have no write access to hpc-agent-core
(PLAN.md §2b). A dialect these three knobs don't cover should subclass
SlurmBackend in the machine's own repo and override just the one method
that differs, rather than forking this file.
"""
from __future__ import annotations

import shlex
import time

from hpc_agent_core.middleware import run_command, write_remote_file
from hpc_agent_core.models import Job, JobSpec, JobState, JobStatus, map_slurm_state
from .base import SchedulerBackend, duration_to_hms, parse_exit_code, render_body, to_epoch

_SACCT_FIELDS = "JobID,JobName,Partition,State,Elapsed,Start,End,ExitCode,NodeList,WorkDir"
_SQUEUE_FIELDS = "%i|%T|%R|%P|%Z"  # id|state|reason|partition|workdir(cwd at submit)

_GPU_REQUEST_STYLES = ("gpus_total", "gres")


def _parse_sacct(output: str) -> list[Job]:
    jobs = []
    for line in output.strip().splitlines():
        parts = line.split("|")
        if len(parts) < 10 or parts[0] == "JobID":
            continue
        if "." in parts[0]:  # skip job steps (e.g. 15614.batch)
            continue
        native_state = parts[3]
        state = map_slurm_state(native_state)
        start_epoch = to_epoch(parts[5])
        end_epoch = to_epoch(parts[6])
        status_time = end_epoch if end_epoch else start_epoch
        jobs.append(Job(
            id=parts[0],
            status=JobStatus(
                state=state,
                time=status_time,
                exit_code=parse_exit_code(parts[7]),
                meta_data={
                    "native_state": native_state,
                    "name": parts[1],
                    "partition": parts[2],
                    "elapsed": parts[4],
                    "start_time": parts[5],
                    "end_time": parts[6],
                    "nodes": parts[8],
                    "workdir": parts[9],
                },
            ),
        ))
    return jobs


def _attach_reasons(jobs: list[Job]) -> list[Job]:
    """For queued/held jobs, attach the squeue wait reason as status.message.

    Only used on the has_accounting=True path — sacct has no wait-reason
    field, so this is a follow-up squeue call. The has_accounting=False path
    gets the reason "for free" as part of its primary squeue query instead.
    """
    waiting = [j for j in jobs if j.status and j.status.state in (JobState.QUEUED, JobState.HELD)]
    if not waiting:
        return jobs
    ids = ",".join(j.id for j in waiting)
    output = run_command(f"squeue --jobs={ids} --format='%i|%R' --noheader")
    reasons = dict(
        line.split("|", 1) for line in output.strip().splitlines() if "|" in line
    )
    for job in jobs:
        if job.status and job.id in reasons:
            job.status.message = reasons[job.id].strip()
    return jobs


def _parse_squeue(output: str) -> list[Job]:
    """Parse `squeue --format='{_SQUEUE_FIELDS}'` output (live jobs only —
    finished jobs simply disappear from squeue)."""
    jobs = []
    for line in output.strip().splitlines():
        parts = line.split("|")
        if len(parts) < 5:
            continue
        job_id, native_state, reason, partition, workdir = parts[:5]
        reason = reason.strip()
        state = map_slurm_state(native_state)
        # %R is a wait reason for QUEUED/HELD jobs but the *node list* for an
        # ACTIVE job — only surface it as `message` where it's actually a
        # reason, so message doesn't hold a node name for a running job.
        message = None
        if state in (JobState.QUEUED, JobState.HELD) and reason and reason not in ("None", "(null)"):
            message = reason
        jobs.append(Job(
            id=job_id,
            status=JobStatus(
                state=state,
                message=message,
                meta_data={"native_state": native_state, "partition": partition, "workdir": workdir},
            ),
        ))
    return jobs


def _parse_scontrol_show_job(output: str) -> Job | None:
    """Parse `scontrol show job <id>` — the has_accounting=False fallback for
    a job that just left the queue. Returns None if scontrol no longer knows
    about it (it ages out ~MinJobAge, default 300s, after completion; past
    that there is simply no record without sacct).
    """
    text = output.strip()
    if not text or "invalid job id" in text.lower():
        return None
    fields: dict[str, str] = {}
    for token in text.split():
        if "=" in token:
            key, _, val = token.partition("=")
            fields[key] = val
    job_id = fields.get("JobId")
    if not job_id:
        return None
    native_state = fields.get("JobState", "")
    end_epoch = to_epoch(fields.get("EndTime", ""))
    start_epoch = to_epoch(fields.get("StartTime", ""))
    return Job(
        id=job_id,
        status=JobStatus(
            state=map_slurm_state(native_state),
            time=end_epoch if end_epoch else start_epoch,
            exit_code=parse_exit_code(fields.get("ExitCode", "")),
            meta_data={
                "native_state": native_state,
                "partition": fields.get("Partition", ""),
                "workdir": fields.get("WorkDir", ""),
                "nodes": fields.get("NodeList", ""),
            },
        ),
    )


class SlurmBackend(SchedulerBackend):
    def __init__(self, name: str = "slurm", jobs_dir: str = "agent/jobs",
                 has_accounting: bool = True,
                 gpu_request_style: str = "gpus_total",
                 nodes_always_explicit: bool | None = None,
                 no_gpu_flag_prefixes: frozenset[str] | None = None,
                 gpu_vendor_map: dict[str, str] | None = None,
                 default_gpu_vendor_flag: str = "--nv"):
        """
        gpu_request_style / nodes_always_explicit are deliberately two
        independent knobs (PHASE4_AUDIT.md §1.1 caught this — RCCS-Cloud
        uses "gpus_total"'s flag but "gres"'s always-explicit --nodes,
        a combination a single conflated enum couldn't express):
        - gpu_request_style: "gpus_total" (--gpus=N) | "gres" (--gres=gpu:N).
        - nodes_always_explicit: when False, --nodes is omitted unless the
          caller sets node_count != 1, letting Slurm derive placement from
          the GPU count (Rikyu/HOKUSAI). When True, --nodes is always
          emitted (Octopus, RCCS-Cloud). Defaults to True for "gres" and
          False for "gpus_total" if not given explicitly — matching every
          real dialect seen so far without needing an override — but
          RCCS-Cloud needs the explicit override (gpus_total + always-explicit).
        no_gpu_flag_prefixes: partition-name prefixes that need NO GPU flag
          at all, e.g. RCCS-Cloud's unified CPU+GPU superchip partitions
          ("qc-gh200", "ng-dgx-m") where --gpus/--gres would be wrong to emit.
        """
        if gpu_request_style not in _GPU_REQUEST_STYLES:
            raise ValueError(f"gpu_request_style must be one of {_GPU_REQUEST_STYLES}, got {gpu_request_style!r}")
        self.name = name
        self._jobs_dir = jobs_dir
        self.has_accounting = has_accounting
        self.gpu_request_style = gpu_request_style
        self.nodes_always_explicit = (
            (gpu_request_style == "gres") if nodes_always_explicit is None else nodes_always_explicit
        )
        self.no_gpu_flag_prefixes = frozenset(no_gpu_flag_prefixes or ())
        self.gpu_vendor_map = dict(gpu_vendor_map or {})
        self.default_gpu_vendor_flag = default_gpu_vendor_flag

    def _resolve_gpu_vendor_flag(self, queue_name: str) -> str:
        """partition-name prefix -> container GPU flag, e.g. Octopus's
        {"h200": "--nv", "mi300x": "--rocm"}. Falls back to
        default_gpu_vendor_flag when gpu_vendor_map is empty (single-vendor
        machines like Rikyu/HOKUSAI) or the partition matches no prefix."""
        for prefix, flag in self.gpu_vendor_map.items():
            if queue_name.startswith(prefix):
                return flag
        return self.default_gpu_vendor_flag

    def _gpu_flag_suppressed(self, queue_name: str) -> bool:
        """True for a partition where no --gpus/--gres flag should be
        emitted at all (e.g. a unified CPU+GPU superchip partition)."""
        return any(queue_name.startswith(p) for p in self.no_gpu_flag_prefixes)

    def _header(self, spec: JobSpec) -> list[str]:
        res = spec.resources
        attr = spec.attributes
        # gpus takes precedence over PSI/J gpu_cores_per_process
        gpus = res.gpus if res.gpus else res.gpu_cores_per_process

        lines = [
            "#!/bin/bash",
            f"#SBATCH --job-name={spec.name}",
            f"#SBATCH --partition={attr.queue_name}",
            f"#SBATCH --time={duration_to_hms(attr.duration)}",
        ]
        if gpus and not self._gpu_flag_suppressed(attr.queue_name):
            if self.gpu_request_style == "gpus_total":
                lines.append(f"#SBATCH --gpus={gpus}")
            else:  # "gres"
                lines.append(f"#SBATCH --gres=gpu:{gpus}")

        if self.nodes_always_explicit or res.node_count != 1:
            lines.append(f"#SBATCH --nodes={res.node_count}")

        lines.append(f"#SBATCH --ntasks-per-node={res.processes_per_node}")
        if res.process_count:
            lines.append(f"#SBATCH --ntasks={res.process_count}")
        if res.cpu_cores_per_process:
            lines.append(f"#SBATCH --cpus-per-task={res.cpu_cores_per_process}")
        if res.exclusive_node_use:
            lines.append("#SBATCH --exclusive")
        if res.memory:
            mb = max(1, res.memory // (1024 * 1024))
            lines.append(f"#SBATCH --mem={mb}M")
        if attr.account:
            lines.append(f"#SBATCH --account={attr.account}")
        if attr.reservation_id:
            lines.append(f"#SBATCH --reservation={attr.reservation_id}")
        if spec.directory:
            lines.append(f"#SBATCH --chdir={spec.directory}")
        if spec.stdin_path:
            lines.append(f"#SBATCH --input={spec.stdin_path}")
        if spec.stdout_path:
            lines.append(f"#SBATCH --output={spec.stdout_path}")
        if spec.stderr_path:
            lines.append(f"#SBATCH --error={spec.stderr_path}")
        for key, val in attr.custom_attributes.items():
            lines.append(f"#SBATCH --{key}={val}")
        return lines

    def render_script(self, spec: JobSpec) -> str:
        """Render a JobSpec as an sbatch script."""
        res = spec.resources
        gpu_requested = bool(res.gpus or res.gpu_cores_per_process)
        vendor_flag = self._resolve_gpu_vendor_flag(spec.attributes.queue_name)
        return "\n".join(self._header(spec)) + render_body(spec, gpu_requested, vendor_flag)

    def submit(self, spec: JobSpec) -> dict:
        """Write the rendered script on the cluster and sbatch it."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        script_path = write_remote_file(
            f"{self._jobs_dir}/{spec.name}-{stamp}.sh", self.render_script(spec)
        )
        output = run_command(f"sbatch --parsable {shlex.quote(script_path)}")
        # --parsable prints "<job_id>" or "<job_id>;<cluster>"
        job_id = output.strip().splitlines()[-1].split(";")[0] if output.strip() else ""
        if not job_id.isdigit():
            raise RuntimeError(f"sbatch failed: {output}")
        return {"job_id": job_id, "script_path": script_path}

    def _scontrol_fallback(self, job_id: str) -> Job:
        """scontrol show job <id> — the has_accounting=False fallback for a
        job not found live in squeue."""
        scontrol_out = run_command(f"scontrol show job {shlex.quote(job_id)}")
        job = _parse_scontrol_show_job(scontrol_out)
        if job:
            return job
        return Job(id=job_id, status=JobStatus(
            state=JobState.UNKNOWN,
            message="Not found in squeue or scontrol. This machine has no Slurm "
                    "accounting, so a job aged out of scontrol's short-lived "
                    "record (~MinJobAge after completion) has no further history.",
        ))

    def _get_status_no_accounting(self, job_id: str) -> Job:
        """squeue (live) falling back to scontrol (just-finished), for a
        single job_id — used by cancel(). get_statuses() batches the squeue
        call across every requested id instead of calling this per-id."""
        try:
            squeue_out = run_command(f"squeue --jobs={shlex.quote(job_id)} --format='{_SQUEUE_FIELDS}' --noheader")
        except RuntimeError:
            squeue_out = ""  # squeue can error on an id it no longer knows about
        live = _parse_squeue(squeue_out)
        return live[0] if live else self._scontrol_fallback(job_id)

    def _get_statuses_no_accounting(self, job_ids: list[str]) -> list[Job]:
        """One batched squeue call for every requested id (live jobs), then
        scontrol only for whichever ids weren't found live — cuts SSH
        round-trips substantially versus querying each id independently."""
        if not job_ids:
            return []
        ids = ",".join(shlex.quote(j) for j in job_ids)
        try:
            squeue_out = run_command(f"squeue --jobs={ids} --format='{_SQUEUE_FIELDS}' --noheader")
        except RuntimeError:
            squeue_out = ""  # squeue can error if the whole batch has an id it doesn't know
        live = {j.id: j for j in _parse_squeue(squeue_out)}
        return [live[jid] if jid in live else self._scontrol_fallback(jid) for jid in job_ids]

    def get_statuses(self, job_ids: list[str]) -> list[Job]:
        """Fetch normalized statuses for one or more jobs."""
        if not self.has_accounting:
            return self._get_statuses_no_accounting(job_ids)
        ids = ",".join(shlex.quote(j) for j in job_ids)
        output = run_command(
            f"sacct --jobs={ids} --format={_SACCT_FIELDS} --parsable2 --noheader"
        )
        return _attach_reasons(_parse_sacct(output))

    def get_recent_statuses(self, since: str = "now-2days") -> list[Job]:
        """Statuses of the current user's jobs since the given time.

        On a has_accounting=False machine, `since` is ignored: without
        sacct there is no history to look back through, so this degrades to
        the current user's live queue only (matches the Banyan/Dgx1 KT
        reports' documented limitation).
        """
        if not self.has_accounting:
            output = run_command(f"squeue -u $USER --format='{_SQUEUE_FIELDS}' --noheader")
            return _parse_squeue(output)
        output = run_command(
            f"sacct --starttime={shlex.quote(since)} --format={_SACCT_FIELDS} "
            f"--parsable2 --noheader"
        )
        return _attach_reasons(_parse_sacct(output))

    def cancel(self, job_id: str) -> Job | str:
        """scancel, then report the job's state.

        On a has_accounting=False machine, the state is re-read via
        squeue/scontrol rather than sacct (which doesn't exist there) —
        per the Banyan KT report's explicit recommendation not to read the
        final state back via sacct on this dialect.
        """
        run_command(f"scancel {shlex.quote(job_id)}")
        if not self.has_accounting:
            return self._get_status_no_accounting(job_id)
        jobs = self.get_statuses([job_id])
        return jobs[0] if jobs else f"scancel sent; job {job_id} not found in sacct"
