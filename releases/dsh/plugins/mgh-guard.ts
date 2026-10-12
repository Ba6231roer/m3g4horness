// SPDX-License-Identifier: Apache-2.0
//
// mgh-guard — dsh (deepseek-harness) `tools/pre-execute` plugin (THIN SHIM / GLUE ONLY).
//
// Third wiring face, peer of the claude settings.json PreToolUse hook and the opencode
// `tool.execute.before` plugin. dsh's hook surface is Cordis TypeScript plugins; the
// blockable pre-execution waterfall event is `tools/pre-execute`. This shim gives dsh users
// the same runtime orchestrator-discipline enforcement, reusing the ONE decision source:
// the sibling Python guard ./block_adhoc_scripts.py (byte-identical to the other faces).
//
// What lives HERE (glue only): tool scoping + event normalization + process spawn + outcome
// translation. What NEVER lives here: run-domain gating, introspection regexes, the verb
// tables, the MGH_TARGET subtree judgment — ALL of that is the Python guard's job (single
// decision source, zero drift across three faces).
//
// Blocking contract: the listener returns a decision — `{ kind: "deny", reason }` aborts the
// tool call and the reason text lands in the model-visible tool result as `Error: <reason>`
// (full text, no truncation; peer of claude exit-2+stderr and opencode throw(message)). We
// pass the guard's stderr recipe through as the reason so the model sees the sanctioned-primitive
// recipe. A pass MUST `return next()` (the waterfall adopts the OUTER listener's value; not
// returning rejects the chain silently).
//
// Run-domain activation: dsh plugin processes do NOT inherit env exported mid-session by the
// orchestrator's shell tool (same boundary as opencode), so activation rides the DISK
// SENTINEL: the guard walks up from the payload `cwd` (session working directory) looking
// for `<dir>/<run-root>/.active`. Env is inherited best-effort (harmless when absent).
//
// Failure mode (fail-soft): if the guard can't be reached (no python interpreter, file
// moved, spawn error), we log one diagnostic to the host log and PASS — never break the
// user's session. install self-check proves Python availability at mirror time; missing
// python later is post-install environment drift.

import { spawn } from "node:child_process"
import { fileURLToPath } from "node:url"

// dsh tool ids -> guard dispatch names. The wiring invariant (wiring-coverage regression
// test) statically parses this table and asserts: guard dispatch set ⊆ values ∪, and every
// dsh id routed here exists as a key. `multiedit`/`notebookedit` are claude-native ids dsh
// never emits — listed only so the invariant "shim table ⊇ guard dispatch set" is uniformly
// machine-checkable (same convention as the opencode HANDLED set). `web_fetch` is NOT
// mapped: its schema carries no file-output parameter (`{url}` only), so there is no
// file-mutating shape to judge; first-run observation may add it later.
export const TOOL_MAP = {
  bash: "Bash",
  pwsh: "Bash", // same path-net judgment as the Bash face (verb tables + allowset net)
  read: "Read",
  write: "Write",
  edit: "Edit",
  multiedit: "MultiEdit",
  notebookedit: "NotebookEdit",
  str_replace_editor: "ApplyPatch", // paths extracted from the command payload (glue only)
  glob: "Glob",
  grep: "Grep",
  run_code: "RunCode", // guard rule (n): bundled code runner = `py -c` analogue
  terminal_open: "TerminalIO",
  terminal_send: "TerminalIO",
  terminal_read: "TerminalIO",
  terminal_signal: "TerminalIO",
  terminal_close: "TerminalIO",
  terminal_list: "TerminalIO",
  job_output: "JobCtl",
  job_list: "JobCtl",
  job_kill: "JobCtl",
} as const

// dsh args -> the guard's snake_case tool_input (mirrors the opencode normalize()). dsh
// field names verified against the host schema: bash/pwsh `command`; read/write/edit
// `file_path`; glob `pattern`/`path`; grep `pattern`/`path`/`include`;
// str_replace_editor `command`(view|create|str_replace|insert)/`path`/`file_text`/
// `old_str`/`new_str`. Renaming happens HERE, never in the guard core.
function normalize(tool: string, args: Record<string, unknown> | undefined, cwd: string) {
  const name = (TOOL_MAP as Record<string, string>)[tool]
  if (!name) return null // unmapped id: pass through untouched (host approval decides)
  if (name === "Bash") return { tool_name: "Bash", tool_input: { command: String(args?.command ?? "") }, cwd }
  if (name === "Glob") return {
    tool_name: "Glob",
    tool_input: { pattern: String(args?.pattern ?? ""), path: String(args?.path ?? "") },
    cwd,
  }
  if (name === "Grep") return {
    tool_name: "Grep",
    tool_input: {
      pattern: String(args?.pattern ?? ""),
      path: String(args?.path ?? ""),
      glob: String(args?.include ?? args?.glob ?? ""),
    },
    cwd,
  }
  if (name === "ApplyPatch") {
    // str_replace_editor mutating commands map onto the ApplyPatch paths[]/operations[]
    // shape (view is non-mutating: empty paths[] => guard passes). GLUE ONLY — the
    // out-of-tree / script-ext / sanctioned-subtree decision is the guard's.
    const cmd = String(args?.command ?? "")
    const path = String(args?.path ?? "")
    const paths: string[] = []
    const operations: string[] = []
    if (path && cmd === "create") { paths.push(path); operations.push("add") }
    else if (path && (cmd === "str_replace" || cmd === "insert")) { paths.push(path); operations.push("update") }
    return { tool_name: "ApplyPatch", tool_input: { paths, operations }, cwd }
  }
  if (name === "RunCode" || name === "TerminalIO" || name === "JobCtl") {
    return { tool_name: name, tool_input: {}, cwd }
  }
  // Read / Write / Edit / MultiEdit / NotebookEdit: file path under file_path.
  return { tool_name: name, tool_input: { file_path: String(args?.file_path ?? args?.path ?? "") }, cwd }
}

function guardPath(): string {
  // Sibling co-location: the guard is mirrored next to this shim
  // (<dest>/mgh-core/dsh/), so the path is correct regardless of the project cwd.
  return fileURLToPath(new URL("./block_adhoc_scripts.py", import.meta.url))
}

interface GuardResult { code: number; stderr: string }

function feedGuard(py: string, payload: unknown): Promise<GuardResult> {
  return new Promise((resolve, reject) => {
    let proc: ReturnType<typeof spawn>
    try {
      proc = spawn(py, [guardPath()], { cwd: process.cwd(), env: process.env, stdio: ["pipe", "ignore", "pipe"] })
    } catch (e) {
      reject(e); return
    }
    let out = ""
    let settled = false
    proc.on("error", (e) => { if (!settled) { settled = true; reject(e) } })
    proc.stderr?.on("data", (d: Buffer) => { out += d.toString() })
    proc.on("close", (code) => {
      if (!settled) { settled = true; resolve({ code: code ?? 0, stderr: out }) }
    })
    proc.on("spawn", () => {
      try {
        // One-shot Buffer write + end (streaming pipes deadlocked opencode's bundled Bun;
        // same posture here).
        proc.stdin?.end(Buffer.from(JSON.stringify(payload), "utf8"))
      } catch (e) {
        if (!settled) { settled = true; reject(e) }
      }
    })
  })
}

async function runGuard(payload: unknown): Promise<GuardResult> {
  // `py` (Windows launcher / some Linux), else `python3`, else `python` — same fallback
  // chain as the opencode face (spike-verified on dsh/windows: `py` present, python/
  // python3 absent => the chain order matters). Glue only.
  for (const py of ["py", "python3", "python"]) {
    try {
      return await feedGuard(py, payload)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      // ENOENT = this interpreter isn't on PATH; try the next one.
      if (/ENOENT|not found|no such file/i.test(msg)) continue
      return { code: 0, stderr: `[mgh-guard] guard invoke failed (${py}): ${msg}` }
    }
  }
  return { code: 0, stderr: "[mgh-guard] no python interpreter found (py/python3/python); passing (fail-soft)" }
}

export const name = "mgh-guard"

export function apply(ctx: any): void {
  ctx.on("tools/pre-execute", async (exec: any, next: () => Promise<unknown>) => {
    const tool = String(exec?.name ?? "")
    if (!(tool in TOOL_MAP)) return next() // unmapped: never feed the guard, never guess
    // The guard's activation anchor: the session working directory (the dsh plugin process
    // cwd is not the session context; payload `cwd` is what the sentinel walk starts from).
    const sessionCwd = String(exec?.agent?.session?.header?.cwd ?? process.cwd())
    const payload = normalize(tool, exec?.arguments as Record<string, unknown> | undefined, sessionCwd)
    if (!payload) return next()
    const { code, stderr } = await runGuard(payload)
    if (code === 2) {
      return { kind: "deny", reason: stderr.trim() || "blocked by mgh-guard (block_adhoc_scripts)" }
    }
    if (stderr) console.error(stderr.trim()) // one fail-soft diagnostic, non-blocking
    return next()
  })
}
