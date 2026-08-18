---
name: hpc-monitoring-jobs
description: Use when the user wants to check job status, read a running or finished job's output, cancel a job, or modify a queued/running job's attributes on any onboarded HPC facility.
user-invocable: true
---

# Monitoring jobs

Every tool here takes an explicit `facility` slug as its first argument —
the same one the job was submitted on. If you don't already know it, ask
the user or check `get_facilities()`.

## Status

- `get_job_status(facility, job_id)` — one job's normalized status
  (`queued`/`active`/`completed`/`failed`/`canceled`/`held`/`unknown`).
  For a queued job, `status.message` explains the wait reason.
- `get_job_statuses(facility, job_ids)` — several jobs at once, or every
  job the current user has touched in roughly the last two days if
  `job_ids` is empty (on a facility with Slurm accounting; otherwise just
  the current live queue).

## Reading output

Job stdout/stderr default to `slurm-<job_id>.out` in the job's working
directory (the home directory, unless the JobSpec set `directory` or
explicit `stdout_path`/`stderr_path`). Read it with `fs_tail(facility,
path, lines=...)` for a running job's latest output, or `fs_view(facility,
path)` for the whole thing once it's finished.

## Cancelling

`cancel_job(facility, job_id)` — **confirm with the user before calling
this**, then report the resulting state from the return value.

## Updating a queued/running job

`update_job(facility, job_id, updates)` — `updates` is a field-name → value
dict passed to `scontrol update`, e.g. `{"TimeLimit": "02:00:00"}` to
extend the wall time. Only affects jobs still queued or running; some
fields can only be lowered, not raised, by a non-admin user — a permission
error from the scheduler surfaces as a tool error, not a silent no-op.

## Polling until done, from a notebook

Interactively, just call `get_job_status` again after a pause and tell the
user what changed. If you're writing a reproducible notebook instead (see
`hpc-reproducing`), use `hpc_agent_core.client`'s `wait_for_job(job_id,
facility=facility)` rather than a hand-rolled polling loop.
