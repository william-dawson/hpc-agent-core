---
name: hpc-configuring
description: Use when the user wants to set up, configure, or troubleshoot SSH access or the embedding endpoint for any onboarded HPC facility, or when a facility's tools fail with connection or embedding errors.
---

# Configuring a facility

Each facility has its own settings file at `~/.hpc-agent/<slug-with-
underscores>.json` (a hyphenated slug like `rccs-cloud` uses the underscore
form, `rccs_cloud.json` — this matches the family's pre-existing config
files, so an already-configured facility keeps working with no changes).
Ask the user which facility they mean, or check `get_facilities()` for the
exact slug, before touching any file.

Example, for a facility with slug `rikyu`:

```json
{
  "ssh": {"host": "rikyu"},
  "embedding": {"api_key": "..."}
}
```

Env var overrides (replace `RIKYU` with the facility's slug, uppercased,
hyphens to underscores — e.g. `rccs-cloud` → `RCCS_CLOUD`):
`<SLUG>_HOST`, `<SLUG>_CONFIG` (an arbitrary override path),
`<SLUG>_EMBED_API_KEY`. The embedding key also falls back to a shared
`RCCS_EMBED_API_KEY` env var if several RIKEN R-CCS facilities share the
same endpoint.

## Guided setup — interview the user, then write the file

Read the existing config file first (`~/.hpc-agent/<slug>.json`) and only
ask about what's missing or being changed.

1. **SSH** — ask how they reach that facility's login node:
   - An alias in `~/.ssh/config` (recommended) → `"host": "<alias>"`.
   - Otherwise username + hostname → `"host": "user@<hostname>"`.
   - **Running the agent session directly on that facility's own
     front-end/login node** (not a personal laptop)? Use
     `"host": "localhost"` instead — no SSH key needed. Skip the
     verification step below for this case.
   - Verify with: `ssh -o BatchMode=yes <host> 'echo ok'` (BatchMode
     matters — key-based auth is required; the server cannot answer a
     password prompt). Not applicable for `"host": "localhost"`.
2. **Embedding API key** (optional — skippable; BM25 keyword search still
   works without it). Store it under `embedding.api_key`.
3. **Write the file** to `~/.hpc-agent/<slug>.json` (`mkdir -p
   ~/.hpc-agent` first if needed), then `chmod 600` it — it may hold an API
   key. Never commit it or echo the key back in conversation.
4. **Validate**:
   ```bash
   uv tool run --quiet --from git+https://github.com/william-dawson/hpc-agent-hub.git@main hpc-doctor <slug>
   ```
   (From a checkout of this repo: `.venv/bin/python -m hpc_mcp.doctor
   <slug>` also works. Omit `<slug>` to check every registered facility at
   once.)
5. **If the embedding endpoint was added or changed**, rebuild that
   facility's docs index so it gains vector embeddings:
   ```bash
   uv tool run --quiet --from git+https://github.com/william-dawson/hpc-agent-hub.git@main python -m hpc_mcp.ingest <slug>
   ```
   Then run the doctor again — it should report "chunks with embeddings".

## Notes

- Settings are read fresh on every tool call, so a config file edit
  (including switching `ssh.host` to/from `"localhost"`) applies
  immediately — no server restart needed. A rebuilt docs index still needs
  the `hpc-docs` server restarted to be picked up (loaded once, cached in
  memory).
- One doctor run checks every registered facility by default — read its
  per-facility sections; a failure on one facility doesn't mean another is
  broken.
