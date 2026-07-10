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
// from its inherited process env (MGH_{INIT,SAST,SRA}_ACTIVE); outside a run it exits 0 silently.
//
// Blocking contract: throw inside `tool.execute.before` aborts the tool call (the error message
// surfaces to the model). The guard writes a remediation "recipe" to stderr on a hit and exits
// with code 2; we rethrow that stderr so the model sees the sanctioned-primitive recipe.
//
// Failure mode (fail-soft): if the guard can't be reached (python missing, file moved, spawn
// error), we log and PASS — never break the user's session. The shell bright-lines + per-stage
// `--check` boundary validation remain the real backstop either way.

import { fileURLToPath } from "node:url"

// opencode tool ids are lowercase; only these three mirror Claude's Bash|Write|Edit matcher
// (D7 parity — do NOT run the guard on every read/grep/glob, which would over-trigger).
const HANDLED = new Set(["bash", "write", "edit"])

// opencode args (camelCase) -> Claude tool_input (snake_case) the guard expects:
//   bash  -> { command }            (guard reads tool_input.command)
//   write -> { filePath -> file_path }   (guard reads tool_input.file_path)
//   edit  -> { filePath -> file_path }
function normalize(tool: string, args: Record<string, unknown> | undefined) {
  if (tool === "bash") return { tool_name: "Bash", tool_input: { command: args?.command ?? "" } }
  const fp = (args?.filePath as string) ?? (args?.file_path as string) ?? ""
  return { tool_name: tool === "write" ? "Write" : "Edit", tool_input: { file_path: fp } }
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
        stdin: stdin,
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
