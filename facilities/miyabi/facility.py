"""Miyabi (JCAHPC) registration for the unified hub.

This port is derived from the separately live-tested Miyabi-Agent repository.
It has not been revalidated against Miyabi since joining this hub because the
facility is currently inaccessible.  Keep that distinction visible: the PBS
dialect below is evidence-backed, but a new live doctor/read-only/job smoke
run is still required when access returns.

Miyabi's interactive 2FA means the supported arrangement is unusual: run the
agent on a Miyabi login node and set ssh.host to ``localhost``.  That invokes
a local login shell; it does not automate or bypass the remote login.
"""
import os
from pathlib import Path

from hpc_agent_core import config
from hpc_agent_core.models import JobSpec
from facilities.miyabi.compute import PBSBackend
from facilities.registry import register_backend

SLUG = "miyabi"

FACILITY = config.register_facility(
    slug=SLUG,
    display_name="Miyabi (JCAHPC)",
    description="JCAHPC Miyabi: 1,120-node Grace Hopper GPU system plus "
                "190-node Xeon Max CPU system, PBS Professional, full-GPU "
                "and MIG queues. The agent runs locally on a login node.",
    default_host="localhost",
    data_dir=Path(__file__).parent / "data",
    # No Miyabi embedding service has been verified. Keyword search is the
    # deliberate default until a real endpoint is confirmed.
    embed_base_url="",
    embed_model="",
    docs_cite_url="",
    config_example={
        "ssh": {"host": "localhost"},
        "defaults": {"group": "<your-project-group>"},
    },
    setup_help=(
        "Run Codex/Claude and this plugin on a Miyabi login node; remote SSH\n"
        "automation is unsupported because Miyabi login requires interactive\n"
        "2FA. Use ssh.host=localhost, which runs a local shell and does not\n"
        "start SSH or bypass 2FA. Set defaults.group to your own PBS project\n"
        "group: every job requires #PBS -W group_list=<group>. Never copy a\n"
        "group from another user. MIYABI_GROUP overrides the configured group."
    ),
)


def _default_group() -> str | None:
    """MIYABI_GROUP > the user's defaults.group; never a bundled fallback."""
    cfg = config.file_config(SLUG)
    return (os.environ.get(f"{FACILITY.env_prefix}_GROUP")
            or (cfg.get("defaults") or {}).get("group"))


class MiyabiBackend(PBSBackend):
    def apply_defaults(self, spec: JobSpec) -> None:
        """Resolve the mandatory per-user PBS project group.

        There is deliberately no queue default: CPU, full-GPU and MIG queues
        have materially different resources, and even their debug variants
        are not interchangeable.
        """
        if spec.attributes.account is None:
            spec.attributes.account = _default_group()
        if not spec.attributes.account:
            raise ValueError(
                "Miyabi requires a project group for every job "
                "(#PBS -W group_list=<group>). Set spec.attributes.account, "
                f"or configure defaults.group in {config.config_path(SLUG)} "
                f"(or the {FACILITY.env_prefix}_GROUP environment variable). "
                "Use your own allocation; there is no safe shared fallback."
            )


BACKEND = MiyabiBackend(facility=SLUG)
register_backend(SLUG, BACKEND)
