# IRI Facility API coverage — what hpc-agent-core provides

Every machine repo's MCP tool surface is meant to mirror the [IRI Facility
API](https://api.alcf.anl.gov/openapi.json) (the DOE standard this family
targets — the spec isn't vendored anywhere in this family; fetch it fresh
with `curl -s https://api.alcf.anl.gov/openapi.json` when checking
coverage, per PORTING.md §2's rule against vendoring a live external
source).

This file is **not** a per-machine coverage checklist — `hpc-agent-core`
doesn't implement any MCP tools itself. It maps each IRI capability group
onto the primitive this package provides, so a porter knows what's already
handled versus what their own `hpc_server.py` still has to write. Each
machine repo keeps its own `IRI_CHECKLIST.md` with real
implemented/deferred/extension verdicts against its actual cluster — those
verdicts are machine-specific and don't belong here.

## Capability groups

| IRI endpoint group | Backing primitive in `hpc-agent-core` | What a machine repo's `hpc_server.py` still writes |
|---|---|---|
| `GET /facility` | — (no shared primitive; static per-machine facts) | A `<machine>_config.json` + a `get_facility` tool that reads it |
| `GET /resources`, `GET /resources/{id}` | `SchedulerBackend.get_live_resources()` / `get_drained_nodes()` (live `sinfo`/`qstat`-style occupancy) | `get_resources`/`get_resource` tools calling those |
| `GET /projects`, `GET /projects/{id}` | — (accounting is scheduler- and site-specific; no shared primitive yet) | Its own `sacctmgr`/`sshare`-style tool, or omit entirely on a machine with no per-project accounting |
| `POST /compute/jobs` | `SchedulerBackend.submit()` (renders + submits a script) | `submit_job` tool applying the machine's own defaults (partition, account) before calling it |
| `GET /compute/jobs/{id}`, `GET /compute/jobs` | `SchedulerBackend.get_statuses()` / `get_recent_statuses()` | `get_job_status`/`get_job_statuses` tools |
| `DELETE /compute/jobs/{id}` | `SchedulerBackend.cancel()` | `cancel_job` tool |
| `PATCH /compute/jobs/{id}` | — (hold/release/time-limit changes are scheduler-specific: `scontrol`/`qalter`) | `update_job` tool, written per machine |
| `GET /storage` (listing, metadata, content), `PUT /storage`, compression, checksums | `middleware.py` — `run_command`, `write_remote_file`, `download_file`, `upload_file`, `quote_path`, `norm_path` | The full `fs_*` tool set (`fs_ls`, `fs_stat`, `fs_view`/`fs_head`/`fs_tail`, `fs_upload`/`fs_download`, `fs_cp`/`fs_mv`/`fs_mkdir`/`fs_symlink`, `fs_chmod`/`fs_chown`, `fs_checksum`, `fs_compress`/`fs_extract`) — thin, mostly one-line wrappers over the primitives above; copy the set from any existing machine repo |

## Extensions common across the family (no IRI counterpart)

These aren't part of the IRI spec, but every machine repo provides them
because they're broadly useful on top of the primitives above:

- `render_job_script` — preview the rendered script before submitting
  (`SchedulerBackend.render_script()`, exposed as its own tool).
- `read_job_output` — tail a job's console log via `fs_tail`-style access.
- `run_command_on_cluster` — escape hatch for arbitrary login-node commands,
  built on `middleware.run_command`. Always show the command to the user
  first (see PORTING.md's invariants).
- `search_docs`, `list_doc_sections`, `read_doc_section` — the RAG
  docs-search tools. Fully generic, provided as-is by `docs_server.build()`;
  a machine repo doesn't reimplement these, only registers its own guide.

## Not this file's job

- Per-machine coverage verdicts, deferrals, and the reasoning behind
  them — see each machine repo's own `IRI_CHECKLIST.md`.
- The actual OpenAPI spec — never vendor it; fetch it live when needed.
