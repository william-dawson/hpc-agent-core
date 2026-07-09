"""SchedulerBackend ABC and scheduler-neutral script body."""
from __future__ import annotations

import shlex
from abc import ABC, abstractmethod
from datetime import datetime

from hpc_agent_core.models import Job, JobSpec


def duration_to_hms(duration: int | str) -> str:
    """Convert IRI duration (int seconds or HH:MM:SS string) to HH:MM:SS."""
    if isinstance(duration, str):
        return duration
    h, rem = divmod(int(duration), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def to_epoch(s: str) -> float | None:
    """Parse a datetime string (ISO-like) to epoch seconds."""
    if not s or s in ("Unknown", "N/A", "None", ""):
        return None
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def parse_exit_code(s: str) -> int | None:
    """Parse an exit-code field like '0:0' → 0."""
    try:
        return int(s.split(":")[0])
    except (ValueError, IndexError):
        return None


def render_body(spec: JobSpec, gpu_requested: bool, gpu_vendor_flag: str = "--nv") -> str:
    """Render the scheduler-neutral body of a batch script.

    Covers everything after the scheduler-specific header: environment exports,
    pre_launch, the command (optionally wrapped in a Singularity container),
    launcher prefix, and post_launch. Starts with a blank line to separate
    from the header.

    gpu_vendor_flag is the Singularity container GPU flag to add when a
    container job requests GPUs (e.g. "--nv" for NVIDIA, "--rocm" for AMD).
    Pass "" to add no vendor flag (e.g. a machine where GPUs aren't
    container-managed).
    """
    lines: list[str] = [""]  # blank line after headers

    for key, value in spec.environment.items():
        lines.append(f"export {key}={shlex.quote(value)}")

    if spec.pre_launch:
        lines.append(spec.pre_launch)

    command = spec.executable
    if spec.arguments:
        command += " " + " ".join(shlex.quote(a) for a in spec.arguments)

    if spec.container:
        c = spec.container
        sing_flags: list[str] = []
        if gpu_requested and gpu_vendor_flag:
            sing_flags.append(gpu_vendor_flag)
        for m in c.volume_mounts:
            bind = f"{m.source}:{m.target}" + (":ro" if m.read_only else "")
            sing_flags.append(f"--bind {shlex.quote(bind)}")
        # Double-quote image so shell variables like $HOME expand in the script
        sing_flags.append(f'"{c.image}"')
        command = "singularity exec " + " ".join(sing_flags) + " bash -c " + shlex.quote(command)

    if spec.launcher:
        command = spec.launcher + " " + command
    lines.append(command)

    if spec.post_launch:
        lines.append(spec.post_launch)

    lines.append("")
    return "\n".join(lines)


class SchedulerBackend(ABC):
    """Abstract base class for a batch-scheduler backend."""

    name: str

    @abstractmethod
    def render_script(self, spec: JobSpec) -> str:
        """Render *spec* as a scheduler-specific batch script."""

    @abstractmethod
    def submit(self, spec: JobSpec) -> dict:
        """Submit *spec*; return ``{job_id, script_path}``."""

    @abstractmethod
    def get_statuses(self, job_ids: list[str]) -> list[Job]:
        """Return normalized status for each job in *job_ids*."""

    @abstractmethod
    def get_recent_statuses(self, since: str = "now-2days") -> list[Job]:
        """Return live/recent jobs for the current user."""

    @abstractmethod
    def cancel(self, job_id: str) -> Job | str:
        """Cancel *job_id* and return its resulting state."""

    def get_live_resources(self) -> list[dict]:
        """Live per-partition/queue occupancy (allocated/idle/other/total
        node counts) — the IRI `GET /resources` list, i.e. "will a job start
        soon", as opposed to get_facility's static hardware description.

        Optional: not every scheduler backend implements this (the default
        raises NotImplementedError so a machine's hpc_server.py gets a clear
        error rather than something silently returning nothing). Override in
        a subclass if your scheduler supports a live query for this —
        SlurmBackend already does, via sinfo.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement get_live_resources()"
        )

    def get_drained_nodes(self) -> list[dict]:
        """Nodes currently drained/down and why, if the scheduler exposes
        this. Optional, same default-raises convention as get_live_resources()."""
        raise NotImplementedError(
            f"{type(self).__name__} does not implement get_drained_nodes()"
        )
