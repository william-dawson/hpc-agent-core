"""Generic MCP server for searching a machine's bundled documentation guide.

Read-only and needs no SSH access. Uses the pre-built packaged index at
config.docs_index_dir() (chunks.json + optional embeddings.npy); queries are
embedded against the configured serving infrastructure when available, with
automatic fallback to keyword search.

Per PLAN.md §3d, a chunk only carries a "Source: ..." line when the machine
registered a docs_cite_url via config.configure() — most machines leave it
blank (no live site worth citing), in which case results never mention a
URL at all. This is a deliberate per-machine policy, not a bug: don't add a
URL back in here without checking config.docs_cite_url() first.

Each machine repo provides a thin entry point (e.g. <machine>_mcp/docs_server.py)
that imports its own config module first (registering machine settings),
constructs FastMCP(name), and calls build(mcp) below before serve(mcp).
"""
from functools import lru_cache

from mcp.server.fastmcp import FastMCP

from hpc_agent_core import config
from hpc_agent_core.rag.store import DocsIndex


@lru_cache(maxsize=1)
def _index() -> DocsIndex:
    return DocsIndex(config.docs_index_dir())


def _format(result: dict) -> str:
    header = f"## {result['breadcrumb']}\n"
    if result.get("url"):
        header += f"Source: {result['url']}\n"
    return header + f"\n{result['text']}"


def build(mcp: FastMCP) -> FastMCP:
    """Register the docs-search tools on an existing FastMCP instance."""

    @mcp.tool()
    def search_docs(query: str, top_k: int = 4) -> str:
        """Search the machine's bundled documentation guide.

        Always call this first before answering any machine-specific
        question — job submission, modules, storage, login procedure, or
        any other cluster-specific detail. Do not rely on prior knowledge or
        the orientation facts embedded in skills — those are fallback aids,
        not authoritative.

        If a result carries no "Source:" line, that's deliberate (see this
        server's module docstring) — do not invent or guess a URL to send
        the user to.

        If this tool errors or returns no results, fall back to the inline
        facts in the active skill and note that docs were unavailable.

        When results begin with `[search_method: bm25]`, inform the user
        that keyword search was used because the embedding server could not
        be reached. Results may miss semantically relevant sections that
        don't share exact keywords with the query.

        Args:
            query: Natural-language question or keywords.
            top_k: Number of sections to return.
        """
        results = _index().search(query, top_k=top_k)
        if not results:
            return "No matching documentation sections found."
        sections = "\n\n---\n\n".join(_format(r) for r in results)
        if results[0]["method"] == "bm25":
            return f"[search_method: bm25]\n\n{sections}"
        return sections

    @mcp.tool()
    def list_doc_sections() -> str:
        """List every section of the bundled guide (table of contents)."""
        return "\n".join(f"- {c['breadcrumb']}" for c in _index().chunks)

    @mcp.tool()
    def read_doc_section(breadcrumb: str) -> str:
        """Read one guide section in full by its breadcrumb.

        Args:
            breadcrumb: Section path as shown by list_doc_sections or
                search_docs, e.g. 'Running jobs'. Partial matches work.
        """
        needle = breadcrumb.lower()
        matches = [c for c in _index().chunks if needle in c["breadcrumb"].lower()]
        if not matches:
            return f"No section matching '{breadcrumb}'. Use list_doc_sections to see all sections."
        return "\n\n---\n\n".join(_format(c) for c in matches)

    return mcp
