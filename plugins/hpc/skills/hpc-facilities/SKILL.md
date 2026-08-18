---
name: hpc-facilities
description: Use to discover which HPC facilities are available through this plugin and pick the right one before calling any other tool or skill — e.g. when the user hasn't named a specific machine, or you're unsure which facility slug applies.
---

# Which facility?

This plugin serves every onboarded facility through one MCP server. Every
tool takes an explicit `facility` argument (a slug like `"rikyu"`) as its
first parameter — there is no default facility. Once you know the facility,
its own skill (`<slug>-submitting-jobs`, `<slug>-monitoring-jobs`,
`<slug>-configuring`, `<slug>-demo`, `<slug>-reproducing`) has the real,
facility-specific how-to; this skill only covers picking the slug.

## Resolve the facility first

If the user's request doesn't already make the facility obvious (they named
it, or it's the only one they've ever mentioned in this conversation), call
`get_facilities()` before calling anything else. It returns every
registered slug with a display name and a one-line description — pick the
one that matches what the user asked for, or ask them to confirm if more
than one plausibly fits. Never guess a slug that wasn't returned by this
call: every other tool raises a clear error listing the valid slugs if you
pass a wrong one, but it's cheaper and clearer to check first.

## Facilities currently onboarded

<!-- FACILITY_TABLE:START -->
| slug | facility | scheduler | description |
|---|---|---|---|
| `hokusai` | HOKUSAI BigWaterfall2 (HBW2) | slurm | CPU-first Slurm cluster (312-node MPC, large-memory, H100 GPU subsystems); a project account is mandatory on every job. |
| `rccs-cloud` | R-CCS Cloud | slurm | Heterogeneous ~20-partition cluster (CPU/NVIDIA/AMD/Intel GPU), Slurm with accounting. |
| `rikyu` | RIKYU (RIKEN AI4S / GB200) | slurm | RIKEN AI4S GB200 GPU cluster, Slurm with accounting, job-total GPU request. |
<!-- FACILITY_TABLE:END -->

Once you've resolved the slug, load that facility's own skill — its content
is written specifically for that machine (dialect, module names, failure
modes, SSH setup) rather than generic advice.
