---
name: hpc-demo
description: Interactive demo of the unified HPC plugin — walks through facility discovery, live cluster status, docs search, filesystem access, and job submission on a chosen facility.
user-invocable: true
---

# HPC plugin demo

Run each step in order — actually call the tools, don't just describe the
plan. Present results as a readable narrative, not raw JSON dumps. Use
markdown headers and tables to make it scannable. Pause after each step and
show the output before moving on.

## Step 1 — List facilities

Call `get_facilities()`. Show the table of slugs, display names, and
descriptions. Ask the user which one to demo, or pick the first one if they
don't care.

## Step 2 — Facility facts

Call `get_facility(facility)` for the chosen slug. Summarize the partitions,
storage tiers, and modules.

## Step 3 — Live status

Call `get_resources(facility)`. Point out which partitions have idle nodes
right now.

## Step 4 — Docs search

Call `search_docs(facility, query="how do I submit a job")` on the
`hpc-docs` server. Show the top result.

## Step 5 — Filesystem

Call `fs_ls(facility, path=".")` to show the top of the user's home
directory on that facility.

## Step 6 — Submit a small job

Tell the user you'll submit a tiny test job (an `echo` command, minimal
resources, on an idle partition from Step 3), then call `submit_job`. Show
the returned `job_id`.

## Step 7 — Watch it finish

Poll `get_job_status(facility, job_id)` every ~10 seconds, showing state
changes, until it reaches a terminal state. Then read the output with
`fs_tail(facility, path="slurm-<job_id>.out")` and show it.
