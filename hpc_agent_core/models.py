"""Data models mirroring the IRI Facility API schemas.

The IRI (Integrated Research Infrastructure) Facility API is the DOE
standard for programmatic facility access (spec at api.alcf.anl.gov/openapi.json).
Its compute schemas follow PSI/J: a JobSpec with ResourceSpec + JobAttributes,
and a normalized JobState. We implement a pragmatic subset; deviations are
noted in each machine repo's IRI_CHECKLIST.md.

This module is machine-agnostic: field *shapes* live here, but per-machine
*defaults* (default partition, default GPU count, default duration, ...) do
not — those come from the machine's own config data. A machine's tool layer
is expected to fill in JobSpec/ResourceSpec/JobAttributes defaults itself
before calling submit(); until that layer exists, the neutral defaults below
(no GPUs, no partition, 1-hour duration) are placeholders, not
recommendations for any specific machine.
"""
from enum import Enum

from pydantic import BaseModel, Field


class JobState(str, Enum):
    """Normalized job states (IRI/PSI-J), mapped from scheduler-native states."""
    NEW = "new"
    QUEUED = "queued"
    HELD = "held"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    UNKNOWN = "unknown"


_SLURM_STATE_MAP = {
    "PENDING": JobState.QUEUED,
    "CONFIGURING": JobState.QUEUED,
    "REQUEUED": JobState.QUEUED,
    "SUSPENDED": JobState.HELD,
    "RUNNING": JobState.ACTIVE,
    "COMPLETING": JobState.ACTIVE,
    "STAGE_OUT": JobState.ACTIVE,
    "COMPLETED": JobState.COMPLETED,
    "CANCELLED": JobState.CANCELED,
    "FAILED": JobState.FAILED,
    "TIMEOUT": JobState.FAILED,
    "OUT_OF_MEMORY": JobState.FAILED,
    "NODE_FAIL": JobState.FAILED,
    "BOOT_FAIL": JobState.FAILED,
    "DEADLINE": JobState.FAILED,
    "PREEMPTED": JobState.FAILED,
}


def map_slurm_state(native: str) -> JobState:
    # sacct reports e.g. "CANCELLED by 12345"
    return _SLURM_STATE_MAP.get(native.split()[0].rstrip("+"), JobState.UNKNOWN)


# qstat single/multi-letter state codes (Altair/Univa Grid Engine), verified
# against shinobulab-cell-cluster-mcp's live-tested mapping (see PLAN.md §3b).
_GE_STATE_MAP = {
    "qw": JobState.QUEUED,    # waiting in queue
    "hqw": JobState.HELD,     # held while waiting
    "r": JobState.ACTIVE,     # running
    "t": JobState.ACTIVE,     # transferring (starting)
    "Rr": JobState.ACTIVE,    # re-started running (after node failure)
    "dr": JobState.CANCELED,  # deletion requested while running
    "dt": JobState.CANCELED,  # deletion requested while transferring
    "Eqw": JobState.FAILED,   # error in waiting state
    "Er": JobState.FAILED,    # error while running
    "s": JobState.HELD,       # suspended by owner
    "S": JobState.HELD,       # suspended by system/queue
    "ts": JobState.HELD,      # transferring + suspended
    "tS": JobState.HELD,      # transferring + system-suspended
}


def map_ge_state(native: str) -> JobState:
    """Map a Grid Engine qstat state letter to the shared JobState IR.

    Only covers live qstat letters; qacct-finished jobs are resolved by the
    GE backend via the failed / exit_status fields, not a state letter.
    """
    return _GE_STATE_MAP.get(native, JobState.UNKNOWN)


class Scheduler(str, Enum):
    """Target batch scheduler for a job submission — only meaningful on a
    machine that composes more than one SchedulerBackend (e.g. a cluster
    with both a Slurm partition and a Grid Engine partition). Single-scheduler
    machines can ignore this field entirely."""
    SLURM = "slurm"
    GRIDENGINE = "gridengine"


class ResourceSpec(BaseModel):
    """Resources for a job (PSI/J ResourceSpec + a GPU extension).

    gpus is a total-for-the-job GPU count extension (not in upstream PSI/J);
    gpu_cores_per_process is the PSI/J standard equivalent. If both are set,
    gpus takes precedence. How gpus maps to a scheduler flag (--gpus,
    --gres=gpu:N, --gpus-per-node) and whether node_count is derived from it
    or must be set explicitly is a per-machine SchedulerBackend concern —
    see that machine's compute/ module and config.
    """
    node_count: int = 1
    process_count: int | None = Field(None, description="Total processes (alternative to processes_per_node × node_count)")
    processes_per_node: int = 1
    cpu_cores_per_process: int | None = None
    gpu_cores_per_process: int | None = Field(None, description="PSI/J standard GPU field; prefer gpus where a machine supports it")
    gpus: int = Field(0, description="Total GPUs requested for the job (machine-specific extension); 0 means no GPU request")
    exclusive_node_use: bool = Field(False, description="Request exclusive node allocation (--exclusive)")
    memory: int | None = Field(None, description="Memory per node in bytes (maps to --mem)")


class JobAttributes(BaseModel):
    """Scheduler attributes (IRI/PSI/J JobAttributes subset).

    queue_name has no cross-machine default — each machine's tool layer
    should supply its own default_partition (from that machine's config)
    when a JobSpec omits one.
    """
    duration: int | str = Field(
        3600,
        description="Wall time as integer seconds or HH:MM:SS / D-HH:MM:SS string",
    )
    queue_name: str = Field("", description="Scheduler partition/queue; machine-specific default applied by the tool layer if omitted")
    account: str | None = Field(None, description="Account/project to charge")
    reservation_id: str | None = Field(None, description="Scheduler reservation name (--reservation)")
    custom_attributes: dict[str, str] = Field(default_factory=dict)
    scheduler: Scheduler | None = Field(None, description="Override which SchedulerBackend handles this job, on a machine with more than one; None means the machine's tool layer decides (e.g. from queue_name)")
    parallel_env: str = Field("smp", description="Grid Engine parallel environment (-pe); ignored by Slurm backends")


class CompressionType(str, Enum):
    """Compression format for fs_compress / fs_extract (IRI CompressionType)."""
    NONE = "none"
    BZIP2 = "bzip2"
    GZIP = "gzip"
    XZ = "xz"


class VolumeMount(BaseModel):
    """A host path mounted into a container (IRI VolumeMount)."""
    source: str = Field(description="Host path to mount")
    target: str = Field(description="Path inside the container")
    read_only: bool = Field(True, description="Mount as read-only")


class Container(BaseModel):
    """Container specification (IRI Container); executed via singularity exec.

    image must be a path to a .sif file (absolute or using $HOME) or a
    docker:// URI. GPU passthrough is added automatically by the rendering
    backend when the job requests GPUs (vendor-specific flag chosen by that
    machine's config, e.g. --nv vs --rocm). launcher (e.g. 'srun') is placed
    outside singularity exec so MPI works.
    """
    image: str = Field(description="Singularity image path or URI (e.g. docker://ubuntu:22.04)")
    volume_mounts: list[VolumeMount] = Field(default_factory=list)


class JobSpec(BaseModel):
    """Job specification (IRI/PSI/J JobSpec subset).

    executable plus arguments form the command run inside the batch script;
    executable may be a shell line (e.g. 'module load foo && srun ./app').
    launcher, if set, is prepended to executable (e.g. 'srun').
    pre_launch / post_launch are script lines inserted before / after.
    If container is set, the command is wrapped in 'singularity exec'.
    """
    name: str = "agent-job"
    executable: str
    arguments: list[str] = Field(default_factory=list)
    directory: str | None = Field(None, description="Working directory for the job")
    environment: dict[str, str] = Field(default_factory=dict)
    inherit_environment: bool = Field(True, description="Inherit submission environment variables")
    stdin_path: str | None = Field(None, description="Path to use as stdin (--input)")
    stdout_path: str | None = None
    stderr_path: str | None = None
    resources: ResourceSpec = Field(default_factory=ResourceSpec)
    attributes: JobAttributes = Field(default_factory=JobAttributes)
    pre_launch: str | None = Field(None, description="Script lines to insert before executable")
    post_launch: str | None = Field(None, description="Script lines to insert after executable")
    launcher: str | None = Field(None, description="Launcher prefix, e.g. 'srun' or 'mpirun -np 4'")
    container: Container | None = Field(None, description="Run inside a Singularity container")


class JobStatus(BaseModel):
    """IRI-compliant job status (state + time + message + exit_code + meta_data).

    Scheduler-specific detail (native_state, partition, nodes, workdir,
    elapsed, start/end times, queue reason) is carried in meta_data.
    """
    state: JobState
    time: float | None = Field(None, description="Epoch seconds: end_time if finished, start_time if running")
    message: str | None = Field(None, description="Human-readable status (queue reason, error, etc.)")
    exit_code: int | None = None
    meta_data: dict | None = Field(None, description="Scheduler-specific fields: native_state, partition, nodes, workdir, elapsed, etc.")


class Job(BaseModel):
    """IRI Job: identifier + current status + originating spec."""
    id: str
    status: JobStatus | None = None
    job_spec: JobSpec | None = None
