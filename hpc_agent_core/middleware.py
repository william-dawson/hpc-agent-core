"""Remote-execution layer: all cluster interaction funnels through here.

Built on remotemanager's Computer.cmd (a direct SSH exec, ~0.6s per call).
Three conventions are enforced in one place:

- Commands run under a login shell (the scheduler's own configuration is
  usually only visible through the login environment; a bare non-login
  shell often can't find it).
- The working directory is the user's home, so relative paths behave the
  way users expect.
- Commands and file contents travel base64-encoded, so arbitrary quoting
  survives the SSH layer intact.
- Non-zero exit codes raise RuntimeError so FastMCP surfaces a clean tool
  error; callers never need to parse error text from the return value.

Nothing in this module touches config or SSH at import time — get_frontend()
is built lazily, on first use, inside a tool call. This is a deliberate
invariant: the MCP server must never fail to start because config is
missing or malformed; only an individual tool call that actually needs SSH
should fail, with a clear message pointing at the machine's configuring
skill.

Extending this: machine repos cannot edit this file (no write access to
hpc-agent-core — see PLAN.md §2b). get_frontend()'s Computer() construction
(login-shell template, bash submitter, python3) is a fixed default; if a
machine genuinely needs different connection parameters, don't fork this
file — write an equivalent middleware.py in your own repo that builds its
own Computer via remotemanager directly (using hpc_agent_core.config.ssh_host()
for the host), and skip importing this module. That's a deliberate,
acceptable outcome for an unusual machine, not a sign core needs a plugin
hook — see PLAN.md §2a/§2b.
"""
import base64
import contextlib
import hashlib
import re
import shlex
import sys
from pathlib import Path

from remotemanager import Computer

from hpc_agent_core import config

# Cap what a single call can pour into the MCP context.
OUTPUT_LIMIT_BYTES = 200_000

#: Hosts remotemanager's URL.is_local treats as local (no ssh at all, per
#: URL.ssh returning ""). Kept here too so doctor.py and machine repos can
#: label output correctly without importing remotemanager directly.
LOCAL_HOSTS_PREFIX = "127."
LOCAL_HOST = "localhost"


def is_local_host(host: str) -> bool:
    """True if host resolves to a purely local connection (no SSH at all).

    Mirrors remotemanager.connection.url.URL.is_local's exact check
    (host == "localhost" or host.startswith("127.")) without importing
    URL directly — this is a plain string check, not a live connection
    property, so duplicating the two-line condition is simpler than
    constructing a Computer just to ask it.
    """
    return host == LOCAL_HOST or host.startswith(LOCAL_HOSTS_PREFIX)


def norm_path(path: str) -> str:
    """Strip a leading ~ so remote paths resolve under the home directory.

    run_command sets CWD to $HOME, so relative paths already resolve there.
    shlex.quote wraps in single quotes which suppresses tilde expansion, so
    ~/foo must become foo before quoting; bare ~ becomes '.'.
    """
    if path == "~":
        return "."
    if path.startswith("~/"):
        return path[2:]
    return path


def quote_path(path: str) -> str:
    """shlex.quote a remote path after normalizing a leading ~."""
    return shlex.quote(norm_path(path))


def get_frontend() -> Computer:
    """The Computer targeting the machine's login node (or the local host,
    if config.ssh_host() is "localhost"/"127.*" — remotemanager's
    URL.is_local already routes that case to a bare local shell with no ssh
    subprocess at all; no transport-layer change is needed here for it).

    Deliberately NOT cached (it was, via @lru_cache, until this was found to
    be pure staleness risk for no benefit — Computer.cmd() already does a
    fresh SSH exec per call with no persistent connection state on the
    object, so caching only meant a config file edit wasn't picked up until
    the whole MCP server restarted). Reconstructing it is cheap: two config
    reads plus a plain constructor call, negligible next to the network
    round-trip callers make immediately after.

    Every remotemanager.Computer constructor option is supported here, not
    just the four (template/host/submitter/python) every machine happened
    to share so far — see config.COMPUTER_OPTION_NAMES and
    config.computer_kwargs(). A machine that needs something different
    (a non-bash shell, a longer timeout, a specific keyfile, ...) sets it
    via configure(computer_defaults=...) in its own config.py; it does not
    need to touch this function.
    """
    return Computer(host=config.ssh_host(), **config.computer_kwargs())


def run_command(cmd: str) -> str:
    """Run a shell command on the login node; return stdout.

    Raises RuntimeError on non-zero exit so callers receive a clean MCP tool
    error rather than having to parse error text from the output.
    Output beyond OUTPUT_LIMIT_BYTES is truncated with a marker.
    """
    payload = 'cd "$HOME" && ' + cmd
    encoded = base64.b64encode(payload.encode()).decode()
    # remotemanager may print progress to stdout, which would corrupt the
    # MCP stdio transport — divert anything it emits.
    with contextlib.redirect_stdout(sys.stderr):
        try:
            result = get_frontend().cmd(
                f"echo {encoded} | base64 -d | bash -l", raise_errors=False,
            )
        except Exception as exc:
            if not config.config_path().exists():
                raise RuntimeError(
                    "Plugin not configured — run the configuring skill to "
                    f"create {config.config_path()}."
                ) from exc
            raise
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        if not config.config_path().exists():
            raise RuntimeError(
                "Plugin not configured — run the configuring skill to "
                f"create {config.config_path()}."
                + (f" SSH error: {detail}" if detail else "")
            )
        raise RuntimeError(detail or f"command exited with code {result.returncode}")
    output = result.stdout or ""
    if len(output) > OUTPUT_LIMIT_BYTES:
        output = (output[:OUTPUT_LIMIT_BYTES]
                  + f"\n[output truncated at {OUTPUT_LIMIT_BYTES} bytes]")
    return output


#: Directories grep_files skips by default — VCS metadata and the usual
#: dependency/venv/build dirs, mirroring what a local Grep tool excludes.
_GREP_DEFAULT_EXCLUDES = [".git", ".svn", ".hg", "node_modules", "__pycache__",
                          ".venv", "venv", ".mypy_cache", ".pytest_cache"]

#: A glob pattern is embedded in the remote shell command unquoted (it must
#: undergo real glob expansion, so it can't be shlex.quote()'d like a normal
#: argument) — so it's validated against this allowlist first instead.
#: Deliberately excludes shell metacharacters (;|&`$(){}<> etc. beyond the
#: brace-expansion {,} pair) that would otherwise let a pattern smuggle in
#: a second command.
_GLOB_SAFE_RE = re.compile(r"^[A-Za-z0-9_./*?\[\]{},!+@-]+$")


def grep_files(pattern: str, path: str = ".", *, glob: str | None = None,
                case_insensitive: bool = False, max_results: int = 200) -> str:
    """Search file contents on the cluster, recursively, for a regex —
    remote analogue of a local Grep tool. Returns grep-style
    "path:line:text" output, one match per line, capped at max_results
    (truncated with a marker if there are more).

    Binary files and common VCS/dependency directories are skipped by
    default (see _GREP_DEFAULT_EXCLUDES). `glob` filters which filenames
    are searched (e.g. "*.py"); `pattern` is a POSIX extended-ish regex,
    exactly what `grep -rn` accepts.

    `pattern` is passed through shlex.quote — unlike glob_files's pattern,
    it never needs to be interpreted by the shell itself, only by grep, so
    it can be safely quoted as an opaque argument with no character
    restriction.
    """
    exclude_flags = " ".join(f"--exclude-dir={shlex.quote(d)}" for d in _GREP_DEFAULT_EXCLUDES)
    include_flag = f"--include={shlex.quote(glob)}" if glob else ""
    ci_flag = "-i" if case_insensitive else ""
    cmd = (
        f"grep -rnI {exclude_flags} {include_flag} {ci_flag} "
        f"-- {shlex.quote(pattern)} {quote_path(path)}; "
        # grep exits 1 for "no matches" — a normal, non-error outcome here,
        # not something run_command should raise on. Exit 2+ is a real
        # error (bad regex, unreadable path, ...) and should still raise.
        "ec=$?; [ $ec -le 1 ] && exit 0; exit $ec"
    )
    output = run_command(cmd)
    lines = output.splitlines()
    if len(lines) > max_results:
        lines = lines[:max_results] + [f"[truncated at {max_results} results]"]
    return "\n".join(lines)


def glob_files(pattern: str, path: str = ".") -> str:
    """Find files under `path` matching a shell glob pattern — remote
    analogue of a local Glob tool. Supports `**` for recursive matching
    (bash's globstar) and standard wildcards (`*`, `?`, `[...]`, `{...}`).
    Returns one path per line, relative to `path`, sorted; empty string if
    nothing matches (not an error).

    `pattern` must pass _GLOB_SAFE_RE — it's embedded in the remote shell
    command so the shell's own glob engine can expand it, which rules out
    shlex.quote() (that would suppress expansion entirely, matching the
    pattern as a literal filename instead). The allowlist keeps this to
    genuine glob syntax, rejecting anything that could smuggle in a second
    shell command.
    """
    if not _GLOB_SAFE_RE.match(pattern):
        raise ValueError(
            f"glob pattern {pattern!r} contains characters outside what's "
            "allowed for a glob (letters, digits, / . * ? [ ] { } , ! + @ -)"
        )
    cmd = (
        f"cd {quote_path(path)} && "
        f"shopt -s globstar nullglob && "
        f"for f in {pattern}; do printf '%s\\n' \"$f\"; done | sort"
    )
    return run_command(cmd)


def write_remote_file(path: str, content: str | bytes) -> str:
    """Write a file on the cluster, creating parent directories.

    Relative paths resolve against the home directory. Returns the absolute
    path of the written file; raises on failure.
    """
    path = norm_path(path)
    raw = content if isinstance(content, bytes) else content.encode()
    encoded = base64.b64encode(raw).decode()
    quoted = shlex.quote(path)
    output = run_command(
        f'mkdir -p "$(dirname {quoted})" && '
        f"echo {encoded} | base64 -d > {quoted} && realpath {quoted}"
    )
    abs_path = output.strip().splitlines()[-1] if output.strip() else ""
    if not abs_path.startswith("/"):
        raise RuntimeError(f"Failed to write {path}: {output}")
    return abs_path


# ---------------------------------------------------------------------------
# File transfer (local ↔ remote)
# ---------------------------------------------------------------------------

def _make_transport():
    """Return a fresh rsync transport, falling back to scp if rsync < 3.0.

    remotemanager's rsync transport defaults to flags "auvh" (+ --checksum),
    where "u" is rsync's --update: skip the copy whenever the destination
    file's mtime is newer than the source's. fs_upload/fs_download are
    explicit, one-shot "make this path equal to that path" operations, not a
    two-way sync — if the agent (or a running job) has touched the remote
    file more recently than the local one, --update makes rsync silently
    skip the transfer instead of overwriting it, which is the opposite of
    what an explicit push/pull call means. Content-based staleness is still
    covered by --checksum (kept via the checksum=True default) and by the
    sha256 verification below; only the mtime-based skip is dropped.
    """
    from remotemanager.transport.rsync import rsync
    from remotemanager.transport.scp import scp as Scp
    c = get_frontend()
    try:
        return rsync(url=c, flags="avh")
    except RuntimeError:
        return Scp(url=c)


def _sha256_local(path: Path) -> str:
    """SHA-256 of a local file, streamed in 1 MB chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(remote_path: str, local_dest: Path) -> dict:
    """Pull remote_path to local_dest via rsync or scp; return transfer metadata."""
    local_dest = Path(local_dest)
    local_dest.parent.mkdir(parents=True, exist_ok=True)

    remote_sha = run_command(f"sha256sum {quote_path(remote_path)}").split()[0]

    remote_name = Path(remote_path).name
    transport = _make_transport()
    transport.queue_for_pull(
        files=remote_name,
        remote=str(Path(remote_path).parent),
        local=str(local_dest.parent),
    )
    with contextlib.redirect_stdout(sys.stderr):
        transport.transfer()

    landed = local_dest.parent / remote_name
    if landed != local_dest:
        landed.rename(local_dest)

    local_sha = _sha256_local(local_dest)
    if remote_sha != local_sha:
        raise RuntimeError(
            f"Download of {remote_path} landed at {local_dest} but content "
            f"doesn't match (remote sha256 {remote_sha}, local sha256 "
            f"{local_sha}). The remote file may have changed between the "
            "checksum and the transfer."
        )
    return {
        "local_path": str(local_dest),
        "bytes": local_dest.stat().st_size,
        "sha256": local_sha,
        "verified": True,
        "transport": type(transport).__name__,
    }


def upload_file(local_path: Path, remote_path: str) -> dict:
    """Push local_path to remote_path via rsync or scp; return transfer metadata."""
    local_path = Path(local_path)
    if not local_path.exists():
        raise FileNotFoundError(str(local_path))

    local_sha = _sha256_local(local_path)
    remote_path = norm_path(remote_path)

    run_command(f"mkdir -p {quote_path(str(Path(remote_path).parent))}")

    transport = _make_transport()
    transport.queue_for_push(
        files=local_path.name,
        local=str(local_path.parent),
        remote=str(Path(remote_path).parent),
    )
    with contextlib.redirect_stdout(sys.stderr):
        transport.transfer()

    landed = str(Path(remote_path).parent / local_path.name)
    if landed != remote_path:
        run_command(f"mv {quote_path(landed)} {quote_path(remote_path)}")

    remote_sha = run_command(f"sha256sum {quote_path(remote_path)}").split()[0]
    if remote_sha != local_sha:
        raise RuntimeError(
            f"Upload of {local_path} to {remote_path} completed but content "
            f"doesn't match (local sha256 {local_sha}, remote sha256 "
            f"{remote_sha}). The remote file may have been modified "
            "concurrently, or the transfer was silently skipped."
        )
    return {
        "remote_path": remote_path,
        "bytes": local_path.stat().st_size,
        "sha256": local_sha,
        "verified": True,
        "transport": type(transport).__name__,
    }
