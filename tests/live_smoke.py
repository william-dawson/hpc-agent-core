"""Live smoke test for the unified multi-facility server, over real MCP stdio.

The read-only tier is facility-agnostic: it iterates whatever
get_facilities() reports, so a newly onboarded facility is exercised the
moment it's registered — nothing here to update per facility.

    .venv/bin/python tests/live_smoke.py                    # read-only, every facility
    .venv/bin/python tests/live_smoke.py --job rikyu        # + submit a real job there
    .venv/bin/python tests/live_smoke.py --job hokusai --account rb230090

Needs a working ~/.hpc-agent/<slug>.json and real SSH access for each
registered facility.
"""
import argparse
import asyncio
import os
import time

from hpc_agent_core.client import connect, dev_params

#: Per-facility job spec for the --job tier. A facility absent from here can
#: still be job-tested by passing --partition/--account explicitly; this just
#: holds a known-good, deliberately tiny default per facility.
JOB_DEFAULTS = {
    "rikyu": {"queue_name": "gpu", "gpus": 1},
    "hokusai": {"queue_name": "mpc"},
    "rccs-cloud": {"queue_name": "genoa"},
    # Fugaku: PJM, no GPUs; queue_name is mandatory (no safe default).
    "fugaku": {"queue_name": "small"},
}


async def read_only_tier(hpc, docs_hpc) -> list[str]:
    tools = await hpc.session.list_tools()
    names = sorted(t.name for t in tools.tools)
    print(f"{len(names)} tools registered: {names}")
    for required in ("get_facilities", "submit_job", "render_job_script", "get_projects"):
        assert required in names, f"missing tool: {required}"

    facilities = await hpc.get_facilities()
    slugs = sorted(f["slug"] for f in facilities)
    assert slugs, "no facilities registered"
    print(f"\nfacilities: {slugs}")

    for slug in slugs:
        res = await hpc.get_resources(facility=slug)
        assert isinstance(res, list) and res, f"{slug}: no partitions returned"
        print(f"\n[{slug}] get_resources: {len(res)} partitions, e.g. {res[0]}")

        fac = await hpc.get_facility(facility=slug)
        assert fac, f"{slug}: empty facility facts"
        print(f"[{slug}] get_facility keys: {list(fac.keys())[:5]}")

        # Not every scheduler has per-project accounting — Fugaku's PJM has
        # no sacctmgr at all. A clear "does not implement" is the correct
        # answer there, not a failure; anything else still is.
        try:
            projects = await hpc.get_projects(facility=slug)
            print(f"[{slug}] get_projects: {[p['account'] for p in projects]}")
        except Exception as e:
            assert "does not support" in str(e), e
            print(f"[{slug}] get_projects: not supported by this scheduler (expected)")

        docs = await docs_hpc.search_docs(facility=slug, query="how do I submit a job")
        assert docs.strip(), f"{slug}: empty docs result"
        print(f"[{slug}] search_docs: {docs[:70]!r}...")

    try:
        await hpc.get_resources(facility="not-a-real-facility")
        raise AssertionError("expected an error for an unknown facility")
    except Exception as e:
        assert "Unknown facility" in str(e), e
        print(f"\nunknown-facility error path OK")
    return slugs


async def job_tier(hpc, slug: str, account: str | None) -> None:
    defaults = JOB_DEFAULTS.get(slug, {})
    resources = {"node_count": 1, "processes_per_node": 1}
    if defaults.get("gpus"):
        resources["gpus"] = defaults["gpus"]
    attributes = {"duration": defaults.get("duration", 300)}
    if defaults.get("queue_name"):
        attributes["queue_name"] = defaults["queue_name"]
    if account:
        attributes["account"] = account

    spec = {
        "name": "hub-smoke",
        "executable": "echo",
        "arguments": ["hub-smoke-ok"],
        "resources": resources,
        "attributes": attributes,
    }

    # render first — proves apply_defaults/validate_spec run without spending
    # anything, and shows exactly what is about to be submitted.
    script = await hpc.render_job_script(facility=slug, spec=spec)
    print(f"\n[{slug}] rendered script:\n{script}")

    print(f"[{slug}] submitting real job ...")
    result = await hpc.submit_job(facility=slug, spec=spec)
    job_id = result["job_id"]
    print(f"[{slug}] submitted: {result}")

    state = None
    start = time.monotonic()
    while time.monotonic() - start < 600:
        status = await hpc.get_job_status(facility=slug, job_id=job_id)
        state = status["status"]["state"]
        print(f"  state: {state}")
        if state in ("completed", "failed", "canceled"):
            break
        await asyncio.sleep(10)
    assert state == "completed", status

    # Output filename is scheduler-specific: Slurm writes slurm-<id>.out in
    # the workdir; PJM writes <jobname>.<id>.out in the submission directory.
    workdir = (status["status"].get("meta_data") or {}).get("workdir", "") or ""
    candidates = [f"{workdir.rstrip('/')}/slurm-{job_id}.out" if workdir else f"slurm-{job_id}.out",
                  f"agent/jobs/{spec['name']}.{job_id}.out"]
    out = ""
    for path in candidates:
        try:
            out = await hpc.fs_tail(facility=slug, path=path)
            print(f"[{slug}] output from {path}")
            break
        except Exception:
            continue
    assert out, f"no output found in any of {candidates}"
    print(f"[{slug}] output tail: {out.strip()!r}")
    assert "hub-smoke-ok" in out, out


async def main(job_facility: str | None, account: str | None) -> None:
    # Pass the environment through explicitly. StdioServerParameters(env=None)
    # gives the server subprocess a *minimal* environment, not this process's
    # — so a `FACILITY_X=... python tests/live_smoke.py` override silently
    # never reaches the server and it falls back to the config file. That cost
    # a whole round of misdiagnosis on Fugaku: a run launched with
    # FUGAKU_GFSCACHE=/vol0004 actually submitted the config file's value, and
    # the resulting failure looked like it exonerated that setting.
    env = dict(os.environ)
    async with connect(dev_params("hpc_mcp", "hpc_server", env=env), mode="live") as hpc, \
               connect(dev_params("hpc_mcp", "docs_server", env=env), mode="live") as docs_hpc:
        slugs = await read_only_tier(hpc, docs_hpc)
        if job_facility:
            assert job_facility in slugs, f"{job_facility!r} is not registered (have {slugs})"
            await job_tier(hpc, job_facility, account)
        print("\nALL LIVE CHECKS PASSED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", metavar="FACILITY", default=None,
                         help="Also submit a real, tiny job on this facility.")
    parser.add_argument("--account", default=None,
                         help="Project/account to charge for --job (needed where "
                              "the facility requires one and no default is configured).")
    args = parser.parse_args()
    asyncio.run(main(args.job, args.account))
