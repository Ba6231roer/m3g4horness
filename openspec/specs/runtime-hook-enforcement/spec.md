# runtime-hook-enforcement Specification

## Purpose

跨五命令(`/mgh-init`|`/mgh-sast`|`/mgh-sra`|`/mgh-srr`|`/mgh-ut-init`)共享的运行时纪律守卫契约——激活模型
(env 或磁盘哨兵)、运行域脚本只读、脚本扩展名集、写入受信子树限定。取代此前分散在各命令 spec、
措辞漂移的重复 hook 要求,作为 `block_adhoc_scripts` 守卫(双端 byte-identical)的单一真相源。本能力由
change `harden-mgh-opencode-hook-enforcement` 建立、`add-mgh-ut-init` 扩到第 5 域 `mgh-ut-init`、
`harden-mgh-init-deterministic-enforcement` 把 init 域哨兵写入改为 `write_runconfig` 确定性副作用
(+ `resume_state --check` 存在性校验 + re-arm)并增读侧叶源码拦截。
## Requirements
### Requirement: Run-domain activation via env or disk sentinel

The `block_adhoc_scripts` guard SHALL activate inside an mgh run-domain when **EITHER** (a) env
`MGH_{INIT,SAST,SRA,SRR,UT_INIT}_ACTIVE=1` is set, **OR** (b) a disk sentinel `.active` exists at
`<dir>/<run-root>/.active` for **any dir on the anchor-to-drive-root chain** — where the anchor is
the **best available cwd signal**: the `cwd` field of the hook's stdin payload when present
(claude PreToolUse carries the session/tool cwd), falling back to the guard process's own cwd.
Sentinel discovery SHALL walk upward from the anchor (anchor itself first, then each ancestor,
stopping at the filesystem root or after a bounded depth of 16 levels, whichever first), checking
`<dir>/<run-root>/.active` at each level. `<run-root>` is the domain's run directory:
`mgh-init`→`.mgh-init/`, `mgh-sast`→`security-scan/`, `mgh-sra`→`.mgh-sra/`, `mgh-srr`→`.mgh-srr/`,
`mgh-ut-init`→`.mgh-ut-init/`. The sentinel SHALL be JSON
`{"domain":"mgh-<d>","target":"<abs target>","out_roots":["<abs>..."],"v":1}` — for `/mgh-init`
written by a **deterministic script side-effect** (`write_runconfig.py` co-writes it atomically with
`run_config.json`, reusing the Windows-native `target_abs` and deriving `out_roots[]` from non-default
`--out`/`--rules-dir`), NOT by an orchestrator `Bash printf`; `resume_state.py --check` SHALL validate
its existence whenever `run_config.json` exists and the pipeline is not `done` (missing sentinel
mid-run = guard dormant = exit 2 + re-arm recipe; `done` without it is not a violation), and
`--rearm-sentinel` SHALL rewrite it deterministically from the persisted `run_config.target`.
Other domains write it from the orchestrator at step 0 via `Bash`; every domain removes it at run
completion / clean-stop. `MGH_TARGET` for the
subtree check SHALL resolve with precedence **env `MGH_TARGET` > sentinel.`target` > degrade** —
when neither pins a target the subtree (out-of-tree) check SHALL pass; the script-extension write
block and `py -c` introspection block still fire whenever the guard is active. Outside all
run-domains (neither env nor sentinel present on the whole walked chain) the guard SHALL exit 0
silently (zero day-to-day noise). The upward walk closes the anchor-mismatch gap: a reader
subagent (or a host whose plugin/server process started outside the target) whose anchor cwd is a
**subdirectory of the target** still discovers the sentinel, so the guard stays armed for the whole
fan-out instead of silently degrading to pass. A residual boundary is EXPLICIT and documented: when
the anchor cwd is entirely OUTSIDE the target tree (e.g. an opencode server started in a different
directory, whose plugin process cwd never enters the target chain), the sentinel is NOT discovered
and the guard stays dormant — the run requirement "start the host in the target root (or any
subdirectory of it)" SHALL be stated in the contract doc; the guard NEVER scans the drive to
compensate.

#### Scenario: sentinel discovered from a target-subdirectory anchor (claude hook cwd)
- **WHEN** claude PreToolUse payload 携 `cwd=D:\parent1\parent2\curr_proj\aa\bb\cc`(target 子目录),env 未设,哨兵在
  `D:\parent1\parent2\curr_proj\.mgh-init\.active`
- **THEN** 向上 walk 在第 3 级找到哨兵,守卫以 `mgh-init` 域激活;该 subagent 的越树 Read / 越树写 /
  `py -c` 内省均 fail-loud(此前 cwd-only 发现在该锚下找不到哨兵 → 守卫休眠 → 全部放行)

#### Scenario: opencode plugin anchor outside the target is a documented residual boundary
- **WHEN** opencode 从 target 根以外的目录启动,插件进程 cwd(锚)不在 target 子树链上,env 未继承
- **THEN** 向上 walk 不命中,守卫休眠——这是**显式记录的残余边界**(契约注明「在 target 根或其子目录
  启动 opencode」运行要求),非缺陷;守卫 NEVER 整盘扫描补偿

#### Scenario: upward walk is bounded and stops at the drive root
- **WHEN** 锚距盘根 ≤ 16 级且链上无任何哨兵,或锚距盘根 > 16 级
- **THEN** walk 在盘根(或 16 级上限)终止,守卫退出码 0 放行(非运行域零噪声;有界 walk 不做整盘扫描)

#### Scenario: env activation unchanged and takes precedence for activation
- **WHEN** `MGH_INIT_ACTIVE=1` env 已设(哨兵在或不在、锚任意)
- **THEN** 守卫激活(env 仍是有效激活源;向上 walk 只是发现面的扩展,不改变 env-first 激活语义)

#### Scenario: opencode activates via sentinel when env is unset
- **WHEN** opencode 触发 `tool.execute.before`,且 `MGH_INIT_ACTIVE` env 未设、但锚起向上 walk 链上某级
  `<dir>/.mgh-init/.active` 哨兵存在
- **THEN** 守卫激活(等效于 env 已设),`py -c` 内省/越权脚本写/越树写均按运行域规则 fail-loud;哨兵经
  磁盘对 opencode 插件进程可见,绕开 mid-session env 不继承

#### Scenario: claude activates via env (sentinel optional)
- **WHEN** claude `PreToolUse` 触发,且 `MGH_INIT_ACTIVE=1`(哨兵在或不在)
- **THEN** 守卫激活;env 仍是 claude 端的有效激活源,哨兵为兜底

#### Scenario: Non-run-domain session is silent
- **WHEN** 既无任何 `MGH_*_ACTIVE` env、锚起向上 walk 全链(有界)亦无哨兵
- **THEN** 守卫退出码 0 放行,零日常噪声

#### Scenario: Sentinel carries target so the subtree check fires without env
- **WHEN** opencode 下 `MGH_TARGET` env 未设,但哨兵 `.active` 携 `target=<abs>`,编排器 `Write` 一个落在该 target 子树外的路径(如 `D:/raw.json`)
- **THEN** 守卫以退出码 2 拦截越树写;`MGH_TARGET` 取自哨兵,子树判定在 opencode 上可靠

#### Scenario: Active domain with no pinned target degrades the subtree check
- **WHEN** 守卫激活(env `MGH_*_ACTIVE=1` 或哨兵在),但 `MGH_TARGET` env 未设且哨兵无 `target`
- **THEN** 脚本扩展名写 / `py -c` 内省仍 fail-loud(退出码 2);越树写子树检查**降级放行**(NEVER 用 cwd 硬拦,避 over-block)

#### Scenario: Orchestrator writes sentinel at step 0 and removes on completion
- **WHEN** 审阅 `mgh-*.md` 编排流起步与完成态
- **THEN** step 0 经确定性脚本(`write_runconfig` 副作用,init/ut-init)写 `<target>/.mgh-<domain>/.active`(非编排器 `printf`);run 完成 / 干净停止含移除该哨兵的步

#### Scenario: write_runconfig writes the sentinel as a deterministic side-effect
- **WHEN** 编排器 step 0 执行 `py …/write_runconfig.py --target <abs target> [--out <custom>] [--rules-dir <custom>]`
- **THEN** 除原子写 `<init-dir>/run_config.json` 外,脚本**确定性**写 `<init-dir>/.active` 哨兵(`domain` 按 run-root、`target`= 其 stdout 的 `target`(Windows 原生绝对)、`out_roots[]` = 非默认 `--out`/`--rules-dir` 解析后绝对根(默认产物根不列)、`v:1`);哨兵不依赖编排器读懂并执行 `printf` 配方——脚本一跑哨兵必在

#### Scenario: resume_state --check fails when the sentinel is missing mid-run
- **WHEN** `run_config.json` 存在、`resume_state.py` 判定 step ≠ `done`(流水线进行中),但 `<init-dir>/.active` 哨兵缺失
- **THEN** `resume_state.py --check` 退出码 2 + recipe(守卫休眠 → 先 re-arm 哨兵,NEVER 静默继续);`done` 步(已收尾)则哨兵缺失非违例

#### Scenario: resume re-arms the sentinel deterministically from run_config.target
- **WHEN** 编排器 `--resume`(哨兵已在上一 run 完成时移除/或残留待覆盖),`resume_state.py --rearm-sentinel` 提供确定性 re-arm(据磁盘 `run_config.target` 重写 `<init-dir>/.active`)
- **THEN** 哨兵经确定性脚本重写(非编排器 `printf`),守卫在 fan-out 前即可靠激活

#### Scenario: mgh-ut-init activates via env or sentinel as the fifth domain
- **WHEN** `MGH_UT_INIT_ACTIVE=1` env 已设,**或**锚起向上 walk 链上某级 `<dir>/.mgh-ut-init/.active` 哨兵存在
- **THEN** 守卫在 `mgh-ut-init` 运行域激活(第 5 域,与既有 4 域同机制);哨兵 `domain:"mgh-ut-init"`、run-root `.mgh-ut-init`

### Requirement: Runtime script writes blocked (leaf scripts read-only)

When active, the guard SHALL block `Write`/`Edit` of any file whose extension is in the script set
`{.py, .ps1, .sh, .bash, .zsh, .bat, .cmd, .ts, .js, .mjs, .cjs}`, with **no** path-based whitelist exemption.
The prior `core/scripts`/`mgh-core/scripts` and `tests`/`tools`/`hooks` exemptions are **removed** — they were
only reachable while the guard was inactive (install/dev time), at which point `main()` already returns 0 before
any whitelist check; at runtime there is no legitimate script write (all sanctioned producers emit JSON/`.md`
artifacts: checkpoints, inputs, rules, manifest, report). Leaf scripts under `mgh-core/scripts/` (and
`core/scripts/`) are **read-only** for the orchestrator at runtime. A hit SHALL fail-loud (exit 2) + stderr
recipe. When inactive, script writes SHALL pass (install/CI/dev unaffected).

#### Scenario: Writing a leaf .py during a run is blocked
- **WHEN** `mgh-init` 运行域内编排器 `Write`/`Edit` `.claude/mgh-core/scripts/list_clusters.py`
- **THEN** 守卫以退出码 2 拦截(此前因 `core/scripts` 白名单放行——即「agent 改叶脚本」失守形状);recipe 指向 sanctioned 出口

#### Scenario: Writing a .ps1 ad-hoc script during a run is blocked
- **WHEN** `mgh-init` 运行域内编排器 `Write` `<target>/process_induct.ps1`
- **THEN** 守卫以退出码 2 拦截(`.ps1` 在脚本扩展名集内,不再只拦 `.py`)

#### Scenario: Non-script artifact writes are not blocked by this rule
- **WHEN** `mgh-init` 运行域内写 `.mgh-init/checkpoints/scout/scout-001.json` 或 `.claude/rules/security-x.md`
- **THEN** 该规则不拦(`.json`/`.md` 不在脚本集);其**位置**由 write-confinement 规则管

#### Scenario: Inactive session passes script writes (install/dev)
- **WHEN** 既无 env 也无哨兵的非运行域会话,`Write` `tests/test_x.py` 或 `mgh-core/scripts/new_leaf.py`
- **THEN** 守卫退出码 0 放行(install/CI/本仓开发态不受影响)

### Requirement: Write confinement to sanctioned locations

When active, the guard SHALL block any `Write`/`Edit` whose resolved target falls **outside** the resolved
`MGH_TARGET` tree (e.g. a drive root, `%LocalAppData%\Temp`, another project dir) — for all five run-domains.
For the `mgh-init` and `mgh-ut-init` domains, the guard SHALL **additionally** require the target to fall **inside**
a sanctioned subtree (positive allowlist): for `mgh-init` — `<target>/.mgh-init/**`,
`<target>/.claude/rules/**`, `<target>/docs/security-controls/**`, `<target>/AGENTS.md`; for `mgh-ut-init` —
`<target>/.mgh-ut-init/**`, `<target>/.claude/rules/**`, `<target>/docs/test-conventions/**`, `<target>/AGENTS.md`;
plus any absolute root the orchestrator recorded in the sentinel's `out_roots[]` (for customized `--out`/`--rules-dir`).
A write inside `MGH_TARGET` but outside the sanctioned subtrees (e.g. project-root `temp_clusters*.json`) SHALL
fail-loud (exit 2) + recipe pointing at the producer stdout `checkpoint_path`/`rule_path`. `mgh-sast`/`mgh-sra`/
`mgh-srr` retain the out-of-tree check **without** the positive allowlist (no root-pollution reported for those
domains; their output paths are already narrowed to `security-scan/`, `.mgh-sra/`, `.mgh-srr/`).

#### Scenario: Out-of-tree write is blocked in every domain
- **WHEN** 任一运行域内编排器 `Write`/`Edit` `D:/raw.json` 或 `%LocalAppData%\Temp\x.json`
- **THEN** 守卫以退出码 2 拦截,recipe 指向 producer stdout 的绝对产物路径字段

#### Scenario: init root-level pollution is blocked
- **WHEN** `mgh-init` 运行域内编排器 `Write` `<target>/temp_clusters1.json`(在 `MGH_TARGET` 内、但不在受信子树)
- **THEN** 守卫以退出码 2 拦截(既有 `_is_out_of_tree` 只挡树外、放行了树内根污染——即 temp_clusters 失守形状)

#### Scenario: init sanctioned-subtree writes pass
- **WHEN** `mgh-init` 运行域内写 `<target>/.mgh-init/inputs/t1/u.input.json`、`<target>/.claude/rules/x.md`、`<target>/docs/security-controls/auth.md`、或 `<target>/AGENTS.md`
- **THEN** 守卫放行(落入受信子树)

#### Scenario: init custom output root recorded in sentinel passes
- **WHEN** 编排器以 `--out <custom>` 启动、把解析后的绝对根写入哨兵 `out_roots[]`,运行域内 `Write` `<custom>/x.json`
- **THEN** 守卫放行(`out_roots[]` 承载自定义产物根,防 over-block)

#### Scenario: mgh-ut-init sanctioned-subtree writes pass
- **WHEN** `mgh-ut-init` 运行域内写 `<target>/.mgh-ut-init/inputs/t1/u.input.json`、`<target>/.claude/rules/test-junit5.md`、`<target>/docs/test-conventions/mockito.md`、或 `<target>/AGENTS.md`
- **THEN** 守卫放行(落入 ut-init 受信子树;ut-init 与 init 同形写 rules,共用 `.claude/rules` + `AGENTS.md`)

#### Scenario: mgh-ut-init root-level pollution is blocked
- **WHEN** `mgh-ut-init` 运行域内编排器 `Write` `<target>/temp_clusters1.json`(在 `MGH_TARGET` 内、但不在 ut-init 受信子树)
- **THEN** 守卫以退出码 2 拦截(ut-init 与 init 同形状根污染风险,同正向允许清单治理)

### Requirement: Bash command temp-directory I/O detection (defense-in-depth)

When active, the guard SHALL scan the `command` string of each `Bash` tool invocation for patterns
indicating write-redirection to a known temporary directory followed by a read-back of the same file
within the **same** invocation. A match SHALL fail-loud (exit 2) with a stderr recipe pointing to the
orchestrator-discipline fragment's "stdout 直消费" instruction.

Detection scope:
- **Known temp directory patterns**: `$env:TEMP` / `$env:TMP` / `%TEMP%` / `%TMP%` / `/tmp` / `$TMPDIR`
  (case-insensitive for env-var names on Windows)
- **Write pattern**: one of these temp patterns followed by a write redirection (`>` or `>>`) to a file
- **Read-back pattern**: the same file path read via `Get-Content` / `cat` / `type` / `gc` within the
  same `command` string

This is a **defense-in-depth** rule; the primary fix is in the orchestrator-discipline prompt.
The regex detection covers observed failure shapes and SHALL NOT claim exhaustive coverage of all
possible temp-directory I/O patterns.

#### Scenario: PowerShell temp-file write-and-read is blocked

- **WHEN** `mgh-init` 运行域内编排器执行 `Bash` 命令 `py .../list_scout_batches.py ... > $env:TEMP/scout_page0.json; Get-Content $env:TEMP/scout_page0.json -Raw | ConvertFrom-Json ...`
- **THEN** 守卫检测到 `$env:TEMP` + `>` 写重定向 + `Get-Content` 回读同文件 → 退出码 2 + stderr recipe 指向 orchestrator-discipline "stdout 直消费,NEVER temp 中介"

#### Scenario: POSIX temp-file write-and-read is blocked

- **WHEN** `mgh-init` 运行域内编排器执行 `Bash` 命令 `py .../list_scout_batches.py ... > /tmp/scout_page0.json; cat /tmp/scout_page0.json | jq ...`
- **THEN** 守卫检测到 `/tmp` + `>` 写重定向 + `cat` 回读 → 退出码 2

#### Scenario: Legitimate in-tree redirect is NOT blocked

- **WHEN** `mgh-init` 运行域内编排器执行 `py .../discover_controls.py ... > <target>/.mgh-init/discover_stdout.log`(重定向到受信子树)
- **THEN** 守卫不拦(temp 检测未命中;路径不在已知临时目录模式内)

#### Scenario: Temp write without read-back is NOT blocked (conservative)

- **WHEN** `mgh-init` 运行域内编排器执行 `py .../some_script.py > /tmp/debug.log`(写入 temp 但无回读)
- **THEN** 守卫不拦(仅限「同调用内写 + 回读」配对模式;单独写 temp 无回读不计为违例,交由上级纪律治理)

#### Scenario: Inactive session passes all Bash commands

- **WHEN** 既无 env 也无哨兵的非运行域会话
- **THEN** 守卫退出码 0 放行,不做 Bash 命令扫描(零日常噪声)

### Requirement: Bash file-association script execution is blocked

When active, the guard SHALL block any `Bash` command that **executes a script-extension file** (any extension
in the script set `{.py, .ps1, .sh, .bash, .zsh, .bat, .cmd, .ts, .js, .mjs, .cjs}`) **via the shell's file
association** — i.e. the script path appears as the **command body** (either as the operand of a shell
call-operator such as PowerShell `&`, or as the first command token of the command, optionally quote-wrapped)
**without an explicit interpreter-launcher prefix**. A hit SHALL fail-loud (exit 2) + stderr recipe pointing at
the explicit-launcher form.

Commands SHALL PASS when the script path is reached via an explicit interpreter launcher token — `py`, `python`,
`python3`, `bash`, `sh`, `pwsh -File`, `pwsh -Command`, `powershell -File`, `cmd /c` — preceding the script path
(the canonical `py <abs script>` recipe passes). A script path that appears only as a `--flag <path>`
**argument** to a legitimately-launched command (not as the command body) SHALL NOT be blocked.

This is a **defense-in-depth** rule, a peer of "Bash command temp-directory I/O detection". The primary fix is
the stage-prompt recipe; the regex covers the observed failure shape and SHALL NOT claim exhaustive coverage of
all possible file-association invocation forms. Its host-neutral placement (the guard normalizes the command
string identically for claude and opencode) closes the Windows failure shape where opencode runs every `Bash`
command under PowerShell (`tool/shell.ts`: win32 → `powershell -Command …`) and a degraded
`& "<abs>.py"` resolves the `.py` file association (e.g. Notepad) — opening a GUI editor / "create file?" dialog
that blocks the shell tool, hangs the subagent ack, and deadlocks the parent `task.wait`.

#### Scenario: PowerShell call-operator on a .py is blocked

- **WHEN** `mgh-init` 运行域内(激活)编排器或 subagent 执行 `Bash` 命令
  `& "D:\proj\.opencode\mgh-core\scripts\chunk_sources.py" --out "D:\proj\.mgh-init\slices\scout\scout-003" "d:\proj\…\X.java"`
- **THEN** 守卫以退出码 2 拦截;recipe 指向显式 launcher 形态 `py "<abs script>"`(call-operator `&` 作用在 `.py` 上 =
  文件关联,在 win32 PowerShell 下解析为 Notepad/编辑器 → 弹窗死锁)

#### Scenario: Bare quoted script path as command body is blocked

- **WHEN** `mgh-init` 运行域内执行 `Bash` 命令 `"D:\proj\.opencode\mgh-core\scripts\chunk_sources.py" --in x`
  (无 launcher 前缀,引号包裹的 `.py` 路径作为命令体)
- **THEN** 守卫以退出码 2 拦截;recipe 指向 `py "<abs script>"`

#### Scenario: Canonical py-launcher form passes

- **WHEN** `mgh-init` 运行域内执行 `Bash` 命令
  `py "D:\proj\.opencode\mgh-core\scripts\chunk_sources.py" --in x --out y.json`
- **THEN** 守卫放行(显式 `py` launcher → Python 解释器,无文件关联)

#### Scenario: Other explicit launchers pass

- **WHEN** `mgh-init` 运行域内执行 `python "<abs>.py" …` 或 `bash "<abs>.sh" …` 或 `pwsh -File "<abs>.ps1"`
- **THEN** 守卫放行(显式解释器前缀)

#### Scenario: Script path as a flag argument is NOT blocked

- **WHEN** `mgh-init` 运行域内执行 `Bash` 命令 `py "<abs>discover.py" --in "<other>.py"`(`.py` 路径仅作 `--in` 参数)
- **THEN** 守卫放行(`.py` 不在命令体位置;operand-vs-arg 区分避免误伤)

#### Scenario: Inactive session passes all Bash commands

- **WHEN** 既无 env 也无哨兵的非运行域会话执行 `& "…\.py" …`
- **THEN** 守卫退出码 0 放行,不做 Bash 命令扫描(零日常噪声;install/CI/开发态不受影响)

### Requirement: opencode shim feeds the guard payload via a Bun-compatible stdin

The opencode `.ts` shim SHALL feed the guard subprocess its JSON payload via a Bun-compatible
`stdin` form — `new Blob([<stringified payload>])` (or the `"pipe"` + `proc.stdin.write/end`
form). The shim MUST NOT pass a bare string to `Bun.spawn`'s `stdin`: opencode's bundled Bun
rejects a string stdin (`TypeError: stdio must be 'inherit'|'pipe'|'ignore'|Bun.file|number|null`),
which throws inside the shim's guard-invocation path; the shim's fail-soft handling then returns a
pass and the guard silently never blocks (the D7 incident — a `py -c` introspection one-liner ran
unblocked and zeroed 25 T1 checkpoints). The Python guard (single decision source) is unchanged.

#### Scenario: a py -c introspection one-liner is blocked in opencode
- **WHEN** an opencode session is inside an mgh run-domain (env `MGH_*_ACTIVE=1` at opencode launch
  OR the `<cwd>/<run-root>/.active` sentinel present) and the model issues a Bash `py -c` command
  carrying introspection tokens (`import json` / `open(` / `load(` / `.json`)
- **THEN** the shim feeds the normalized payload to the guard as `new Blob([stdin])`, the guard
  exits 2, the shim throws and the tool call is blocked (the model sees the sanctioned-primitive
  recipe) — the guard is NOT silently disabled by a stdin-delivery throw

#### Scenario: the shim source form is regression-guarded in CI
- **WHEN** the shim source is checked in CI (no Bun runtime available)
- **THEN** a parity-test source-form assertion requires `new Blob([stdin])` to be present, preventing
  a silent revert to a bare string stdin (the runtime delivery itself is verified manually in opencode)

### Requirement: Read-side confinement to the MGH_TARGET tree

When active, the guard SHALL block any `Read`/`Glob`/`Grep` tool call whose resolved target path (or,
for `Glob`/`Grep`, the resolved `path` anchor — defaulting to the guard's cwd when `path` is absent)
falls **outside** the resolved `MGH_TARGET` tree, for all five run-domains (`mgh-init`/`mgh-sast`/
`mgh-sra`/`mgh-srr`/`mgh-ut-init`). Path resolution SHALL fold `..` segments (the resolved path is
what gets judged — a `..\..\…` chain that climbs out to a drive root resolves outside the tree and
is blocked), and SHALL resolve against the filesystem identically to how the write side resolves.
A hit SHALL fail-loud (exit 2) + stderr recipe pointing the model at reading only its batch's
`input_path`/`targets[]` and anchoring `Glob`/`Grep` at the repo root — the read does NOT reach the
host permission prompt. `MGH_TARGET` resolves with the SAME precedence as the write side — **env
`MGH_TARGET` > sentinel.`target` > degrade (pass)** — so when neither pins a target the read-side
check SHALL pass (never use cwd as a hard block target, to avoid over-blocking; the
script-extension write block and `py -c` introspection block still fire). The read-side check SHALL
be a peer of the write-side out-of-tree check (same resolve + `is_relative_to(target)` semantics),
NOT a positive-allowlist check — any file inside the `MGH_TARGET` tree is readable. The `Glob`/
`Grep` `pattern` field SHALL NOT be parsed for path traversal (the `path` anchor is the
authoritative scope). This judgment holds **identically on both hosts** once the guard is both
**consulted** (wiring coverage, install/plugin face) and **active** (sentinel discovery,
activation face) in the calling context; it catches every shape that resolves outside the tree
(drive-root overshoot via `..` chains, parent/sibling dirs, hallucinated out-of-tree prefixes
like an underscore directory name regenerated as a separator pair). It cannot catch a hallucinated
segment that still resolves INSIDE the tree (that is a provenance-layer concern, governed by the
reader anchoring requirement).

#### Scenario: Read of a `..`-chain drive-root overshoot is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent1\parent2\curr_proj`, and a
  scout subagent issues `Read` `file_path=D:\parent1\parent2\curr_proj\aa\bb\cc\..\..\..\..\..\..\xxxx`
  (the `..` chain resolves to `D:\xxxx`, outside the target tree)
- **THEN** the guard folds the `..` chain during resolution, finds the resolved path outside the
  target tree, and blocks with exit 2 + the read-side recipe — the read does NOT reach the host
  permission prompt for the D-drive root (the reported interrupt shape)

#### Scenario: Read of a hallucinated out-of-tree directory prefix is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\acme_wing\curr_proj`, and a
  subagent issues `Read` `file_path=D:\acme\wing\curr_proj\src\X.java` (hallucinated separator pair
  where the real directory is `acme_wing` — resolves outside the target tree)
- **THEN** the guard resolves the path outside the target tree and blocks with exit 2 + the
  read-side recipe (the hallucinated-prefix shape is caught by the same out-of-tree judgment;
  no directory-name semantics are attempted)

#### Scenario: Read of a parent-dir file is blocked (submodule layout)
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and a reader subagent
  issues `Read` `file_path=D:\parent\sonB\src\Main.java` (a sibling module under the parent dir)
- **THEN** the guard resolves it outside the tree and blocks with exit 2 + the read-side recipe

#### Scenario: Read of an in-tree file passes
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and a reader issues
  `Read` `file_path=D:\parent\sonA\src\auth\PermGuard.java`
- **THEN** the guard passes (exit 0); legitimate batch reads are unaffected

#### Scenario: Glob anchored outside the target tree is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and a reader issues
  `Glob` with `path=D:\parent\sonB` and `pattern=**/*.java`
- **THEN** the guard resolves the `path` anchor outside the target tree and blocks with exit 2 + the
  read-side recipe

#### Scenario: Glob/Grep with no path anchor and cwd outside target is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, the reader's cwd is
  `D:\parent`, and the reader issues `Grep` with no `path` and `pattern=TokenInterceptor`
- **THEN** the guard resolves the implicit cwd anchor outside the target tree and blocks with exit 2
  + the cwd-drift recipe

#### Scenario: Glob/Grep anchored at the repo root passes
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and a reader issues
  `Grep` with `path=D:\parent\sonA` and `pattern=TokenInterceptor`
- **THEN** the guard passes (exit 0)

#### Scenario: read-side confinement fires in a subagent whose anchor is a target subdirectory
- **WHEN** a scout subagent's anchor cwd is `D:\parent1\parent2\curr_proj\aa\bb\cc` (inside the
  target tree), the sentinel is at `D:\parent1\parent2\curr_proj\.mgh-init\.active`, and the
  subagent issues an out-of-tree `Read`
- **THEN** the guard activates via upward-walk sentinel discovery and blocks with exit 2 + recipe
  (activation and read-side judgment both hold in the subagent context — the gap where the whole
  read side silently degraded because the cwd-only lookup missed the sentinel is closed)

#### Scenario: Read-side confinement fires identically under sentinel activation on opencode
- **WHEN** an opencode session has NO `MGH_*_ACTIVE` env but the sentinel is present (discovered via
  the upward walk from the plugin process anchor) carrying `target=D:\parent\sonA`, and a reader
  issues `Read` `file_path=D:\parent\sonB\x.java`
- **THEN** the guard activates via the sentinel, resolves `MGH_TARGET` from `sentinel.target`, and
  blocks the cross-module read with exit 2 + recipe

#### Scenario: Active domain with no pinned target degrades the read-side check
- **WHEN** the guard is active but `MGH_TARGET` env is unset AND the sentinel carries no `target`,
  and a reader issues `Read` of any path
- **THEN** the script-extension write block / `py -c` introspection block / temp-I/O /
  file-association blocks still fire (exit 2); the read-side out-of-tree check **degrades to pass**

#### Scenario: Inactive session passes all reads
- **WHEN** neither any `MGH_*_ACTIVE` env nor any sentinel is present on the whole walked chain and
  the model issues any `Read`/`Glob`/`Grep`
- **THEN** the guard exits 0 silently (zero day-to-day noise; install/CI/dev unaffected)

### Requirement: Leaf script source read blocked (read-side peer of scripts read-only)

When active in an mgh run-domain, the guard SHALL block a `Read` whose resolved `file_path` is a
script-extension file (extension in `{.py, .ps1, .sh, .bash, .zsh, .bat, .cmd, .ts, .js, .mjs, .cjs}`)
located under the installed `<mgh-core>/scripts/` mirror of the target project (both
`.claude/mgh-core/scripts/` and `.opencode/mgh-core/scripts/` install layouts) — fail-loud (exit 2)
+ a recipe pointing at "report errors from stderr, NEVER Read leaf script source". This is the
read-side peer of the existing "leaf scripts read-only" write rule: leaf scripts are already
write-blocked at runtime; this closes the remaining context-bloat path where the orchestrator or a
subagent pulls a leaf `.py` (200–900 lines ≈ 3–10K tokens) into its context to "debug" a `--check`
failure, which accelerates compaction and risks the agent reasoning about internals. The block
SHALL NOT apply to the target project's own `.py` source (only the installed mgh-core leaf scripts,
identified by the `mgh-core/scripts` path segment); it SHALL NOT apply to `Read` of non-script
artifacts (`.json`/`.md`). When the guard is inactive (no env, no sentinel), the read SHALL pass
(install/CI/dev unaffected).

#### Scenario: Reading a leaf .py during a run is blocked
- **WHEN** an `mgh-init` run-domain is active (env `MGH_INIT_ACTIVE=1` OR `<cwd>/.mgh-init/.active`
  sentinel present), and the model issues `Read`
  `file_path=D:\parent\sonA\.claude\mgh-core\scripts\list_clusters.py`
- **THEN** the guard resolves the path under `mgh-core/scripts/` with a script extension and blocks
  with exit 2 + a recipe ("report errors from stderr, NEVER Read leaf script source") — the leaf
  source does not enter context

#### Scenario: Reading the target project's own .py passes
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and a reader issues
  `Read` `file_path=D:\parent\sonA\src\auth\PermGuard.java` or `D:\parent\sonA\src\auth\PermGuard.py`
- **THEN** the guard passes (exit 0) — the block targets only installed mgh-core leaf scripts, not
  the working project's source

#### Scenario: Reading a script-extension file outside mgh-core passes
- **WHEN** an `mgh-init` run-domain is active, and the model issues `Read` of a `.py` that is NOT
  under a `mgh-core/scripts` path segment (e.g. a vendored `D:\parent\sonA\tools\helper.py`)
- **THEN** the guard passes (exit 0) — the path-segment condition is the discriminator, not the
  extension alone

#### Scenario: Inactive session passes leaf-script reads
- **WHEN** neither any `MGH_*_ACTIVE` env nor any `<run-root>/.active` sentinel is present and the
  model issues `Read` of `mgh-core/scripts/list_clusters.py`
- **THEN** the guard exits 0 silently (zero day-to-day noise; install/CI/dev unaffected)

### Requirement: opencode shim normalizes read-side tools to the guard

The opencode `.ts` shim SHALL feed the guard for `read`/`glob`/`grep` tool events (in addition to
`bash`/`write`/`edit`), normalizing opencode's camelCase args to the Claude `{tool_name, tool_input}`
stdin shape the guard expects: `read` → `{tool_name:"Read", tool_input:{file_path}}`;
`glob` → `{tool_name:"Glob", tool_input:{pattern, path}}`; `grep` →
`{tool_name:"Grep", tool_input:{pattern, path, glob}}`. The shim SHALL remain glue-only — the
read-side out-of-tree decision logic lives ONLY in the Python guard (single decision source, zero
drift). The shim's `HANDLED` set SHALL include `read`/`glob`/`grep` alongside `bash`/`write`/`edit`.

#### Scenario: opencode read event is normalized and decided by the guard
- **WHEN** an opencode session is inside an `mgh-init` run-domain and the model issues a `read` tool
  call with `filePath=D:\parent\sonB\x.java` (outside `target=D:\parent\sonA`)
- **THEN** the shim normalizes it to `{tool_name:"Read", tool_input:{file_path:"D:\\parent\\sonB\\x.java"}}`,
  feeds it to the guard (single decision source) via `new Blob([stdin])`, the guard exits 2, and the
  shim throws to abort the tool call (the model sees the read-side recipe) — the read-side decision
  does not drift between platforms

#### Scenario: shim remains glue-only for the read side
- **WHEN** the shim source is checked in CI
- **THEN** a parity-test source-form assertion requires the shim to normalize `read`/`glob`/`grep`
  AND forbids it from reimplementing the read-side decision logic (e.g. `_read_out_of_tree` /
  `_out_of_tree_file_search` / `is_relative_to` / target resolution MUST NOT appear in the shim —
  single decision source)

### Requirement: Bash file-search command confinement to the MGH_TARGET tree

When active, the guard SHALL scan each `Bash` command for a leading file-search verb — `rg`/
`ripgrep`/`grep`/`egrep`/`fgrep`/`findstr`/`find`/`fd`/`ag`/`ack` (or the same verb as the first
token of a sub-command after `;`/`|`/`&&`/`||`) — and, on a hit, SHALL block when EITHER (a) any
explicit absolute-path token in the command (Windows drive-letter `[A-Za-z]:[\\/]…`, POSIX `/…`,
or UNC `\\…`) resolves outside the `MGH_TARGET` tree, OR (b) the command carries no explicit
absolute path (its search root defaults to cwd) AND the guard's cwd resolves outside the
`MGH_TARGET` tree. A hit SHALL fail-loud (exit 2) + the read-side recipe. This closes the escape
path where the model, instead of using the native `Grep`/`grep` tool (whose `path` anchor is already
confined by the read-side rule — and whose underlying ripgrep process's scope is therefore bounded),
invokes `rg`/`grep`/… directly in `Bash` (which routes through the `Bash` branch, not the read
branch, and the existing Bash rules do not target out-of-tree search paths). `MGH_TARGET` resolves
with the same precedence as the read/write sides (env > sentinel.`target` > degrade-pass). The
detection is regex-over-observed-shape and SHALL NOT claim exhaustive coverage of every file-search
invocation form (pipes, aliases, env-injected paths are not guaranteed) — consistent with the
temp-I/O and file-association rules.

#### Scenario: Bash rg search in a sibling module is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and a reader issues
  `Bash` `rg "TokenInterceptor" D:\parent\sonB\src` (the native Grep tool's `path` confinement is
  bypassed by invoking rg directly in Bash with an out-of-tree path)
- **THEN** the guard scans the absolute-path token `D:\parent\sonB\src`, resolves it outside the
  target tree, and blocks with exit 2 + the read-side recipe — the cross-module search does not
  reach the host permission prompt

#### Scenario: Bash rg with no path and cwd outside target is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, the reader's cwd is
  `D:\parent` (outside the target tree), and the reader issues `Bash` `rg "TokenInterceptor"` (rg
  recursively searches cwd by default, i.e. the whole parent tree)
- **THEN** the guard finds no explicit absolute path, resolves the implicit cwd anchor outside the
  target tree, and blocks with exit 2 + the read-side recipe

#### Scenario: Bash rg anchored inside the target tree passes
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and a reader issues
  `Bash` `rg "TokenInterceptor" D:\parent\sonA\src` (in-tree path)
- **THEN** the guard passes (exit 0); legitimate in-tree searches via Bash are unaffected

#### Scenario: Bash non-search command is not affected by the file-search rule
- **WHEN** an `mgh-init` run-domain is active and the reader issues `Bash` `py "…discover_controls.py"
  --in "D:\parent\sonA\src\X.java"` (no file-search verb; the `.java`/`.py` paths are arguments, not
  search roots)
- **THEN** the guard does not apply the file-search rule (other Bash rules — script-as-arg — still
  apply as before); a path that is only a `--flag` argument is not a file-search-verb hit

#### Scenario: Inactive session passes Bash rg
- **WHEN** neither any `MGH_*_ACTIVE` env nor any `<run-root>/.active` sentinel is present (a
  day-to-day non-run-domain session) and the model issues `Bash` `rg "x" D:\anywhere`
- **THEN** the guard exits 0 silently (zero day-to-day noise; install/CI/dev unaffected)

### Requirement: Bash write-verb confinement to the MGH_TARGET tree

When active, the guard SHALL scan each `Bash` command for a leading **write verb** — `New-Item`/`ni`,
`Set-Content`/`sc`, `Add-Content`/`ac`, `Out-File`, `tee`, `mkdir`/`md`, `Copy-Item`/`cpi`/`cp`/`copy`/`xcopy`,
`Move-Item`/`mi`/`mv`/`rename`/`Rename-Item` (or the same verb as the first token of a sub-command after
`;`/`|`/`&&`/`||`) — and, on a hit, SHALL block when EITHER (a) the write **destination** resolves outside the
`MGH_TARGET` tree (for single-path verbs any out-of-tree absolute-path token; for `Copy-Item`/`Move-Item`/`xcopy` the
LAST absolute-path token = the destination), OR (b) the command carries no explicit absolute path (destination
defaults to cwd) AND the guard's cwd resolves outside the `MGH_TARGET` tree. A hit SHALL fail-loud (exit 2) + the
write-side recipe. `MGH_TARGET` resolves with the same precedence as the read/write sides (env > sentinel.`target` >
degrade-pass). This closes the bypass where the model, instead of using the native `Write`/`Edit` tool (whose target
is already confined by the existing write-confinement rule), invokes a file-write verb directly in `Bash` (which routes
through the `Bash` branch, and the existing Bash rules — `py -c` introspection / temp-I/O / aggregate-read / file-assoc /
file-search — do not target out-of-tree write paths). The detection is regex-over-observed-shape and SHALL NOT claim
exhaustive coverage of every write form (pipes, aliases, env-injected paths, PowerShell `.NET` static methods like
`[System.IO.File]::WriteAllText`, `robocopy`/`fsutil` are not guaranteed) — consistent with the temp-I/O,
file-association, and read-side Bash file-search rules.

#### Scenario: Bash Set-Content to an out-of-tree path is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `Set-Content D:\out\f.json "x"` (the Write/Edit tool's confinement is bypassed by invoking a write verb directly
  in Bash with an out-of-tree path)
- **THEN** the guard scans the absolute-path token `D:\out\f.json`, resolves it outside the target tree, and blocks
  with exit 2 + the write-side recipe — the out-of-tree write does not silently execute

#### Scenario: Bash New-Item creating an out-of-tree file/dir is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `New-Item -ItemType File -Path D:\out\f.json -Force` (or `-ItemType Directory -Path D:\out\d`)
- **THEN** the guard resolves the `-Path` token outside the target tree and blocks with exit 2 + the write-side recipe

#### Scenario: Bash mkdir of an out-of-tree directory is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `mkdir D:\out\d`
- **THEN** the guard blocks with exit 2 + the write-side recipe

#### Scenario: Bash Copy-Item destination outside the target tree is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `Copy-Item x.java D:\out\` (the LAST absolute-path token = destination, outside the target tree)
- **THEN** the guard resolves the destination token outside the target tree and blocks with exit 2 + the write-side
  recipe; the in-tree source token does not exempt the out-of-tree destination

#### Scenario: Bash write verb with no path and cwd outside target is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, the model's cwd is `D:\parent`
  (outside the target tree), and the model issues `Bash` `Set-Content evil.txt "x"` (relative path resolves under
  cwd, i.e. the parent tree)
- **THEN** the guard finds no explicit absolute path, resolves the implicit cwd anchor outside the target tree, and
  blocks with exit 2 + the write-side recipe — the cwd-drift write leak is caught

#### Scenario: Bash write verb anchored inside the target tree passes
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `Set-Content D:\parent\sonA\.mgh-init\report\out.json "x"` (inside a sanctioned init subtree)
- **THEN** the guard passes (exit 0); legitimate in-tree writes via Bash (inside sanctioned subtrees for init/ut-init)
  are unaffected

#### Scenario: Bash non-write command is not affected by the write-verb rule
- **WHEN** an `mgh-init` run-domain is active and the model issues `Bash` `py "…list_clusters.py" --out
  "D:\parent\sonA\.mgh-init\clusters.json"` (no write verb; the `.json` path is a `--flag` argument to a
  producer, which writes inside the sanctioned subtree itself)
- **THEN** the guard does not apply the write-verb rule (other Bash rules — script-as-arg — still apply as before);
  a path that is only a `--flag` argument to a non-write-verb command is not a write-verb hit

#### Scenario: Active domain with no pinned target degrades the write-verb check
- **WHEN** the guard is active but `MGH_TARGET` env is unset AND the sentinel carries no `target`, and the model
  issues `Bash` `Set-Content D:\out\f.json "x"`
- **THEN** the script-extension write block / `py -c` introspection block / temp-I/O / file-association /
  aggregate-read blocks still fire (exit 2) where applicable; the write-verb out-of-tree check **degrades to pass**
  (NEVER use cwd as a hard block target when no target was pinned, consistent with the read/write sides' degrade rule)

#### Scenario: Inactive session passes Bash write verbs
- **WHEN** neither any `MGH_*_ACTIVE` env nor any `<run-root>/.active` sentinel is present and the model issues
  `Bash` `Set-Content D:\anywhere\f.json "x"`
- **THEN** the guard exits 0 silently (zero day-to-day noise; install/CI/dev unaffected)

### Requirement: Bash destructive-delete confinement to the MGH_TARGET tree

When active, the guard SHALL scan each `Bash` command for a leading **delete verb** — `Remove-Item`/`ri`, `del`,
`erase`, `rm`, `rmdir`/`rd` (or the same verb as the first token of a sub-command after `;`/`|`/`&&`/`||`) — and,
on a hit, SHALL block when EITHER (a) any explicit absolute-path token in the command resolves outside the
`MGH_TARGET` tree, OR (b) the command carries no explicit absolute path AND the guard's cwd resolves outside the
`MGH_TARGET` tree. A hit SHALL fail-loud (exit 2) + a **delete-side recipe** that calls out that deletion is
irreversible. Deletion is structurally worse than write (no artifact is produced; the action cannot be rolled back),
so the recipe SHALL explicitly forbid removing anything outside the target tree, including sibling modules. This
closes the bypass where the model invokes `Remove-Item`/`rm`/… directly in `Bash` (the existing Bash rules do not
target out-of-tree delete paths). `MGH_TARGET` resolves with the same precedence as the other sides
(env > sentinel.`target` > degrade-pass); the detection is regex-over-observed-shape (pipes/aliases/env-injected
paths, `shutil.rmtree` via `py -c`, `.NET` `::Delete` are covered by the `py -c` write-token relabel and the
absolute-path scan where a path literal is present, but not guaranteed for every form).

#### Scenario: Bash Remove-Item of a sibling module is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `Remove-Item D:\parent\sonB -Recurse -Force` (deletes a sibling module outside the target tree — irreversible)
- **THEN** the guard resolves `D:\parent\sonB` outside the target tree and blocks with exit 2 + the delete-side
  recipe ("deletion is irreversible; NEVER Remove-Item / del / rm outside the target tree, including sibling modules")

#### Scenario: Bash rm -rf of an out-of-tree path is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `rm -rf D:\out`
- **THEN** the guard resolves `D:\out` outside the target tree and blocks with exit 2 + the delete-side recipe

#### Scenario: Bash py -c shutil.rmtree of an out-of-tree path is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `py -c "import shutil; shutil.rmtree('D:/out')"` (interpreter-indirect delete; no introspection token, so the
  prior `py -c` rule did not catch it)
- **THEN** the guard's `py -c` write-token relabel recognizes the write/delete shape, scans the absolute-path literal
  `D:/out`, resolves it outside the target tree, and blocks with exit 2 + the delete-side recipe

#### Scenario: Inactive session passes Bash delete verbs
- **WHEN** neither any `MGH_*_ACTIVE` env nor any `<run-root>/.active` sentinel is present and the model issues
  `Bash` `Remove-Item D:\anywhere -Recurse -Force`
- **THEN** the guard exits 0 silently (zero day-to-day noise)

### Requirement: Bash redirect confinement to the MGH_TARGET tree

When active, the guard SHALL detect a `>`/`>>` redirect in a `Bash` command whose target resolves OUTSIDE the
`MGH_TARGET` tree (generalizing the prior temp-only redirect rule, which matched only known temp-dir prefixes) and
SHALL block it (exit 2) + the write-side recipe. For `mgh-init` AND `mgh-ut-init the redirect target SHALL
additionally land inside a sanctioned subtree (positive allowlist), mirroring the Write/Edit tool-layer rule — so a
redirect that pollutes the target root (`echo x > D:\parent\sonA\evil.txt`) fails loud too. The prior temp-dir
write + read-back defense (`_detect_temp_io`) is retained as an independent defense; this rule adds the out-of-tree /
non-sanctioned-subtree axis. `MGH_TARGET` resolves with the same precedence (env > sentinel.`target` > degrade-pass).

#### Scenario: Bash redirect to an out-of-tree non-temp path is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `echo x > D:\out\f.json` (a non-temp out-of-tree redirect the prior temp-only rule did not match)
- **THEN** the guard resolves the redirect target `D:\out\f.json` outside the target tree and blocks with exit 2 +
  the write-side recipe

#### Scenario: Bash append redirect to an out-of-tree path is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `echo x >> D:\out\f.json`
- **THEN** the guard blocks with exit 2 + the write-side recipe

#### Scenario: Bash redirect polluting the target root is blocked (init allowlist)
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `echo x > D:\parent\sonA\evil.txt` (in-tree but at the target root, outside the sanctioned init subtrees)
- **THEN** the guard applies the init positive allowlist to the redirect target, finds it outside the sanctioned
  subtrees, and blocks with exit 2 + the write-side recipe — Bash-side root pollution is caught like the Write-tool
  allowlist catches it

#### Scenario: Bash redirect to a sanctioned in-tree path passes
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `echo x > D:\parent\sonA\.mgh-init\report\out.json` (inside a sanctioned init subtree)
- **THEN** the guard passes (exit 0); legitimate in-tree redirects are unaffected

#### Scenario: Bash temp write + read-back still blocked by the retained temp-I/O rule
- **WHEN** an `mgh-init` run-domain is active and the model issues `Bash` `echo x > $env:TEMP\t.json; Get-Content
  $env:TEMP\t.json`
- **THEN** the retained `_detect_temp_io` defense still fires (exit 2 + the temp-I/O recipe), independent of the
  generalized redirect rule

### Requirement: In-tree Bash write confined to sanctioned subtrees for init and ut-init

When active in an `mgh-init` OR `mgh-ut-init` run-domain, the guard SHALL apply the existing positive-allowlist check
(the same `_ALLOWLIST_SUBTREES` used for the `Write`/`Edit` tool layer) to the destination of a Bash write verb
(`Set-Content`/`Add-Content`/`Out-Content`/`Out-File`/`New-Item`/`tee`/`>` redirect) even when that destination is
INSIDE the `MGH_TARGET` tree. This closes the bypass where a Bash write verb pollutes the target root
(`Set-Content D:\parent\sonA\evil.txt`) — the Write/Edit tool-layer allowlist governs only the tool abstraction, not
Bash. sast/sra/srr retain the out-of-tree check without the allowlist (mirroring their Write/Edit tool-layer stance).
The sanctioned subtrees for init are `<target>/.mgh-init`, `<target>/.claude/rules`, `<target>/docs/security-controls`,
plus `<target>/AGENTS.md` and sentinel `out_roots[]`; for ut-init `<target>/.mgh-ut-init`, `<target>/.claude/rules`,
`<target>/docs/test-conventions`, plus `<target>/AGENTS.md` and `out_roots[]`.

#### Scenario: Bash Set-Content polluting the init target root is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `Set-Content D:\parent\sonA\evil.txt "x"` (in-tree but at the target root, outside the sanctioned init subtrees)
- **THEN** the guard applies the init allowlist to the Bash write destination, finds it outside the sanctioned
  subtrees, and blocks with exit 2 + the write-side recipe — the Bash root-pollution bypass of the Write-tool
  allowlist is closed

#### Scenario: Bash Set-Content inside a sanctioned init subtree passes
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `Set-Content D:\parent\sonA\.mgh-init\report\out.json "x"`
- **THEN** the guard passes (exit 0)

#### Scenario: sast domain Bash write inside target tree passes (no allowlist)
- **WHEN** an `mgh-sast` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `Set-Content D:\parent\sonA\src\notes.txt "x"` (in-tree; sast has no positive allowlist, only the out-of-tree check)
- **THEN** the guard passes (exit 0); sast/sra/srr retain the out-of-tree check without the allowlist

### Requirement: claude MultiEdit and NotebookEdit confined like Write/Edit

The guard SHALL treat claude's `MultiEdit` and `NotebookEdit` tools identically to `Write`/`Edit` for confinement:
both SHALL enter the write-confinement branch. `MultiEdit` carries its target under `file_path`; `NotebookEdit`
carries its target under `notebook_path` — the path extraction SHALL read `tool_input.file_path` falling back to
`tool_input.notebook_path` then `tool_input.path`. The same script-extension block, out-of-tree check, and init/ut-init
positive allowlist SHALL apply. `.ipynb` SHALL NOT be added to the script-extension set (notebooks are artifacts, not
runtime scripts; `NotebookEdit` is confined only by tree location, not by extension). This closes the bypass where an
out-of-tree batch edit (`MultiEdit file_path=D:\out\f.json`) or out-of-tree notebook edit
(`NotebookEdit notebook_path=D:\out\nb.ipynb`) fell through to `return 0` because the write-confinement branch
matched only `Write`/`Edit`.

#### Scenario: claude MultiEdit outside the target tree is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `MultiEdit`
  `file_path=D:\out\f.json` `edits=[…]`
- **THEN** the guard resolves `D:\out\f.json` outside the target tree and blocks with exit 2 + the write-side recipe

#### Scenario: claude NotebookEdit outside the target tree is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `NotebookEdit`
  `notebook_path=D:\out\nb.ipynb`
- **THEN** the guard resolves `D:\out\nb.ipynb` outside the target tree (reading `notebook_path`) and blocks with
  exit 2 + the write-side recipe

#### Scenario: claude MultiEdit inside a sanctioned init subtree passes
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `MultiEdit`
  `file_path=D:\parent\sonA\.claude\rules\auth.md` (inside a sanctioned init subtree)
- **THEN** the guard passes (exit 0)

### Requirement: opencode apply_patch confined to the MGH_TARGET tree

The opencode `.ts` shim SHALL feed the guard for `apply_patch` tool events (opencode's multi-file mutating tool —
add/update/delete/move, whose file paths live inside a `patchText` blob as `*** Add File: <path>` /
`*** Update File: <path>` / `*** Delete File: <path>` / `*** Move to: <path>` marker lines). The shim SHALL normalize
`apply_patch` by extracting every marker path into a `paths[]` list (glue-only field extraction; NO confinement
decision logic in the shim — single decision source, zero drift) and pass `{tool_name:"ApplyPatch",
tool_input:{paths:[…]}}` to the guard. The guard SHALL, for an `ApplyPatch` tool event, run the existing
script-extension block, out-of-tree check, and init/ut-init positive allowlist against EACH path in `paths[]`, and
SHALL block (exit 2 + write-side recipe, delete-side wording for delete operations) if ANY path is out-of-tree / a
blocked script extension / outside the sanctioned subtrees. The shim's `HANDLED` set SHALL include `apply_patch`
alongside `bash`/`write`/`edit`/`read`/`glob`/`grep`.

#### Scenario: opencode apply_patch adding an out-of-tree file is blocked
- **WHEN** an opencode session is inside an `mgh-init` run-domain (sentinel `target=D:\parent\sonA`) and the model
  issues `apply_patch` with `patchText` containing `*** Add File: D:\out\evil.ps1`
- **THEN** the shim extracts `D:\out\evil.ps1` into `paths[]`, the guard resolves it outside the target tree (and as
  a `.ps1` script extension), and blocks with exit 2 + the write-side recipe; the shim throws to abort the tool call
  (the model sees the recipe)

#### Scenario: opencode apply_patch deleting an out-of-tree file is blocked with delete wording
- **WHEN** an opencode session is inside an `mgh-init` run-domain and the model issues `apply_patch` with `patchText`
  containing `*** Delete File: D:\parent\sonB\x.java` (a sibling module, outside the target tree)
- **THEN** the shim extracts the path, the guard blocks with exit 2 + the delete-side recipe ("deletion is
  irreversible; NEVER delete outside the target tree, including sibling modules")

#### Scenario: opencode apply_patch entirely inside sanctioned subtrees passes
- **WHEN** an opencode session is inside an `mgh-init` run-domain and the model issues `apply_patch` whose every
  marker path is inside `<target>/.mgh-init` or `<target>/.claude/rules`
- **THEN** the guard passes (exit 0); legitimate in-tree patches are unaffected

#### Scenario: shim remains glue-only for apply_patch
- **WHEN** the shim source is checked in CI
- **THEN** a parity-test source-form assertion requires the shim to extract `apply_patch` marker paths AND forbids it
  from reimplementing the confinement decision logic (e.g. `_out_of_tree_mutation` / `_WRITE_VERBS` / `_DELETE_VERBS`
  / `is_relative_to` / target resolution / `ApplyPatch` guard-side branching MUST NOT appear in the shim — single
  decision source)

### Requirement: opencode shim arg-name defense-in-depth for write/edit/read

The opencode `.ts` shim's `normalize` SHALL read the file path for `edit`/`write`/`read` from a fallback chain
`args.filePath ?? args.file_path ?? args.path` (the opencode tool schema field is `path`; relying solely on `filePath`
— which the LLM emits in camelCase — would silently yield an empty path if opencode ever passes schema-validated
args). This is a defense-in-depth with zero behavior change for the current camelCase-emitting LLM; it closes a
latent parity gap where a schema-validated `path` arg would bypass confinement (empty `file_path` → guard degrades to
pass). The `grep` source field SHALL be read as `args.include ?? args.glob` (the opencode schema field is `include`).

#### Scenario: opencode write with schema-validated path arg is still confined
- **WHEN** an opencode session is inside an `mgh-init` run-domain and the model issues a `write` tool call whose args
  carry the path under the schema field `path` (not `filePath`), targeting `D:\out\f.json`
- **THEN** the shim's fallback chain resolves the path from `args.path`, the guard blocks the out-of-tree write with
  exit 2 + the write-side recipe (rather than silently passing on an empty `filePath`)

### Requirement: Guard tool-surface wiring coverage enforced by CI

The guard's decision-branch tool set (every tool name the guard's `main()` dispatches on:
`Bash`, `Write`, `Edit`, `MultiEdit`, `NotebookEdit`, `ApplyPatch`, `Read`, `Glob`, `Grep`) SHALL
be fully covered by BOTH host wiring faces, and a CI regression test SHALL enforce it: (a) the
claude-side default PreToolUse matcher injected by `tools/install_hook.py` SHALL contain every
guard tool name; (b) the opencode `.ts` shim's `HANDLED` set (plus its `normalize` mapping) SHALL
cover every guard tool name (via its lowercase mapping). Adding a guard decision branch without
extending both wiring faces SHALL fail the regression test (exit non-zero), structurally closing
the "dead branch" gap class on both hosts — the claude matcher previously covered only
`Bash|Write|Edit`, leaving the read-side branches unconsulted (an out-of-tree `Read` reached the
host permission prompt and interrupted the run instead of failing loud with a recipe), and nothing
prevented the same drift on either host.

#### Scenario: matcher covers the full guard tool surface on fresh install
- **WHEN** `install.sh --claude <target>` 注入 PreToolUse hook
- **THEN** settings.json 的 matcher 含守卫全部分派工具名(`Bash|Write|Edit|MultiEdit|NotebookEdit|Read|Glob|Grep`)

#### Scenario: reinstall evolves a narrower legacy matcher in place
- **WHEN** 目标项目 settings.json 已有 `block_adhoc_scripts` 条目且 matcher 为旧的
  `Bash|Write|Edit`,重跑 `install.sh --claude`
- **THEN** 该条目的 matcher 被更新为全工具面默认值(按 command 内 `block_adhoc_scripts` marker 锚定,
  只改 matcher、不动用户自定义 command;用户自定义非子集 matcher 不动 + stderr 提示;幂等)

#### Scenario: CI fails when a guard branch lacks wiring coverage
- **WHEN** 守卫源新增一个分派工具名(如未来加 `WebFetch`),而 matcher 或 shim `HANDLED` 未同步扩
- **THEN** 接线覆盖回归测 fail(非零退出)——「新增分支忘扩接线面」从「静默死代码」变为 CI 拦截

#### Scenario: out-of-tree Read is consulted by the guard on claude
- **WHEN** claude 会话处于 `mgh-init` 运行域(激活),模型 `Read` 一个越树路径(如 `..` 链折叠后落
  `D:\xxxx`)
- **THEN** PreToolUse hook 被触发(matcher 含 `Read`)→ 守卫退出码 2 → 工具调用被阻断、模型看到
  read-side recipe;**不出现**宿主 D 盘根权限询问(报告的中断形态消除)

### Requirement: Reader anchoring on the materialized repo and poisoned-input rejection

Every `--materialize` work-list producer (scout/T1/ut-init family) SHALL write the absolute `repo`
root as a top-level field of each materialized unit input file (and carry it in its stdout
`pending[]` context), so every reader subagent's input carries a deterministic anchor without
re-deriving it. Every reader stage prompt (starting with `init-scout.md`, and every same-shape
fan-out reader) SHALL carry: (a) an **anchoring discipline** — the working anchor is the absolute
`repo` root carried in the input; every path the subagent passes to tools SHALL be either a
verbatim producer-materialized path or built relative to that anchor — NEVER hand-assembled from
memory (no `<drive>:\<guessed dirs>` reconstruction, no `..` chains); (b) a **poisoned-input
rejection rule** — when an input path field (`checkpoint_path`/`input_path`/`done_marker`/
`slice_dir`) resolves outside the anchored target tree (e.g. a drive-root-drifted
`checkpoint_path` like `D:\.mgh-init\…`), the subagent SHALL treat it as poisoned input: reply
`failed <suspected path drift>` WITHOUT reading or writing anything, so the orchestrator records
the `.failed` marker and the failure surfaces instead of executing against a wrong tree. The
orchestrator-side dispatch fragment SHALL instruct byte-verbatim copying of `pending[]` path
fields from the producer stdout (NEVER hand-assembling `checkpoint_path`/`input_path`). Absolute
paths SHALL remain the sanctioned fan-out form (verbatim producer-materialized paths are correct;
the rejection criterion is "resolves outside the anchor tree", NOT "contains a drive letter").

#### Scenario: every materialized unit input carries the absolute repo anchor
- **WHEN** `list_scout_batches.py --materialize`(或 T1/ut-init 同形 producer)写出
  `<unit>.input.json`
- **THEN** 该 input.json 顶层含绝对 `repo` 字段(与 stdout 同源),reader 锚定无需重派生

#### Scenario: scout subagent anchors reads on the materialized repo root
- **WHEN** 审阅 `init-scout.md` stage 提示词
- **THEN** 含路径锚定纪律段:工作锚 = 输入绝对 repo 根;工具路径 = producer 物化路径 verbatim 或
  相对锚构造;NEVER 凭记忆手拼盘符绝对路径、NEVER `..` 链

#### Scenario: poisoned checkpoint_path is rejected, not executed
- **WHEN** scout subagent 的任务输入携带 `checkpoint_path=D:\.mgh-init\checkpoints\…`(盘符根漂移,
  不在锚定 target 树内)
- **THEN** subagent 按提示词回 `failed <suspected path drift>` ack、不 Read / 不 Write 任何东西;
  编排器写 `.failed` marker(既有契约),该批显式失败而非对着错误树执行

#### Scenario: dispatch fragment mandates byte-verbatim path copy
- **WHEN** 审阅 `init-stage/scout.md` 派发段
- **THEN** 含「`checkpoint_path`/`input_path`/`done_marker`/`slice_dir` 逐字节从 `list_scout_batches.py`
  stdout `pending[]` 复制,NEVER 手拼/NEVER 改写」的 recipe(编排器弱模型防漂移的正引导)

#### Scenario: legitimate absolute materialized paths are not refused
- **WHEN** subagent 输入里的 `checkpoint_path`/`input_path`/`targets[].file` 为落在锚定 target 树内的
  绝对路径(producer 物化的正常形态)
- **THEN** 提示词不拒(绝对路径是 fan-out 契约的正确形态;拒识判据是「解析后不在锚定树内」,非
  「带盘符」)
