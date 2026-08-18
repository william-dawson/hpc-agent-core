---
name: hokusai-demo
description: Interactive demo of HOKUSAI BigWaterfall2 (HBW2) — walks through facility info, live cluster status, docs search, filesystem access, and job submission.
user-invocable: true
---

# HOKUSAI BigWaterfall2 (HBW2) demo

Run each step in order — actually call the tools, don't just describe the
plan. Present results as a readable narrative, not raw JSON dumps. Use
markdown headers and tables to make it scannable. Pause after each step and
show the output before moving on. Every tool call uses `facility="hokusai"`.

## Step 1 — Facility facts

Call `get_facility(facility="hokusai")`. Summarize the partitions, storage
tiers, and modules.

## Step 2 — Live status

Call `get_resources(facility="hokusai")`. Point out which partitions have
idle nodes right now.

## Step 3 — Docs search

Call `search_docs(facility="hokusai", query="how do I submit a job")` on
the `hpc-docs` server. Show the top result.

## Step 4 — Filesystem

Call `fs_ls(facility="hokusai", path=".")` to show the top of the user's
home directory.

## Step 5 — Submit a small job

Tell the user you'll submit a tiny test job (an `echo` command, minimal
resources, on an idle partition from Step 2), then call `submit_job`. Show
the returned `job_id`.

## Step 6 — Watch it finish

Poll `get_job_status(facility="hokusai", job_id=...)` every ~10 seconds,
showing state changes, until it reaches a terminal state. Then read the
output with `fs_tail(facility="hokusai", path="slurm-<job_id>.out")` and
show it.

## Worth highlighting for HBW2

HBW2 requires a project account on every job — if `get_projects` shows more
than one, or `defaults.account` isn't configured yet, sort that out before
Step 5 rather than hitting the error mid-demo. Consider adding a
`get_projects(facility="hokusai")` call to the walkthrough: fair-share
standing is the thing that explains queue waits here, so it's genuinely
interesting output on this facility rather than boilerplate.

Use the default `mpc` CPU partition for the test job — HBW2 is CPU-first
and `mpc` has 312 nodes, so it's the least contended choice.
