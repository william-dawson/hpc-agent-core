/**
 * pi bridge for the HPC agent hub — MCP servers, as native pi tools.
 *
 * Why this exists. pi has no built-in MCP client, but the hub's tool surface
 * is MCP servers (`plugins/hpc/mcp.json` spawns `hpc-mcp` / `hpc-docs-mcp`
 * over stdio). Rather than fork a pi-specific tool surface, this extension
 * IS a minimal MCP stdio client: it spawns those same two servers, does the
 * `initialize` / `tools/list` handshake, and `pi.registerTool()`s each one
 * with its live schema and docstring. The agent then calls `submit_job`,
 * `search_docs`, `fs_ls`, ... as native structured tools — exactly the
 * payload every MCP harness (Codex, Claude Code) gets, no translation, no
 * drift. The repo's tool code, skills, and `.mcp.json` are reused
 * unchanged; this file is the only pi-specific artifact, the analog of
 * `.codex-plugin/` and `.claude-plugin/` for one more harness.
 *
 * What "specific to ours" adds over a generic MCP client: it bundles the
 * repo's skills in the same package, and it gates WHICH facility skills
 * land in context — pi loads `plugins/hpc/skills` (the discovery skill)
 * from the package manifest, and this extension's `resources_discover`
 * adds a selected facility's `plugins/hpc-<slug>/skills` only when the user
 * has chosen it. The selection is made once, at the first session after
 * install, via a `ctx.ui.select` loop (pi's `select` is single-pick, so we
 * loop with a "Done" option). The choice persists to `~/.hpc-agent/`; later
 * changes use `/hpc-add <slug>` / `/hpc-remove <slug>`, which update the
 * file and `ctx.reload()` so the new skill set takes effect.
 *
 * The 36 tools themselves are NOT gated by selection: they are
 * facility-parametrized (every call names a `facility` slug), so they are
 * identical regardless of which facilities the user works with — same as
 * MCP mode, where both servers always expose all tools. Skill selection is
 * what keeps context lean; tools are always all of them.
 *
 * Two known gaps, deliberately NOT hidden:
 *  - First-run spawn cost. `uv tool run --from git+...` builds the MCP
 *    server on first use (tens of seconds). It blocks `session_start`; a
 *    status line is shown while it runs. A background/lazy spawn is a
 *    later optimization, not in this first attempt.
 *  - Schema fidelity vs provider. `submit_job` / `update_job` /
 *    `render_job_script` carry a nested JobSpec whose JSON Schema uses
 *    `$defs` / `$ref` / `anyOf:[T,null]`. We pass the MCP `inputSchema`
 *    through verbatim (pi stores it and hands it to the provider, the same
 *    shape typebox produces). Most providers accept it; if yours rejects
 *    `$ref`/`anyOf`, those three tools need a normalization pass — add it
 *    here, not in the repo's Python.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { spawn, type ChildProcess } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

// A protocol version the installed mcp SDK advertises; the server negotiates
// (it falls back to its latest if it doesn't recognize this one), so an exact
// match is not required — but staying current avoids a degraded handshake.
const PROTOCOL_VERSION = "2025-11-25";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// <clone>/plugins/hpc/pi/extensions  ->  <clone>
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..", "..");
const MCP_JSON = path.join(REPO_ROOT, "plugins", "hpc", "mcp.json");
const FACILITIES_DIR = path.join(REPO_ROOT, "facilities");
const HPC_CONFIG_DIR = path.join(process.env.HOME || "~", ".hpc-agent");
const SELECTION_FILE = path.join(HPC_CONFIG_DIR, "hpc-pi-selection.json");

type FacilityFacts = {
  slug: string;
  display_name: string;
  description: string;
  live_validated?: boolean;
};

// ---------------------------------------------------------------------------
// Minimal MCP stdio client (JSON-RPC 2.0, newline-delimited).
// ---------------------------------------------------------------------------

class McpClient {
  private proc: ChildProcess;
  private nextId = 1;
  private pending = new Map<number, { resolve: (v: any) => void; reject: (e: any) => void }>();
  private buffer = "";
  readonly serverName: string;

  constructor(serverName: string, command: string, args: string[], env: Record<string, string>) {
    this.serverName = serverName;
    this.proc = spawn(command, args, {
      env: { ...process.env, ...env },
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.proc.stdout.setEncoding("utf-8");
    this.proc.stdout.on("data", (d: string) => this.onData(d));
    // The hub logs to stderr only (its invariant); surface it for debugging.
    this.proc.stderr.on("data", (d: Buffer) => process.stderr.write(`[hpc-mcp:${serverName}] ${d}`));
    this.proc.on("error", (e) => this.failAll(e));
    this.proc.on("close", (code) => this.failAll(new Error(`${serverName} exited (code ${code})`)));
  }

  private onData(chunk: string): void {
    this.buffer += chunk;
    let nl: number;
    while ((nl = this.buffer.indexOf("\n")) >= 0) {
      const line = this.buffer.slice(0, nl);
      this.buffer = this.buffer.slice(nl + 1);
      if (!line.trim()) continue;
      let msg: any;
      try {
        msg = JSON.parse(line);
      } catch {
        continue; // not a JSON-RPC message we recognize
      }
      // A response carries an id that matches a pending request.
      if (msg.id !== undefined && (msg.result !== undefined || msg.error !== undefined)) {
        const p = this.pending.get(msg.id);
        if (p) {
          this.pending.delete(msg.id);
          if (msg.error) p.reject(new Error(msg.error.message ?? JSON.stringify(msg.error)));
          else p.resolve(msg.result);
        }
      }
      // Notifications (no id) from the server are ignored — the hub does not
      // send any we need to act on here.
    }
  }

  private failAll(e: any): void {
    for (const p of this.pending.values()) p.reject(e);
    this.pending.clear();
  }

  private call(method: string, params?: any): Promise<any> {
    return new Promise((resolve, reject) => {
      const id = this.nextId++;
      this.pending.set(id, { resolve, reject });
      this.proc.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params: params ?? {} }) + "\n");
    });
  }

  private notify(method: string, params?: any): void {
    this.proc.stdin.write(JSON.stringify({ jsonrpc: "2.0", method, params: params ?? {} }) + "\n");
  }

  async initialize(): Promise<any> {
    const result = await this.call("initialize", {
      protocolVersion: PROTOCOL_VERSION,
      capabilities: {},
      clientInfo: { name: "pi-hpc-bridge", version: "0.1.0" },
    });
    this.notify("notifications/initialized", {});
    return result;
  }

  async listTools(): Promise<Array<{ name: string; description?: string; inputSchema?: any }>> {
    const result = await this.call("tools/list", {});
    return result?.tools ?? [];
  }

  callTool(name: string, args: any): Promise<any> {
    return this.call("tools/call", { name, arguments: args });
  }

  close(): void {
    try {
      this.proc.stdin.end();
    } catch {
      /* already closed */
    }
    try {
      this.proc.kill();
    } catch {
      /* already gone */
    }
  }
}

// ---------------------------------------------------------------------------
// Facility discovery + persisted selection (which skills to load).
// ---------------------------------------------------------------------------

function listFacilities(): FacilityFacts[] {
  // The canonical source is facilities/<slug>/facility.json (also read by the
  // facility-table generator), not the generated skill packs — so a facility
  // shows up here even before its skills are built.
  const out: FacilityFacts[] = [];
  let names: string[];
  try {
    names = fs.readdirSync(FACILITIES_DIR);
  } catch {
    return out;
  }
  for (const name of names) {
    if (name.startsWith(".")) continue;
    const p = path.join(FACILITIES_DIR, name, "facility.json");
    if (!fs.existsSync(p)) continue;
    try {
      out.push(JSON.parse(fs.readFileSync(p, "utf-8")));
    } catch {
      /* skip malformed */
    }
  }
  return out.sort((a, b) => a.slug.localeCompare(b.slug));
}

// Config files the user has already written (~/.hpc-agent/<slug>.json). A
// facility with one is a sensible default to pre-check in the picker. The
// filename uses the underscore form of the slug (rccs-cloud -> rccs_cloud).
function configuredSlugs(): Set<string> {
  const out = new Set<string>();
  let files: string[];
  try {
    files = fs.readdirSync(HPC_CONFIG_DIR);
  } catch {
    return out;
  }
  for (const f of files) {
    const m = f.match(/^(.+)\.json$/);
    if (m) out.add(m[1].replace(/_/g, "-")); // selection stores slug form
  }
  return out;
}

function facilitySkillPath(slug: string): string {
  return path.join(REPO_ROOT, "plugins", `hpc-${slug}`, "skills");
}

// In-memory cache of the persisted selection, so resources_discover (which
// fires after session_start) sees what session_start just chose even before
// the file is re-read. null = "no selection file yet, still need to ask".
let currentSelection: string[] | null = null;

function loadSelection(): string[] | null {
  if (currentSelection !== null) return currentSelection;
  try {
    currentSelection = JSON.parse(fs.readFileSync(SELECTION_FILE, "utf-8"));
  } catch {
    return null;
  }
  return currentSelection;
}

function saveSelection(slugs: string[]): void {
  currentSelection = slugs;
  try {
    fs.mkdirSync(HPC_CONFIG_DIR, { recursive: true });
    fs.writeFileSync(SELECTION_FILE, JSON.stringify(slugs, null, 2) + "\n");
  } catch {
    /* non-fatal: in-memory cache still drives this session */
  }
}

/**
 * The first-session ask. Loops single-selects (pi has no multi-select) with
 * a "Done" terminator. Facilities the user already configured are pre-
 * checked. Writes the result so later sessions skip the ask. Returns the
 * selected slugs (possibly empty). In non-interactive modes there is no UI
 * to ask with, so we persist an empty selection and move on — tools still
 * work, the user adds skills later via /hpc-add or by editing the file.
 */
async function ensureSelection(ctx: any): Promise<string[]> {
  if (loadSelection() !== null) return currentSelection!;
  const facs = listFacilities();
  if (facs.length === 0) {
    saveSelection([]);
    return [];
  }
  if (!ctx.hasUI) {
    saveSelection([]);
    return [];
  }
  const chosen = new Set<string>(configuredSlugs());
  const slugByLabel = new Map<string, string>();
  const done = "➤  Done";
  while (true) {
    const remaining = facs.filter((f) => !chosen.has(f.slug));
    const opts: string[] = [];
    slugByLabel.clear();
    for (const f of remaining) {
      const tag = f.live_validated ? "" : "  (awaiting live validation)";
      const label = `${f.display_name}  [${f.slug}]${tag}`;
      opts.push(label);
      slugByLabel.set(label, f.slug);
    }
    opts.push(done);
    const pick = await ctx.ui.select(
      "Add an HPC facility to load skills for (pick one, repeat, then Done)",
      opts,
    );
    if (!pick || pick === done) break;
    const slug = slugByLabel.get(pick);
    if (slug) chosen.add(slug);
  }
  const list = [...chosen];
  saveSelection(list);
  return list;
}

// ---------------------------------------------------------------------------
// Extension
// ---------------------------------------------------------------------------

export default function (pi: ExtensionAPI) {
  const clients: McpClient[] = [];

  // session_start: ask which facilities, then spawn the MCP servers and
  // register every tool they expose. The ask must complete before
  // resources_discover reads the selection; the hub lifecycle fires
  // session_start before resources_discover, and awaiting here persists the
  // choice first. A failed MCP spawn is non-fatal: skills still load and the
  // session is usable; the user fixes the cause (e.g. `uv` missing) and
  // /reloads.
  pi.on("session_start", async (_event, ctx) => {
    try {
      await ensureSelection(ctx);
    } catch (e: any) {
      ctx.ui?.notify?.(`HPC facility selection failed: ${e?.message ?? e}`, "error");
    }

    if (ctx.hasUI) ctx.ui.setStatus("hpc", "Starting HPC MCP servers (first run may build via uv)…");
    try {
      const cfg = JSON.parse(fs.readFileSync(MCP_JSON, "utf-8"));
      const servers: Record<string, any> = cfg.mcpServers ?? {};
      await Promise.all(
        Object.entries(servers).map(async ([name, s]) => {
          const client = new McpClient(name, s.command, s.args ?? [], s.env ?? {});
          clients.push(client);
          await client.initialize();
          const tools = await client.listTools();
          for (const t of tools) {
            pi.registerTool({
              name: t.name,
              label: t.name,
              description: t.description ?? "",
              parameters: t.inputSchema ?? { type: "object", properties: {} },
              async execute(_toolCallId, params, signal) {
                if (signal?.aborted) {
                  return { content: [{ type: "text", text: "cancelled" }], isError: true, details: { server: name } };
                }
                try {
                  const result = await client.callTool(t.name, params);
                  const content = Array.isArray(result?.content)
                    ? result.content
                    : [{ type: "text", text: JSON.stringify(result) }];
                  return {
                    content,
                    isError: !!result?.isError,
                    details: { server: name, tool: t.name },
                  };
                } catch (e: any) {
                  return {
                    content: [{ type: "text", text: `HPC tool ${t.name} failed: ${e?.message ?? e}` }],
                    isError: true,
                    details: { server: name, tool: t.name },
                  };
                }
              },
            });
          }
        }),
      );
    } catch (e: any) {
      ctx.ui?.notify?.(
        `HPC MCP servers failed to start: ${e?.message ?? e}. HPC tools unavailable until fixed and /reload.`,
        "error",
      );
    } finally {
      if (ctx.hasUI) ctx.ui.setStatus("hpc", "");
    }
  });

  // Contribute the selected facilities' skill directories. The base
  // hpc-facilities skill loads from the package manifest; this adds the
  // per-facility packs only for facilities the user chose. Fired on startup
  // and on /reload (reason: "reload"), so /hpc-add / /hpc-remove take effect.
  pi.on("resources_discover", async (_event, _ctx) => {
    const sel = loadSelection();
    return { skillPaths: sel ? sel.map(facilitySkillPath) : [] };
  });

  // Tear down the spawned MCP servers on session end / reload.
  pi.on("session_shutdown", async () => {
    for (const c of clients) c.close();
    clients.length = 0;
  });

  pi.registerCommand("hpc-add", {
    description: "Load skills for an HPC facility, then reload: /hpc-add <slug>",
    handler: async (args, ctx) => {
      const slug = (args ?? "").trim();
      if (!slug) {
        ctx.ui.notify("Usage: /hpc-add <slug>", "warning");
        return;
      }
      const facs = listFacilities();
      if (!facs.some((f) => f.slug === slug)) {
        ctx.ui.notify(
          `Unknown facility slug: ${slug}. Valid: ${facs.map((f) => f.slug).join(", ")}`,
          "error",
        );
        return;
      }
      const sel = new Set(loadSelection() ?? []);
      if (sel.has(slug)) {
        ctx.ui.notify(`${slug} is already loaded`, "info");
        return;
      }
      sel.add(slug);
      saveSelection([...sel]);
      ctx.ui.notify(`Added ${slug}. Reloading…`, "info");
      // ctx.reload() re-emits session_shutdown (kills the servers) then
      // session_start (spawns fresh) and resources_discover (new skills).
      // Per pi's docs, return immediately after — old runtime state is stale.
      await ctx.reload();
    },
  });

  pi.registerCommand("hpc-remove", {
    description: "Stop loading skills for an HPC facility, then reload: /hpc-remove <slug>",
    handler: async (args, ctx) => {
      const slug = (args ?? "").trim();
      if (!slug) {
        ctx.ui.notify("Usage: /hpc-remove <slug>", "warning");
        return;
      }
      const sel = new Set(loadSelection() ?? []);
      if (!sel.has(slug)) {
        ctx.ui.notify(`${slug} was not selected`, "warning");
        return;
      }
      sel.delete(slug);
      saveSelection([...sel]);
      ctx.ui.notify(`Removed ${slug}. Reloading…`, "info");
      await ctx.reload();
    },
  });
}
