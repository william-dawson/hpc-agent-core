"""Shared MCP stdio smoke-test plumbing — see PORTING.md §9 for the tiered
pattern this backs (offline / read-only / job).

Only the genuinely machine-agnostic pieces live here: reading a tool result
correctly, a collision-safe job name, and a pass/fail/skip summary. The tier
functions themselves (which tools to check, what a live call should assert,
the job spec shape) stay in each machine repo's own tests/smoke.py — they
differ too much machine to machine to be worth forcing into a shared shape,
and a machine repo has no write access here to adjust one anyway if it
didn't. If you're tempted to centralize the orchestration too, read
PORTING.md §9's note on why it deliberately isn't.
"""
from __future__ import annotations

import json
import os
import secrets
from collections.abc import Awaitable

from mcp import ClientSession


async def call(session: ClientSession, name: str, args: dict | None = None):
    """Call a tool and raise if it errored, with the server's own error text
    folded into the exception so the failure is diagnosable from the
    harness's own output, not a separate log line.
    """
    result = await session.call_tool(name, args or {})
    if result.is_error:
        detail = "".join(getattr(block, "text", "") for block in result.content)
        raise AssertionError(f"{name} failed: {detail or '(server returned no error detail)'}")
    return result


def payload(result):
    """Return a tool result's actual value.

    Prefers `structured_content`; only falls back to the joined content-block
    text when it's absent. Non-object return types (e.g. `list[dict]`) are
    wire-wrapped as `{"result": ...}`; unwrapped here so an empty list reads
    as an empty list rather than a truthy one-key dict.

    `structured_content` is absent specifically for a bare, unparameterized
    `dict` return annotation (e.g. `def get_facility() -> dict`) — the MCP
    surface can't derive an output schema for it, unlike `list[dict]` (whose
    array-of-object shape it can schema, and which *does* arrive via
    structured_content already). For that fallback case, the joined text is
    itself the tool's JSON serialization (verified against a real mcp 2.0.0
    server), so it's parsed here rather than every call site needing its own
    `json.loads` wrapper. Only promoted to the parsed value when the parse
    succeeds *and* yields a dict/list — a scalar-looking result (a bare
    number, "true", "null") stays a string, so plain command output that
    happens to look numeric (e.g. an echoed job ID) isn't silently coerced
    into an int and quietly loses things like trailing whitespace a caller
    might still care about.
    """
    value = result.structured_content
    if value is not None:
        if isinstance(value, dict) and value.keys() == {"result"}:
            return value["result"]
        return value
    text = "".join(getattr(block, "text", "") for block in result.content)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text
    return parsed if isinstance(parsed, (dict, list)) else text


def job_name(prefix: str) -> str:
    """A run-scoped job name so two concurrent smoke runs never collide."""
    return f"{prefix}-{os.getpid()}-{secrets.token_hex(4)}"


class Summary:
    """Tracks passed/failed/skipped tiers; one final summary line, with
    skips named rather than folded silently into the passed count."""

    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[tuple[str, BaseException]] = []
        self.skipped: list[tuple[str, str]] = []

    def ok(self, tier: str) -> None:
        self.passed.append(tier)

    def fail(self, tier: str, exc: BaseException) -> None:
        self.failed.append((tier, exc))

    def skip(self, tier: str, reason: str) -> None:
        self.skipped.append((tier, reason))

    @property
    def all_passed(self) -> bool:
        return not self.failed

    def line(self) -> str:
        skipped_str = "; ".join(f"{tier} ({reason})" for tier, reason in self.skipped)
        out = f"SUMMARY passed={len(self.passed)} failed={len(self.failed)} skipped={len(self.skipped)}"
        if self.skipped:
            out += f" SKIPPED({skipped_str})"
        return out


async def run_tier(summary: Summary, name: str, coro: Awaitable, *, stderr_print=print) -> None:
    """Run one tier, recording the outcome on summary and printing a
    PASSED/FAILED line. Never raises — check summary.all_passed after."""
    try:
        await coro
        summary.ok(name)
        print(f"[{name}] tier: PASSED")
    except Exception as exc:
        summary.fail(name, exc)
        stderr_print(f"[{name}] tier: FAILED — {exc}")


def confirm_billing_gate(args, *, flag_name: str = "confirm_billing", job_flag: str = "job",
                          reason: str) -> str | None:
    """For a machine where a --job submission is billable: returns a refusal
    message if --job was given without the matching --confirm-billing flag,
    or None if it's safe to proceed (either --job wasn't requested, or both
    flags are present). Callers should print the message to stderr and exit
    non-zero before constructing any client — this must be checked before
    any SSH/async work starts.

    Optional — a machine with no billing concern (or no usage cap concern)
    just doesn't call this.
    """
    if getattr(args, job_flag, False) and not getattr(args, flag_name, False):
        return (
            f"Refusing to submit: --{job_flag.replace('_', '-')} was given without "
            f"--{flag_name.replace('_', '-')}.\n{reason}\n"
            "No client was constructed and no SSH connection was attempted."
        )
    return None
