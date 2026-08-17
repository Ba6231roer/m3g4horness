// SPDX-License-Identifier: Apache-2.0
//
// block_adhoc_scripts — opencode `tool.execute.before` plugin (THIN SHIM / GLUE ONLY).
//
// opencode's hook surface is JS/TS plugins (not Claude's settings.json command hook); the
// pre-tool event is `tool.execute.before` (blockable). This plugin gives opencode users the
// same runtime orchestrator-discipline enforcement Claude Code gets, by reusing the ONE
// decision source: the platform-neutral Python guard at ../hooks/block_adhoc_scripts.py.
//
// What lives HERE (glue only): tool scoping + event normalization + pipe + block-on-exit-2.
// What NEVER lives here: run-domain env gating, introspection regexes, the .py whitelist, the
// MGH_TARGET subtree guard — ALL of that is the Python guard's job. This file MUST NOT
// reimplement any of it (single decision source, zero drift). The guard reads the run-domain
// from its inherited process env (MGH_{INIT,SAST,SRA,SRR}_ACTIVE); outside a run it exits 0 silently.
//
// Blocking contract: throw inside `tool.execute.before` aborts the tool call (the error message
// surfaces to the model). The guard writes a remediation "recipe" to stderr on a hit and exits
// with code 2; we rethrow that stderr so the model sees the sanctioned-primitive recipe.
//
// Failure mode (fail-soft): if the guard can't be reached (python missing, file moved, spawn
// error), we log and PASS — never break the user's session. The shell bright-lines + per-stage
// `--check` boundary validation remain the real backstop either way.

import { fileURLToPath } from "node:url"

// opencode tool ids are lowercase; these mirror Claude's Bash|Write|Edit|Read|Glob|Grep
// matcher. read/glob/grep are now handled so the guard's read-side out-of-tree confinement
// (peer of the write side) decides on both platforms. apply_patch is opencode's multi-file
// mutating tool (add/update/delete/move); its file paths live inside a `patchText` blob, which
// normalize() extracts into paths[] (glue-only field extraction — the guard decides). A DIRECT
// `rg`/`grep`/… in Bash routes through the `bash` tool (handled above) and the guard's Bash
// file-search rule — it does NOT need a HANDLED entry here (only the native read/glob/grep
// TOOLS do). multiedit/notebookedit are CLAUDE-native tool ids with no opencode counterpart —
// they are listed (and routed through the generic filePath fallback) ONLY to keep the wiring
// invariant "shim HANDLED ⊇ guard dispatch set" machine-checkable; opencode never emits them.
const HANDLED = new Set(["bash", "write", "edit", "read", "glob", "grep", "apply_patch",
  "multiedit", "notebookedit"])

// apply_patch `patchText` marker lines (opencode packages/core/src/patch.ts:35-51):
//   *** Add File: <path>      *** Update File: <path>      *** Delete File: <path>
//   *** Move to: <path>
// Captures every path; the operation (add/update/delete/move) rides in a parallel operations[]
// so the guard can surface the delete wording. GLUE ONLY — no confinement decision here.
const PATCH_MARKER_RX = /\*\*\* (?:Add|Update|Delete) File: (.+?)$|\*\*\* Move to: (.+?)$/gm

// opencode args (camelCase) -> Claude tool_input (snake_case) the guard expects:
//   bash        -> { command }                 (guard reads tool_input.command)
//   write/edit  -> { filePath -> file_path }   (guard reads tool_input.file_path)
//   read        -> { filePath -> file_path }
//   glob        -> { pattern, path }
//   grep        -> { pattern, path, glob/include }
//   apply_patch -> { paths[], operations[] }   (extracted from args.patchText markers)
// Defense-in-depth (D9): opencode's tool schema field for the path is `path`, not `filePath`
// (packages/core/src/tool/{edit,write,read}.ts); relying solely on camelCase `filePath` would
// yield an empty path if opencode ever passes schema-validated args. The fallback chain reads
// `filePath ?? file_path ?? path` (zero behavior change for the current camelCase-emitting LLM).
// grep's source field is schema-validated `include`; fall back to `glob` for the current shape.
function normalize(tool: string, args: Record<string, unknown> | undefined) {
  if (tool === "bash") return { tool_name: "Bash", tool_input: { command: args?.command ?? "" } }
  if (tool === "glob") return {
    tool_name: "Glob",
    tool_input: { pattern: (args?.pattern as string) ?? "", path: (args?.path as string) ?? "" },
  }
  if (tool === "grep") return {
    tool_name: "Grep",
    tool_input: {
      pattern: (args?.pattern as string) ?? "",
      path: (args?.path as string) ?? "",
      glob: (args?.include as string) ?? (args?.glob as string) ?? "",
    },
  }
  if (tool === "apply_patch") {
    // Extract every marker path from the patchText blob into paths[] (parallel operations[]).
    // GLUE ONLY: no out-of-tree / extension / sanctioned-subtree decision — that is the guard's.
    const patchText = (args?.patchText as string) ?? ""
    const paths: string[] = []
    const operations: string[] = []
    let m: RegExpExecArray | null
    PATCH_MARKER_RX.lastIndex = 0
    while ((m = PATCH_MARKER_RX.exec(patchText)) !== null) {
      const raw = (m[1] ?? m[2] ?? "").trim()
      if (raw) {
        paths.push(raw)
        // the marker verb decides the operation label (delete => delete wording downstream)
        const line = patchText.slice(Math.max(0, m.index), m.index + 20).toLowerCase()
        if (line.includes("delete file")) operations.push("delete")
        else if (line.includes("move to")) operations.push("move")
        else if (line.includes("update file")) operations.push("update")
        else operations.push("add")
      }
    }
    return { tool_name: "ApplyPatch", tool_input: { paths, operations } }
  }
  // write / edit / read (and the claude-native multiedit/notebookedit ids, kept for the
  // wiring invariant) all carry a file path under filePath/file_path/path.
  const fp = (args?.filePath as string) ?? (args?.file_path as string) ?? (args?.path as string) ?? ""
  const name = tool === "read" ? "Read" : tool === "write" ? "Write"
    : tool === "multiedit" ? "MultiEdit" : tool === "notebookedit" ? "NotebookEdit" : "Edit"
  return { tool_name: name, tool_input: { file_path: fp } }
}

function guardPath(): string {
  // Resolve relative to this plugin file so it is correct regardless of the project cwd:
  // plugin = <project>/.opencode/plugins/block_adhoc_scripts.ts
  // guard = <project>/.opencode/hooks/block_adhoc_scripts.py
  return fileURLToPath(new URL("../hooks/block_adhoc_scripts.py", import.meta.url))
}

async function runGuard(payload: unknown): Promise<{ code: number; stderr: string }> {
  const guard = guardPath()
  const stdin = JSON.stringify(payload)
  // `py` (Windows launcher / some Linux), else `python3`, else `python`. Glue only.
  for (const py of ["py", "python3", "python"]) {
    try {
      const proc = Bun.spawn({
        cmd: [py, guard],
        cwd: process.cwd(),
        env: process.env, // inherit — carries MGH_*_ACTIVE if set at opencode launch
        // Bun.spawn in opencode's bundled Bun rejects a STRING stdin (TypeError: stdio must
        // be 'inherit'|'pipe'|'ignore'|Bun.file|number|null); a Blob is accepted and delivers
        // the JSON payload. (Confirmed opencode 1.18.3: a bare `stdin: stdin` threw inside
        // runGuard -> caught -> fail-soft-pass -> the guard NEVER blocked. Probe-reproduced;
        // this was the real D7 root cause, not plugin loading / tool-id / cwd.)
        stdin: new Blob([stdin]),
        stdout: "ignore",
        stderr: "pipe",
      })
      const code = await proc.exited
      const stderr = proc.stderr ? await new Response(proc.stderr).text() : ""
      return { code, stderr }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      // spawn ENOENT = this python isn't on PATH; try the next one.
      if (/ENOENT|not found|no such file/i.test(msg)) continue
      // any other failure: fail-soft pass (don't break the session).
      return { code: 0, stderr: `[block_adhoc_scripts] guard invoke failed (${py}): ${msg}` }
    }
  }
  return { code: 0, stderr: "[block_adhoc_scripts] no python interpreter found (py/python3/python); passing (fail-soft)" }
}

export const BlockAdhocScripts = async (ctx: { client?: any }) => {
  return {
    "tool.execute.before": async (input: { tool: string }, output: { args: any }) => {
      // Tool-scope parity with Claude's Bash|Write|Edit matcher (D7). Other tools: pass, no gate.
      if (!HANDLED.has(input.tool)) return
      const { code, stderr } = await runGuard(normalize(input.tool, output.args))
      if (code === 2) {
        // Throwing aborts the opencode tool call; stderr is the guard's remediation recipe.
        throw new Error(stderr.trim() || "blocked by block_adhoc_scripts guard")
      }
      if (stderr) {
        // Non-blocking diagnostic from the guard/shim (e.g. fail-soft notice). Best-effort log.
        try {
          await ctx.client?.app?.log?.({
            body: { service: "block_adhoc_scripts", level: "warn", message: stderr.trim() },
          })
        } catch {
          /* logging is best-effort */
        }
      }
    },
  }
}
