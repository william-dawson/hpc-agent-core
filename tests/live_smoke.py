"""Live, read-only-by-default smoke test for the unified multi-facility
server, run over real MCP stdio against both onboarded facilities.

    .venv/bin/python tests/live_smoke.py            # read-only
    .venv/bin/python tests/live_smoke.py --job       # + submits a real tiny job on rikyu

Needs a working ~/.hpc-agent/{rikyu,rccs_cloud}.json and real SSH access.
"""
import asyncio
import sys
import time

from hpc_agent_core.client import connect, dev_params


async def main(submit_job: bool) -> None:
    async with connect(dev_params("hpc_mcp", "hpc_server"), mode="live") as hpc, \
               connect(dev_params("hpc_mcp", "docs_server"), mode="live") as docs_hpc:
        tools = await hpc.session.list_tools()
        names = sorted(t.name for t in tools.tools)
        print(f"{len(names)} tools registered: {names}")
        assert "get_facilities" in names and "submit_job" in names

        facilities = await hpc.get_facilities()
        slugs = sorted(f["slug"] for f in facilities)
        print("facilities:", slugs)
        assert slugs == ["rccs-cloud", "rikyu"], slugs

        for slug in slugs:
            res = await hpc.get_resources(facility=slug)
            print(f"[{slug}] get_resources: {len(res)} partitions, "
                  f"e.g. {res[0] if res else None}")
            assert isinstance(res, list) and res

            fac = await hpc.get_facility(facility=slug)
            print(f"[{slug}] get_facility keys: {list(fac.keys())[:5]}")

            docs = await docs_hpc.search_docs(facility=slug, query="how do I submit a job")
            print(f"[{slug}] search_docs: {docs[:80]!r}...")

        try:
            await hpc.get_resources(facility="not-a-real-facility")
            raise AssertionError("expected ValueError for unknown facility")
        except Exception as e:
            assert "Unknown facility" in str(e), e
            print("unknown-facility error path OK:", str(e)[:100])

        if submit_job:
            spec = {
                "name": "hub-smoke",
                "executable": "echo",
                "arguments": ["hub-smoke-ok"],
                "resources": {"gpus": 1, "node_count": 1, "processes_per_node": 1},
                "attributes": {"queue_name": "gpu", "duration": 300, "account": "rkp00012"},
            }
            print("submitting real job on rikyu ...")
            result = await hpc.submit_job(facility="rikyu", spec=spec)
            job_id = result["job_id"]
            print("submitted:", result)
            start = time.monotonic()
            while time.monotonic() - start < 300:
                status = await hpc.get_job_status(facility="rikyu", job_id=job_id)
                state = status["status"]["state"]
                print("  state:", state)
                if state in ("completed", "failed", "canceled"):
                    break
                await asyncio.sleep(10)
            assert state == "completed", status
            out = await hpc.fs_tail(facility="rikyu", path=f"slurm-{job_id}.out")
            print("output tail:", out[-300:])

        print("\nALL LIVE CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main(submit_job="--job" in sys.argv))
