"""Build a documentation index from a machine's bundled guide.

Per PLAN.md §3d: this only ever chunks a local, hand-written guide file —
it never git-clones or fetches a remote docs site at ingest time. If a
machine's official docs are worth indexing directly, that's a deliberate,
occasional, human-reviewed re-sync (read the source, rewrite the guide in
your own words, re-run this, commit the diff), not something a script
re-fetches unattended — a past attempt at "always re-fetch the live site"
(Rikyu-Agent, pre-2026-07-09) silently went stale when the source site moved
domains and was restructured, with nothing to catch it.

    python -m hpc_agent_core.rag.ingest                # bundled guide + embeddings
    python -m hpc_agent_core.rag.ingest --source FILE   # use a specific markdown file
    python -m hpc_agent_core.rag.ingest --no-embed      # keyword-only index

Precondition: the machine package's own config.py (which calls
hpc_agent_core.config.configure(...)) must already be imported by the time
this runs, since defaults for --source/--out/embedding settings come from
the registered config. Each machine repo should provide a tiny entry point
that imports its config module first, then calls main() here — see
PORTING.md for the exact wrapper shape.

Embeddings use the shared endpoint (config.embed_base_url()/embed_model())
and require an API key (<ENV_PREFIX>_EMBED_API_KEY or embedding.api_key in
the config file, or the shared RCCS_EMBED_API_KEY fallback). Without a key,
ingest writes a BM25-only index and says so.

End users never need to run this — chunks.json (+ embeddings.npy) is
committed to the machine repo as package data.
"""
import argparse
import json
import re
from pathlib import Path

from hpc_agent_core import config

_HEADING = re.compile(r"^(#{1,4})\s+(.*)$")


def chunk_markdown(text: str, page_url: str) -> list[dict]:
    """Split a markdown guide into one chunk per heading section.

    Each chunk carries a breadcrumb of its parent headings so retrieval and
    the model both see the context (e.g. 'Running jobs'). page_url is
    attached to every chunk verbatim — pass "" (the default from
    config.docs_cite_url()) to cite nothing, per PLAN.md §3d.
    """
    lines = text.splitlines()
    sections: list[dict] = []
    stack: list[tuple[int, str]] = []  # (level, title)
    current: list[str] = []
    in_code = False

    def flush():
        body = "\n".join(current).strip()
        if body and stack:
            sections.append({
                "breadcrumb": " > ".join(t for _, t in stack),
                "url": page_url,
                "text": body,
            })
        current.clear()

    for line in lines:
        if line.strip().startswith("```"):
            in_code = not in_code
            current.append(line)
            continue
        match = None if in_code else _HEADING.match(line)
        if match:
            flush()
            level = len(match.group(1))
            title = match.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
        else:
            current.append(line)
    flush()
    return sections


def build_index(source: Path, out_dir: Path, embed: bool, page_url: str = "") -> None:
    chunks = chunk_markdown(source.read_text(), page_url)
    for i, chunk in enumerate(chunks):
        chunk["id"] = i

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "chunks.json", "w") as f:
        json.dump(chunks, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(chunks)} chunks to {out_dir / 'chunks.json'}")

    emb_path = out_dir / "embeddings.npy"
    if not embed:
        emb_path.unlink(missing_ok=True)
        print("Skipped embeddings (BM25 keyword search only).")
        return
    if not config.embed_api_key():
        emb_path.unlink(missing_ok=True)
        print("No embedding API key configured — wrote a BM25-only index "
              "(set the machine's *_EMBED_API_KEY and re-run to add vectors).")
        return

    import numpy as np

    from hpc_agent_core.rag.embed import get_client
    from hpc_agent_core.rag.store import chunk_text
    vectors = get_client().embed([chunk_text(c) for c in chunks])
    np.save(emb_path, np.asarray(vectors, dtype="float32"))
    print(f"Wrote {len(vectors)} embeddings (dim {len(vectors[0])}) to {emb_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, default=None,
                        help="Markdown guide to index (defaults to the registered machine's bundled guide).")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output directory (defaults to the registered machine's docs index dir).")
    parser.add_argument("--url", default=None,
                        help="URL to cite in results (defaults to the registered machine's docs_cite_url, usually blank).")
    parser.add_argument("--no-embed", action="store_true",
                        help="Skip embeddings; build a keyword-search-only index.")
    args = parser.parse_args()
    source = args.source or config.docs_source()
    out = args.out or config.docs_index_dir()
    url = args.url if args.url is not None else config.docs_cite_url()
    build_index(source, out, embed=not args.no_embed, page_url=url)


if __name__ == "__main__":
    main()
