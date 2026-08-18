# IRI Facility API coverage

The unified tool surface (`hpc_mcp/hpc_server.py`) mirrors the [IRI Facility
API](https://api.alcf.anl.gov/openapi.json). The spec is **not vendored
here** — fetch it fresh when doing coverage work:

```bash
curl -s https://api.alcf.anl.gov/openapi.json
```

Every path below was verified against that document (ALCF implementation of
the IRI Facility API, `info.version` 1.0.0, 42 paths) rather than carried
over from an earlier checklist. Paths are written exactly as the spec has
them, including the `/api/v1` prefix and the `{resource_id}` segment —
earlier revisions of this file used a shortened, partly invented form
(`PATCH /compute/jobs/{id}` for what is really
`PUT /compute/job/{rid}/{jid}`), which is why they are spelled out in full
now.

Because there is exactly **one** tool set shared by every registered
facility (each tool taking a `facility` slug), these verdicts are real and
repo-wide, not a per-machine template.

## Implemented

| IRI endpoint | Tool | Notes |
|---|---|---|
| `GET /api/v1/facility` | `get_facility` | Static per-facility JSON |
| `GET /api/v1/status/resources` | `get_resources` | Live `sinfo`-style occupancy |
| `GET /api/v1/status/resources/{resource_id}` | `get_resource` | Scoped to a partition rather than a cluster — see Deviations |
| `GET /api/v1/account/projects` | `get_projects` | `SchedulerBackend.get_projects()`; the Slurm default is `sacctmgr show associations`, and a facility may enrich it (HBW2 adds `sshare` fair-share standing). Needs `has_accounting=True` |
| `GET /api/v1/account/projects/{project_id}` | `get_project` | |
| `POST /api/v1/compute/job/{resource_id}` | `submit_job` | |
| `PUT /api/v1/compute/job/{resource_id}/{job_id}` | `update_job` | Takes a JobSpec, as the spec does; only the fields set by the caller, and only those a scheduler can change post-submission, are applied |
| `GET /api/v1/compute/status/{resource_id}/{job_id}` | `get_job_status` | |
| `POST /api/v1/compute/status/{resource_id}` | `get_job_statuses` | Empty `job_ids` means "this user's recent jobs" |
| `DELETE /api/v1/compute/cancel/{resource_id}/{job_id}` | `cancel_job` | |
| `GET /api/v1/filesystem/ls/{resource_id}` | `fs_ls` | |
| `GET /api/v1/filesystem/stat/{resource_id}` | `fs_stat` | |
| `GET /api/v1/filesystem/view/{resource_id}`, `GET .../file/{resource_id}` | `fs_view` | One tool covers both read forms |
| `GET /api/v1/filesystem/head/{resource_id}` | `fs_head` | |
| `GET /api/v1/filesystem/tail/{resource_id}` | `fs_tail` | |
| `POST /api/v1/filesystem/mkdir/{resource_id}` | `fs_mkdir` | |
| `POST /api/v1/filesystem/upload/{resource_id}` | `fs_upload` | Deviates: rsync/scp, not multipart |
| `GET /api/v1/filesystem/download/{resource_id}` | `fs_download` | Deviates: rsync/scp, not base64-in-body |
| `GET /api/v1/filesystem/checksum/{resource_id}` | `fs_checksum` | |
| `POST /api/v1/filesystem/cp/{resource_id}` | `fs_cp` | |
| `POST /api/v1/filesystem/mv/{resource_id}` | `fs_mv` | |
| `PUT /api/v1/filesystem/chmod/{resource_id}` | `fs_chmod` | |
| `PUT /api/v1/filesystem/chown/{resource_id}` | `fs_chown` | |
| `POST /api/v1/filesystem/symlink/{resource_id}` | `fs_symlink` | |
| `POST /api/v1/filesystem/compress/{resource_id}` | `fs_compress` | |
| `POST /api/v1/filesystem/extract/{resource_id}` | `fs_extract` | |

## Deviations worth knowing

- **`update_job`**: matches the spec's JobSpec-shaped body, with one
  refinement the spec leaves open ("only some attributes of a scheduled
  job can be updated — check the facility documentation"). Only fields the
  caller actually set are applied, so bumping a wall time doesn't also
  reset the job to the JobSpec default of one node; fields a scheduler
  can't change after submission are reported back in the returned status
  rather than silently dropped.
- **`get_resource`**: the spec's `{resource_id}` identifies a *compute
  resource* (a cluster). Here the facility slug already selects the
  cluster, so our `name` argument selects a **partition within** it — the
  granularity that actually answers "will my job start soon".
- **`fs_upload`/`fs_download`**: rsync (scp fallback) with sha256
  verification and no size limit, rather than the spec's multipart /
  base64-in-body shapes.

## Extensions (no IRI counterpart)

- `get_facilities` — list every registered facility; the discovery tool an
  agent calls before choosing a `facility` value. No IRI analogue, since
  the spec assumes one facility per API deployment.
- `render_job_script` — preview the fully-defaulted batch script without
  submitting and without touching the scheduler.
- `get_drained_nodes` — nodes currently down/drained, and why.
- `run_command_on_cluster` — escape hatch for arbitrary login-node
  commands. Always show the command to the user first (PORTING.md §10).
- `search_docs`, `list_doc_sections`, `read_doc_section` — RAG docs search,
  on the separate `hpc-docs-mcp` server.

## Not implemented

Verified absent from our tool surface, with the reason:

| IRI endpoint | Why not |
|---|---|
| `DELETE /api/v1/filesystem/rm/{resource_id}` | **A genuine gap, not a decision.** No file-delete tool exists here, nor in any of the three predecessor repos. Deleting user data deserves a deliberate design pass (confirmation semantics, recursive vs single file) rather than a one-line `rm` wrapper. Deletion is still possible via `run_command_on_cluster`, which shows the command to the user first. |
| `GET /api/v1/task`, `GET,DELETE /api/v1/task/{task_id}` | The spec's async task-handle model. Our tools are synchronous over SSH — a call returns when the work is done, so there is no handle to poll or cancel. |
| `GET /api/v1/status/events`, `/events/{id}`, `/incidents`, `/incidents/{id}` | Facility outage/maintenance feeds. These are site web services, not derivable over SSH, and no onboarded facility exposes an equivalent we could call. |
| `GET /api/v1/account/capabilities`, `/capabilities/{id}` | Capability discovery for the REST API itself; not meaningful for an MCP surface where the tool list *is* the capability list. |
| `GET .../project_allocations[/{id}]`, `.../user_allocations[/{id}]` | Allocation/balance detail. Partially covered already — HBW2's `get_projects` returns fair-share standing and raw usage. A general version needs a per-facility source (each site reports balances differently), so it belongs in a facility's `get_projects()` override rather than as new generic tools. |
| `GET /api/v1/facility/sites`, `/sites/{site_id}` | Multi-site topology under one facility. `get_facilities` covers the analogous need here, and no onboarded facility is multi-site. |

## Not this file's job

The OpenAPI spec itself — never vendor it; fetch it live when needed.
