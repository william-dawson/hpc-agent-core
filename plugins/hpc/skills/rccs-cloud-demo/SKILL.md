---
name: rccs-cloud-demo
description: Interactive demo of R-CCS Cloud — walks through facility info, live cluster status, docs search, filesystem access, and job submission.
user-invocable: true
---

# R-CCS Cloud demo

Run each step in order — actually call the tools, don't just describe the
plan. Present results as a readable narrative, not raw JSON dumps. Use
markdown headers and tables to make it scannable. Pause after each step and
show the output before moving on. Every tool call uses `facility="rccs-cloud"`.

## Step 1 — Facility facts

Call `get_facility(facility="rccs-cloud")`. Summarize the partitions, storage
tiers, and modules.

## Step 2 — Live status

Call `get_resources(facility="rccs-cloud")`. Point out which partitions have
idle nodes right now.

## Step 3 — Docs search

Call `search_docs(facility="rccs-cloud", query="how do I submit a job")` on
the `hpc-docs` server. Show the top result.

## Step 4 — Filesystem

Call `fs_ls(facility="rccs-cloud", path=".")` to show the top of the user's
home directory.

## Step 5 — Submit a small job

Tell the user you'll submit a tiny test job (an `echo` command, minimal
resources, on an idle partition from Step 2), then call `submit_job`. Show
the returned `job_id`.

## Step 6 — Watch it finish

Poll `get_job_status(facility="rccs-cloud", job_id=...)` every ~10 seconds,
showing state changes, until it reaches a terminal state. Then read the
output with `fs_tail(facility="rccs-cloud", path="slurm-<job_id>.out")` and
show it.

## Worth highlighting for R-CCS Cloud

This is a heterogeneous ~20-partition cluster — when picking a partition
for Step 5's test job, prefer one with an idle CPU-only node (e.g. `genoa`)
for a quick, uncontended demo rather than a scarce GPU partition, unless
the user specifically wants to see a GPU job.
