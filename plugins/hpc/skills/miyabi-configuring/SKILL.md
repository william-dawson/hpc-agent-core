---
name: miyabi-configuring
description: Use when the user wants to set up, configure, or troubleshoot Miyabi (JCAHPC) — SSH access, the embedding endpoint for docs search (RAG), or the ~/.hpc-agent/miyabi.json file. Also use when miyabi tools fail with connection or embedding errors.
---

# Configuring Miyabi (JCAHPC)

Settings live in `~/.hpc-agent/miyabi.json` (the common directory
shared by every facility this plugin serves — one file per facility). Env
vars `MIYABI_HOST` and `MIYABI_EMBED_API_KEY` override the
file; the embedding key also falls back to a shared `RCCS_EMBED_API_KEY`
env var if several facilities share the same endpoint.

The file this facility needs (add `"embedding": {"api_key": "..."}` too if
docs search should use vector rather than keyword matching):

```json
{
  "ssh": {
    "host": "localhost"
  },
  "defaults": {
    "group": "<your-project-group>"
  }
}
```

## What must be true before it can connect

Run Codex/Claude and this plugin on a Miyabi login node; remote SSH
automation is unsupported because Miyabi login requires interactive
2FA. Use ssh.host=localhost, which runs a local shell and does not
start SSH or bypass 2FA. Set defaults.group to your own PBS project
group: every job requires #PBS -W group_list=<group>. Never copy a
group from another user. MIYABI_GROUP overrides the configured group.

## Guided setup — interview the user, then write the file

Read the existing `~/.hpc-agent/miyabi.json` first and only ask
about what's missing or being changed.

1. **SSH** — ask how they reach this facility's login node:

Miyabi is local-login-node only. Run the agent on a Miyabi login node and use
`"host": "localhost"`; this opens a local shell, not SSH. Do not offer a
remote hostname or suggest bypassing the interactive 2FA login.

Every PBS job also needs the user's own project group. Put it under
`defaults.group`, or set `MIYABI_GROUP`. Never reuse a group from an example.

   - **Running the agent session directly on this facility's own
     front-end/login node** (not a personal laptop)? Use
     `"host": "localhost"` instead — no SSH key needed. Skip the
     verification step below for this case; there's nothing to probe.
   - Verify with: `ssh -o BatchMode=yes <host> 'echo ok'` (BatchMode
     matters — the server cannot answer a password prompt; key-based auth
     is required). Not applicable for `"host": "localhost"`.
2. **Embedding API key** (optional — skippable; BM25 keyword search still
   works without it). Store it under `embedding.api_key`.
3. **Write the file** to `~/.hpc-agent/miyabi.json` (`mkdir -p
   ~/.hpc-agent` first if needed), then `chmod 600` it — it may hold an API
   key. Never commit it or echo the key back in conversation.
4. **Validate**:
   ```bash
   uv tool run --quiet --from git+https://github.com/william-dawson/hpc-agent-core.git@unified-hub hpc-doctor miyabi
   ```
   (From a checkout of this repo: `.venv/bin/python -m hpc_mcp.doctor
   miyabi` also works.)
5. **If the embedding endpoint was added or changed**, rebuild this
   facility's docs index:
   ```bash
   uv tool run --quiet --from git+https://github.com/william-dawson/hpc-agent-core.git@unified-hub python -m hpc_mcp.ingest miyabi
   ```
   Then run the doctor again — it should report "chunks with embeddings".

## Notes

- Settings are read fresh on every tool call, so a config file edit
  (including switching `ssh.host` to/from `"localhost"`) applies
  immediately — no server restart needed. A rebuilt docs index still needs
  the `hpc-docs` server restarted to be picked up.
- Off-network or without a key, docs search transparently falls back to
  BM25 keyword search over the same content — the plugin still works.
