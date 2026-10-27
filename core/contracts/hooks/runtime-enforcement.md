# Contract: runtime hook enforcement (`block_adhoc_scripts`)

Producer: for `/mgh-init` (and `/mgh-ut-init`, which shares the writer), the sentinel is a
**deterministic side-effect of `write_runconfig.py`** (co-written atomically with
`run_config.json`; `resume_state.py --check` validates its existence mid-run and
`--rearm-sentinel` rewrites it from the persisted `run_config.target` on resume); the
remaining domains' writer surface is per-domain and pinned in the Lifecycle section —
sra/srr/sast write it from the orchestrator shell step 0 (Bash), and **sdr has a fully
scripted lifecycle with no `printf` recipe anywhere** (see "sdr sentinel lifecycle"
below). Consumer: the shared guard
`core/scripts/block_adhoc_scripts.py` — the canonical copy; the three distributed guard
copies (claude `hooks/`, opencode `hooks/`, dsh `mgh-core/dsh/` sibling) are byte-identical
to it, asserted by `tests/test_dsh_hook_parity.py`. The opencode `.ts` plugin and the dsh
`.ts` shim are glue-only: each normalizes its host's tool-execution event into the same
`{tool_name, tool_input, cwd}` payload and pipes it to the same `.py` (all decision logic
lives in the Python guard — NEVER in either `.ts`). Spec:
`openspec/specs/runtime-hook-enforcement/spec.md`.

> **激活 = env 或磁盘哨兵(最优锚点起有界向上发现)。** 守卫在一个 mgh 运行域内激活当且仅当
> (a) env `MGH_<DOM>_ACTIVE=1` 已设,**或** (b) 锚到盘根链上任一级 `<dir>/<run-root>/.active`
> 哨兵存在。锚 = **最优可用 cwd 信号**:hook stdin payload 的 `cwd` 字段优先——claude PreToolUse
> 携带会话/工具 cwd(发起工具调用的那个上下文);dsh 由 shim 从会话头 `exec.agent.session.header.cwd`
> 取同一语义的目录填入 payload `cwd`;opencode 2.x 插件在 `setup` 时捕获
> `ctx.location.directory`(会话项目根)逐调用注入 payload `cwd`(见下「opencode 2.x plugin
> module contract」节)。缺省回退守卫进程 cwd 仅作**最后兜底**(opencode 2.x 的守卫进程 =
> 常驻服务进程,cwd 与项目无关;claude/dsh 的进程 cwd 则通常是发起调用的同一上下文)。
> 哨兵发现从锚自身起**向上 walk**(锚 → 逐祖先,至盘根或 16 级有界,先到者止),每级
> 查 `<dir>/<run-root>/.active`。向上 walk 闭合锚错配缺口:reader subagent(或锚是 target
> 子目录任意深度的宿主)仍能在 `<target>/<run-root>/.active` 命中哨兵——旧
> cwd-only 单点发现在该锚下找不到哨兵 → 守卫休眠 → 读/写侧全部静默降级放行。哨兵绕开
> opencode「插件进程不继承 mid-session bash 导出的 env」的可靠性边界(该边界同样存在于 dsh:
> 插件/shim 进程 env 不随会话导出而变,磁盘哨兵对三端同源可见)。运行域外(锚起向上
> walk 全链有界皆无哨兵且无 env):退出码 0 放行(零日常噪声)。
>
> **opencode / dsh 残余边界(显式运行要求,非缺陷)**:opencode 2.x 的锚由插件从
> `ctx.location.directory` 注入,与「从哪个目录启动宿主/服务」解耦——从 target 树**外**启动
> opencode 不再使守卫休眠(锚始终是会话项目根)。残余退化形状:插件拿不到
> `ctx.location.directory`(缺席/不可解析)→ payload 无 `cwd` → 回退服务进程 cwd,锚不在
> target 链上时守卫整 run 休眠。dsh 的锚来自会话头 cwd(每工具调用随 payload 传入),休眠面
> 仅剩「会话头缺失 → 回退 shim 进程 cwd」;env 不继承边界两端同在(磁盘哨兵补偿)。守卫
> **NEVER 整盘扫描补偿**(性能 + 越权)。
>
> **dsh fail-soft 条款**:shim 找不到可用 Python 解释器(回退链 `py`→`python3`→`python` 全
> 缺)、守卫 spawn 自身崩溃、或 payload 无法归一化 → **一律放行 + 日志一条**(失败绝不
> 阻断正常开发)。deny 通道 = 守卫退出码 2 → shim 返回 `{kind:"deny", reason:<守卫 stderr
> 全文>}`,宿主把它渲染成模型可见的 `Error: <reason>`(不截断);recipe 文案的唯一来源是
> 守卫,shim 不加工。

## Sentinel `<dir>/<run-root>/.active` (anchored upward discovery)

```json
{"domain": "mgh-init", "target": "<abs target>", "out_roots": ["<abs>..."], "v": 1}
```

Optional field (absent by default; absence preserves the shape byte-for-byte):

```json
{"domain": "mgh-sdr", "target": "<abs target>", "out_roots": [], "read_roots": ["<abs external repo>"], "v": 1}
```

| Field | Purpose |
|---|---|
| `domain` | `mgh-init` / `mgh-sast` / `mgh-sra` / `mgh-srr` / `mgh-ut-init` / `mgh-sdr` (advisory; discovery is by path) |
| `target` | abs project root (Windows-native; **MUST** come from a Python leaf-script stdout — `describe_artifact --field repo` / `prepare_augment`/`ingest_requirements` stdout `project_root` / `write_runconfig` stdout `target` / sdr: `sdr_context` stdout `repo` (the launcher and `resume_sdr_state` re-use that same source) — never bash `pwd`, which emits MSYS `/c/...` that pathlib mis-resolves on Windows) |
| `out_roots[]` | abs roots for customized `--out` / `--rules-dir` (init & ut-init; honors custom output locations without over-blocking) |
| `read_roots[]` | **optional** abs external READ-ONLY roots (sdr: confirmed external repos the launcher/sdr_context actually searched). BOTH read faces honor them: the tool face (`Read`/`Glob`/`Grep`) AND the Bash face (search/listing verbs + the catch-all path-token allowset, rule m) — **语义反转** (the prior "tool-face only; Bash search verbs judged against `MGH_TARGET` alone" decision is reversed; what is readable at all is readable through any tool). The write side (tool + Bash verb + redirect + delete) is NEVER honored — judged against `MGH_TARGET` alone; likewise the leaf-source / `py -c` / temp-I/O / file-assoc blocks. **read_roots 最小化纪律**: declare only roots actually searched in this run — NEVER a user-supplied catch-all / drive root. Fail-closed: a declared root must exist and be a directory at judgment time; a missing root grants zero. |
| `v` | schema version |

`out_roots[]` (write-side allowlist extension, init/ut-init) and `read_roots[]` (read-side-only
extension, any domain) are independent fields with disjoint effects.

### Project read-roots config `<target>/.mgh/read-roots.json`

A per-project, hand-editable config extends the unified read allow-set in EVERY run-domain
(guard reads it on every active call, once — same order as the sentinel read):

```json
{"v": 1, "read_roots": ["<abs root>", "..."]}
```

| Aspect | Contract |
|---|---|
| Location | `<MGH_TARGET>/.mgh/read-roots.json` (inside the target tree — writes to it are governed by the ordinary write-confinement rules) |
| Union | entries merge with the sentinel's `read_roots[]` into ONE allow-set feeding the tool-face read rule, the Bash search/listing rules, and the rule-m catch-all net — the SAME set on both faces |
| Read-only | a config root NEVER grants write access (write side judges `MGH_TARGET` alone) and NEVER relaxes the leaf-source / `py -c` / temp-I/O / file-assoc blocks |
| Fail-closed | missing file = behavior identical to no config; malformed JSON / `read_roots` not a list / non-dict body = zero grants, no crash, no other judgment altered; each entry needs exist-and-is-dir containment at judgment time (a missing entry grants zero) |
| Tolerance | unknown fields ignored; non-string / blank entries skipped |
| Authoring | hand-editable by the user; TWO deterministic writers are landed — `read_roots_config.py --add` and `sdr_context.py --approve-external` (ONE shared validated atomic-write implementation behind both entry points, NEVER two drifting copies; both demand an existing absolute directory, exit 2 zero-write otherwise, idempotent) |

**语义反转注记**: with rule m in place the Bash face judges paths directly (verb-independently),
so the prior decision that a declared root NEVER becomes a Bash-searchable location is REVERSED —
"凡允许读的目录,用什么工具读都放行". The read/write asymmetry is deliberate: declared roots are
readable, never writable.

### Per-domain run-root (sentinel location, discovered on the anchor chain)

| Domain | env flag | run-root | sentinel path |
|---|---|---|---|
| `mgh-init` | `MGH_INIT_ACTIVE` | `.mgh-init` | `<dir>/.mgh-init/.active` |
| `mgh-sast` | `MGH_SAST_ACTIVE` | `security-scan` | `<dir>/security-scan/.active` |
| `mgh-sra` | `MGH_SRA_ACTIVE` | `.mgh-sra` | `<dir>/.mgh-sra/.active` |
| `mgh-srr` | `MGH_SRR_ACTIVE` | `.mgh-srr` | `<dir>/.mgh-srr/.active` |
| `mgh-sdr` | `MGH_SDR_ACTIVE` | `.mgh-sdr` | `<dir>/.mgh-sdr/.active` |
| `mgh-ut-init` | `MGH_UT_INIT_ACTIVE` | `.mgh-ut-init` | `<dir>/.mgh-ut-init/.active` |

`<dir>` runs over the anchor-to-drive-root chain (anchor itself first, then each ancestor,
bounded to 16 levels / the filesystem root). The anchor = payload `cwd` (claude / dsh — the
dsh shim fills it from the session header cwd; opencode 2.x — the plugin injects
`ctx.location.directory`, see the section below) ?? guard process cwd (last-resort only).

## dsh tool-name normalization (shim `TOOL_MAP`, glue only)

dsh emits lowercase snake_case tool ids. The shim's static `TOOL_MAP` constant normalizes
them onto the guard's canonical names (the same names the claude face dispatches on); the
guard NEVER sees a dsh-native id, and fields are renamed to the snake_case tool_input shape
(`file_path` etc.) the guard already parses:

| dsh tool id | normalized name | notes |
|---|---|---|
| `bash` | `Bash` | dsh's bash tool is win32-disabled; see `pwsh` |
| `pwsh` | `Bash` | zero new guard code — hits the existing five verb tables + rule-m catch-all verbatim |
| `read` / `write` / `edit` / `multiedit` / `notebookedit` | `Read` / `Write` / `Edit` / `MultiEdit` / `NotebookEdit` | field `file_path` passes through |
| `str_replace_editor` | `ApplyPatch` | shim extracts `paths[]`/`operations[]` from `command`+`path` (`view` → empty paths = non-mutating pass); mutating commands enter the write-confinement tool face |
| `glob` / `grep` | `Glob` / `Grep` | `pattern`/`path`/`include`→`glob` |
| `run_code` | `RunCode` | bundled inline interpreter = introspection-shaped violation's peer on the tool face: domain-active → exit 2 + recipe pointing at the sanctioned exit (run the INSTALLED leaf script verbatim); body is NOT sniffed (shape-only, same stance as the heredoc rule) |
| `terminal_open/send/read/signal/close/list` | `TerminalIO` | interactive terminal bypasses foreground confinement → domain-active deny |
| `job_output/list/kill` | `JobCtl` | background-job bypass likewise → domain-active deny |
| anything else (e.g. `web_fetch`) | *unmapped* | shim returns `next()` untouched (pass-through; observed-and-adjudicated during first-run acceptance) |

## opencode 2.x plugin module contract (shim shape, glue only)

The opencode `.ts` shim targets the **opencode 2.x plugin module contract**; 1.x opencode
installations keep the previously released shim file (accepted discontinuation — the
enterprise deployment is 2.x; see the version matrix below). Facts below are pinned against
the opencode source (packages/core/src/plugin/module.ts, packages/plugin/src/effect/tool.ts,
packages/core/src/tool/plugin/{shell,patch,write,edit,read,glob,grep}.ts).

| Aspect | Contract |
|---|---|
| Module shape | **default export only**: `{ id: <string>, setup: <async fn> }` (or `{ id, effect }`). A 1.x-style named export (`export const …` returning the hook map) is REJECTED at load — and the rejection is **fail-soft** (a WARN in the service log, sessions continue), so shape drift silently disables the guard. CI asserts the shape statically (`tests/test_opencode_hook_parity.py::TestShimV2ModuleShape`, shared with the installed-copy check in `tests/test_install_opencode_plugin.py`) — the runtime cannot fail loud by design. |
| Hook registration | **both** hook faces registered **inside `setup`, each awaited before it returns**: `await ctx.tool.hook("execute.before", cb)` (tool guard) and `await ctx.permission.hook("evaluate", cb)` (permission gate) — a fire-and-forget registration lets the first tool call / first permission assertion slip past an unregistered hook. |
| Event shape | the callback reads a **single event object**: tool id from `event.tool`, args from `event.input` (plus `sessionID`/`agent`/`messageID`/`id`). The 1.x two-parameter `(input, output)` form does not exist in 2.x. |
| Blocking contract | rejecting the callback (throw) surfaces a `Tool.Error` and aborts the tool call; the guard's exit-2 stderr is rethrown verbatim as the recipe. Unchanged from 1.x. |
| Anchor injection | `setup` captures `ctx.location.directory` (the session's project root) and injects it as the payload `cwd` on EVERY guarded call (omitted when unresolvable). The 2.x plugin runs inside the **resident service process** whose cwd is unrelated to the project — without the injection the guard's process-cwd fallback anchors to the wrong place and sentinel discovery is dead for the whole run. Guard-side precedence (payload `cwd` > process cwd) is pre-existing; Python unchanged. |
| Diagnostics | the 1.x app-log diagnostic channel does not exist in 2.x; non-blocking diagnostics go to `console.warn` (best-effort, service log). Blocking contract unchanged. |
| Version matrix | implemented against **2.1.0** (local, real-machine gated) and **2.0.32** (enterprise shared-service form, gated on the intranet before archive); the module contract + hook/event shapes above are the common surface both accept per the 2.0.32 gate checklist in the change's real-machine notes. |
| Loader notes | `.opencode/plugins/*.ts` auto-discovery unchanged; plugin runtime imports are limited to `effect` / `@opencode/plugin` / node builtins (the shim uses `node:fs`/`node:url`/`Bun.spawn` only — no npm dependency). |

> **Scope note**: the mgh plugin directory carries a SECOND repo-owned file,
`mgh_dispatch.ts` (native-dispatch tool + token-expansion hook). It is placed by the same
installer (fixed two-file set) but is NOT part of the guard's contract — its input
contract / dispatch semantics / version matrix live in the fan-out runtime contract's
「native dispatch tool」节. This file's rules (shape anchors, glue-only, HANDLED set)
govern ONLY `block_adhoc_scripts.ts`.

**Two-generation tool-id convergence** (the same install file may be loaded by a 2.0.x or a
2.1.x host; dropping either generation silently un-guards that host — upgrade-drift AND
revert-drift are both CI-guarded, see `TestShimV2ModuleShape`):

| Guard face | 1.x tool id | 2.x tool id | args → tool_input |
|---|---|---|---|
| `Bash` | `bash` | `shell` | `{ command }` (2.x adds `workdir`/`timeout`/`background` — ignored by the shim, the command string is the judged surface) |
| `ApplyPatch` | `apply_patch` | `patch` | identical `patchText` field + `*** Add/Update/Delete File:` / `*** Move to:` marker syntax (same upstream parser serves both) |
| `Read`/`Write`/`Edit` | `read`/`write`/`edit` | unchanged | `filePath ?? file_path ?? path` fallback chain — load-bearing in 2.x, whose Input schemas are schema-validated `path` |
| `Glob` | `glob` | unchanged | `{ pattern, path }` |
| `Grep` | `grep` | unchanged | `{ pattern, path, include→glob }` |


## opencode permission gate (`permission.evaluate`, unattended ask/question closure)

The same plugin (same file, same `setup`, second awaited registration) rewrites permission
assertions in a run domain so an unattended run NEVER waits on an interactive approval:
opencode 2.x asks have **no timeout** — a pending with no answerer (unattended TUI, pure
service-form session) hangs the tool fiber forever (real-machine reproduced; `Permission.assert`
has no deadline and nothing auto-replies). The gate runs at `permission.evaluate`, which the
host triggers AFTER rule evaluation but BEFORE any pending/question is created
(`packages/core/src/permission.ts::evaluateInput`); the callback mutates `event.effect` /
`event.message` in place and the host consumes the rewritten event. Facts pinned against the
opencode source (packages/plugin/src/effect/permission.ts `PermissionEvaluation`, the
promise-mode adapter wiring `ctx.permission.hook`, and the trigger loop in
packages/core/src/plugin/hooks.ts — same event object passed through callbacks in place).

**Activation — six run roots, direct children only (narrower than the tool guard's anchor
chain, deliberately)**: the gate reads `<projectRoot>/<run-root>/.active` for
`.mgh-init` / `security-scan` / `.mgh-sra` / `.mgh-srr` / `.mgh-ut-init` / `.mgh-sdr` (project
root = the `ctx.location.directory` captured in `setup`). NO upward walk: a sentinel in an
ancestor directory marks a DIFFERENT project's run, and rewriting that project's asks from
this project's plugin would be out of scope (the mgh run roots are pinned to the project root
by contract, so the narrow check loses nothing). Out-of-domain (no sentinel under any of the
six roots) → the event passes through **untouched**: day-to-day non-mgh ask/question behavior
is exactly what it would be without the plugin. Env activation (`MGH_*_ACTIVE`) is NOT
consulted here — the 2.x plugin process inherits the resident service's env, which mid-session
exports never reach; the disk sentinel is the only reliable signal (same conclusion as the
tool guard's opencode activation).

**Rewrite rules (in-domain only; this is the ONE declared in-process exception to "decisions
live in the Python guard" — fixed two-and-a-half rules, no regex, no path-policy reasoning;
shape-pinned by CI in `tests/test_opencode_hook_parity.py::TestPermissionGateShape`)**:

| # | Condition (in-domain) | Rewrite | Rationale |
|---|---|---|---|
| 1 | `effect === "ask"` | `deny` + substitute-path hint | an ask with no answerer is the hang face; deny + hint lets the model finish the turn |
| 1a | …except `action === "external_directory"` and **every** resource falls inside the sentinel's `read_roots[]` | `allow` | those roots are the user's pre-approved read-only external dirs (armed at run start); keeping the ask would preserve the hang face, denying would regress the external-repo workflow |
| 2 | `action === "question"` and `effect !== "deny"` | `deny` + batch-clarify/resume hint | `question` (ask-the-user-anything) defaults to allow on the default agent; the tool family's unattended discipline is batch clarification + checkpoint resume, never a live answer |
| 3 | anything else (`allow` effects; `deny`) | untouched | `deny` never reaches the hook (rule-level deny short-circuits before it); `allow` has nothing to close |

Partial membership (some resources inside `read_roots[]`, some outside) = rule 1 (deny) —
never a partial allow, which would have no user-consent basis. Path membership is glue:
resources arrive forward-slash absolute with a glob tail (`C:/ext/dir/*` — opencode's
file-access slash()es paths), sentinel roots are host-native (`C:\ext\dir`); both sides are
normalized (backslash→slash, trailing slash trimmed, case-folded) and prefix-matched — pure
functions, round-trip-sample pinned.

**Failure posture — fail-closed toward asks, fail-open toward the host**: a present but
unparsable sentinel still marks the domain ACTIVE with zero read_roots (asks deny; a corrupt
sentinel never deactivates a domain another sentinel marks); read_roots entries are
type-checked (non-string grants nothing); ANY error inside the callback is caught, logged
best-effort (`console.warn`), and downgraded to an out-of-domain pass — a gate bug must never
defect the host's permission evaluation (a callback rejection is a host-side defect in the
promise adapter, a bigger blast radius than the hang face the gate removes). The gate is
stateless (fresh stat + small JSON parse per evaluation — trivially cheap next to the
per-call Python spawn).

**Fallback layer (rule-level, plugin-independent)**: every opencode mgh agent definition pins
`question: deny`, and every agent needing external-directory isolation (the fanout twins +
their non-fanout siblings) pins `external_directory: deny`. Rule-level deny short-circuits
BEFORE the hook, so the two layers never conflict: with the plugin absent the rule pins still
terminate the ask/question faces for mgh agents; with the plugin present the gate additionally
covers non-mgh agent shapes (user sessions, default agent) inside the run domain. CI asserts
the pins (`TestAgentQuestionDenyPinned` — deleting any pin is red).

**Residual hang faces this gate does NOT cover (disclosed, watchdog change TBD)**: ① Form /
MCP elicitation (a separate elicitation mechanism that does not route through
`permission.evaluate`); ② provider-executed tools (server-side tools that bypass the local
permission layer); ③ custom tools that make no permission assertion; ④ opencode hosts that
fail to LOAD the plugin (load failure is fail-soft — a WARN — so the gate is silently absent;
covered by install self-check + the two-version real-machine gate, not by runtime symptoms).

**Gate version matrix**: implemented against **2.1.0** (local, real-machine gated: in-domain
ask/question pending count stays 0, read_roots resources pass, out-of-domain asks unchanged);
**2.0.32** (enterprise) gated on the intranet with the same sample set — the open questions
recorded there are (a) whether `question`'s default effect on the default agent matches 2.1.0
(allow) and (b) whether the `external_directory` resource glob tail (`/*`) has the same shape
on both versions; the implementation defends on both (non-deny question rewrite is harmless if
the default is already deny; glob-tail-stripped prefix matching tolerates either resource
shape).

### Lifecycle

- **step 0 (deterministic for init/ut-init)**: after `export MGH_<DOM>_ACTIVE=1`,
  `write_runconfig.py` co-writes the sentinel as a side-effect of its atomic
  `run_config.json` write — `target` = the already-computed Windows-native `target_abs`,
  `out_roots[]` derived from non-default `--out`/`--rules-dir` (default product roots are
  built into the guard allowlist and never listed). The orchestrator NEVER needs a
  `printf` recipe; the script running IS the sentinel existing. Other domains (sra/srr/
  sast) write it from the orchestrator step 0: `target` from the first Python leaf-script
  stdout that yields the abs project root (sra: `prepare_augment`; srr: `ingest_requirements`;
  sast: activation-only — `target` empty, out-of-tree uses `MGH_TARGET` env on claude /
  degrades on opencode, sast output already narrowed to `security-scan/`).
- **existence check (`resume_state.py --check`, init/ut-init)**: a run in progress
  (`run_config.json` present ∧ step ≠ `done`) with the sentinel missing = the guard is
  DORMANT → fail-loud (exit 2) with a re-arm recipe; a `done` run without the sentinel is
  NOT a violation (the guard should be dormant then).
- **resume re-arm (`resume_state.py --rearm-sentinel`, init/ut-init)**: deterministically
  rewrites the sentinel from the persisted `run_config.target` (+ `rules_dir`-derived
  out_roots) — the `--resume` / post-compaction first step; atomic + idempotent. Single
  source convention: fresh run → `write_runconfig` side-effect; resume → `resume_state`
  re-arm; both derive from `run_config`, never from an orchestrator `printf`.
- **completion / clean-stop (orchestrator, Bash)**: `rm <sentinel>` so a stale sentinel does
  not arm the guard during subsequent day-to-day dev. A residual (crash without cleanup) arms
  the guard's FULL face for its domain — NOT scripts-only: for init/ut-init every write
  outside the sanctioned subtrees is blocked (ANY extension — `.json`/`.md` included) plus
  out-of-tree reads blocked, i.e. a full write lock on day-to-day dev (an init completion-state
  residual is detected as a violation by `resume_state --check`); for sast/sra/srr/sdr script
  writes + out-of-tree writes + out-of-tree reads are blocked (in-tree non-script writes pass).
  Disposition: `rm` the residual promptly, or let a `--resume` re-arm overwrite it — never
  leave it armed during ordinary development.
- **sdr sentinel lifecycle (fully scripted — no `printf` recipe exists in any sdr shell)**:
  pre-arm → co-write → second-gate refresh → re-arm → existence check → completion removal.
  ① **pre-arm** (shell step 0, BEFORE step 1 wakes the guard — closes the "step-1 args are
  wrong → sentinel never written → guard dormant for the whole run" window):
  `resume_sdr_state.py --run-dir <abs> --repo <abs> --arm-sentinel` (same-target re-run =
  no-op; an already-refined `read_roots[]` is never emptied). ② **co-write**: `sdr_context.py`
  — the one step both entries (launcher and host shell) pass through — refines the SAME
  sentinel (`target` = its stdout `repo`; `read_roots[]` = the roots it ACTUALLY searched ∪
  operator `--read-root`) and atomically writes the sibling `<run-dir>/run_config.json`
  codegraph signal; both fail-loud (exit 2), never silent. ③ **launcher second-gate
  refresh**: `mgh_sdr_launch.py` re-judges every root against the project config
  immediately before spawning the host CLI (idempotent same-source refresh — a
  version-skewed sibling cannot leak an unapproved root into `read_roots[]`). ④ **re-arm**:
  `resume_sdr_state.py --rearm-sentinel` deterministically rewrites the sentinel from the
  persisted run state (post-compaction / new-session resume). ⑤ **existence check**:
  `resume_sdr_state.py --check` — a run in progress (step ∈ group|fanout|render) with the
  sentinel missing = guard DORMANT → fail-loud (exit 2) + re-arm recipe. ⑥ **completion /
  clean stop**: the host-shell step 5 `rm`s the sentinel AND the launcher removes it after
  the host CLI exits; a crash residual is a detectable state (⑤ catches it; the next
  launcher start reuses + refreshes a same-target residual) — never a silent lock of
  day-to-day dev.

## MGH_TARGET resolution (subtree check)

Precedence: **env `MGH_TARGET` > `sentinel.target` > degrade**. When both are absent the
subtree check degrades to pass (the anchor is the implicit run-root context — sentinel
discovery is anchor-relative — but is **not** used as a hard block target, to avoid
over-blocking when no target was pinned).

## Runtime write discipline (active guard)

1. **Bash inline interpreter code** → exit 2 + introspection recipe. Two shapes under one rule:
   `py -c`/`python -c` **introspection** of artifacts (`import json` / `open(` / `load(` /
   `.json`; benign-bodied `py -c` is not this rule's target), and **heredoc / here-string** fed
   to the interpreter via a standalone `-` (`py - <<EOF`, `py - <<< '…'`,
   `python3 x.py … | python3 - <<'EOF'`) which blocks by SHAPE alone — no body-token requirement
   (heredoc bodies are often invisible or truncated in the command string). Command bodies are
   split on `;`/`&&`/`||`/`|` and judged per segment. A standalone `-` WITHOUT `<<`/`<<<` is
   NOT in this rule face (minimal interception surface; new observed shapes net in later).
2. **Script-write block** — `Write`/`Edit` of any extension in
   `_SCRIPT_EXTS = {.py, .ps1, .sh, .bash, .zsh, .bat, .cmd, .ts, .js, .mjs, .cjs}` → exit 2.
   **No path whitelist** (the prior `core/scripts` + `tests`/`tools`/`hooks` exemptions only
   mattered while inactive, at which point `main()` already returned 0). Leaf scripts are
   read-only at runtime. `.json`/`.md` are not in the set (legit artifacts).
3. **Write confinement** — `Write`/`Edit` resolved target:
   - **all five domains**: block if OUTSIDE the resolved `MGH_TARGET` tree (drive root, `%TEMP%`,
     another project dir).
   - **`mgh-init` AND `mgh-ut-init` additionally** (positive allowlist): block unless inside a
     sanctioned subtree (see the two tables below). `out_roots[]` extends the allowlist.
     sast/sra/srr retain the out-of-tree check **without** the allowlist.
4. **Bash whole-read** of a multi-unit aggregate (cat/head/tail/type/Get-Content of
   `clusters.json` / `controls_candidates.json` / `scout_plan.json` / `controls_inventory.json`
   / `s3_chunks.json` / `s5_filtered.json` / `scope_manifest.json` / `change_context.json`)
   → exit 2 (request-context-budget defense-in-depth; structural fix = `list_* --materialize`).
5. **Write/delete-side out-of-tree interception (Bash + tool face)** — the read-side's symmetric
   closure for the mutation surface. `MGH_TARGET` precedence + `is_relative_to(target)` semantics
   identical to (3) and the read side; target absent ⇒ degrade to pass. Regex-over-observed-shape
   (does NOT claim exhaustive coverage of pipes/aliases/env-injected paths, PowerShell `.NET`
   static methods, `robocopy`/`fsutil` — same stance as temp-I/O / file-assoc / read-side Bash
   file-search).

   | Surface | Verb / shape | Destination judged | Blocked when |
   |---|---|---|---|
   | Bash write verb | `New-Item`/`ni`, `Set-Content`/`sc`, `Add-Content`/`ac`, `Out-File`, `tee`, `mkdir`/`md`, `Copy-Item`/`cpi`/`cp`/`copy`/`xcopy`, `Move-Item`/`mi`/`mv`, `rename`/`Rename-Item` (leading token of the command or a sub-command after `;`/`\|`/`&&`/`\|\|`) | any out-of-tree absolute-path token; Copy/Move/xcopy = LAST token (destination) | destination resolves outside `MGH_TARGET` tree, OR no explicit path + cwd outside the target tree |
   | Bash delete verb | `Remove-Item`/`ri`, `del`, `erase`, `rm`, `rmdir`/`rd` (leading token) | any out-of-tree absolute-path token | outside `MGH_TARGET` tree, OR no path + cwd outside the target tree → **delete-side recipe** (irreversible; NEVER sibling modules) |
   | Bash redirect | `>` / `>>` to any target (generalizes the temp-only redirect) | the redirect target | resolves outside `MGH_TARGET` tree (temp targets still caught by the retained temp-I/O rule) |
   | In-tree Bash write (P1) | write verb / redirect destination INSIDE `MGH_TARGET` | the destination | `mgh-init`/`mgh-ut-init`: outside a sanctioned subtree (root pollution `Set-Content <target>\evil.txt`) — mirrors the Write/Edit tool-layer allowlist. sast/sra/srr: pass (no allowlist) |
   | Rule-a relabel (L1) | `py -c` WRITE/DELETE shape (`write(`/`makedirs`/`shutil.copy`/`shutil.move`/`shutil.rmtree`/`os.replace`/`os.rename`/`os.remove`/`os.unlink`/`write_text`/`write_bytes`) | any out-of-tree absolute path | outside `MGH_TARGET` tree → write/delete recipe (NOT introspection); pure in-tree `py -c` writes governed by the tool layer |
   | Tool face | claude `MultiEdit`/`NotebookEdit` (`file_path` / `notebook_path`) enter the write-confinement branch like `Write`/`Edit` | the path | outside tree / blocked script-ext / (init/ut-init) non-sanctioned subtree. `.ipynb` is NOT a script-ext (artifact) |
   | Tool face | opencode `apply_patch` (1.x) / `patch` (2.x) — same `patchText` marker syntax (`*** (Add\|Update\|Delete) File:` / `*** Move to:` markers extracted into `paths[]` by the `.ts` shim; delete op → delete wording) | each path | ANY path outside tree / blocked script-ext / non-sanctioned subtree |

   A hit → exit 2 + stderr **write-side recipe** (points at producer stdout `checkpoint_path` /
   `rule_path` / `draft_path` absolute paths; NEVER Bash `Set-Content`/`New-Item`/`tee`/`>` /
   `apply_patch`/`MultiEdit`/`NotebookEdit` outside the tree). A delete hit additionally calls
   out irreversibility ("NEVER `Remove-Item`/`del`/`rm`/`rmtree` outside the target tree,
   including sibling modules"). Unrecognized write-shaped verbs (`robocopy`/`fsutil`/`.NET`
   static methods/…) are no longer a silent pass: the rule-m catch-all net beneath blocks any
   out-of-tree token they carry — with the READ-net recipe (allowed roots + config remedy),
   not the write recipe, since the verb was never recognized as a write verb.

### `mgh-init` sanctioned subtrees (positive allowlist)

| Subtree | Purpose |
|---|---|
| `<target>/.mgh-init/**` | artifacts / checkpoints / inputs / manifest / report / sentinel |
| `<target>/.claude/rules/**` | claude rules output |
| `<target>/docs/security-controls/**` | opencode per-category detail files |
| `<target>/AGENTS.md` | opencode lazy index |
| `out_roots[]` (sentinel) | customized `--out` / `--rules-dir` abs roots |

### `mgh-ut-init` sanctioned subtrees (positive allowlist)

Same shape as init (ut-init writes rules into the project root too): `mgh-ut-init` is the
fifth run-domain and the second rules-writing command.

| Subtree | Purpose |
|---|---|
| `<target>/.mgh-ut-init/**` | artifacts / checkpoints / inputs / run_config / sentinel |
| `<target>/.claude/rules/**` | claude test-convention rules output (`test-*.md`) |
| `<target>/docs/test-conventions/**` | opencode per-category detail files |
| `<target>/AGENTS.md` | opencode lazy index |
| `out_roots[]` (sentinel) | customized `--out` / `--rules-dir` abs roots |

A hit → exit 2 + stderr recipe pointing at `list_*` / `describe_artifact` / producer stdout
`checkpoint_path` / `rule_path` / `draft_path`.

## Runtime read discipline (active guard)

The read side is the **peer** of the write discipline — same `MGH_TARGET` precedence
(env > sentinel.`target` > degrade), same `Path.resolve().is_relative_to(target)` semantics,
NOT a positive-allowlist check within the tree (any file inside the target tree is readable;
the goal is "stay in the working project", not "stay in a sanctioned subtree"). The allow-set
is the **unified read allow-set** = resolved `MGH_TARGET` tree ∪ sentinel `read_roots[]` ∪
project config `read_roots[]` — the SAME set on the tool face and the Bash face. It
replaces the soft failure (a cross-module read reaching the host **permission prompt and
interrupting the run**) with a fail-loud recipe. `MGH_TARGET` absent => the read checks
degrade to pass (NEVER a hard read block when no target was pinned; the script-ext write
block / `py -c` / temp-I/O / file-assoc blocks still fire).

| Layer | Tool / shape | Anchor | Blocked when |
|---|---|---|---|
| Tool abstraction | `Read` | `file_path` | resolved `file_path` outside the target tree **and** outside every declared `read_roots[]` root (sentinel ∪ config; a root must exist + be a dir at judgment time, else grants zero) |
| Tool abstraction | `Read` (leaf-source rule) | `file_path` | script extension ∧ `mgh-core/scripts` path segment (installed leaf script source — the read-side peer of "leaf scripts read-only"; target-project `.py` and non-script artifacts pass; fires even in the degrade-no-target case). NEVER relaxed by `read_roots[]` |
| Tool abstraction | `Glob` / `Grep` | `path` (default = cwd) | resolved `path` outside the target tree **and** outside every declared `read_roots[]` root; `path` absent + cwd outside both (cwd-drift leak) |
| Tool abstraction | — | `pattern` / `glob` | **NOT parsed** (the `path` anchor is authoritative; conservative vs false positives) |
| Bash escape | `Bash: rg`/`ripgrep`/`grep`/`egrep`/`fgrep`/`findstr`/`find`/`fd`/`ag`/`ack` (leading token of the command or a sub-command after `;`/`\|`/`&&`/`\|\|`) | any explicit absolute-path argument OR cwd | any absolute-path arg resolves outside the unified allow-set, OR no abs path + cwd outside both |
| Bash escape | `Bash: ls`/`dir`/`Get-ChildItem`/`gci` (leading token) | any path argument (cwd-relative `..` folded) OR cwd | any argument resolves outside the unified allow-set, OR no path + cwd outside both |
| Bash catch-all (rule m) | **ANY `Bash` command** — every path-like token (drive-letter `C:\…`/`C:/…`, UNC `\\…`, POSIX `/…`, `..`-leading [resolved vs guard cwd], `~/`-leading; bare `~`/`..` NOT tokens; `://` URL tokens excluded) | token resolution | ANY token resolves outside the unified allow-set → exit 2 + recipe naming the three allow-root classes (target tree / sentinel `read_roots[]` / config `read_roots[]`) + the config remedy. **Verb-independent, runs LAST (after all enumeration rules)** — mutation-shaped hits surface their write/delete recipe first; the enumeration tables REMAIN IN FORCE as refinements (write/delete recipes, cwd-drift, P1 root pollution). No path token => pass; unpinned target => degrade |
| Path resolution | `..` chain (e.g. `<target>\aa\bb\cc\..\..\..\..\xxxx` folding to a drive root) | the resolved path | `Path.resolve()` folds `..` segments; a chain that climbs out of the tree resolves outside and is blocked (the reported D-root permission-prompt interrupt shape) |
| Path resolution | hallucinated out-of-tree prefix (an underscore dir name regenerated as a separator pair, e.g. `acme_wing` → `acme\wing`) | the resolved path | resolves outside the tree and is blocked by the same out-of-tree judgment — no directory-name semantics are attempted |

**Residual boundaries (rule m, disclosed — same style as the honest-boundary docs)**: ① an
UNKNOWN write verb writing INTO a declared read-only root passes the net (token inside the
read allow-set; the mutation rules do not recognize the verb) — governed by the sdr
approval-flow change once declared roots are user-approved; ② alias/variable indirection
(`$p='D:\out'; cp x $p`) extracts no bare path token → leaks (same no-shell-parser stance as
every other Bash rule); ③ the interpreter-exec rule (executed script location) keeps judging
`MGH_TARGET` alone — declared roots are read-only, running code from them is not a read.

### heredoc / here-string 数据体剥离（fix-mgh-guard-heredoc-body）

四类**结构判定**——写动词 / 删除动词 / `>`/`>>` 重定向 / rule-m 路径净网——在判定前先做
**数据体剥离**（守卫 `_strip_data_bodies`）：bash heredoc（`<<` / `<<-`，定界符含
引号形态）与 PowerShell here-string（`@"…"@` / `@'…'@`）的**数据体**（定界符行之后到
终结定界符行，含终结行）替换为单个空格——数据体是被写入文件的数据，不是命令结构。
观测来源（评审登记册 #22，scout-338 会话取证）：数据体里的 `yyyy/MM/dd` 被净网/
mutation 扫描器误判为越树路径片段、`>2000` 被误判为重定向，合法 checkpoint 写入连拦
两次，模型第三次**改掉记录内容**才放行——守卫误伤直接篡改产物。

| 边界 | 语义 |
|---|---|
| 保留面 | 操作符 token、操作符行上的其余命令（`cat > f <<'EOF'; echo done` 的 `; echo done` 照判）、重定向目标（`cat > <路径> <<` 的路径）、其余全部命令 token 逐字保留 |
| 消费面 | 恰上述四类结构判定；其余规则（激活/解码、内联解释器、`py -c` 内省、temp-I/O、聚合整读、file-assoc、search/listing、executed-script）一律判**原文** |
| 解释器喂养不豁免 | 接收命令是解释器（py/python 族含点版本、node/deno、powershell/pwsh、Invoke-Expression/iex；bash/sh 等代码解释器同拒剥离）时该段 **不剥离**；内联解释器拦截在**原文**上先行，覆盖无 `-` 形态（`python <<'EOF'` / `node <<EOF`）与 here-string 喂养（`Invoke-Expression @"…"@`）——剥离 NEVER 弱化既有拦截 |
| 畸形保守 | 未终结 heredoc（到文本结束无终结行）/ here-string 未配对 / 起始 `@"` 非行末 / `<<` 出现在引号内 → 该段**不剥离**、按原文判定（可能维持误拦，NEVER 漏拦） |
| `<<-` 制表 | 终结定界符行行首制表符按 shell 语义折叠后匹配 |
| 非目标残余 | `<<<`（bash here-string，单串喂 stdin）不剥离，属已声明残余；非 heredoc 位置的日期/数字形态 token（如引号参数里的 `yyyy/MM/dd`）仍按普通 token 判定——本语义修结构、不建词表白名单 |

A hit → exit 2 + stderr **read-side recipe** (points at "read only this batch's `input_path`/
`targets[]`; anchor `Glob`/`Grep` (and `rg`/`grep`/… in Bash) at the repo root; NEVER read
the parent dir / sibling modules"; when roots are declared the recipe adds "declared roots
(sentinel ∪ config) are not a wildcard"). The rule-m recipe instead names the three
allow-root classes + the `<target>/.mgh/read-roots.json` remedy. Regex-over-observed-shape:
pipes/aliases/env-injected paths in the Bash file-search form are NOT guaranteed (same
stance as the temp-I/O and file-association rules). Under the pre-rule-m search/listing
rules a `--flag <path>` value on a non-search verb did NOT trip — the rule-m net NOW judges
every token including flag values (an accepted new block: `--flag=<out-of-tree>` values,
`git -C <out>`, harmless out-of-tree mentions).

### Read-side path materialization (scout / T1 fan-out)

`list_scout_batches.py` / `list_clusters.py` materialize each fan-out unit's file paths
(`targets[].file` / `evidence_files[]` / `usage_sites[]` / candidate `file`) **ABSOLUTE**
(resolved against the plan's `repo`), keeping the original as `repo_relative`. A subagent
thus resolves the same file under any cwd AND stays inside the target tree (so the read
check passes it) — closing the non-subjective out-of-tree read path (fan-out output paths
are already absolute for the write side; this extends that absolutization to the read side).

## Guard tool-surface wiring coverage (CI-enforced invariant)

The guard's decision-branch tool set (every tool name `main()` dispatches on: `Bash`,
`Write`, `Edit`, `MultiEdit`, `NotebookEdit`, `ApplyPatch`, `Read`, `Glob`, `Grep`,
`RunCode`, `TerminalIO`, `JobCtl`) SHALL be fully covered by **ALL THREE** host wiring
faces, enforced by regression tests:

| Face | What must cover every guard tool name | Where |
|---|---|---|
| claude install face | the default PreToolUse matcher `_DEFAULT_MATCHER` (`\|`-split) | `tools/install_hook.py` |
| opencode plugin face | the `.ts` shim `HANDLED` set + its lowercase `normalize` mapping — **both tool generations converge**: `bash`/`shell` → `Bash`, `apply_patch`/`patch` → `ApplyPatch` (2.x renamed ids must never drop the 1.x ids or vice versa) | `releases/opencode/plugins/block_adhoc_scripts.ts` |
| dsh shim face | the `.ts` shim static `TOOL_MAP` constant's value range | `releases/dsh/plugins/mgh-guard.ts` |

`RunCode`/`TerminalIO`/`JobCtl` are dsh-only ids that claude/opencode NEVER emit; they are
listed on the claude matcher and the opencode `HANDLED` set anyway (same convention as
`multiedit` on opencode) so the coverage invariant is machine-checkable on all three
faces. Adding a guard decision branch WITHOUT extending all three wiring faces SHALL fail
the regression tests (`tests/test_opencode_hook_parity.py::TestWiringCoverage` checks
matcher ∧ HANDLED ∧ TOOL_MAP; `tests/test_dsh_hook_parity.py` checks the three-face
same-fixture parity). The claude matcher previously covered only
`Bash|Write|Edit`, leaving the read-side / tool-face branches unconsulted (an out-of-tree
`Read` reached the host permission prompt and interrupted the run instead of failing loud
with a recipe); nothing prevented the same drift on opencode. Reinstall evolves a legacy
matcher (`Bash|Write|Edit` ⊂ default) in place; a user-customized non-subset matcher is left
untouched (stderr note).

## Cross-references

- Guard source (single decision source): `core/scripts/block_adhoc_scripts.py` (canonical;
  claude/opencode `hooks/` twins + the dsh sibling copy are byte-identical — parity test
  `tests/test_dsh_hook_parity.py`, plus the opencode twin parity in
  `tests/test_opencode_hook_parity.py`).
- Guard unit tests: `tests/test_block_adhoc_scripts.py` (incl. upward-walk sentinel discovery
  + the dsh bypass-tool branches).
- Wiring coverage tests: `tests/test_opencode_hook_parity.py::TestWiringCoverage` (three
  faces), `tests/test_dsh_hook_parity.py` (three-face same-fixture + shim glue-only scan).
- Install / opt-out (`--no-enforce-hook`): `install.sh` + `core/contracts/.../spec.md` per command.
