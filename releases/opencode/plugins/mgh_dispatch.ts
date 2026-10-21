// SPDX-License-Identifier: Apache-2.0
//
// mgh_dispatch — opencode 2.x plugin: the IN-PROCESS deterministic execution face of the mgh
// native-dispatch route. ONE default export { id, setup } (the same 2.x module contract as the
// guard plugin, which this file NEVER touches — independent concerns: execution face vs
// interception face; both live in .opencode/plugins/ and the host auto-loads both).
//
// setup() awaits TWO registrations:
//
//   (1) the custom tool `mgh_dispatch` (ctx.tool.transform + editor.add): ONE call reads a
//       native plan artifact (native_plan.json, produced by the deterministic plan
//       materializer), then creates + prompts + waits the plan's units as child sessions —
//       in-wave concurrency = the plan's wave size, waves strictly sequential (the next wave
//       starts only after every unit of the previous wave reached a terminal state) — and
//       classifies each unit by DISK MARKERS ONLY, returning a compact structured summary.
//       This is the in-process equivalent of the subprocess fan-out dispatcher: the wave loop
//       that used to burn one orchestrator LLM round per wave lives here, in the host
//       process. Hundreds-to-thousands-unit plans run with ZERO LLM wave turns.
//
//   (2) a `tool.execute.before` token-expansion hook: a task text whose FIRST line is a token
//       line (`mgh-dispatch: plan=<plan-ref> unit=<short-id>`) is replaced, BEFORE the
//       built-in subagent tool runs, with the referenced unit's task-file content verbatim.
//       Non-token text passes untouched (the hook is NOT a general rewriter). This closes the
//       last long-path transcription face on the built-in subagent channel: the orchestrator
//       transcribes one plan reference + a 4-char short id, the host expands it
//       deterministically from the same plan artifact — the spawned subagent's task text is
//       byte-identical to the materialized task file by construction.
//
// Dispatch semantics are aligned with the built-in subagent tool
// (packages/core/src/tool/plugin/subagent.ts), gate for gate — a plugin that skipped any of
// them would open a hole the built-in closed:
//   permission  — before EVERY child creation, permission.assert on the `subagent` action with
//                 the target agent as the resource (same action, same save, same source face).
//                 The plugin NEVER bypasses the permission layer and NEVER answers on the
//                 user's behalf; an assertion failure surfaces as a tool error.
//   depth       — the parentID chain of the calling session is walked and compared against the
//                 nesting-depth limit, exactly like the built-in. The plugin face cannot read
//                 the host config (`experimental.subagent_depth`), so the built-in's DEFAULT
//                 (1) is used: identical behavior under default config; explicitly raised
//                 limits are not honored here (an honest, disclosed restriction).
//   agent mode  — the plan carries the target agent name; a PRIMARY-mode agent is refused
//                 before any spawn (tiers need their own subagent-form twin definitions).
//                 NEVER a silent fallback to another agent name.
//   task text   — description = the unit's short id; the task message = the unit's task file
//                 read by the plugin and injected verbatim (framed with the same
//                 "You are a subagent spawned by another session." line the built-in uses).
//                 The orchestrator model NEVER writes or paraphrases task content.
//   waves       — in-wave concurrency = how many units the plan put in that wave; waves run
//                 sequentially (a wave barrier, same discipline as the subprocess runner).
//
// Marker truth source (route-wide invariant): the plugin NEVER writes any unit marker and
// NEVER interprets findings. A unit is `done` when its done-marker exists, `failed` when its
// failed-marker exists, `no-marker` otherwise (reported as-is — the session's own outcome is
// NEVER substituted for the marker judgment; terminal session state only decides "markers can
// be read now"). The tool does NOT re-dispatch inside one call: units carrying a terminal
// marker are skipped, so RETRY = the orchestrator invoking the tool again (idempotent
// re-entry). At most one dispatch per unit per call — a bounded run, never an unbounded loop.
//
// Quota self-limiting: the env profile at <projectRoot>/.mgh/env-profile.json may carry
// quota {calls, window_s, calls_per_unit}. Between waves the same ESTIMATED sliding-window
// admission arithmetic as the subprocess dispatcher applies (in-window dispatches x K + K <=
// N; K = calls_per_unit): when the estimate says the next wave would not fit, the tool SLEEPS
// in ~1s shards until the window slides open (wait episodes + waited time disclosed in the
// summary). Profile missing / quota absent / profile unparsable => zero throttling (the
// Python reader owns fail-closed profile validation; this plugin does not re-implement a
// second judgment source — an unparsable profile is disclosed, never silently "valid"). A
// quota that can NEVER admit (calls_per_unit > calls even at zero dispatches) is disclosed
// and bypassed rather than hanging the tool call forever. The estimate is an ESTIMATE: real
// per-unit call counts are gateway-side facts.
//
// Cancel cascade: when the tool call is aborted (host abort signal), every created child
// session that is still active is interrupted, one by one, before the tool ends — no orphan
// child keeps burning quota. Sessions that already reached a terminal state keep their
// markers (abort != failure; an interrupted unit simply has no terminal marker and re-enters
// the pending set on the next materialization).
//
// Summary compactness: the return value carries counts + short-id lists + per-unit session
// ids + the waves actually run + quota-wait facts — NEVER findings content, NEVER task text
// (details live on disk; a big fan-out must not inflate the orchestrator context with a
// per-unit report — the same "summary, not details" discipline as the subprocess runner).
//
// Input contract (closed set): plan (REQUIRED — the ONLY path-shaped field the tool ever
// accepts; absolute or project-root-relative), wave (optional integer, 1-based, runs only
// that wave), units (optional short-id array, runs only those units; wave and units are
// mutually exclusive). Unit task/checkpoint/marker paths NEVER enter the input — they always
// come from the plan artifact. Every validation failure (plan unreadable/unparsable, short id
// not in the plan, wave out of range, wave+units together) => tool error + one recipe line,
// and ZERO sessions created: a mis-transcribed call is collected at the door, not after
// spawning.
//
// Failure mode: this plugin is glue around the host session API and the plan artifact; it
// holds no credentials, writes no run artifacts, and makes no policy decisions. If the plan
// is stale relative to disk, re-materializing (the plan --check contract) is the repair —
// never an in-tool patch.
//
// The shape of this file is regression-guarded in CI
// (tests/test_opencode_hook_parity.py :: TestDispatchPluginShape): the double registration,
// the three per-spawn gates, the cancel cascade, the short-id validation, the token prefix
// constant, and the never-writes-markers property are all pinned — removing any of them turns
// CI red (the "miss one gate = a security/completeness gap" checklist is machine-enforced).

import { existsSync, readFileSync } from "node:fs"
import { isAbsolute, join } from "node:path"

// ---------------------------------------------------------------------------
// Token-line contract (ONE constant, shared shape with the sdr native wave-discipline
// fragment — pinned by CI so the hook and its first consumer cannot drift apart):
//
//   mgh-dispatch: plan=<plan-ref> unit=<short-id>
//
// The token line is the ENTIRE task text (first line); the hook replaces the whole text with
// the referenced unit's task-file content. The plan reference may be absolute or relative to
// the project root; the short id is the plan's 4-char per-unit id.
// ---------------------------------------------------------------------------
const TOKEN_PREFIX = "mgh-dispatch:"
const TOKEN_RX = /^mgh-dispatch:[ \t]+plan=(\S+)[ \t]+unit=(\S+)[ \t]*$/

// The built-in subagent tool frames every prompt with this exact first line
// (packages/core/src/tool/plugin/subagent.ts); the dispatch tool mirrors it so plugin-created
// children are behaviorally indistinguishable from built-in-spawned ones.
const SUBAGENT_FRAME = "You are a subagent spawned by another session."

const SUBAGENT_TOOL = "subagent"

// Nesting-depth limit used when the host config is unreachable from the plugin face (see
// header: equals the built-in's DEFAULT; explicitly raised limits are not honored, disclosed).
const DEPTH_LIMIT_DEFAULT = 1

// Bound on the parentID walk so a corrupted parent chain cannot hang the tool.
const MAX_DEPTH_WALK = 64

// m(e): one-line message from an unknown throw shape.
function m(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

// fail(message): tool error + recipe in one throw. Every fail BEFORE the dispatch loop
// guarantees zero sessions were created.
function fail(message: string): never {
  throw new Error(message)
}

// Host API results arrive as direct payloads in some shapes and {data: ...} wrappers in
// others (endpoint schemas differ across faces); accept both. A payload that legitimately
// carries no `data` field passes through untouched.
function unwrap<T>(result: T): any {
  if (result && typeof result === "object" && "data" in (result as Record<string, unknown>)) {
    const d = (result as Record<string, unknown>).data
    if (d !== undefined && d !== null) return d
  }
  return result
}

// Project-root-anchored resolution of the ONE path-shaped input field. A relative reference
// without a project root anchor cannot be resolved (the service process cwd is unrelated to
// the project) and must fail loud rather than guess.
function resolvePlanRef(ref: string, projectRoot: string): string {
  if (!ref) return ""
  if (isAbsolute(ref)) return ref
  return projectRoot ? join(projectRoot, ref) : ""
}

// Read + shape-check a plan artifact. Deliberately minimal: the plan materializer's --check
// owns deep validation (byte-identity, anchor-tree, short-id distance); this only asserts the
// fields the tool actually consumes, so a plan that passes here is guaranteed walkable.
// Returns { ok: true, plan } | { ok: false, error }.
function readPlan(planPath: string): { ok: boolean; plan?: PlanShape; error?: string } {
  if (!planPath) return { ok: false, error: "计划引用为空" }
  let body: any
  try {
    body = JSON.parse(readFileSync(planPath, "utf8"))
  } catch (e) {
    return { ok: false, error: `计划不可读/不可解析: ${planPath} (${m(e)})` }
  }
  if (!body || typeof body !== "object" || Array.isArray(body))
    return { ok: false, error: `计划不是 JSON 对象: ${planPath}` }
  if (!Array.isArray(body.waves) || body.waves.length === 0)
    return { ok: false, error: `计划缺 waves[](非空数组): ${planPath}` }
  const waves: { wave: number; units: PlanUnit[] }[] = []
  for (const w of body.waves) {
    if (!w || typeof w !== "object" || !Number.isInteger(w.wave) || !Array.isArray(w.units))
      return { ok: false, error: `计划波次形状非法(需 {wave: 整数, units: 数组}): ${planPath}` }
    for (const u of w.units) {
      if (!u || typeof u !== "object" || typeof u.id !== "string" || !u.id ||
          typeof u.task_file !== "string" || !u.task_file)
        return { ok: false, error: `计划单元缺 id/task_file(字符串): ${planPath}` }
    }
    waves.push({ wave: w.wave, units: w.units })
  }
  if (typeof body.agent !== "string" || !body.agent)
    return { ok: false, error: `计划缺 agent 字段(目标 agent 名): ${planPath}` }
  return { ok: true, plan: { agent: body.agent, waves } }
}

interface PlanUnit {
  id: string
  task_file: string
  done_marker?: unknown
  failed_marker?: unknown
  [k: string]: unknown
}

interface PlanShape {
  agent: string
  waves: { wave: number; units: PlanUnit[] }[]
}

// First unit matching a short id, keeping the plan's own wave numbering.
function findUnit(plan: PlanShape, shortId: string): { wave: number; unit: PlanUnit } | undefined {
  for (const w of plan.waves)
    for (const u of w.units)
      if (u.id === shortId) return { wave: w.wave, unit: u }
  return undefined
}

// Marker existence is disk truth; any read error counts as "not there" (classification then
// honestly reports no-marker rather than guessing).
function markerExists(p: unknown): boolean {
  if (typeof p !== "string" || !p) return false
  try {
    return existsSync(p)
  } catch {
    return false
  }
}

function isTerminal(unit: PlanUnit): boolean {
  return markerExists(unit.done_marker) || markerExists(unit.failed_marker)
}

// The THREE-way disk classification. The child session's own outcome is NEVER consulted:
// done-marker present => done; else failed-marker present => failed; else no-marker
// (reported as-is, never rewritten, never inferred).
function classifyUnit(unit: PlanUnit): "done" | "failed" | "no-marker" {
  if (markerExists(unit.done_marker)) return "done"
  if (markerExists(unit.failed_marker)) return "failed"
  return "no-marker"
}

// Port of the subprocess dispatcher's quota admission arithmetic (same estimate, same
// shapes): a unit is admissible iff `in-window dispatches x K + K <= N` (K = calls_per_unit,
// N = calls). Inadmissible -> the timestamp at which enough of the OLDEST in-window
// dispatches slid out. A quota that can never admit (K > N even at zero dispatches) reports
// `now` — the caller must never busy-spin on an already-past resume ts. Pure.
function quotaAdmission(
  dispatchTimes: number[], windowS: number, calls: number, perUnit: number, nowS: number,
): { admissible: boolean; used: number; resumeS: number } {
  const recent = dispatchTimes.filter((t) => nowS - t <= windowS)
  const used = recent.length * perUnit
  if (used + perUnit <= calls) return { admissible: true, used, resumeS: 0 }
  const maxInWindow = Math.max(0, Math.floor(calls / perUnit) - 1)
  const needSlide = recent.length - maxInWindow
  if (needSlide <= 0) return { admissible: false, used, resumeS: nowS }
  const resumeS = [...recent].sort((a, b) => a - b)[needSlide - 1] + windowS
  return { admissible: false, used, resumeS }
}

// Best-effort quota read from the project env profile. The Python reader owns fail-closed
// profile validation (shells gate on it at step 0); this plugin does NOT re-implement that
// judgment — it only reads an already-valid profile for THROTTLING:
//   missing file / no quota object / absent fields -> null (zero throttling);
//   unparsable file / non-positive or wrong-typed quota fields -> { broken: true }
//   (zero throttling + a disclosure counter in the summary, never a crash, never a silent
//   "treat as valid").
function readQuota(projectRoot: string): { calls: number; windowS: number; perUnit: number } | null | { broken: true } {
  if (!projectRoot) return null
  const p = join(projectRoot, ".mgh", "env-profile.json")
  if (!existsSync(p)) return null
  try {
    const q = JSON.parse(readFileSync(p, "utf8"))?.quota
    if (!q || typeof q !== "object") return null
    const { calls, window_s: windowS, calls_per_unit: perUnit } = q
    if (!Number.isInteger(calls) || calls <= 0 ||
        !Number.isInteger(windowS) || windowS <= 0 ||
        !Number.isInteger(perUnit) || perUnit <= 0)
      return { broken: true }
    return { calls, windowS, perUnit }
  } catch {
    return { broken: true }
  }
}

const sleep = (ms: number) => new Promise<void>((res) => setTimeout(res, ms))

// opencode 2.x plugin module contract: default export { id, setup }, setup async, BOTH
// registrations awaited inside it (a fire-and-forget registration lets the first tool call /
// first dispatch slip past an unregistered face — probe-reproduced during the 2.x migration).
export default {
  id: "mgh-dispatch",
  async setup(ctx: {
    location?: { directory?: string }
    tool: {
      hook: (event: string, cb: (event: {
        tool?: string
        input?: Record<string, unknown>
      }) => Promise<void>) => Promise<unknown>
      transform: (callback: (editor: {
        add: (tool: Record<string, unknown>) => void
      }) => void) => Promise<unknown>
    }
    session: {
      get: (input: { sessionID: string }) => Promise<unknown>
      create: (input: Record<string, unknown>) => Promise<unknown>
      prompt: (input: { sessionID: string; text: string }) => Promise<unknown>
      wait: (input: { sessionID: string }) => Promise<unknown>
      interrupt: (input: { sessionID: string }) => Promise<unknown>
    }
    permission: {
      assert: (input: Record<string, unknown>) => Promise<void>
    }
    agent: {
      get: (input: { agentID: string }) => Promise<unknown>
    }
  }) {
    // The 2.x resident service process's cwd is unrelated to the analyzed project; this is
    // the ONE authoritative project-root signal (same anchor the guard plugin captures).
    const projectRoot: string = ctx?.location?.directory ?? ""

    // ------------------------------------------------------------------
    // (1) Token-expansion hook: subagent task texts that are a token line get expanded to
    // the unit's task-file content BEFORE the built-in subagent tool runs. Non-token text
    // passes untouched (zero interference with ordinary subagent usage). Unknown short id /
    // unreadable plan => tool error + recipe, the subagent never starts — mis-transcription
    // is collected before spawn, the same defense line as the dispatch tool's input gate.
    // ------------------------------------------------------------------
    await ctx.tool.hook("execute.before", async (event) => {
      if (event?.tool !== SUBAGENT_TOOL) return
      const prompt = event?.input?.prompt
      if (typeof prompt !== "string" || !prompt.startsWith(TOKEN_PREFIX)) return
      const nl = prompt.indexOf("\n")
      const firstLine = (nl === -1 ? prompt : prompt.slice(0, nl)).trim()
      const tok = TOKEN_RX.exec(firstLine)
      if (!tok) return
      const loaded = readPlan(resolvePlanRef(tok[1], projectRoot))
      if (!loaded.ok)
        fail(`${loaded.error};recipe: 令牌行的计划引用逐字来自 emit_native_plan.py stdout 摘要的 plan_path——先物化 + --check,再以其 stdout 的 plan_path 重试`)
      const hit = findUnit(loaded.plan!, tok[2])
      if (!hit)
        fail(`未知短号: ${tok[2]};recipe: 合法短号只来自计划工件(native_plan.json 的 waves[].units[].id,或物化 stdout 摘要)——NEVER 凭记忆转述`)
      let taskText: string
      try {
        taskText = readFileSync(hit.unit.task_file, "utf8")
      } catch (e) {
        fail(`任务文件不可读: ${hit.unit.task_file} (${m(e)});recipe: 计划与任务文件以最新一次 emit_native_plan.py 物化为准——重跑物化后重试`)
      }
      // Whole-text replacement: the subagent receives the file content verbatim; the
      // orchestrator's output carried only the token line, zero long paths.
      event.input!.prompt = taskText
    })

    // ------------------------------------------------------------------
    // (2) The mgh_dispatch tool itself.
    // ------------------------------------------------------------------
    await ctx.tool.transform((editor) =>
      editor.add({
        name: "mgh_dispatch",
        options: { codemode: false },
        description: [
          "mgh 原生派发执行面:按计划工件(native_plan.json)在宿主进程内按波次并发创建、驱动、收割子会话——一次调用跑完计划全部波次,零 LLM 波次回合。",
          "输入:plan=计划文件引用(必填;绝对路径或相对项目根;输入中唯一允许的路径字段);wave=只跑该波(1-based 整数);units=只派这些短号单元(字符串数组)。",
          "wave 与 units 互斥,只能传其一;缺省 = 按计划顺序跑全部波次。",
          "单元的任务文件/产物/标记路径 NEVER 作为输入——一律来自计划工件。",
          "幂等:已有终态标记(.done/.failed)的单元自动跳过;重试 = 再次调用本工具。",
          "返回紧凑摘要(分类计数 + failed/no-marker 短号清单 + 每单元会话 id + 实跑波次),不含 findings 内容。",
          "仅随 mgh 运行域使用(计划工件由 emit_native_plan.py 物化)。",
        ].join("\n"),
        input: {
          type: "object",
          additionalProperties: false,
          required: ["plan"],
          properties: {
            plan: {
              type: "string",
              description:
                "计划文件引用(native_plan.json;绝对路径或相对项目根)。输入中唯一允许的路径字段,逐字来自物化 stdout 摘要的 plan_path。",
            },
            wave: {
              type: "integer",
              minimum: 1,
              description: "只跑该波(1-based)。与 units 互斥。",
            },
            units: {
              type: "array",
              items: { type: "string" },
              minItems: 1,
              description: "只派这些短号单元(须在计划内)。与 wave 互斥。",
            },
          },
        },
        execute: async (
          input: { plan?: unknown; wave?: unknown; units?: unknown },
          context: {
            sessionID: string
            agent: string
            messageID: string
            id: string
            signal?: AbortSignal
          },
        ) => {
          const summary: Record<string, unknown> = {
            plan: typeof input?.plan === "string" ? input.plan : "",
            mode: "all",
            waves_run: [] as number[],
            dispatched: 0,
            skipped_terminal: 0,
            done: 0,
            failed: 0,
            no_marker: 0,
            failed_units: [] as string[],
            no_marker_units: [] as string[],
            units: [] as Record<string, unknown>[],
            aborted: false,
          }
          const finish = () => ({ content: JSON.stringify(summary), metadata: summary })

          // ---- input contract: closed set; EVERY failure here = tool error + recipe,
          //      ZERO sessions created ----
          if (typeof input?.plan !== "string" || !input.plan)
            fail("plan 必填(计划文件引用,绝对路径或相对项目根);recipe: 传 emit_native_plan.py stdout 摘要的 plan_path")
          if (input.wave !== undefined && input.units !== undefined)
            fail("wave 与 units 互斥(一次调用只选其一);recipe: 全部波次 = 两个都不传")
          if (input.wave !== undefined) summary.mode = "wave"
          if (input.units !== undefined) summary.mode = "units"
          const planPath = resolvePlanRef(input.plan as string, projectRoot)
          const loaded = readPlan(planPath)
          if (!loaded.ok)
            fail(`${loaded.error};recipe: 计划由 emit_native_plan.py 物化——先重跑物化 + --check,再以其 stdout 摘要的 plan_path 调用本工具`)
          const plan = loaded.plan!
          if (input.wave !== undefined) {
            if (!Number.isInteger(input.wave) || (input.wave as number) < 1)
              fail(`wave 必须是 >=1 的整数(1-based;got ${JSON.stringify(input.wave)})`)
            if ((input.wave as number) > plan.waves.length)
              fail(`wave ${input.wave} 越界(计划共 ${plan.waves.length} 波);recipe: 波号来自物化 stdout 摘要的 waves/wave_size`)
          }
          let selected: { wave: number; unit: PlanUnit }[] | null = null
          if (input.units !== undefined) {
            if (!Array.isArray(input.units) ||
                input.units.length === 0 ||
                !input.units.every((u) => typeof u === "string" && u))
              fail("units 必须是非空短号字符串数组;recipe: 短号逐字来自计划工件")
            const missing = (input.units as string[]).filter((s) => !findUnit(plan, s))
            if (missing.length > 0)
              fail(`未知短号: ${missing.join(", ")};recipe: 合法短号只来自计划工件(native_plan.json 的 waves[].units[].id,或物化 stdout 摘要)——NEVER 凭记忆转述`)
            selected = (input.units as string[]).map((s) => findUnit(plan, s)!)
          }

          // Worklist in plan order (wave barriers preserved; `units` selection filters
          // within that order — it never reorders or merges waves).
          const work: { wave: number; unit: PlanUnit }[] = []
          for (const w of plan.waves) {
            if (input.wave !== undefined && w.wave !== input.wave) continue
            for (const u of w.units) {
              if (selected && !input.units.includes(u.id)) continue
              work.push({ wave: w.wave, unit: u })
            }
          }
          // Idempotent re-entry: terminal-marked units are skipped, never re-dispatched.
          const pending = work.filter((item) => {
            if (isTerminal(item.unit)) {
              summary.skipped_terminal = (summary.skipped_terminal as number) + 1
              return false
            }
            return true
          })
          if (pending.length === 0) return finish()

          // ---- dispatch semantics, aligned with the built-in subagent tool ----
          // Depth: the SAME parent-chain walk the built-in does, against the built-in's
          // DEFAULT limit (the plugin face cannot read experimental.subagent_depth — a
          // disclosed restriction; behavior under default config is identical).
          let depth = 0
          try {
            let cursor: string | undefined = context.sessionID
            for (let i = 0; i < MAX_DEPTH_WALK && cursor; i++) {
              const info = unwrap(await ctx.session.get({ sessionID: cursor }))
              cursor = info?.parentID
              if (cursor) depth++
            }
          } catch {
            // a broken parent chain degrades to the depth counted so far — the walk must
            // never hang the tool; the host still enforces its own limits server-side.
          }
          if (depth >= DEPTH_LIMIT_DEFAULT)
            fail(`子代理嵌套深度已达上限(${DEPTH_LIMIT_DEFAULT};插件面按宿主缺省保守限制);recipe: 编排器→子代理单层是默认合法形态——不要在子代理里再调本工具`)

          // Agent mode: the plan's agent must resolve to a subagent-form twin; primary mode
          // is refused BEFORE any spawn. NEVER a silent fallback to another agent name.
          let agentRaw: unknown
          try {
            agentRaw = await ctx.agent.get({ agentID: plan.agent })
          } catch (e) {
            fail(`agent 查询失败: ${plan.agent} (${m(e)});recipe: 计划的 agent 须是本机已定义的 subagent 形态孪生`)
          }
          const agent = unwrap(agentRaw)
          if (!agent || !agent.id)
            fail(`未知 agent: ${plan.agent};recipe: 计划的 agent 须是本机已定义的 subagent 形态孪生(mode: subagent,如 sdr-review-native);primary 形态(子进程派发孪生)会被拒绝`)
          if (agent.mode === "primary")
            fail(`agent ${plan.agent} 是 primary 形态,不能作为子代理派发;recipe: 各 tier 需要各自的 subagent 形态孪生定义(mode: subagent)——NEVER 降级尝试或静默换名`)

          // The child's model: the agent's configured model wins, else the parent's (same
          // precedence the built-in applies). A parent fetch failure degrades to the host
          // default rather than failing the dispatch.
          let parentModel: unknown
          try {
            parentModel = unwrap(await ctx.session.get({ sessionID: context.sessionID }))?.model
          } catch {
            parentModel = undefined
          }

          // Quota self-limiting state. A never-admissible quota (K > N even at zero
          // dispatches) is disclosed and bypassed: sleeping toward it would hang the tool
          // call forever on an estimate.
          const quota = readQuota(projectRoot)
          const quotaBroken = quota !== null && "broken" in quota
          const quotaNeverAdmissible =
            quota !== null && !quotaBroken && (quota as { perUnit: number; calls: number }).perUnit >
              (quota as { calls: number }).calls
          const quotaActive = quota !== null && !quotaBroken && !quotaNeverAdmissible
          if (quotaBroken) summary.quota_profile_broken = true
          if (quotaNeverAdmissible) summary.quota_never_admissible = true
          if (quotaActive)
            summary.quota = { waits: 0, waited_ms: 0 }
          const dispatchTimes: number[] = []

          // ---- cancel cascade machinery: every created child that is still active when the
          //      abort signal fires is interrupted, one by one; interrupts settle before the
          //      tool returns ----
          const active = new Set<string>()
          const interrupts: Promise<unknown>[] = []
          let aborted = false
          const onAbort = () => {
            aborted = true
            summary.aborted = true
            for (const id of [...active]) {
              active.delete(id)
              interrupts.push(ctx.session.interrupt({ sessionID: id }).catch(() => {}))
            }
          }
          const signal = context?.signal
          if (signal) {
            if (signal.aborted) onAbort()
            else signal.addEventListener("abort", onAbort, { once: true })
          }
          // ONE shared abort promise: every in-wave wait races against it, so an abort
          // releases the whole wave immediately (the cascade listener owns the children).
          const abortPromise: Promise<{ __aborted: true }> | null = signal
            ? new Promise((res) => {
                if (signal.aborted) res({ __aborted: true })
                else signal.addEventListener("abort", () => res({ __aborted: true }), { once: true })
              })
            : null

          const dispatchUnit = async (item: { wave: number; unit: PlanUnit }) => {
            const { unit } = item
            // Permission assert PER SPAWN — same action, same resource face, same save and
            // source fields the built-in subagent tool asserts. The plugin never bypasses
            // the permission layer and never answers on the user's behalf.
            try {
              await ctx.permission.assert({
                action: SUBAGENT_TOOL,
                resources: [agent.id],
                save: [agent.id],
                sessionID: context.sessionID,
                agent: context.agent,
                source: { type: "tool", messageID: context.messageID, id: context.id },
              })
            } catch (e) {
              fail(`子代理权限断言未通过(subagent -> ${agent.id}) (${m(e)});recipe: 本插件不绕过权限层也不代答——在权限配置中放行 subagent 动作后重试;已收割单元的磁盘标记不受影响`)
            }
            // Task message = the unit's task file VERBATIM (the plugin reads the file; the
            // orchestrator model never writes or paraphrases task content), framed with the
            // same line the built-in uses.
            let taskText: string
            try {
              taskText = readFileSync(unit.task_file, "utf8")
            } catch (e) {
              fail(`任务文件不可读: ${unit.task_file} (${m(e)});recipe: 计划与任务文件以最新一次 emit_native_plan.py 物化为准——重跑物化后重试`)
            }
            let childRaw: unknown
            try {
              childRaw = await ctx.session.create({
                parentID: context.sessionID,
                title: unit.id,
                agent: plan.agent,
                model: agent.model ?? parentModel ?? undefined,
              })
            } catch (e) {
              fail(`子会话创建失败(unit ${unit.id}) (${m(e)})`)
            }
            const child = unwrap(childRaw)
            if (!child || !child.id)
              fail(`子会话创建返回异常(unit ${unit.id})`)
            active.add(child.id)
            summary.dispatched = (summary.dispatched as number) + 1
            const row = { id: unit.id, wave: item.wave, session: child.id, status: "no-marker" }
            ;(summary.units as Record<string, unknown>[]).push(row)
            dispatchTimes.push(Date.now() / 1000)
            try {
              await ctx.session.prompt({
                sessionID: child.id,
                text: `${SUBAGENT_FRAME}\n${taskText}`,
              })
            } catch (e) {
              fail(`子会话 prompt 失败(unit ${unit.id}, session ${child.id}) (${m(e)})`)
            }
            // Wait raced against abort: losing to abort leaves THIS session to the cascade
            // listener (already interrupted by it); a wait rejection still falls through to
            // the disk-marker classification (the session's outcome is never the judge).
            const waitP = ctx.session.wait({ sessionID: child.id }).catch(() => {})
            const r = abortPromise ? await Promise.race([waitP, abortPromise]) : await waitP
            if (r && (r as { __aborted?: boolean }).__aborted) return
            active.delete(child.id)
            row.status = classifyUnit(unit)
            if (row.status === "done") {
              summary.done = (summary.done as number) + 1
            } else if (row.status === "failed") {
              summary.failed = (summary.failed as number) + 1
              ;(summary.failed_units as string[]).push(unit.id)
            } else {
              summary.no_marker = (summary.no_marker as number) + 1
              ;(summary.no_marker_units as string[]).push(unit.id)
            }
          }

          // Wave barriers: waves run strictly in plan order; a wave's units all run
          // concurrently (in-wave concurrency = the plan's wave size); a batch error is
          // raised only AFTER the whole batch settled, so already-created children are
          // always harvested (or cascaded) — never abandoned mid-wave.
          const wavesToRun = [...new Set(pending.map((p) => p.wave))].sort((a, b) => a - b)
          try {
            for (const wv of wavesToRun) {
              if (aborted) break
              if (quotaActive) {
                // Admission gate BEFORE creating any session of this wave: sleep in ~1s
                // shards toward the sliding-window reopen ts (never busy-spin), counting
                // wait episodes and waited time into the summary.
                const q = quota as { calls: number; windowS: number; perUnit: number }
                let waitActive = false
                for (;;) {
                  if (aborted) break
                  const nowS = Date.now() / 1000
                  const gate = quotaAdmission(dispatchTimes, q.windowS, q.calls, q.perUnit, nowS)
                  if (gate.admissible) break
                  if (!waitActive) {
                    waitActive = true
                    ;(summary.quota as { waits: number }).waits++
                  }
                  const resumeInMs = Math.max(0, (gate.resumeS - Date.now() / 1000) * 1000)
                  if (resumeInMs <= 0) {
                    // Defensive: an already-past reopen ts (never-admissible shape that
                    // slipped through the up-front guard) must not spin — disclose + stop
                    // throttling rather than hang.
                    summary.quota_never_admissible = true
                    break
                  }
                  const t0 = Date.now()
                  await sleep(Math.min(1000, resumeInMs))
                  ;(summary.quota as { waited_ms: number }).waited_ms += Date.now() - t0
                }
                if (aborted) break
              }
              const batch = pending.filter((p) => p.wave === wv)
              ;(summary.waves_run as number[]).push(wv)
              const settled = await Promise.allSettled(batch.map(dispatchUnit))
              const firstError = settled.find((s) => s.status === "rejected")
              if (firstError)
                fail((firstError as PromiseRejectedResult).reason instanceof Error
                  ? (firstError as PromiseRejectedResult).reason.message
                  : String((firstError as PromiseRejectedResult).reason))
            }
          } finally {
            if (signal) signal.removeEventListener("abort", onAbort)
            if (aborted) onAbort() // idempotent: sweep anything still active
            await Promise.allSettled(interrupts)
          }
          return finish()
        },
      }),
    )
  },
}
