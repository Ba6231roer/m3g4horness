## MODIFIED Requirements

### Requirement: Run-domain activation via env or disk sentinel

The `block_adhoc_scripts` guard SHALL activate inside an mgh run-domain when **EITHER** (a) env
`MGH_{INIT,SAST,SRA,SRR,UT_INIT}_ACTIVE=1` is set, **OR** (b) a disk sentinel `<run-root>/.active` exists relative to
the guard's cwd, where `<run-root>` is the domain's run directory: `mgh-init`→`.mgh-init/`, `mgh-sast`→
`security-scan/`, `mgh-sra`→`.mgh-sra/`, `mgh-srr`→`.mgh-srr/`, `mgh-ut-init`→`.mgh-ut-init/`. The sentinel SHALL be JSON
`{"domain":"mgh-<d>","target":"<abs target>","out_roots":["<abs>..."],"v":1}`, written by a deterministic script —
for `/mgh-init`, `write_runconfig.py` SHALL co-write the sentinel as a **side-effect** of its atomic
`run_config.json` write (reusing the already-computed Windows-native `target_abs` and deriving `out_roots[]` from
`--out`/`--rules-dir`), NOT by an orchestrator `Bash printf` — and removed at run completion / clean-stop. For
`/mgh-init`, `resume_state.py --check` SHALL validate that the sentinel exists whenever `run_config.json` exists and
the pipeline is not `done`: a missing sentinel in an in-progress run means the guard is dormant (scripts read-only /
subtree confinement silently disabled on opencode, which does not inherit mid-session env), so `--check` SHALL
fail-loud (exit 2) with a re-arm recipe. A `--resume` re-dispatch SHALL re-arm the sentinel deterministically from
the persisted `run_config.target`. `MGH_TARGET` for the subtree check SHALL resolve
with precedence **env `MGH_TARGET` > sentinel.`target` > degrade** — when neither pins a target the subtree
(out-of-tree) check SHALL pass (cwd is the implicit run root for cwd-relative sentinel discovery but is **not**
used as a hard block target, to avoid over-blocking when no target was pinned); the script-extension write block
and `py -c` introspection block still fire whenever the guard is active. Outside all run-domains (neither env nor
sentinel present) the guard SHALL exit 0 silently (zero day-to-day noise). The disk-sentinel activation path
exists because the opencode `.ts` plugin process does not inherit mid-session bash-exported env; env-only
activation left the opencode guard dormant for an entire run (the prior fail-soft reliability boundary is now
closed by the sentinel, host-neutral and parity-preserving on both claude and opencode).

#### Scenario: opencode activates via sentinel when env is unset
- **WHEN** opencode 触发 `tool.execute.before`,且 `MGH_INIT_ACTIVE` env 未设、但 `<cwd>/.mgh-init/.active` 哨兵存在
- **THEN** 守卫激活(等效于 env 已设),`py -c` 内省/越权脚本写/越树写均按运行域规则 fail-loud;哨兵经磁盘对 opencode 插件进程可见,绕开 mid-session env 不继承

#### Scenario: claude activates via env (sentinel optional)
- **WHEN** claude `PreToolUse` 触发,且 `MGH_INIT_ACTIVE=1`(哨兵在或不在)
- **THEN** 守卫激活;env 仍是 claude 端的有效激活源,哨兵为兜底

#### Scenario: Non-run-domain session is silent
- **WHEN** 既无任何 `MGH_*_ACTIVE` env、各域 `<run-root>/.active` 哨兵亦不存在
- **THEN** 守卫退出码 0 放行,零日常噪声

#### Scenario: Sentinel carries target so the subtree check fires without env
- **WHEN** opencode 下 `MGH_TARGET` env 未设,但哨兵 `.active` 携 `target=<abs>`,编排器 `Write` 一个落在该 target 子树外的路径(如 `D:/raw.json`)
- **THEN** 守卫以退出码 2 拦截越树写;`MGH_TARGET` 取自哨兵,子树判定在 opencode 上可靠

#### Scenario: Active domain with no pinned target degrades the subtree check
- **WHEN** 守卫激活(env `MGH_*_ACTIVE=1` 或哨兵在),但 `MGH_TARGET` env 未设且哨兵无 `target`
- **THEN** 脚本扩展名写 / `py -c` 内省仍 fail-loud(退出码 2);越树写子树检查**降级放行**(NEVER 用 cwd 硬拦,避 over-block)

#### Scenario: write_runconfig writes the sentinel as a deterministic side-effect
- **WHEN** 编排器 step 0 执行 `py …/write_runconfig.py --target <abs target> [--out <custom>] [--rules-dir <custom>]`
- **THEN** 除原子写 `<init-dir>/run_config.json` 外,脚本**确定性**写 `<init-dir>/.active` 哨兵(`domain:"mgh-init"`、
  `target`= 其 stdout 的 `target`(Windows 原生绝对)、`out_roots[]` = `--out`/`--rules-dir` 解析后绝对根(默认产物根不列)、`v:1`);
  哨兵不依赖编排器读懂并执行 `printf` 配方——脚本一跑哨兵必在

#### Scenario: resume_state --check fails when the sentinel is missing mid-run
- **WHEN** `run_config.json` 存在、`resume_state.py` 判定 step ≠ `done`(流水线进行中),但 `<init-dir>/.active` 哨兵缺失
- **THEN** `resume_state.py --check` 退出码 2 + recipe(守卫休眠 → 先 re-arm 哨兵,NEVER 静默继续);`done` 步(已收尾)则哨兵缺失非违例

#### Scenario: resume re-arms the sentinel deterministically from run_config.target
- **WHEN** 编排器 `--resume`(哨兵已在上一 run 完成时移除/或残留待覆盖),`resume_state.py` 提供确定性 re-arm(据磁盘 `run_config.target` 重写 `<init-dir>/.active`)
- **THEN** 哨兵经确定性脚本重写(非编排器 `printf`),守卫在 fan-out 前即可靠激活

#### Scenario: Orchestrator writes sentinel at step 0 and removes on completion
- **WHEN** 审阅 `mgh-*.md` 编排流起步与完成态
- **THEN** step 0 经确定性脚本(`write_runconfig` 副作用)写 `<target>/.mgh-<domain>/.active`(非编排器 `printf`);run 完成 / 干净停止含移除该哨兵的步(移除可为编排器 `rm`,低风险——残留哨兵只挡脚本写)

#### Scenario: mgh-ut-init activates via env or sentinel as the fifth domain
- **WHEN** `MGH_UT_INIT_ACTIVE=1` env 已设,**或** `<cwd>/.mgh-ut-init/.active` 哨兵存在
- **THEN** 守卫在 `mgh-ut-init` 运行域激活(第 5 域,与既有 4 域同机制:`py -c` 内省/脚本扩展名写/越权子树写均 fail-loud);哨兵 `domain:"mgh-ut-init"`、run-root `.mgh-ut-init`

## ADDED Requirements

### Requirement: Leaf script source read blocked (read-side peer of scripts read-only)

When active in an mgh run-domain, the guard SHALL block a `Read` whose resolved `file_path` is a script-extension
file (extension in `{.py, .ps1, .sh, .bash, .zsh, .bat, .cmd, .ts, .js, .mjs, .cjs}`) located under the installed
`<mgh-core>/scripts/` mirror of the target project (both `.claude/mgh-core/scripts/` and `.opencode/mgh-core/scripts/`
install layouts) — fail-loud (exit 2) + a recipe pointing at "report errors from stderr, NEVER Read leaf script
source". This is the read-side peer of the existing "leaf scripts read-only" write rule: leaf scripts are already
write-blocked at runtime; this closes the remaining context-bloat path where the orchestrator or a subagent pulls a
leaf `.py` (200–900 lines ≈ 3–10K tokens) into its context to "debug" a `--check` failure, which accelerates
compaction and risks the agent reasoning about internals. The block SHALL NOT apply to the target project's own
`.py` source (only the installed mgh-core leaf scripts, identified by the `mgh-core/scripts` path segment); it SHALL
NOT apply to `Read` of non-script artifacts (`.json`/`.md`). When the guard is inactive (no env, no sentinel), the
read SHALL pass (install/CI/dev unaffected).

#### Scenario: Reading a leaf .py during a run is blocked
- **WHEN** an `mgh-init` run-domain is active (env `MGH_INIT_ACTIVE=1` OR `<cwd>/.mgh-init/.active` sentinel present),
  and the model issues `Read` `file_path=D:\parent\sonA\.claude\mgh-core\scripts\list_clusters.py`
- **THEN** the guard resolves the path under `mgh-core/scripts/` with a script extension and blocks with exit 2 + a
  recipe ("report errors from stderr, NEVER Read leaf script source") — the leaf source does not enter context

#### Scenario: Reading the target project's own .py passes
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and a reader issues `Read`
  `file_path=D:\parent\sonA\src\auth\PermGuard.java` or `D:\parent\sonA\src\auth\PermGuard.py` (the target's own source)
- **THEN** the guard passes (exit 0) — the block targets only installed mgh-core leaf scripts, not the working project's source

#### Scenario: Reading a script-extension file outside mgh-core passes
- **WHEN** an `mgh-init` run-domain is active, and the model issues `Read` of a `.py` that is NOT under a
  `mgh-core/scripts` path segment (e.g. a vendored `D:\parent\sonA\tools\helper.py`)
- **THEN** the guard passes (exit 0) — the path-segment condition (`mgh-core/scripts`) is the discriminator, not the extension alone

#### Scenario: Inactive session passes leaf-script reads
- **WHEN** neither any `MGH_*_ACTIVE` env nor any `<run-root>/.active` sentinel is present (a day-to-day non-run-domain
  session) and the model issues `Read` of `mgh-core/scripts/list_clusters.py`
- **THEN** the guard exits 0 silently (zero day-to-day noise; install/CI/dev unaffected)
