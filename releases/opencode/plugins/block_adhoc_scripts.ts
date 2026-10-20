// SPDX-License-Identifier: Apache-2.0
//
// block_adhoc_scripts — opencode 2.x `tool.execute.before` guard + `permission.evaluate`
// gate plugin (THIN SHIM / GLUE ONLY).
//
// opencode's hook surface is JS/TS plugins (not Claude's settings.json command hook); the
// pre-tool event is `tool.execute.before` (blockable). This plugin gives opencode users the
// same runtime orchestrator-discipline enforcement Claude Code gets, by reusing the ONE
// decision source: the platform-neutral Python guard at ../hooks/block_adhoc_scripts.py.
//
// Module contract (opencode 2.x, packages/core/src/plugin/module.ts): ONLY a default export
// `{ id, setup }` (or `{ id, effect }`) is accepted. The 1.x named-export hook-map form is
// REJECTED at load — and the rejection is fail-soft (a WARN in the service log, sessions
// continue), so a shape drift silently disables the guard. This file targets 2.x only; 1.x
// opencode installations keep the previously released shim (no dual-shape file — a file
// satisfying both contracts is not expressible, and carrying two files would double the
// wiring surface). The shape is regression-guarded in CI (tests/test_opencode_hook_parity.py
// :: TestShimV2ModuleShape) precisely because the runtime cannot fail loud.
//
// 2.x execution model: plugins run inside the RESIDENT SERVICE process — its cwd is unrelated
// to the analyzed project, so the guard's cwd fallback would anchor to the wrong place. setup()
// captures `ctx.location.directory` (the session's project root) and injects it as the payload
// `cwd` on every guarded call; the guard's existing precedence (payload cwd > process cwd)
// then anchors sentinel discovery AND relative-token judgments to the project. Python side
// unchanged. Both hook registrations are awaited inside setup so the first tool call / first
// permission assertion cannot slip past an unregistered hook.
//
// permission.evaluate gate (the ONE declared in-process decision exception — everything on the
// tool face still lives in the Python guard): an unattended mgh run must NEVER wait on an
// interactive approval. In opencode 2.x an `ask` has NO timeout — the pending hangs forever
// with no answerer. This gate rewrites asks/questions to deterministic terminations BEFORE the
// pending is created (hooks.trigger passes the same event object through callbacks in place,
// and the rewritten effect/message flow back into the host's decision). Rules, active ONLY
// inside a run domain (any of the six run roots has a `.active` sentinel under the project
// root): ask -> deny + alternative-path hint, with the single exception of
// `external_directory` asks whose EVERY resource falls inside the sentinel's user-approved
// read-only `read_roots[]` -> allow; `question` (non-deny) -> deny + batch-clarify hint; deny
// is unreachable here (rule-level deny short-circuits before hooks); out-of-domain -> the
// event passes through untouched (daily non-mgh usage is unaffected). Corrupt sentinel JSON =
// no read_roots (asks deny, fail-closed); ANY error inside the callback is swallowed to an
// out-of-domain pass — a gate bug must never corrupt the host's permission decisions.
//
// What lives HERE (glue only): tool scoping + event normalization + anchor injection + pipe +
// block-on-exit-2. What NEVER lives here: run-domain env gating, introspection regexes, the
// .py whitelist, the MGH_TARGET subtree guard — ALL of that is the Python guard's job. This
// file MUST NOT reimplement any of it (single decision source, zero drift).
//
// Blocking contract: rejecting the `tool.execute.before` callback surfaces a Tool.Error and
// aborts the tool call (the error message surfaces to the model). The guard writes a
// remediation "recipe" to stderr on a hit and exits with code 2; we rethrow that stderr so
// the model sees the sanctioned-primitive recipe.
//
// Failure mode (fail-soft): if the guard can't be reached (python missing, file moved, spawn
// error), we log and PASS — never break the user's session. The shell bright-lines + per-stage
// `--check` boundary validation remain the real backstop either way.

import { existsSync, readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"

// opencode tool ids are lowercase; these mirror Claude's Bash|Write|Edit|Read|Glob|Grep
// matcher. TWO GENERATIONS converge on the same guard faces (2.x renamed ids without changing
// the guard; the same install file may be loaded by a 2.0.x or a 2.1.x host — dropping either
// generation silently un-guards it):
//   bash (1.x) / shell (2.x)  -> Bash face   (both carry { command })
//   apply_patch (1.x) / patch (2.x) -> ApplyPatch face (SAME patchText field + marker
//     syntax: packages/core/src/tool/plugin/patch.ts Input = { patchText })
// read/glob/grep/write/edit kept their names across both generations (2.x write/edit/read
// args are schema-validated `path` — the fallback chain in normalize covers it).
// read/glob/grep are handled so the guard's read-side out-of-tree confinement (peer of the
// write side) decides on both platforms. A DIRECT `rg`/`grep`/… in Bash/shell routes through
// the Bash face (handled above) and the guard's Bash file-search rule — it does NOT need a
// HANDLED entry here (only the native read/glob/grep TOOLS do).
// multiedit/notebookedit are CLAUDE-native tool ids with no opencode counterpart; patch is
// 2.x-native; runcode/terminalio/jobctl are dsh-dialect guard branches (rule (n)) — these are
// listed (routed through their guard names / the generic filePath fallback) ONLY to keep the
// wiring invariant "shim HANDLED ⊇ guard dispatch set" machine-checkable; opencode never
// emits the claude/dsh-native ids.
const HANDLED = new Set(["bash", "shell", "write", "edit", "read", "glob", "grep",
  "apply_patch", "patch", "multiedit", "notebookedit", "runcode", "terminalio", "jobctl"])

// patch/apply_patch `patchText` marker lines (opencode packages/util/src/patch.ts — the SAME
// parser serves 1.x `apply_patch` and 2.x `patch`):
//   *** Add File: <path>      *** Update File: <path>      *** Delete File: <path>
//   *** Move to: <path>
// Captures every path; the operation (add/update/delete/move) rides in a parallel operations[]
// so the guard can surface the delete wording. GLUE ONLY — no confinement decision here.
const PATCH_MARKER_RX = /\*\*\* (?:Add|Update|Delete) File: (.+?)$|\*\*\* Move to: (.+?)$/gm

// opencode args -> Claude tool_input (snake_case) the guard expects:
//   bash/shell  -> { command }                 (guard reads tool_input.command)
//   write/edit/read -> { filePath -> file_path } (guard reads tool_input.file_path)
//   glob        -> { pattern, path }
//   grep        -> { pattern, path, glob/include }
//   apply_patch/patch -> { paths[], operations[] }  (extracted from args.patchText markers)
// Defense-in-depth (D9): the tool schema field for the path is `path` (2.x write/edit/read
// Input schemas are schema-validated `path`); relying solely on camelCase `filePath` would
// yield an empty path whenever the host passes schema-validated args. The fallback chain reads
// `filePath ?? file_path ?? path` (zero behavior change for camelCase-emitting models).
// grep's source field is schema-validated `include`; fall back to `glob` for other shapes.
function normalize(tool: string, args: Record<string, unknown> | undefined) {
  if (tool === "bash" || tool === "shell") return { tool_name: "Bash", tool_input: { command: args?.command ?? "" } }
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
  if (tool === "apply_patch" || tool === "patch") {
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
  // runcode/terminalio/jobctl are dsh-dialect guard names (rule (n)) listed only for the
  // wiring invariant — opencode never emits them, but the fallback chain must NOT coerce
  // them into Edit, so they map to their guard names directly.
  if (tool === "runcode") return { tool_name: "RunCode", tool_input: {} }
  if (tool === "terminalio") return { tool_name: "TerminalIO", tool_input: {} }
  if (tool === "jobctl") return { tool_name: "JobCtl", tool_input: {} }
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
  // Fail-soft pre-check: python exits 2 (`can't open file ... .py`) for a MISSING guard
  // script — the SAME exit code as a guard denial. A missing/skewed install must degrade
  // to a pass + one diagnostic, NEVER a deny (the fail-soft contract is "guard absent ->
  // PASS").
  if (!existsSync(guard)) {
    return { code: 0, stderr: `[block_adhoc_scripts] guard file missing (${guard}); passing (fail-soft)` }
  }
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
        // the JSON payload. (A bare `stdin: stdin` throws inside runGuard -> caught ->
        // fail-soft-pass -> the guard NEVER blocks. Probe-reproduced on 1.x; the same
        // constraint holds on 2.x's bundled Bun.)
        stdin: new Blob([stdin]),
        stdout: "ignore",
        stderr: "pipe",
      })
      const code = await proc.exited
      const stderr = proc.stderr ? await new Response(proc.stderr).text() : ""
      // can't-open-file exit 2 (guard moved/deleted after the pre-check — TOCTOU or an
      // unusual missing shape) is python's own error, NOT a guard denial: fail-soft pass.
      if (code === 2 && /can't open file/i.test(stderr)) {
        return { code: 0, stderr: `[block_adhoc_scripts] guard file missing at spawn time (${guard}); passing (fail-soft)` }
      }
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

// ---------------------------------------------------------------------------
// permission.evaluate gate — glue helpers. The THREE rewrite rules below are
// the one declared in-process exception to "decisions live in the Python
// guard" (fixed two-and-a-half rules, no regex, no path-policy reasoning;
// shape-pinned by CI in tests/test_opencode_hook_parity.py). Everything on the
// tool face is still the Python guard's job.
// ---------------------------------------------------------------------------

// The six run roots, always DIRECT children of the project root. A `.active`
// sentinel under any of them marks an in-flight mgh run domain. NO ancestor
// walk (the Python guard's 16-level chain is intentionally NOT replicated): a
// sentinel in an ancestor directory marks a DIFFERENT project's run, and this
// plugin rewriting that project's asks would be out of scope. The mgh run
// roots are pinned to the project root by contract, so the narrow check loses
// nothing.
const RUN_ROOTS = [".mgh-init", "security-scan", ".mgh-sra", ".mgh-srr", ".mgh-ut-init", ".mgh-sdr"]

// Normalize a host path for membership checks: backslashes -> forward slashes,
// trailing slashes trimmed, case-folded (Windows drives/dirs are
// case-insensitive). Pure function.
function normPath(p: string): string {
  return p.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase()
}

// Does one permission resource fall inside one declared read-only root? The
// resource face for `external_directory` is forward-slash absolute with a glob
// tail (`C:/ext/dir/*` — opencode's file-access slash()es paths and appends
// `/*` for the directory boundary); a sentinel read_roots[] entry is a
// host-native absolute directory (`C:\ext\dir`). Strip the glob tail, then
// plain prefix membership on normalized forms. Pure function.
function inDeclaredRoot(resource: string, root: string): boolean {
  const res = normPath(String(resource).replace(/\/\*$/, ""))
  const r = normPath(root)
  if (!res || !r) return false
  return res === r || res.startsWith(r + "/")
}

// Discover the run domain from disk: whether any of the six run roots has a
// `.active` sentinel, and the UNION of their read_roots[] (absolute read-only
// roots the user approved when the run was armed). Stateless by design — the
// sentinel is written at step 0, so a fresh stat+parse per evaluation is
// correct and trivially cheap next to the per-call Python spawn. A present but
// unparsable sentinel still marks the domain ACTIVE with zero read_roots
// (asks deny — fail-closed); a parse failure of one sentinel never deactivates
// a domain another sentinel marks.
function declaredReadRoots(projectRoot: string): { active: boolean; roots: string[] } {
  let active = false
  const roots: string[] = []
  for (const runRoot of RUN_ROOTS) {
    const sentinelPath = projectRoot + "/" + runRoot + "/.active"
    if (!existsSync(sentinelPath)) continue
    active = true
    try {
      const sentinel = JSON.parse(readFileSync(sentinelPath, "utf8"))
      if (Array.isArray(sentinel?.read_roots)) {
        for (const root of sentinel.read_roots) {
          if (typeof root === "string" && root) roots.push(root)
        }
      }
    } catch (e) {
      console.warn(`[block_adhoc_scripts] unreadable sentinel ${sentinelPath} (read_roots ignored, asks deny): ${e instanceof Error ? e.message : e}`)
    }
  }
  return { active, roots }
}

// The gate callback's fixed rewrite rules. Returns having MUTATED
// `event.effect` / `event.message` in place (opencode's hooks.trigger passes
// the same event object through callbacks and reuses it for the decision).
// deny effects never reach here (rule-level deny short-circuits before hooks);
// they would be left untouched anyway.
function applyGate(event: { action?: string; resources?: ReadonlyArray<string>; effect?: string; message?: string }, roots: string[]) {
  // (2) question -> deny: a subagent asking the user anything is an
  // unattended-hang face; the tool family's substitute path is batch
  // clarification + checkpoint resume, not a live answer.
  if (event.action === "question") {
    if (event.effect !== "deny") {
      event.effect = "deny"
      event.message = "无人值守运行不向用户发问:把待澄清项写入本步骤产物/续跑记录,由编排流程统一走批量澄清与断点续跑。"
    }
    return
  }
  // (1) ask -> deny, with the single read_roots exception. allow passes
  // untouched (nothing to close).
  if (event.effect !== "ask") return
  if (
    event.action === "external_directory" &&
    roots.length > 0 &&
    (event.resources?.length ?? 0) > 0 &&
    event.resources!.every((resource) => roots.some((root) => inDeclaredRoot(resource, root)))
  ) {
    // User-approved read-only roots: the approval already happened at run
    // arming; keeping the ask would just preserve the hang face.
    event.effect = "allow"
    return
  }
  event.effect = "deny"
  event.message = "无人值守运行不接受交互式授权等待:改用运行域受信路径(目标树内或哨兵 read_roots 已声明的只读根);确需的外部资源请经受控方式物化进运行域后重试。"
}

// opencode 2.x plugin module contract: a default export { id, setup }. setup is async and
// AWAITS the hook registration before returning — a fire-and-forget registration lets the
// first tool call slip past an unregistered hook (probe-reproduced during the 2.x migration).
export default {
  id: "block-adhoc-scripts",
  async setup(ctx: {
    location?: { directory?: string }
    tool: { hook: (event: string, cb: (event: { tool?: string; input?: Record<string, unknown> }) => Promise<void>) => Promise<unknown> }
    permission: { hook: (event: string, cb: (event: { action?: string; resources?: ReadonlyArray<string>; effect?: string; message?: string }) => Promise<void>) => Promise<unknown> }
  }) {
    // The 2.x resident service process's cwd is unrelated to the analyzed project;
    // ctx.location.directory is the ONE authoritative "where is this project" signal the
    // plugin gets. Capture it once; inject per call (never via env — multiple locations must
    // not step on each other). Empty/absent -> omit the field; the guard then falls back to
    // its process cwd (the same last-resort it had before).
    const projectRoot: string = ctx?.location?.directory ?? ""
    await ctx.tool.hook("execute.before", async (event) => {
      const tool = event?.tool ?? ""
      // Tool-scope parity with Claude's Bash|Write|Edit matcher. Other tools: pass, no gate.
      if (!HANDLED.has(tool)) return
      const base = normalize(tool, event?.input)
      const payload = projectRoot ? { ...base, cwd: projectRoot } : base
      const { code, stderr } = await runGuard(payload)
      if (code === 2) {
        // Rejecting the callback aborts the opencode tool call (a Tool.Error surfaces to
        // the model); stderr is the guard's remediation recipe.
        throw new Error(stderr.trim() || "blocked by block_adhoc_scripts guard")
      }
      if (stderr) {
        // Non-blocking diagnostic from the guard/shim (e.g. fail-soft notice). The 1.x
        // app-log diagnostic channel is gone in 2.x; console.warn is best-effort — visible
        // in the service log when the service log is visible at all. Logging NEVER blocks
        // the call.
        console.warn(stderr.trim())
      }
    })
    // Permission gate registration: SAME awaited-inside-setup contract as the tool face (a
    // fire-and-forget registration would let the first permission assertion slip past).
    // Anything thrown inside applyGate is caught at THIS level and downgraded to an
    // out-of-domain pass — the callback NEVER rejects toward the host (a rejection would
    // defect the host's permission evaluation itself, a bigger blast radius than the hang
    // face this gate removes).
    await ctx.permission.hook("evaluate", async (event) => {
      try {
        const gate = declaredReadRoots(projectRoot)
        if (!gate.active) return
        applyGate(event, gate.roots)
      } catch (e) {
        console.warn(`[block_adhoc_scripts] permission gate error (passing untouched): ${e instanceof Error ? e.message : e}`)
      }
    })
  },
}
