"""RIKYU (RIKEN AI4S / GB200) registration — see PORTING.md.

RIKYU is Slurm, single GPU vendor (NVIDIA), a job-total `--gpus=N` GPU
request style, and Slurm derives node count from the GPU count (no job
script in the RIKYU user guide ever sets --nodes explicitly). Accounting
(sacct/sacctmgr) is available — the first row of PORTING.md's dialect
table, and hpc_agent_core.compute.slurm.SlurmBackend's own docstring lists
Rikyu by name as a verified `has_accounting=True,
gpu_request_style="gpus_total"` facility — no override of
nodes_always_explicit or gpu_vendor_map is needed.

RIKYU only accepts a fixed set of per-job GPU counts (see rikyu_config.json's
job_resources.supported_gpu_counts) and has exactly one partition, "gpu" —
both facility-specific enough to live here as SchedulerBackend hook
overrides rather than in the generic server.
"""
from pathlib import Path

from hpc_agent_core import config
from hpc_agent_core.compute.slurm import SlurmBackend
from hpc_agent_core.models import JobSpec
from facilities.registry import register_backend

SLUG = "rikyu"

FACILITY = config.register_facility(
    slug=SLUG,
    display_name="RIKYU (RIKEN AI4S / GB200)",
    description="RIKEN AI4S GB200 GPU cluster (400 nodes, single 'gpu' "
                 "partition), Slurm with accounting, job-total GPU request.",
    default_host="login.rikyu.r-ccs.riken.jp",
    data_dir=Path(__file__).parent / "data",
    embed_base_url="http://llm.ai.r-ccs.riken.jp:11434/v1",  # shared RIKEN R-CCS endpoint
    embed_model="bge-m3:567m",
    docs_cite_url="",  # RIKYU is in Early Access; leave blank per PORTING.md
)


class RikyuBackend(SlurmBackend):
    def apply_defaults(self, spec: JobSpec) -> None:
        """RIKYU has exactly one partition, so a blank queue_name always
        means "gpu".

        No account default is filled in here, unlike HBW2 — but note that a
        user who belongs to more than one RIKYU project *does* get a hard
        sbatch rejection ("You belong to multiple projects, so the project
        to be charged must be specified explicitly") when a job omits
        --account. Verified live. Such a user must set
        spec.attributes.account per job today; wiring HBW2-style
        config-driven account defaulting for RIKYU too would be a small,
        obviously-correct follow-up (see facilities/hokusai/facility.py for
        the pattern) — it just hasn't been done yet.
        """
        if not spec.attributes.queue_name:
            spec.attributes.queue_name = "gpu"

    def validate_spec(self, spec: JobSpec) -> None:
        """RIKYU only accepts these GPU counts per job (Job Resources guide
        page) — everything else about the resource ceiling (node count, CPU
        cores, memory) follows deterministically from this count, so a bad
        count is worth catching before submission rather than as a
        confusing sbatch-time rejection."""
        gpus = spec.resources.gpus or spec.resources.gpu_cores_per_process
        if not gpus:
            return
        supported = config.load_facts(SLUG)["job_resources"]["supported_gpu_counts"]
        if gpus not in supported:
            raise ValueError(
                f"RIKYU only accepts these GPU counts per job: {supported}. Got {gpus}."
            )


BACKEND = RikyuBackend(
    facility=SLUG,
    has_accounting=True,
    gpu_request_style="gpus_total",
    jobs_dir="agent/jobs",  # the default; RIKYU has no reason to override it
)
register_backend(SLUG, BACKEND)
