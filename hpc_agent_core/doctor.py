"""Generic health checks for an hpc-agent-core-based MCP plugin.

Checks the config file, SSH access to the cluster, scheduler availability,
the embedding endpoint, and the docs index. Exits nonzero if a required
check fails (the embedding endpoint is optional — docs search falls back to
BM25; a missing/malformed config file is a WARN, not a FAIL, per the "never
fail to start" invariant — see PORTING.md).

Each machine repo provides a tiny entry point, e.g.:

    # <machine>_mcp/doctor.py
    from rikyu_mcp import config  # noqa: F401 -- registers via configure()
    from hpc_agent_core.doctor import main

    if __name__ == "__main__":
        import sys
        sys.exit(main(scheduler_probe="sinfo --version", scheduler_name="slurm"))

Extending this: main() is a convenience default (config, ssh+scheduler,
guide-bundled, docs index, embedding), but every check_* function is
independently callable. If a machine needs a different set (e.g. add a Spack
check, skip embedding entirely, use a Grid Engine probe main() doesn't
support), don't edit this file — write your own main() in your repo that
calls whichever check_* functions you want, in whatever order, plus your own
additions. Machine repos have no write access to hpc-agent-core (PLAN.md §2b).
"""
import json
import sys

from hpc_agent_core import config

OK, WARN, FAIL = "✓", "!", "✗"


def check_config_file() -> bool:
    path = config.config_path()
    if not path.exists():
        print(f"{WARN} config file: {path} not found "
              f"(using env vars / defaults — the configuring skill can create it)")
        return True
    try:
        config._file_config()
    except RuntimeError as e:
        print(f"{FAIL} config file: {e}")
        return False
    print(f"{OK} config file: {path}")
    return True


def check_ssh(ok_token: str, scheduler_probe: str, scheduler_name: str) -> bool:
    from hpc_agent_core.middleware import run_command
    host = config.ssh_host()
    try:
        output = run_command(f"echo {ok_token} && hostname")
    except Exception as e:
        print(f"{FAIL} ssh ({host}): {e}")
        return False
    if ok_token not in output:
        print(f"{FAIL} ssh ({host}): unexpected response: {output[:200]}")
        return False
    print(f"{OK} ssh ({host}): connected to {output.strip().splitlines()[-1]}")

    scheduler_out = run_command(scheduler_probe)
    if scheduler_out.strip().lower().startswith(scheduler_name.lower()):
        print(f"{OK} {scheduler_name}: {scheduler_out.strip()}")
        return True
    print(f"{FAIL} {scheduler_name}: {scheduler_out.strip()[:200]}")
    return False


def check_embedding() -> bool:
    """Probe the embedding endpoint, or report a WARN if the machine has no
    shared endpoint configured at all (not every machine has one — a
    machine that never calls configure(embed_base_url=..., embed_model=...)
    with real values is BM25-only by design, which is fine, not a failure).
    A configured endpoint that merely lacks/rejects an API key still
    attempts the connection and reports FAIL, since that's a real signal
    (e.g. a 401) worth surfacing, unlike "no endpoint decided for this
    machine" which isn't an error to fix.
    """
    if not (config.embed_base_url() and config.embed_model()):
        print(f"{WARN} embedding: not configured for this machine; docs search uses BM25 keyword matching")
        return True
    from hpc_agent_core.rag.embed import get_client
    client = get_client()
    try:
        vector = client.embed(["connectivity probe"])[0]
    except Exception as e:
        print(f"{FAIL} embedding ({config.embed_model()} @ {config.embed_base_url()}): {e}")
        return False
    print(f"{OK} embedding: {config.embed_model()} @ {config.embed_base_url()} (dim {len(vector)})")
    return True


def check_docs_guide_bundled() -> bool:
    """Verify the guide markdown actually shipped as package data — catches
    a missing package-data glob (e.g. forgetting "data/*.md") before a user
    hits it as a confusing empty docs index."""
    path = config.docs_source()
    if not path.exists():
        print(f"{FAIL} guide file: {path} missing — check package-data in pyproject.toml "
              f"includes the guide's extension (e.g. 'data/*.md')")
        return False
    print(f"{OK} guide file: {path}")
    return True


def check_docs_index() -> bool:
    chunks_path = config.docs_index_dir() / "chunks.json"
    if not chunks_path.exists():
        print(f"{FAIL} docs index: {chunks_path} missing — run: python -m hpc_agent_core.rag.ingest")
        return False
    with open(chunks_path) as f:
        n_chunks = len(json.load(f))
    emb_path = config.docs_index_dir() / "embeddings.npy"
    if not emb_path.exists():
        print(f"{OK} docs index: {n_chunks} chunks (no embeddings — BM25 only; "
              f"run: python -m hpc_agent_core.rag.ingest)")
        return True
    import numpy as np
    n_vectors = np.load(emb_path).shape[0]
    if n_vectors != n_chunks:
        print(f"{FAIL} docs index: {n_chunks} chunks but {n_vectors} embeddings — "
              f"rebuild with: python -m hpc_agent_core.rag.ingest")
        return False
    print(f"{OK} docs index: {n_chunks} chunks with embeddings")
    return True


def main(scheduler_probe: str = "sinfo --version", scheduler_name: str = "slurm",
         ok_token: str | None = None) -> int:
    ok_token = ok_token or f"{config.ssh_host()}-doctor-ok".replace(" ", "-")
    results = [
        check_config_file(),
        check_ssh(ok_token, scheduler_probe, scheduler_name),
        check_docs_guide_bundled(),
        check_docs_index(),
        check_embedding(),
    ]
    if all(results):
        print("\nAll checks passed.")
        return 0
    print("\nSome checks FAILED — see above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
