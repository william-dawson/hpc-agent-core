---
name: hpc-submitting-jobs
description: Use when the user wants to submit, describe, or shape a batch job on any onboarded HPC facility (partitions/queues, GPUs, nodes, containers, environment).
user-invocable: true
---

# Submitting jobs

Every job tool takes an explicit `facility` slug as its first argument. If
it isn't already clear from context which facility the user means, call
`get_facilities()` first (see the `hpc-reference` skill) and confirm.

## Before submitting

1. **Check live occupancy**: `get_resources(facility)` shows every
   partition's allocated/idle/other/total node counts — pick an idle
   partition if the user hasn't named one, rather than guessing.
2. **Check static facts if needed**: `get_facility(facility)` returns the
   partition table, GPU-count limits, storage tiers, and modules for that
   facility. Some facilities (e.g. RIKYU) only accept specific per-job GPU
   counts — a bad count is rejected with a clear error before submission,
   but checking `get_facility` first avoids the round trip.
3. **Search the guide for anything narrative** (module load patterns,
   container conventions, common failure modes): `search_docs(facility,
   query)` on the `hpc-docs` server.

## Submitting

Call `submit_job(facility, spec)`. `spec` is a JobSpec: `name`,
`executable`, `arguments`, `resources` (`gpus`, `node_count`,
`processes_per_node`, `cpu_cores_per_process`, `memory`,
`exclusive_node_use`), `attributes` (`queue_name`, `duration`, `account`,
`reservation_id`), plus optional `environment`, `pre_launch`/`post_launch`,
`container`, `directory`, `stdout_path`/`stderr_path`.

- Leave `attributes.queue_name` blank if you don't have a specific partition
  in mind — some facilities (e.g. RIKYU, which has exactly one partition)
  fill in a sensible default automatically; others (a heterogeneous cluster
  with many partition families) require it, and `submit_job` returns a
  clear error if so.
- **Show the user the spec (or a plain-language description of it) before
  submitting, unless they've explicitly said to just run it.** This is a
  strict rule with no exceptions for `submit_job` and
  `run_command_on_cluster` specifically — it does not apply to read-only
  calls like `get_resources`.
- `submit_job` returns `{"job_id": ..., "script_path": ...}`. Hand the
  `job_id` to the user and mention `hpc-monitoring-jobs` for checking on it.

## Previewing without submitting

There is no dedicated "render only" tool yet. If the user wants to see the
script before deciding whether to submit, describe the JobSpec back to them
in plain language (partition, resources, command, environment) rather than
submitting just to inspect the rendered script — that spends real compute
for a preview. Only after they confirm, call `submit_job`.
