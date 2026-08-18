# IRI Facility API coverage

The unified tool surface (`hpc_mcp/hpc_server.py`) is meant to mirror the
[IRI Facility API](https://api.alcf.anl.gov/openapi.json) (the DOE standard
this family targets — the spec isn't vendored anywhere in this repo; fetch
it fresh with `curl -s https://api.alcf.anl.gov/openapi.json` when checking
coverage, per PORTING.md's rule against vendoring a live external source).

Unlike the old per-machine-repo model, there is exactly **one** tool set for
every registered facility (every tool takes a `facility` slug argument), so
this checklist has real, concrete implemented/deferred verdicts instead of
being a per-machine template — coverage is uniform by construction.

| IRI endpoint group | Tool(s) | Status |
|---|---|---|
| `GET /facility` | `get_facility` | Implemented — static per-facility JSON |
| `GET /resources`, `GET /resources/{id}` | `get_resources`, `get_resource` | Implemented — live `sinfo`-style occupancy |
| `GET /projects`, `GET /projects/{id}` | `get_projects`, `get_project` | Implemented — `SchedulerBackend.get_projects()`; the Slurm default is `sacctmgr show associations`, and a facility can enrich it (HBW2 adds `sshare` fair-share standing). Requires `has_accounting=True` |
| `POST /compute/jobs` | `submit_job` | Implemented |
| `GET /compute/jobs/{id}`, `GET /compute/jobs` | `get_job_status`, `get_job_statuses` | Implemented |
| `DELETE /compute/jobs/{id}` | `cancel_job` | Implemented |
| `PATCH /compute/jobs/{id}` | `update_job` | Implemented — generic `scontrol update` field-dict; Slurm-specific (a future Grid-Engine facility needs `qalter`-based semantics, likely a facility-level override) |
| `GET /storage` (listing, metadata, content), `PUT /storage`, compression, checksums | `fs_ls`, `fs_stat`, `fs_view`/`fs_head`/`fs_tail`, `fs_upload`/`fs_download`, `fs_cp`/`fs_mv`/`fs_mkdir`/`fs_symlink`, `fs_chmod`/`fs_chown`, `fs_checksum`, `fs_compress`/`fs_extract` | Implemented |

## Extensions (no IRI counterpart)

- `get_facilities` — list every registered facility (slug, display name,
  description); the discovery tool an agent calls before picking a
  `facility` value for anything else.
- `run_command_on_cluster` — escape hatch for arbitrary login-node commands.
  Always show the command to the user first (see PORTING.md's invariants).
- `get_drained_nodes` — nodes currently down/drained and why.
- `search_docs`, `list_doc_sections`, `read_doc_section` — the RAG
  docs-search tools (on the separate `hpc-docs-mcp` server), fully generic.
- `render_job_script` — preview the fully-defaulted batch script without
  submitting (and without touching the scheduler). The "show before you
  run" rule's cheapest form.

**Not yet implemented anywhere in this repo**:

- `read_job_output` (a `fs_tail`-flavored shortcut scoped to a job's known
  output path — `fs_tail` already covers this generically once you know the
  path).
- `fs_grep` / `fs_glob` — remote analogues of a local Grep/Glob tool, backed
  by `middleware.grep_files()` / `glob_files()` (already facility-
  parametrized, just not exposed as tools yet).

## Not this file's job

The actual OpenAPI spec — never vendor it; fetch it live when needed.
