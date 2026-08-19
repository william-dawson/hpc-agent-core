Miyabi is local-login-node only. Run the agent on a Miyabi login node and use
`"host": "localhost"`; this opens a local shell, not SSH. Do not offer a
remote hostname or suggest bypassing the interactive 2FA login.

Every PBS job also needs the user's own project group. Put it under
`defaults.group`, or set `MIYABI_GROUP`. Never reuse a group from an example.
