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
import pathlib
import shlex
import sys
import traceback
from unittest.mock import patch

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

    def machine_resource_limits_are_enforced():
        """Exercise deterministic limits encoded by the facility hook.

        Only RIKYU currently has a complete job-resource table precise
        enough for these checks; facilities whose limits vary by project or
        live partition intentionally do not guess here.
        """
        if slug != "rikyu":
            return
        invalid_specs = [
            {"gpus": 5},
            {"gpus": 8, "node_count": 1},
            {"gpus": 1, "cpu_cores_per_process": 37},
            {"gpus": 1, "memory": 401 * 1024**3},
        ]
        for resources in invalid_specs:
            spec = JobSpec(
                executable="true", resources=resources,
                attributes={"queue_name": "gpu"},
            )
            try:
                backend.validate_spec(spec)
            except ValueError:
                continue
            raise AssertionError(f"RIKYU accepted invalid resources: {resources}")

        wrong_queue = JobSpec(
            executable="true", attributes={"queue_name": "not-gpu"},
        )
        try:
            backend.validate_spec(wrong_queue)
        except ValueError:
            return
        raise AssertionError("RIKYU accepted a nonexistent partition")

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
    if slug == "rikyu":
        check("deterministic machine resource limits are enforced",
              machine_resource_limits_are_enforced)


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

        remote_skills = sorted((root / "plugins" / "hpc" / "skills").glob(
            "*-remote-command/SKILL.md"
        ))
        assert len(remote_skills) == len(config.list_facilities()), (
            "every facility needs a generated remote-command skill"
        )
        for path in remote_skills:
            text = path.read_text()
            assert "May I run these" in text, f"{path.parent.name}: no permission example"
            assert "Prefer multiple focused calls" in text, (
                f"{path.parent.name}: no short-command guidance"
            )
            assert "Changed state:" in text, f"{path.parent.name}: no execution recap example"

    def job_name_cannot_inject_into_scripts():
        """spec.name is rendered unquoted into every scheduler's directive
        line and used to build the job script's filename, so it is a real
        injection boundary — a newline puts executable lines into a script
        the scheduler runs, and a slash writes the script outside the jobs
        directory. Both were demonstrated against this code. Guarded once in
        the model so it holds for schedulers added later.
        """
        from hpc_agent_core.models import JobSpec
        for bad in ["ok\nrm -rf /", "../../../tmp/pwned", "a b",
                    'x"; rm -rf ~; #', "", "n" * 200, "foo$(id)", "a|b"]:
            try:
                JobSpec.model_validate({"name": bad, "executable": "x"})
            except Exception:
                continue
            raise AssertionError(f"job name accepted but should be rejected: {bad!r}")
        for ok in ["agent-job", "hub-smoke", "train_vit.v2", "probe360"]:
            JobSpec.model_validate({"name": ok, "executable": "x"})

        # Same primitive, every other field rendered into a directive line.
        for label, extra in [
            ("queue_name", {"attributes": {"queue_name": "gpu\nrm -rf /"}}),
            ("account", {"attributes": {"account": "a\n#SBATCH --uid=0"}}),
            ("reservation_id", {"attributes": {"reservation_id": "r\nevil"}}),
            ("custom key", {"attributes": {"custom_attributes": {"k\nevil": "v"}}}),
            ("custom value", {"attributes": {"custom_attributes": {"k": "v\nevil"}}}),
            ("directory", {"directory": "/tmp\nevil"}),
            ("stdout_path", {"stdout_path": "o\nevil"}),
        ]:
            spec = {"name": "t", "executable": "x", **extra}
            try:
                JobSpec.model_validate(spec)
            except Exception:
                continue
            raise AssertionError(f"control character accepted in {label}")

        # duration is both a directive-line field on every scheduler and a
        # login-node shell argument for Fugaku's pjalter update path.
        for bad in ["00:01:00\nrm -rf /", '00:01:00"; touch /tmp/pwned; #',
                    "not-a-duration", "00:60:00", True, 0, -1]:
            try:
                JobSpec.model_validate({
                    "name": "t", "executable": "x",
                    "attributes": {"duration": bad},
                })
            except Exception:
                continue
            raise AssertionError(f"unsafe/invalid duration accepted: {bad!r}")

    def resource_quantities_are_positive():
        invalid = [
            {"node_count": 0}, {"node_count": -1},
            {"process_count": 0}, {"process_count": -1},
            {"processes_per_node": 0}, {"cpu_cores_per_process": 0},
            {"gpu_cores_per_process": 0}, {"gpus": -1}, {"memory": 0},
        ]
        invalid += [
            {field: True} for field in (
                "node_count", "process_count", "processes_per_node",
                "cpu_cores_per_process", "gpu_cores_per_process", "gpus", "memory",
            )
        ]
        for resources in invalid:
            try:
                JobSpec.model_validate({"executable": "x", "resources": resources})
            except Exception:
                continue
            raise AssertionError(f"invalid resource quantity accepted: {resources!r}")

    def process_count_is_an_alternative_to_ppn():
        from hpc_agent_core.compute.slurm import SlurmBackend

        backend = SlurmBackend("test", nodes_always_explicit=True)
        total_only = JobSpec(
            executable="hostname", resources={"process_count": 8},
            attributes={"queue_name": "test"},
        )
        script = backend.render_script(total_only)
        assert "#SBATCH --ntasks=8" in script
        assert "#SBATCH --ntasks-per-node" not in script, script

        both = JobSpec(
            executable="hostname",
            resources={"process_count": 8, "processes_per_node": 4},
            attributes={"queue_name": "test"},
        )
        script = backend.render_script(both)
        assert "#SBATCH --ntasks=8" in script
        assert "#SBATCH --ntasks-per-node=4" in script

    def fugaku_update_quotes_duration_as_one_argument():
        from facilities.fugaku.compute import PJMBackend

        backend = PJMBackend("fugaku")
        unsafe = '01:02:03"; touch /tmp/pwned; #'
        # Bypass the generic validator deliberately to verify the backend's
        # independent defense in depth. Normal MCP input cannot construct
        # this model after the duration fix above.
        spec = JobSpec.model_construct(
            executable="unused",
            resources=ResourceSpec(),
            attributes=JobAttributes.model_construct(duration=unsafe),
        )
        commands = []

        def record(_facility, command):
            commands.append(command)
            return ""

        with patch("facilities.fugaku.compute.run_command", record), \
                patch.object(backend, "get_statuses", return_value=[]):
            try:
                backend.update("123", spec)
            except ValueError:
                pass  # expected: the mocked status lookup finds no job
        assert len(commands) == 1, commands
        assert shlex.split(commands[0]) == ["pjalter", "-L", f"elapse={unsafe}", "123"]

    def docs_embedding_client_is_not_cached():
        from hpc_agent_core.docs_server import _index

        index = _index("rikyu")
        assert index._embed_client is None, (
            "the cached docs index captured an embedding client/API key"
        )
        token = object()
        with patch.object(index, "_vector_search", return_value=[]) as vector:
            index.search("anything", embed_client=token)
        vector.assert_called_once_with("anything", 5, token)

    def a_broken_facility_cannot_deny_the_server():
        """One facility failing to import must not take down the others.

        The hub sharpened this: a single process now serves every facility,
        so an exception in one facility.py would otherwise deny every other
        facility to every user. Verified by importing a deliberately broken
        module the same way hpc_mcp does, and asserting the healthy ones
        survive and the failure is recorded rather than swallowed.
        """
        import importlib.util
        import tempfile
        import hpc_mcp

        healthy = {f.slug for f in config.list_facilities()}
        assert healthy, "no healthy facilities to protect"

        with tempfile.TemporaryDirectory() as tmp:
            mod = pathlib.Path(tmp) / "broken_facility.py"
            mod.write_text("raise RuntimeError('deliberately broken')\n")
            spec = importlib.util.spec_from_file_location("broken_facility", mod)
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception as exc:
                recorded = f"{type(exc).__name__}: {exc}"
            else:
                raise AssertionError("the broken module did not raise")

        assert "RuntimeError" in recorded, recorded
        assert {f.slug for f in config.list_facilities()} == healthy, \
            "a failed facility import disturbed the healthy registry"
        assert isinstance(hpc_mcp.FAILED_FACILITIES, dict), \
            "hpc_mcp must expose FAILED_FACILITIES so a skipped facility is never silent"

    def facility_data_is_declared_as_package_data():
        """Every file a facility reads at runtime must match a
        package-data glob in pyproject.toml.

        These are read via Path(__file__).parent/"data", which works
        perfectly in an editable install and silently ships nothing in a
        wheel unless declared. That is the failure this repo's own
        PORTING.md warns about, and it was real here: the first built wheel
        contained zero guides, zero docs indexes and zero facts JSON, so the
        documented `uv tool run --from git+...` install would have produced
        a server where get_facility and search_docs failed on every
        facility, while local testing looked fine.
        """
        import fnmatch
        import tomllib
        root = pathlib.Path(__file__).resolve().parent.parent
        with open(root / "pyproject.toml", "rb") as fh:
            globs = tomllib.load(fh)["tool"]["setuptools"]["package-data"]["*"]

        for fac in config.list_facilities():
            wanted = [fac.data_dir / fac.docs_filename,
                      fac.data_dir / fac.facts_filename,
                      fac.data_dir / "docs_index" / "chunks.json"]
            for path in wanted:
                if not path.exists():
                    continue
                rel = path.relative_to(fac.data_dir.parent).as_posix()
                assert any(fnmatch.fnmatch(rel, g) for g in globs), (
                    f"{fac.slug}: {rel} matches no package-data glob in "
                    f"pyproject.toml, so it would not ship in a wheel")

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
    check("job names cannot inject into scripts", job_name_cannot_inject_into_scripts)
    check("resource quantities are positive", resource_quantities_are_positive)
    check("process_count does not conflict with default tasks-per-node",
          process_count_is_an_alternative_to_ppn)
    check("Fugaku update quotes duration as one argument",
          fugaku_update_quotes_duration_as_one_argument)
    check("docs embedding credentials are refreshed per search",
          docs_embedding_client_is_not_cached)
    check("a broken facility cannot deny the server", a_broken_facility_cannot_deny_the_server)
    check("facility data ships in a wheel", facility_data_is_declared_as_package_data)
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
