---
name: rikyu-demo
description: Interactive demo of RIKYU (RIKEN AI4S / GB200) — walks through facility info, live cluster status, docs search, filesystem access, and job submission.
user-invocable: true
---

# RIKYU (RIKEN AI4S / GB200) demo

Run each step in order — actually call the tools, don't just describe the
plan. Present results as a readable narrative, not raw JSON dumps. Use
markdown headers and tables to make it scannable. Pause after each step and
show the output before moving on. Every tool call uses `facility="rikyu"`.

## Step 1 — Facility facts

Call `get_facility(facility="rikyu")`. Summarize the partitions, storage
tiers, and modules.

## Step 2 — Live status

Call `get_resources(facility="rikyu")`. Point out which partitions have
idle nodes right now.

## Step 3 — Docs search

Call `search_docs(facility="rikyu", query="how do I submit a job")` on
the `hpc-docs` server. Show the top result.

## Step 4 — Filesystem

Call `fs_ls(facility="rikyu", path=".")` to show the top of the user's
home directory.

## Step 5 — Submit a small job

Tell the user you'll submit a tiny test job (an `echo` command, minimal
resources, on an idle partition from Step 2), then call `submit_job`. Show
the returned `job_id`.

## Step 6 — Watch it finish

Poll `get_job_status(facility="rikyu", job_id=...)` every ~10 seconds,
showing state changes, until it reaches a terminal state. Then read the
output with `fs_tail(facility="rikyu", path="slurm-<job_id>.out")` and
show it.

## Worth highlighting for RIKYU

RIKYU has exactly one partition (`gpu`) but a fixed set of allowed per-job
GPU counts (1, 2, 3, 4, 8, 12, 16) — worth pointing out when summarizing
Step 1's facility facts, since it's the one thing a new user is most likely
to get wrong on their first real submission.
