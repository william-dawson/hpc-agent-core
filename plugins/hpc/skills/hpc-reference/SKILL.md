---
name: hpc-reference
description: Use for quick facts about which HPC facilities are available through this plugin, and as the entry point for picking the right facility slug before calling any other hpc tool.
---

# HPC facility reference

This plugin serves every onboarded facility through one MCP server. Every
tool takes an explicit `facility` argument (a slug like `"rikyu"`) as its
first parameter — there is no default facility.

## Always resolve the facility slug first

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
| `rccs-cloud` | R-CCS Cloud | slurm | Heterogeneous ~20-partition cluster (CPU/NVIDIA/AMD/Intel GPU), Slurm with accounting. |
| `rikyu` | RIKYU (RIKEN AI4S / GB200) | slurm | RIKEN AI4S GB200 GPU cluster, Slurm with accounting, job-total GPU request. |
<!-- FACILITY_TABLE:END -->

## Per-facility facts

Static facts (partitions, storage tiers, modules, resource limits) come
from `get_facility(facility)`, not from this skill — that data is kept
current in each facility's own bundled JSON, not duplicated here where it
would drift. For anything narrative (login procedure, common failure modes,
software environment story), call `search_docs(facility, query)` on the
`hpc-docs` server.

## Related skills

- `hpc-configuring` — set up SSH access and the embedding key for a facility.
- `hpc-submitting-jobs` — submit and shape a job for a specific facility.
- `hpc-monitoring-jobs` — check status, read output, cancel.
- `hpc-reproducing` — turn a session into a reproducible notebook.
- `hpc-demo` — a guided end-to-end walkthrough.
