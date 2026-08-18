## Worth highlighting for HBW2

HBW2 requires a project account on every job — if `get_projects` shows more
than one, or `defaults.account` isn't configured yet, sort that out before
Step 5 rather than hitting the error mid-demo. Consider adding a
`get_projects(facility="{{SLUG}}")` call to the walkthrough: fair-share
standing is the thing that explains queue waits here, so it's genuinely
interesting output on this facility rather than boilerplate.

Use the default `mpc` CPU partition for the test job — HBW2 is CPU-first
and `mpc` has 312 nodes, so it's the least contended choice.
