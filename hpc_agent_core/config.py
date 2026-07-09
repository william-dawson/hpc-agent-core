"""Generic settings resolution shared by every machine built on hpc-agent-core.

A machine package's own `config.py` calls `configure(...)` once, at import
time, before anything else in the machine package touches config:

    # <machine>_mcp/config.py
    from hpc_agent_core import config as _core

    _core.configure(
        env_prefix="RIKYU",              # -> RIKYU_HOST, RIKYU_CONFIG, RIKYU_EMBED_API_KEY
        default_host="rikyu",             # ssh.host fallback (alias or user@hostname)
        package="rikyu_mcp",              # for resources.files(package) / bundled data
        embed_base_url="http://llm.ai.r-ccs.riken.jp:11434/v1",
        embed_model="bge-m3:567m",
    )

    # re-export what the rest of the machine package expects to import from
    # here (kept for readability at call sites — these are just the
    # registered functions/values):
    ssh_host = _core.ssh_host
    embed_api_key = _core.embed_api_key
    CONFIG_PATH = _core.config_path()
    EMBED_BASE_URL = _core.embed_base_url()
    EMBED_MODEL = _core.embed_model()
    DATA_DIR = _core.data_dir()

Every other hpc_agent_core module (middleware, rag.embed, doctor) reads
through this registration rather than importing a machine-specific module
directly, which is what lets one `middleware.run_command()` etc. work
unmodified across every machine.

Settings resolve in order: environment variable > the user config file
(`~/.<env_prefix.lower()>/config.json`, override path via
`<ENV_PREFIX>_CONFIG`) > the registered default. No credentials are stored
in this module — SSH is key-based, and the only secret ever handled here is
an optional embedding API key, read per-call rather than cached, so a
changed key takes effect without a restart.
"""
import json
import os
from contextlib import ExitStack
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path


@dataclass(frozen=True)
class _Registration:
    env_prefix: str
    default_host: str
    package: str
    embed_base_url: str
    embed_model: str
    config_dir_name: str
    docs_filename: str
    docs_cite_url: str


_REG: _Registration | None = None
_RESOURCE_STACK = ExitStack()


def configure(*, env_prefix: str, default_host: str, package: str,
              embed_base_url: str, embed_model: str,
              config_dir_name: str | None = None,
              docs_filename: str | None = None,
              docs_cite_url: str = "") -> None:
    """Register this machine's settings. Call exactly once, at import time,
    before any other hpc_agent_core module that reads config is used.

    config_dir_name defaults to `.{env_prefix.lower()}` (e.g. "RIKYU" -> ".rikyu").
    docs_filename (the bundled guide, under data/) defaults to
    `{package.removesuffix('_mcp')}_guide.md` (e.g. "rikyu_mcp" -> "rikyu_guide.md").
    docs_cite_url (see PLAN.md §3d) is the URL search results should cite —
    leave blank (the default) when there's no live docs site worth pointing
    users at; only set it for a machine with a stable, reliable public site.
    """
    global _REG
    _REG = _Registration(
        env_prefix=env_prefix,
        default_host=default_host,
        package=package,
        embed_base_url=embed_base_url,
        embed_model=embed_model,
        config_dir_name=config_dir_name or f".{env_prefix.lower()}",
        docs_filename=docs_filename or f"{package.removesuffix('_mcp')}_guide.md",
        docs_cite_url=docs_cite_url,
    )
    _config_path.cache_clear()
    _data_dir.cache_clear()


def _reg() -> _Registration:
    if _REG is None:
        raise RuntimeError(
            "hpc_agent_core.config.configure() was not called. The machine "
            "package's own config.py must call configure(...) before any "
            "other hpc_agent_core module is used."
        )
    return _REG


@lru_cache(maxsize=1)
def _config_path() -> Path:
    r = _reg()
    env_var = f"{r.env_prefix}_CONFIG"
    default = f"~/{r.config_dir_name}/config.json"
    return Path(os.environ.get(env_var, default)).expanduser()


def config_path() -> Path:
    """Path to the user config file (may not exist)."""
    return _config_path()


def _file_config() -> dict:
    """The parsed config file, or {} if absent. Raises on malformed JSON."""
    path = _config_path()
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Malformed config file {path}: {e}") from e


def ssh_host() -> str:
    """SSH destination for the machine's login node (alias or user@hostname)."""
    r = _reg()
    return (os.environ.get(f"{r.env_prefix}_HOST")
            or _file_config().get("ssh", {}).get("host")
            or r.default_host)


def embed_base_url() -> str:
    return _reg().embed_base_url


def embed_model() -> str:
    return _reg().embed_model


def embed_api_key() -> str:
    """API key for the shared embedding endpoint (the only user-configurable
    embedding setting — model/base_url are fixed per machine).

    Resolved in order: <ENV_PREFIX>_EMBED_API_KEY, then the shared
    RCCS_EMBED_API_KEY (a common fallback across RIKEN R-CCS plugins that
    all point at the same endpoint), then embedding.api_key in the config
    file. Empty string means no auth header is sent.
    """
    r = _reg()
    file = _file_config().get("embedding", {})
    return (os.environ.get(f"{r.env_prefix}_EMBED_API_KEY")
            or os.environ.get("RCCS_EMBED_API_KEY")
            or file.get("api_key") or "")


@lru_cache(maxsize=1)
def _data_dir() -> Path:
    """Filesystem path to the machine package's bundled data directory,
    including zip-safe extraction fallback."""
    r = _reg()
    data = resources.files(r.package) / "data"
    return _RESOURCE_STACK.enter_context(resources.as_file(data))


def data_dir() -> Path:
    return _data_dir()


def docs_source() -> Path:
    """Path to the bundled guide markdown that rag/ingest.py chunks."""
    return data_dir() / _reg().docs_filename


def docs_index_dir() -> Path:
    """Directory for the built docs index (chunks.json + optional embeddings.npy)."""
    r = _reg()
    return Path(os.environ.get(f"{r.env_prefix}_DOCS_INDEX", data_dir() / "docs_index"))


def docs_cite_url() -> str:
    """URL search results should cite, or "" to cite nothing (see PLAN.md §3d)."""
    return _reg().docs_cite_url
