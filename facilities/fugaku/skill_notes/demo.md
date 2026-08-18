## Worth knowing before demoing Fugaku

**Step 1 will not show projects.** Fugaku has no `sacctmgr`, so
`get_projects` raises a clear "not implemented" error here rather than
returning accounts. That's expected — skip it and use
`run_command_on_cluster(facility="{{SLUG}}", command="id")` to show the
account's real project groups instead, since a valid group is what actually
gates submission.

**Step 2's `get_resources` returns raw `pjstat --rsc` text**, not structured
occupancy — say so rather than presenting it as a partition table.

For Step 6, `attributes.queue_name` is required (no default) and a project
group must be configured. A minimal validation job:

```json
{
  "name": "fugaku-demo",
  "executable": "hostname && lscpu | head -20",
  "resources": {"node_count": 1},
  "attributes": {"duration": 300, "queue_name": "small"}
}
```

If the account's group is `trial`, use a `spot-*` resource group instead —
`small` will be rejected.

For Step 7, read `<name>.<job_id>.out` in the submission directory — and
remember `completed` here only means the scheduler finished, so actually
show the output rather than declaring success from the state alone.
