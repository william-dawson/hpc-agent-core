Start by emphasizing that Miyabi is the exception to the laptop-to-cluster
model: the plugin must run on a Miyabi login node with `host=localhost`
because remote login requires interactive 2FA.

Keep the demo read-only unless the user asks for a job. Show static facts,
live occupancy, and a docs search for `PBS select mpiprocs ompthreads`. Any
`hostname` or raw PBS command must follow the remote-command skill: preview
the exact command, ask permission, wait, then recap the result.
