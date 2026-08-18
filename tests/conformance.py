"""Behavioral conformance checks that run against *every* registered facility.

This is the counterweight to PORTING.md §0a's "duplication between
facilities is fine". Facility code is deliberately written out per machine
rather than collapsed into shared abstractions — so the thing that keeps
those independent implementations honest is a shared *test*, not shared
code. When your facility establishes a behavior every facility should
honor, add the assertion here; it then applies to all of them, including
ones onboarded later, without any of them having to import each other.

Runs entirely offline — no SSH, no scheduler, no network. Everything here
must stay that way so CI can run it. Anything needing a live cluster
belongs in tests/live_smoke.py instead.

    .venv/bin/python tests/conformance.py
"""
import contextlib
import os
import sys
import traceback

import hpc_mcp  # noqa: F401 -- registers every facility
from hpc_agent_core import config
from hpc_agent_core.models import JobAttributes, JobSpec, ResourceSpec
from facilities.registry import get_backend

FAILURES: list[str] = []


@contextlib.contextmanager
def no_user_config(slug: str):
    """Point a facility's config at a path that doesn't exist.

    Without this, checks covering "the user hasn't configured X yet" only
    run on a machine that genuinely hasn't — so they silently pass on a
    developer's fully-configured laptop and on nobody's CI. Forcing the
    unconfigured state makes those paths deterministic everywhere.
    """
    var = f"{config.get_facility(slug).env_prefix}_CONFIG"
    previous = os.environ.get(var)
    os.environ[var] = "/nonexistent/conformance-forced-missing.json"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = previous


def check(label: str, fn) -> None:
    try:
        fn()
    except Exception:
        FAILURES.append(f"{label}\n{traceback.format_exc()}")
        print(f"  ✗ {label}")
    else:
        print(f"  ✓ {label}")


def bare_spec() -> JobSpec:
    """A minimal spec with everything optional left blank — what
    apply_defaults() is supposed to complete."""
    return JobSpec(
        name="conformance",
        executable="echo ok",
        resources=ResourceSpec(node_count=1, processes_per_node=1),
        attributes=JobAttributes(duration=300),
    )


# --- per-facility checks -------------------------------------------------

def check_facility(slug: str) -> None:
    fac = config.get_facility(slug)
    backend = get_backend(slug)

    def registration_is_complete():
        assert fac.display_name.strip(), "display_name is empty"
        assert fac.description.strip(), "description is empty"
        assert (fac.data_dir / fac.docs_filename).exists(), "guide file missing"
        assert (fac.data_dir / fac.facts_filename).exists(), "facts JSON missing"
        assert (fac.data_dir / "docs_index" / "chunks.json").exists(), "docs index missing"

    def facts_load():
        assert config.load_facts(slug), "facts JSON is empty"

    def apply_defaults_is_idempotent():
        """Running apply_defaults twice must not change the result — it's
        called by both render_job_script and submit_job, and an agent
        commonly renders then submits the same spec object."""
        first, second = bare_spec(), bare_spec()
        try:
            backend.apply_defaults(first)
        except ValueError:
            return  # a facility that requires an unset field; covered below
        backend.apply_defaults(first)          # second application
        backend.apply_defaults(second)
        assert first.attributes.queue_name == second.attributes.queue_name
        assert first.attributes.account == second.attributes.account

    def _defaults_then_validate_then_render():
        """The exact sequence submit_job runs. Either it produces a usable
        script, or it raises a ValueError that tells the user what to set —
        never an AttributeError/TypeError from a half-completed spec."""
        spec = bare_spec()
        try:
            backend.apply_defaults(spec)
            backend.validate_spec(spec)
        except ValueError as e:
            msg = str(e)
            assert len(msg) > 40, f"error too terse to act on: {msg!r}"
            # Must tell the user what to do about it, not just what's wrong.
            assert any(w in msg.lower() for w in ("set ", "configure", "use ")), \
                f"error doesn't tell the user what to do: {msg!r}"
            return
        script = backend.render_script(spec)
        assert script.startswith("#!"), "rendered script has no shebang"
        assert "echo ok" in script, "rendered script lost the executable"

    def defaults_then_validate_then_render():
        _defaults_then_validate_then_render()

    def defaults_then_validate_then_render_unconfigured():
        """Same, with the user's config forced missing — this is the path a
        brand-new user hits, and on a facility with a mandatory setting
        it's the *only* way the "you must configure X" error gets
        exercised at all."""
        with no_user_config(slug):
            _defaults_then_validate_then_render()

    def rendered_script_has_a_queue():
        """If apply_defaults supplies a queue, it must actually reach the
        script — catches a facility that sets the wrong attribute."""
        spec = bare_spec()
        try:
            backend.apply_defaults(spec)
            backend.validate_spec(spec)
        except ValueError:
            return
        if spec.attributes.queue_name:
            assert spec.attributes.queue_name in backend.render_script(spec), \
                "queue_name was defaulted but never appears in the script"

    def explicit_values_survive_defaults():
        """apply_defaults must never overwrite something the caller set."""
        spec = bare_spec()
        spec.attributes.queue_name = "caller-chosen-queue"
        spec.attributes.account = "caller-chosen-account"
        backend.apply_defaults(spec)
        assert spec.attributes.queue_name == "caller-chosen-queue", \
            "apply_defaults overwrote a caller-supplied queue_name"
        assert spec.attributes.account == "caller-chosen-account", \
            "apply_defaults overwrote a caller-supplied account"

    def backend_knows_its_facility():
        assert backend.facility == slug, \
            f"backend.facility is {backend.facility!r}, expected {slug!r}"

    def setup_directions_are_actionable():
        """What a user gets when they say "I want to use this machine" and
        nothing is configured. It has to stand on its own: the agent may
        not be able to open any other file, so the directions must name the
        config file, show what to put in it, and cover this machine's own
        prerequisites."""
        assert fac.setup_help.strip(), (
            "no setup_help registered — an unconfigured user would get generic "
            "directions with nothing machine-specific (how to get a key "
            "registered, the real login hostname, any required account)"
        )
        assert fac.config_example, "no config_example registered"
        assert "ssh" in fac.config_example, "config_example has no ssh section"

        with no_user_config(slug):
            text = config.setup_instructions(slug)
            expected_path = str(config.config_path(slug))
        assert expected_path in text, "directions omit the config file path"
        assert f"{slug}-configuring" in text, "directions don't name the configuring skill"
        assert "hpc-doctor" in text, "directions don't say how to verify"
        assert fac.setup_help.splitlines()[0] in text, "setup_help didn't reach the directions"
        # The example must be valid, copy-pasteable JSON.
        import json as _json
        _json.loads(_json.dumps(fac.config_example))

    def unconfigured_tools_still_answer():
        """The never-fail invariant, at tool granularity: everything that
        doesn't need the cluster must keep working with no config at all,
        so an agent can still orient the user before setup."""
        with no_user_config(slug):
            assert config.load_facts(slug), "get_facility would fail unconfigured"
            assert config.docs_source(slug).exists(), "guide unreadable unconfigured"
            assert fac.display_name and fac.description, "get_facilities would be degraded"

    print(f"\n=== {slug} ({fac.display_name}) ===")
    check("registration is complete", registration_is_complete)
    check("facts JSON loads", facts_load)
    check("backend is bound to this facility", backend_knows_its_facility)
    check("setup directions are machine-specific and actionable", setup_directions_are_actionable)
    check("no-config tools still answer (never-fail invariant)", unconfigured_tools_still_answer)
    check("apply_defaults is idempotent", apply_defaults_is_idempotent)
    check("apply_defaults never overwrites caller values", explicit_values_survive_defaults)
    check("defaults -> validate -> render, or an actionable error", defaults_then_validate_then_render)
    check("same with no user config (a brand-new user)", defaults_then_validate_then_render_unconfigured)
    check("a defaulted queue reaches the script", rendered_script_has_a_queue)


# --- repo-wide checks ----------------------------------------------------

def check_repo() -> None:
    print("\n=== repo-wide ===")

    def facilities_exist():
        assert config.list_facilities(), "no facilities registered"

    def unknown_facility_errors_clearly():
        for label, fn in (("config", config.get_facility), ("registry", get_backend)):
            try:
                fn("definitely-not-a-facility")
            except ValueError as e:
                assert "Unknown facility" in str(e), f"{label}: {e}"
                assert "Valid facilities:" in str(e), f"{label}: no slug list in {e}"
            else:
                raise AssertionError(f"{label}: expected ValueError")

    def slugs_are_url_and_identifier_safe():
        for fac in config.list_facilities():
            assert fac.slug == fac.slug.lower(), f"{fac.slug}: not lowercase"
            assert " " not in fac.slug, f"{fac.slug}: contains a space"
            assert fac.slug.replace("-", "").isalnum(), f"{fac.slug}: unexpected characters"

    def unreachable_detection_discriminates():
        """A scheduler error must not be mistaken for an SSH failure.

        Regression guard: a looser version of this check matched a bare
        "permission denied", so Slurm's own "Access/permission denied for
        job 9041823" came back buried in a wall of SSH setup directions
        instead of as the clear scheduler error it is. Caught live while
        testing update_job(hold=True) on HBW2.
        """
        from hpc_agent_core.middleware import _looks_unreachable as unreachable
        scheduler_and_command_errors = [
            ("Access/permission denied for job 9041823", None),
            ("slurm_suspend error:Job has already finished", None),
            ("ls: cannot access '/nope': No such file or directory", None),
            ("sbatch: error: Invalid account or account/partition combination", None),
            ("some remote failure", 2),
        ]
        for text, rc in scheduler_and_command_errors:
            assert not unreachable(text, rc), f"misread as an SSH failure: {text!r}"
        real_ssh_failures = [
            ("user@host: Permission denied (publickey).", None),
            ("ssh: connect to host x port 22: Connection refused", None),
            ("ssh: Could not resolve hostname bad.invalid", None),
            ("", 255),
        ]
        for text, rc in real_ssh_failures:
            assert unreachable(text, rc), f"missed a real SSH failure: {text!r} rc={rc}"

    def fs_rm_refuses_dangerous_paths():
        """fs_rm is the one irreversible tool here — these filesystems have
        no trash. Deleting a home directory or a filesystem root is far more
        likely to be a mistake (an unset variable, a stray default, a glob
        that expanded to nothing) than an intent, so those must be refused
        before any command is built, not just discouraged in a docstring."""
        from hpc_mcp.hpc_server import fs_rm
        for bad in ["", " ", ".", "..", "/", "~", "~/", "*", "$HOME", ".//"]:
            try:
                fs_rm("__no_such_facility__", bad)
            except ValueError as e:
                assert "Refusing to delete" in str(e), (
                    f"{bad!r} reached facility lookup instead of being refused: {e}")
            else:
                raise AssertionError(f"fs_rm did not refuse {bad!r}")

    def generated_skills_are_wellformed():
        """Every generated SKILL.md needs YAML frontmatter whose name
        matches its directory, or the client cannot discover it.

        Caught a real one: Fugaku-Agent's fugaku-build skill shipped with
        no frontmatter at all — the only skill in that repo missing it, so
        it had no name or description to be found by.
        """
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        skills = sorted((root / "plugins" / "hpc" / "skills").glob("*/SKILL.md"))
        assert skills, "no generated skills found"
        for path in skills:
            text = path.read_text()
            assert text.startswith("---\n"), f"{path.parent.name}: no YAML frontmatter"
            front = text.split("---", 2)[1]
            assert f"name: {path.parent.name}\n" in front, (
                f"{path.parent.name}: frontmatter name does not match its directory")
            assert "description:" in front, f"{path.parent.name}: no description"

    def every_facility_has_skill_notes():
        """A facility with no notes for a workflow still renders (a stub is
        substituted), but submitting-jobs is where a port's real value
        lives — an empty one means an unfinished port."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        for manifest in sorted((root / "facilities").glob("*/facility.json")):
            notes = manifest.parent / "skill_notes" / "submitting-jobs.md"
            assert notes.exists() and notes.read_text().strip(), \
                f"{manifest.parent.name}: skill_notes/submitting-jobs.md is missing or empty"

    check("at least one facility is registered", facilities_exist)
    check("unknown facility errors clearly, listing valid slugs", unknown_facility_errors_clearly)
    check("slugs are lowercase and safe", slugs_are_url_and_identifier_safe)
    check("fs_rm refuses home/root paths", fs_rm_refuses_dangerous_paths)
    check("generated skills have matching frontmatter", generated_skills_are_wellformed)
    check("scheduler errors aren't mistaken for SSH failures", unreachable_detection_discriminates)
    check("every facility has real submitting-jobs notes", every_facility_has_skill_notes)


def main() -> int:
    check_repo()
    for fac in config.list_facilities():
        check_facility(fac.slug)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} conformance check(s) FAILED:\n")
        for f in FAILURES:
            print(f)
        return 1
    print("All conformance checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
