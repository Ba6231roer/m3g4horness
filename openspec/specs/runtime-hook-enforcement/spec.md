# runtime-hook-enforcement Specification

## Purpose

跨六命令(`/mgh-init`|`/mgh-sast`|`/mgh-sra`|`/mgh-srr`|`/mgh-ut-init`|`/mgh-sdr`)共享的运行时纪律守卫契约——
激活模型(env 或磁盘哨兵)、运行域脚本只读、脚本扩展名集、写入受信子树限定。取代此前分散在各命令 spec、
措辞漂移的重复 hook 要求,作为 `block_adhoc_scripts` 守卫(双端 byte-identical)的单一真相源。本能力由
change `harden-mgh-opencode-hook-enforcement` 建立、`add-mgh-ut-init` 扩到第 5 域 `mgh-ut-init`、
`harden-mgh-init-deterministic-enforcement` 把 init 域哨兵写入改为 `write_runconfig` 确定性副作用
(+ `resume_state --check` 存在性校验 + re-arm)并增读侧叶源码拦截、`add-mgh-sdr-resume-surface`
扩到第 6 域 `mgh-sdr`(哨兵写入改为 `sdr_context` 确定性副作用 + `resume_sdr_state --check`
存在性校验 + re-arm)。
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
**守卫脚本缺失时 SHALL fail-soft 放行**:shim 在 spawn 前做守卫文件存在性预检(缺失 → 放行 +
一条诊断日志,不 spawn)——python 对不存在的脚本文件以退出码 2 退出(`can't open file`),与守卫的
阻断退出码同值;无预检时一次守卫文件缺失/错位会被误判为 deny(与 fail-soft 契约「守卫不在 → PASS」
矛盾)。stderr 含 python「can't open file」签名的退出码 2 亦 SHALL 按 fail-soft 处理(存在性预检的
兜底)。

**2.x 形态增补**:回调从 2.x 单事件对象取参——工具名读 `event.tool`,工具参数读
`event.input`(1.x 的 `(input, output)` 双参形态移除);payload SHALL 携带 `cwd` 字段 =
插件 `setup` 时捕获的项目根(`ctx.location.directory`)——2.x 插件随常驻服务进程运行,
服务进程 cwd 与被分析项目无关,不注入则守卫锚点链(哨兵发现与相对 token 判定)系统性指错
地方;守卫侧既有优先级(payload `cwd` > 守卫进程 cwd)不变,Python 侧零改动。非阻断诊断
(1.x 经 `ctx.client.app.log` 上报)在 2.x 无对应通道,SHALL 降级为 best-effort 输出;
阻断契约(守卫退出码 2 → throw stderr 作 recipe)不变。

#### Scenario: a py -c introspection one-liner is blocked in opencode

- **WHEN** an opencode session is inside an mgh run-domain (env `MGH_*_ACTIVE=1` at opencode launch
  OR the `<cwd>/<run-root>/.active` sentinel present) and the model issues a Bash `py -c` command
  carrying introspection tokens (`import json` / `open(` / `load(` / `.json`)
- **THEN** the shim feeds the normalized payload to the guard as `new Blob([stdin])`, the guard
  exits 2, the shim throws and the tool call is blocked (the model sees the sanctioned-primitive
  recipe) — the guard is NOT silently disabled by a stdin-delivery throw

#### Scenario: missing guard file degrades to a pass, not a deny

- **WHEN** the guard script file is absent/moved at the shim's resolved path(an incomplete or
  skewed install), and a handled tool call occurs inside a run-domain
- **THEN** the existence pre-check fails → the shim passes the call + logs one diagnostic
  (fail-soft);python's can't-open-file exit 2 is NEVER interpreted as a deny(修复前该形态 =
  误判 deny,与「守卫不在 → PASS」契约矛盾)

#### Scenario: 2.x 服务进程 cwd 非项目根时锚点仍正确

- **WHEN** opencode 2.x 常驻服务进程的 cwd 在别处(如用户主目录),项目内存在
  `<项目>/.mgh-init/.active` 哨兵,模型发起 `bash` 越树写或含 `..` 相对 token 的命令
- **THEN** shim 注入的 payload `cwd` = 项目根,守卫的哨兵发现与相对 token 判定都以项目根
  为锚(修复前回退服务进程 cwd → 哨兵整链发现不到 → 守卫对整个 run 休眠,越树写静默放行)

#### Scenario: the shim source form is regression-guarded in CI

- **WHEN** the shim source is checked in CI (no Bun runtime available)
- **THEN** a parity-test source-form assertion requires `new Blob([stdin])` AND the guard-file
  existence pre-check AND the 2.x single-event-object read(`event.tool`/`event.input`)AND the
  `cwd` injection(`ctx.location.directory` 捕获后写入 payload)to be present, preventing a
  silent revert to a bare string stdin, to exit-code-conflating deny logic, or to the un-anchored
  2.x form (the runtime delivery itself is verified manually in opencode on both 2.0.x and 2.1.x)


### Requirement: opencode 2.x 插件模块契约与形状自检

The opencode `.ts` shim SHALL satisfy the opencode 2.x plugin module contract: a **default
export** of the form `{ id: <string>, setup: <async function> }`, with the
`tool.execute.before` hook registered via the plugin context's tool-hook API **and the
registration awaited inside `setup` before `setup` returns** (a fire-and-forget registration
lets the first tool call slip past an unregistered hook). The hook callback SHALL receive a
**single event object** and read the tool id from `event.tool` and the tool arguments from
`event.input` — the 1.x two-parameter `(input, output)` callback form is removed. The shim
SHALL remain glue-only (activation gating, regexes, whitelists, subtree decisions live only
in the Python guard). The repo's CI SHALL statically assert the module shape (default export
with `id` + `setup` present; the 1.x named-export form absent) so a future opencode
module-contract change cannot silently disable the guard again — opencode's own plugin-load
failure is fail-soft (a WARN in the service log, sessions continue), so shape drift SHALL be
caught by CI, not by runtime. The shim file targets the 2.x contract; 1.x opencode
installations keep the previously released shim file (no dual-shape file — a file satisfying
both contracts is not expressible, and carrying two files would double the wiring surface).

#### Scenario: 2.x 服务加载插件并触发单事件对象回调

- **WHEN** opencode 2.x 加载 mgh 插件(项目 `.opencode/plugins/` 自动发现)且任一会话发
  起工具调用
- **THEN** 插件以 default 导出被接受(服务日志无 `Plugin must export a default
  definition…` 拒载记录),`tool.execute.before` 回调收到含
  `tool/sessionID/agent/messageID/id/input` 的事件对象——不存在 `(input, output)` 双参形态

#### Scenario: 注册竞态防护

- **WHEN** 插件 `setup` 尚未返回时会话已发起首个被管工具调用
- **THEN** 因钩子注册在 `setup` 内被 `await`,该调用仍命中已注册的守卫管道——不存在
  「注册未完成 → 调用漏过 → 守卫静默缺席整段早期会话」的窗口

#### Scenario: CI 静态形状自检

- **WHEN** CI 检查插件源码(无 opencode 运行时)
- **THEN** 源码形状断言要求 `export default` + `{ id` + `await ctx.tool.hook(`(注册被
  await)存在,且 1.x 具名导出形态(`export const BlockAdhocScripts` / 双参回调)缺席——
  模块契约漂移从「运行期静默拒载」变为 CI fail-loud

#### Scenario: 宿主拒载的 fail-soft 边界保持披露

- **WHEN** 宿主自身因任何原因未加载插件(宿主侧加载失败按其设计 fail-soft,仅 WARN)
- **THEN** mgh 不在插件内自救;「守卫缺席 → PASS」的运行期 fail-soft 契约不变,守卫不在
  场的事实由 install 自检与实机验证闸门(双版本加载检查)在安装/验证期暴露,不靠运行期
  症状发现


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
subagent pulls a leaf `.py` (200–900 lines ≈ 3–10K tokens) into their context to "debug" a `--check`
failure, which accelerates compaction and risks the agent reasoning about internals. The block
SHALL NOT apply to the target project's own `.py` source (only the installed mgh-core leaf scripts,
identified by the `mgh-core/scripts` path segment); it SHALL NOT apply to `Read` of non-script
artifacts (`.json`/`.md`). **路径段比较 SHALL 大小写不敏感**(Windows 文件系统大小写不敏感;
`.CLAUDE/Mgh-Core/Scripts/…` 变体与规则 l 的 IGNORECASE 正则同判,SHALL NOT 经大小写变体绕过)。
When the guard is inactive (no env, no sentinel), the read SHALL pass
(install/CI/dev unaffected).

#### Scenario: Reading a leaf .py during a run is blocked

- **WHEN** an `mgh-init` run-domain is active (env `MGH_INIT_ACTIVE=1` OR `<cwd>/.mgh-init/.active`
  sentinel present), and the model issues `Read`
  `file_path=D:\parent\sonA\.claude\mgh-core\scripts\list_clusters.py`
- **THEN** the guard resolves the path under `mgh-core/scripts/` with a script extension and blocks
  with exit 2 + a recipe ("report errors from stderr, NEVER Read leaf script source") — the leaf
  source does not enter context

#### Scenario: Reading a leaf .py via a Windows case variant is blocked

- **WHEN** an `mgh-init` run-domain is active, and the model issues `Read`
  `file_path=D:\parent\sonA\.CLAUDE\Mgh-Core\Scripts\list_clusters.py`(同一文件的 casing 变体)
- **THEN** the guard compares the path segments case-insensitively, still identifies the
  `mgh-core/scripts` segment + script extension, and blocks with exit 2 + the same recipe
  (修复前大小写敏感比较使该变体绕过)

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
### Requirement: Sentinel read_roots grants tool-face read-only access to declared external roots

The run-domain sentinel schema carries an **optional** field `read_roots[]` (a list of absolute
filesystem roots); its absence preserves the existing schema shape (`{"domain","target",
"out_roots[]","v":1}` remains valid). When `read_roots[]` is present and the guard is active,
a call or command whose resolved path falls inside ANY declared `read_roots[]` root SHALL pass on
BOTH read faces: the **tool face** (`Read`/`Glob`/`Grep`) and the **Bash face** (any `Bash`
command's path tokens, judged by the Bash path-token allowlist rule). This REVERSES the prior
decision that a declared root NEVER becomes a Bash-searchable location — the unified model is
"what is readable at all is readable through any tool"; it is safe to unify because the Bash face
now judges paths directly (verb-independently) instead of relying on verb enumeration. The write
side is NOT relaxed: every write layer (`Write`/`Edit`/`MultiEdit`/`NotebookEdit`/`ApplyPatch`,
Bash write verbs, redirects, deletes) SHALL keep judging against `MGH_TARGET` alone — a declared
root NEVER becomes a writable location. The leaf-script-source read block and the `py -c` /
temp-I/O / file-association blocks are likewise NOT relaxed. `out_roots[]` (write-side allowlist
extension for init/ut-init) and `read_roots[]` (read-side extension for any domain) remain
independent fields with disjoint effects. The containment check SHALL require the declared root
to exist and be a directory at judgment time; a non-existent declared root grants nothing
(fail-closed). This judgment holds identically on both hosts (claude PreToolUse guard + opencode
plugin shim pipe the full sentinel JSON to the same Python decision core; byte-level parity, same
wiring-coverage invariant).
resolved target (the same resolution rules as the out-of-tree judgment: `..` folding, identical
resolve semantics) falls inside ANY declared `read_roots[]` root — the declared external roots are
peer **read-only** allowances, and each root is judged with the same `is_relative_to` containment
semantics as `MGH_TARGET`. Every other read-side layer SHALL NOT be relaxed by `read_roots[]`: the
Bash file-search confinement (`rg`/`grep`/`find`/…), the leaf-script-source read block, the write
side (all layers: `Write`/`Edit`/`MultiEdit`/`NotebookEdit`/`ApplyPatch`, Bash write verbs,
redirects, deletes), and the `py -c` / temp-I/O / file-association blocks SHALL keep judging against
`MGH_TARGET` alone — an external root declared via `read_roots[]` NEVER becomes a writable or
Bash-searchable location. `out_roots[]` (write-side allowlist extension for init/ut-init) and
`read_roots[]` (read-side-only extension for any domain) are independent fields with disjoint
effects. The containment check SHALL require the declared root to exist and be a directory at
judgment time; a non-existent declared root grants nothing (fail-closed). This judgment holds
identically on both hosts (claude PreToolUse guard + opencode plugin shim pipe the full sentinel
JSON to the same Python decision core; byte-level parity, same wiring-coverage invariant).

#### Scenario: Declared external root read passes while undeclared is blocked

- **WHEN** an `mgh-sdr` run-domain is active with sentinel `{"domain":"mgh-sdr",
  "target":"D:/work/svc","read_roots":["D:/work/front"],"v":1}`, and a subagent issues
  `Read file_path=D:/work/front/src/api/pay.js` (inside the declared root)
- **THEN** the guard allows the read (exit 0) — the declared root is a peer readable tree

#### Scenario: Undeclared sibling path stays blocked

- **WHEN** the same run-domain sentinel declares only `D:/work/front`, and a subagent issues
  `Read file_path=D:/work/other/src/x.js`
- **THEN** the guard blocks with exit 2 + the read-side recipe (declared roots are not a wildcard;
  only the target tree and listed roots are readable)

#### Scenario: Write into a declared read root is still blocked

- **WHEN** the same sentinel, and a subagent issues `Write file_path=D:/work/front/src/api/pay.js`
  (inside the declared read root)
- **THEN** the write side judges against `MGH_TARGET` alone and blocks (exit 2) — `read_roots[]`
  never grants write access

#### Scenario: Bash search verb confined to MGH_TARGET despite read_roots

- **WHEN** the same sentinel, and a subagent runs `Bash: rg pay D:/work/front/src`
- **THEN** the guard passes (exit 0) — the Bash face judges the path token against the unified
  read allow-set (target ∪ `read_roots[]`), so a declared root is Bash-readable like it is
  tool-face-readable. **语义反转**: the PRIOR behavior (blocked — "declared roots never become
  Bash-searchable") is replaced by this requirement; the scenario retains its historical name
  for delta traceability

#### Scenario: Bash path outside target and all declared roots is blocked

- **WHEN** the same sentinel, and a subagent runs `Bash: rg pay D:/work/other/src`
- **THEN** the guard blocks with exit 2 + the read-side recipe (the path resolves outside the
  target tree AND every declared root)

#### Scenario: Sentinel without read_roots is unchanged

- **WHEN** a legacy sentinel `{"domain":"mgh-srr","target":"T","out_roots":[],"v":1}` (no
  `read_roots` field) is active
- **THEN** guard behavior is unchanged for the sentinel path (no read relaxation from the
  sentinel; the project config file, if present, still applies per its own requirement)

#### Scenario: Non-existent declared root grants nothing

- **WHEN** a sentinel declares `read_roots:["D:/gone/front"]` and the directory does not exist
- **THEN** a `Read` of `D:/gone/front/anything` is blocked (fail-closed containment: root must
  exist and be a directory at judgment time)

### Requirement: Bash path-token allowlist judgment (verb-independent fail-closed net)

When active with a pinned target, the guard SHALL judge EVERY path-like token in each `Bash`
command against the unified read allow-set — the resolved `MGH_TARGET` tree ∪ sentinel
`read_roots[]` ∪ project config `read_roots[]` — **regardless of which verb (if any) leads the
command**: any token that resolves outside ALL of them SHALL block (exit 2) with a recipe naming
the allowed read roots. Path-like tokens are: Windows drive-letter absolute (`C:\…`/`C:/…`), UNC
(`\\…`), POSIX absolute (`/…`), `..`-leading relative tokens (resolved against the guard's cwd),
and `~`-leading path tokens (bare `~` alone is not judged); tokens that are part of a URL
(`<word>://…`) SHALL be excluded from judgment. **Glob-form tokens**: a path-like token
containing glob metacharacters (`*`/`?`) SHALL be judged by its **glob-free prefix** (everything
before the first metacharacter); a glob segment that **directly abuts a quote-closed absolute
path** (`"C:\t"/*.html` or `"C:\t"\*.log`) SHALL be joined with that path into one logical token
before extraction (without the join, the closing quote ends the token and the glob fragment is
misread as a bare `/…` absolute path that resolves to the drive root — a false out-of-tree hit);
a glob whose prefix resolves outside the allow-set (`D:\other\*.log`) remains a block. This
glob-form semantics SHALL apply to EVERY Bash absolute-path-token judgment in the guard
(file-search, directory-listing, write/delete/redirect, and this net), so all rules judge the
same normalized token stream. **token 的左边界字符集含重定向字符 `<` 与 `>`**:无空格
重定向形态(`echo x >D:/out/f`)的路径 token SHALL 可被提取判定(修复前边界类缺这两个字符,紧贴 `>` 的
路径提取不到 → 净网漏拦,与 redirect 规则联动时彻底无拦截)。A command carrying no path-like token SHALL
pass this rule (all other rules still apply to it). This judgment SHALL run AFTER the mutation rules
(write/delete verbs, redirects, `py -c` write-shape relabel) so mutation-shaped hits surface
their specific write/delete recipes, and alongside/after the existing verb-triggered read rules
(file-search, listing, interpreter-exec, mgh-core missing-install), which REMAIN IN FORCE as
refinements — this rule is the structural fail-closed net under them, closing the
"verb not in the enumeration table" escape class (`robocopy`, `curl -o`, `.NET` static write
methods, `Get-Content <out-of-tree file>`, `Expand-Archive`, …). Target unpinned => this rule
degrades to pass (mirror of every other path rule; never a hard block when no target was pinned).

#### Scenario: Unknown mutation verb with an out-of-tree destination is blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model
  issues `Bash: robocopy D:\parent\sonA\docs D:\backup` (the write verb `robocopy` is in NO
  enumeration table)
- **THEN** the guard judges the path tokens, finds `D:\backup` outside the target tree, and
  blocks with exit 2 + a recipe naming the allowed roots (previously passed — no enumerated verb
  matched)

#### Scenario: Direct read of an out-of-tree file is blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model
  issues `Bash: Get-Content D:\parent\sonB\notes.json` (a plain read verb, not a search/listing
  verb; previously passed every rule)
- **THEN** the guard resolves the path token outside the target tree and blocks with exit 2 +
  the recipe

#### Scenario: In-tree command passes untouched

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model
  issues `Bash: py .claude/mgh-core/scripts/list_clusters.py --out D:\parent\sonA\.mgh-init\c.json`
- **THEN** the guard passes (exit 0) — every path token resolves inside the target tree; the
  sanctioned deterministic-script workflow is unaffected

#### Scenario: no-space redirect form extracts its path token

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model
  issues `Bash: echo x >D:/out/f`(重定向符与路径间无空格)
- **THEN** the guard extracts `D:/out/f` as a path token(左边界含 `>`),resolves it outside the
  target tree and read allow-set, and blocks with exit 2 + the recipe(修复前该形态提取不到
  token,净网漏拦)

#### Scenario: `..`-climbing relative token is blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA` (guard cwd inside
  the tree), and the model issues `Bash: type ..\..\secret.txt` (cwd-relative resolution climbs
  out of the tree)
- **THEN** the guard resolves the `..`-leading token against the cwd, finds it outside the tree,
  and blocks with exit 2 + the recipe

#### Scenario: URL token does not false-trip

- **WHEN** an `mgh-init` run-domain is active with a pinned target, and the model issues
  `Bash: py .claude/mgh-core/scripts/tool.py --doc https://example.com/a/b`
- **THEN** the guard passes (exit 0) — the `s://…` fragment of the URL is excluded from
  path-token judgment (URL-scheme exclusion), so no false block

#### Scenario: Write-shaped hit into a declared read root surfaces the write recipe, not the read net

- **WHEN** an `mgh-sdr` run-domain is active with sentinel `read_roots:["D:/work/front"]`, and
  the model issues `Bash: Set-Content D:/work/front/x.js "v"` (a known write verb targeting a
  declared read-only root)
- **THEN** the mutation rules run FIRST, judge the destination against `MGH_TARGET` alone, and
  block with exit 2 + the write-side recipe (the read-net's allow-set never relaxes a write)

#### Scenario: Unpinned target degrades the token judgment to pass

- **WHEN** the guard is active but neither env nor sentinel pins a target, and the model issues
  `Bash: cat D:\anywhere\f.txt`
- **THEN** the token judgment degrades to pass (exit 0); the script-extension write block,
  `py -c` introspection block, temp-I/O, file-association, and mgh-core missing-install rules
  still fire where applicable

#### Scenario: Quoted in-tree path abutting a glob fragment passes

- **WHEN** an `mgh-sdr` run-domain is active with `MGH_TARGET=C:\DEV\springBootTemplate`, and
  the model issues the repo-root report-discovery command
  `ls -la "C:\DEV\springBootTemplate" | grep -i "mgh-sdr" ; ls "C:\DEV\springBootTemplate"/*.html`
- **THEN** the guard passes (exit 0): the glob segment `/*.html` abuts the quote-closed in-tree
  path and is joined with it before judgment (joined prefix in-tree), and the pipe/sub-command
  tokens all resolve inside the target tree — previously this exact form was a false
  out-of-tree block that burned host retry rounds

#### Scenario: Out-of-tree glob prefix is still blocked

- **WHEN** an `mgh-sdr` run-domain is active with `MGH_TARGET=C:\DEV\springBootTemplate`, and
  the model issues `Bash: ls "D:\other\repo"/*.html` (glob abutting an out-of-tree quoted path)
- **THEN** the guard joins the glob with its quoted prefix, resolves the prefix outside the
  target tree, and blocks with exit 2 + the recipe (the join is a false-positive fix, NEVER a
  read-side relaxation)
### Requirement: Project read-roots config file extends the read allow-set in every domain

The guard SHALL consult a per-project read-roots config file at `<MGH_TARGET>/.mgh/read-roots.json`
in EVERY mgh run-domain, merging its `read_roots[]` entries into the unified read allow-set
alongside the sentinel's `read_roots[]` (union; both sources optional; a missing config file
means behavior identical to before this requirement). The schema is
`{"v":1,"read_roots":["<abs root>",…]}`; unknown fields are ignored. A malformed JSON body or a
wrong-typed `read_roots` SHALL grant NOTHING (fail-closed) and SHALL NOT crash the guard or
alter any other judgment. Each entry SHALL be judged with the same fail-closed containment as
the sentinel's `read_roots[]` (the root must exist and be a directory at judgment time; a
non-existent entry grants zero). Config-declared roots are READ-ONLY allowances on the tool face
and the Bash face; they NEVER grant write access (the write side judges `MGH_TARGET` alone),
NEVER relax the leaf-script-source read block, and NEVER relax the `py -c` / temp-I/O /
file-association blocks. The file lives inside the target tree, so writes to it are governed by
the existing write-confinement rules as an ordinary in-tree file. The config is
hand-editable by the user; a deterministic writer (sdr approval flow) is a follow-up change and
is NOT required by this requirement.

#### Scenario: Config root is readable on both faces in every domain

- **WHEN** an `mgh-sast` run-domain is active with config `{"v":1,"read_roots":["D:/shared/specs"]}`,
  and the model issues `Read file_path=D:/shared/specs/auth.md` and `Bash: rg token D:/shared/specs`
- **THEN** both pass (exit 0) — the config extends the read allow-set for the tool face and the
  Bash face alike, in a domain that has no sentinel `read_roots[]`

#### Scenario: Write into a config root is blocked

- **WHEN** the same `mgh-sast` domain and config, and the model issues
  `Write file_path=D:/shared/specs/auth.md`
- **THEN** the write side judges against `MGH_TARGET` alone, finds the path out-of-tree, and
  blocks with exit 2 + the write-side recipe

#### Scenario: Malformed config grants nothing and does not crash

- **WHEN** the config file contains invalid JSON (or `read_roots` is not a list), and the model
  issues `Read file_path=D:/anything/f.txt` (outside the target tree)
- **THEN** the guard blocks the read with exit 2 as if no config existed (fail-closed), exits
  normally on in-tree calls, and never errors out

#### Scenario: Missing config file means unchanged behavior

- **WHEN** no `.mgh/read-roots.json` exists under the target, and the model issues any tool call
- **THEN** guard behavior is identical to before this requirement (no parse, no relaxation, no error)

#### Scenario: Config union with sentinel read_roots

- **WHEN** the sentinel declares `read_roots:["D:/work/front"]` and the config declares
  `read_roots:["D:/shared/specs"]`, and the model reads a file under each root
- **THEN** both reads pass (exit 0) — the two sources are a union, each judged with the same
  fail-closed containment

### Requirement: opencode shim normalizes read-side tools to the guard

The opencode `.ts` shim SHALL feed the guard for `read`/`glob`/`grep` tool events (in addition to
`bash`/`write`/`edit`), normalizing opencode's camelCase args to the Claude `{tool_name, tool_input}`
stdin shape the guard expects: `read` → `{tool_name:"Read", tool_input:{file_path}}`;
`glob` → `{tool_name:"Glob", tool_input:{pattern, path}}`; `grep` →
`{tool_name:"Grep", tool_input:{pattern, path, glob}}`. The shim SHALL remain glue-only — the
read-side out-of-tree decision logic lives ONLY in the Python guard (single decision source, zero
drift). The shim's `HANDLED` set SHALL include `read`/`glob`/`grep` alongside `bash`/`write`/`edit`.
**2.x 工具名增补**:opencode 2.x 更名的工具 id 与 1.x 旧 id SHALL 同时收敛到同一守卫面——
`shell`(2.x 的 bash 更名)与 `bash` 都映射 `{tool_name:"Bash", tool_input:{command}}`;
2.x 的补丁工具 id(若与 `apply_patch` 不同名)与 `apply_patch` 都走补丁面提取。`read`/
`glob`/`grep` 在 2.x 名字不变。

#### Scenario: opencode read event is normalized and decided by the guard

- **WHEN** an opencode session is inside an `mgh-init` run-domain and the model issues a `read` tool
  call with `filePath=D:\parent\sonB\x.java` (outside `target=D:\parent\sonA`)
- **THEN** the shim normalizes it to `{tool_name:"Read", tool_input:{file_path:"D:\\parent\\sonB\\x.java"}}`,
  feeds it to the guard (single decision source) via `new Blob([stdin])`, the guard exits 2, and the
  shim throws to abort the tool call (the model sees the read-side recipe) — the read-side decision
  does not drift between platforms

#### Scenario: 2.x `shell` id 收敛到同一 Bash 面

- **WHEN** opencode 2.x 会话处于运行域内,模型经更名后的 `shell` 工具发起 `py -c` 内省命令
- **THEN** shim 把 `shell` 事件映射为 `{tool_name:"Bash", tool_input:{command}}` 喂守卫,
  守卫按 Bash 面判定并阻断(修复前 HANDLED 不含 `shell` → 事件漏过守卫 → 微脚本内省在 2.x
  裸奔)

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
temp-I/O and file-association rules. Absolute-path token judgment in condition (a) SHALL apply the
glob-form semantics of the path-token allowlist net: a token containing glob metacharacters
(`*`/`?`) is judged by its glob-free prefix, and a glob segment directly abutting a quote-closed
absolute path is joined with that path before judgment (in-tree join => pass; out-of-tree prefix =>
block).

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

#### Scenario: In-tree quoted path abutting a glob passes the search-verb rule

- **WHEN** an `mgh-sdr` run-domain is active with `MGH_TARGET=C:\DEV\springBootTemplate`, and the
  model issues `Bash` `ls "C:\DEV\springBootTemplate"/*.html | grep -i "mgh-sdr"` (search verb
  after the pipe; the glob token abuts a quote-closed in-tree path)
- **THEN** the guard joins the glob with its in-tree quoted prefix, resolves it inside the target
  tree, and passes (exit 0) — the report-discovery form the sdr orchestration legitimately uses is
  no longer a false block

#### Scenario: Out-of-tree glob search root is still blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model
  issues `Bash` `rg "x" "D:\parent\sonB"/*.java` (glob abutting an out-of-tree quoted path)
- **THEN** the guard joins the glob with its out-of-tree quoted prefix, resolves the prefix
  outside the target tree, and blocks with exit 2 + the read-side recipe

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

**写目的地判定的域分派(与各自 Write/Edit 工具面逐字镜像)**:对 `mgh-init`/`mgh-ut-init`(受信子树
allowlist 域),一个**树外**目的地经哨兵 `out_roots[]` 豁免——落在某个 out_root 内则放行(与
Write/Edit 工具层 `_allowlist_write_blocked` 同一查询、同一来源;定制 `--out`/`--rules-dir` 绝对根是
合法写目的地);树内目的地照旧走受信子树 P1。对 sast/sra/srr/sdr(无 allowlist 域),树外目的地一律
拦——它们的 Write/Edit 工具面同样不咨询 `out_roots`,Bash 写动词面与之镜像,NEVER 出现「同一目的地、
工具面拦、Bash 面放行」(或反向)的入口翻转。**`read_roots`(哨兵与项目配置)在任何写面永不豁免**:
已声明的只读根是读侧概念,写入它(任何动词、任何面)SHALL 拦 + 写侧 recipe。

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

#### Scenario: Bash Copy-Item into a sentinel out_root passes (init, tool-face mirror)

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA` and the sentinel declares
  `out_roots:["D:\custom\out"]` (a customized `--out` absolute root), and the model issues `Bash`
  `Copy-Item x.json D:\custom\out\x.json`
- **THEN** the guard consults `out_roots` on the out-of-tree destination (the same query the Write/Edit tool
  layer's allowlist makes), finds it inside a sanctioned write root, and passes (exit 0) — the three write
  entry points (Write/Edit tool, Bash write verb, redirect) reach the SAME verdict for the same destination

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

#### Scenario: Bash write into a declared read root is blocked (read roots are never writable)

- **WHEN** an `mgh-sdr` run-domain is active with sentinel `read_roots:["D:\work\front"]`, and the model issues
  `Bash` `Set-Content D:\work\front\x.js "v"`
- **THEN** the write destination judgment consults only `MGH_TARGET` (+ allowlist `out_roots` where applicable),
  finds the declared read root outside both, and blocks with exit 2 + the write-side recipe — a declared read-only
  root NEVER becomes writable on any write face

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
SHALL block it (exit 2) + the write-side recipe — **对全部六域生效**:无 allowlist 的 sast/sra/srr/sdr 与
init/ut-init 同判(树外 redirect 从非「无白名单即放行」;该形态曾是树外拦截分支上的不可达死代码)。
对 `mgh-init` AND `mgh-ut-init`,树外目的地经哨兵 `out_roots[]` 豁免(与 Write/Edit 工具层 allowlist 同
一查询)、树内目的地 SHALL additionally land inside a sanctioned subtree (positive allowlist), mirroring the
Write/Edit tool-layer rule — so a redirect that pollutes the target root (`echo x > D:\parent\sonA\evil.txt`) fails
loud too. The prior temp-dir write + read-back defense (`_detect_temp_io`) is retained as an independent defense;
this rule adds the out-of-tree / non-sanctioned-subtree axis. `MGH_TARGET` resolves with the same precedence
(env > sentinel.`target` > degrade-pass). **`read_roots` 永不豁免 redirect 目的地**(写入声明只读根 =
拦 + 写侧 recipe)。

#### Scenario: Bash redirect to an out-of-tree non-temp path is blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `echo x > D:\out\f.json` (a non-temp out-of-tree redirect the prior temp-only rule did not match)
- **THEN** the guard resolves the redirect target `D:\out\f.json` outside the target tree and blocks with exit 2 +
  the write-side recipe

#### Scenario: Bash append redirect to an out-of-tree path is blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `echo x >> D:\out\f.json`
- **THEN** the guard blocks with exit 2 + the write-side recipe

#### Scenario: Bash redirect to an out-of-tree path is blocked in a no-allowlist domain too

- **WHEN** an `mgh-sdr`(或 sast/sra/srr)`run-domain` is active with `MGH_TARGET=D:\parent\sonA`, and the model
  issues `Bash` `echo x > D:\out\f.json`
- **THEN** the guard resolves the redirect target outside the target tree and blocks with exit 2 + the write-side
  recipe(修复前 `_redirect_in_sanctioned` 对无 allowlist 域早真放行,该分支不可达——四域 redirect 越树
  整体无拦截,兜底净网报的还是读侧 recipe)

#### Scenario: Bash redirect into a declared read root is blocked (read roots never writable)

- **WHEN** an `mgh-sdr` run-domain is active with sentinel `read_roots:["D:\work\front"]`, and the model issues
  `Bash` `echo x > D:\work\front\f.js`(目的地在声明的只读根内——兜底净网也在允许集内)
- **THEN** the guard blocks with exit 2 + the write-side recipe(修复前该形态全链路 exit 0 放行,直接违反
  「声明只读根永不可写」)

#### Scenario: Bash redirect to a sentinel out_root passes (init)

- **WHEN** an `mgh-init` run-domain is active with the sentinel declaring `out_roots:["D:\custom\out"]`, and the
  model issues `Bash` `echo x > D:\custom\out\f.json`
- **THEN** the guard consults the allowlist (subtrees ∪ out_roots), finds the destination inside a sanctioned
  write root, and passes (exit 0) — 与 Write/Edit 工具面对同一目的地同一结论

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
**2.x 形态下该链语义不变**:参数自 2.x 事件对象的 `event.input` 读取,回退链与字段名沿用。

#### Scenario: opencode write with schema-validated path arg is still confined

- **WHEN** an opencode session is inside an `mgh-init` run-domain and the model issues a `write` tool call whose args
  carry the path under the schema field `path` (not `filePath`), targeting `D:\out\f.json`
- **THEN** the shim's fallback chain resolves the path from `args.path`, the guard blocks the out-of-tree write with
  exit 2 + the write-side recipe (rather than silently passing on an empty `filePath`)

#### Scenario: 2.x 事件对象参数仍走同一回退链

- **WHEN** opencode 2.x 事件对象 `event.input` 携带 schema 校验形参数(`path` 字段而非
  `filePath`),目标越树
- **THEN** shim 自 `event.input` 读参并按同一回退链解析出路径,守卫照常阻断(2.x 事件形状
  不引入新的空路径旁路)

### Requirement: Guard tool-surface wiring coverage enforced by CI

The guard's decision-branch tool set (every tool name the guard's `main()` dispatches on:
`Bash`, `Write`, `Edit`, `MultiEdit`, `NotebookEdit`, `ApplyPatch`, `Read`, `Glob`, `Grep`, plus
the dsh-dialect names mapped in by the third wiring face) SHALL be fully covered by ALL THREE
host wiring faces, and a CI regression test SHALL enforce it: (a) the claude-side default
PreToolUse matcher injected by `tools/install_hook.py` SHALL contain every guard tool name;
(b) the opencode `.ts` shim's `HANDLED` set (plus its `normalize` mapping) SHALL cover every
guard tool name (via its lowercase mapping),**并且同一守卫面在 opencode 2.x 与 1.x 的两代
工具 id SHALL 同时在收(converged)——`shell`/`bash` → Bash、2.x 补丁工具 id/`apply_patch` →
ApplyPatch**;(c) the dsh `.ts` shim's handled-tool set (plus its dsh→guard name mapping,
including the tools admitted only through the dsh dialect: the bundled code runner, the
PowerShell tool, the terminal I/O tools, the job tools, and the patch-shaped editor) SHALL
cover every guard tool name reachable on dsh. Adding a guard decision branch without extending
all wiring faces SHALL fail the regression test (exit non-zero), structurally closing the
"dead branch" gap class on all three hosts — the claude matcher previously covered only
`Bash|Write|Edit`, leaving the read-side branches unconsulted (an out-of-tree `Read` reached
the host permission prompt and interrupted the run instead of failing loud with a recipe), and
nothing prevented the same drift on either host.

#### Scenario: matcher covers the full guard tool surface on fresh install

- **WHEN** `install.sh --claude <target>` 注入 PreToolUse hook
- **THEN** settings.json 的 matcher 含守卫全部分派工具名(`Bash|Write|Edit|MultiEdit|NotebookEdit|Read|Glob|Grep`)

#### Scenario: reinstall evolves a narrower legacy matcher in place

- **WHEN** 目标项目 settings.json 已有 `block_adhoc_scripts` 条目且 matcher 为旧的
  `Bash|Write|Edit`,重跑 `install.sh --claude`
- **THEN** 该条目的 matcher 被更新为全工具面默认值(按 command 内 `block_adhoc_scripts` marker 锚定,
  只改 matcher、不动用户自定义 command;用户自定义非子集 matcher 不动 + stderr 提示;幂等)

#### Scenario: CI fails when a guard branch lacks wiring coverage

- **WHEN** 守卫源新增一个分派工具名(如未来加 `WebFetch`),而 matcher、opencode shim `HANDLED`
  或 dsh shim 分派集任一端未同步扩
- **THEN** 接线覆盖回归测 fail(非零退出)——「新增分支忘扩接线面」从「静默死代码」变为 CI 拦截

#### Scenario: opencode 工具更代时两代 id 同时在收由 CI 强制

- **WHEN** opencode 2.x 更名某工具(bash→shell)且 shim 增补新 id 而删掉旧 id(或反之只留旧 id)
- **THEN** 接线覆盖回归测对 opencode 面断言「两代 id 并存收敛到同一守卫面」——删掉任一代 id
  即 fail(防止「升级断代」与「回退断代」两种静默漏收)

#### Scenario: out-of-tree Read is consulted by the guard on claude

- **WHEN** claude 会话处于 `mgh-init` 运行域(激活),模型 `Read` 一个越树路径(如 `..` 链折叠后落
  `D:\xxxx`)
- **THEN** PreToolUse hook 被触发(matcher 含 `Read`)→ 守卫退出码 2 → 工具调用被阻断、模型看到
  read-side recipe;**不出现**宿主 D 盘根权限询问(报告的中断形态消除)

### Requirement: dsh-exclusive bypass tools are confined by the guard

When any mgh run-domain is active, the guard SHALL treat the dsh-dialect execution surfaces as
bypass-capable and confine them with the same fail-loud posture as their claude/opencode
analogues: (a) the bundled code-runner tool (in-process Python execution, the direct analogue of
the blocked `py -c` inline-interpreter form) SHALL be denied with a recipe pointing to the
legitimate exit (running declared leaf scripts via the shell tool); (b) the PowerShell tool SHALL
be subject to the same verb-enumeration + path-token allowlist judgment as the `Bash` face,
including the redirect and destructive-delete rules; (c) terminal I/O and background-job tools
SHALL be denied inside an active run-domain (they would let a blocked foreground command
continue out-of-sight); (d) file-mutating use of the network-fetch tool SHALL be judged like a
Bash redirect target. Denials SHALL carry the guard's recipe on stderr so the host can surface
the reason to the model. These rules key on dsh-only tool ids and SHALL NOT alter any existing
claude/opencode judgment.

#### Scenario: bundled code runner denied inside run domain
- **WHEN** mgh 运行域激活,dsh 会话尝试经内置代码执行器运行任意 Python 片段(等价 `py -c` 内省)
- **THEN** 守卫退出码 2 + recipe(指向合法出口:经 shell 工具跑声明的叶脚本),该工具调用被宿主阻断

#### Scenario: PowerShell out-of-tree write denied
- **WHEN** mgh 运行域激活,dsh 会话经 PowerShell 工具向 `MGH_TARGET` 子树外路径写文件
  (如 `Set-Content D:\out\x`)
- **THEN** 同 Bash 写动词净网判定 → 退出码 2 + 允许集 recipe

#### Scenario: claude/opencode judgment unchanged
- **WHEN** 双端既有回归测全量运行
- **THEN** dsh 方言工具名不可能出现于双端 payload,既有判定与基线逐一一致(零 diff)

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

### Requirement: Bash directory-listing command confinement to the MGH_TARGET tree

When active with a pinned target, the guard SHALL block a `Bash` command whose **directory-listing
verb** (`ls`, `dir`, `Get-ChildItem`, `gci`, and any pwsh alias resolving to `Get-ChildItem` in
the guard's alias table) leads a simple command (as the FIRST token of the command body or of a
sub-command after a `;`/`|`/`&&`/`||` delimiter) with an **out-of-tree scope** — mirroring the
file-search rule's judgment: an explicit absolute-path argument resolving outside the
`MGH_TARGET` tree, or no explicit absolute path with the guard cwd outside the tree. A hit SHALL
fail-loud (exit 2) + the read-side recipe (`ls`/`dir` are read-side enumeration; the sanctioned
alternative is work-list primitives / `describe_artifact.py`). Scope resolution SHALL follow the
same semantics as the file-search rule (fold `..`, same `resolve()` + `is_relative_to(target)`
judgment, `--flag <path>` arguments on a NON-listing leading verb do NOT trip), including the
glob-form semantics of the path-token allowlist net: a token containing glob metacharacters
(`*`/`?`) is judged by its glob-free prefix, and a glob segment directly abutting a quote-closed
absolute path is joined with that path before judgment (in-tree join => pass; out-of-tree prefix
=> block). Detection SHALL
remain regex-over-observed-shape: pipes feeding a listing verb, aliases beyond the guard's table,
and relative-path listings are not guaranteed (same documented stance as the file-search rule).
Target absent => degrade to pass (mirror of the file-search rule).

#### Scenario: ls of an out-of-tree absolute path is blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=/adhome/u/gitlab_pab/proj/sub_proj`
  (sentinel or env), and the agent issues `ls /home` or `ls /adhome`
- **THEN** the guard finds the listing verb leading the command with an out-of-tree absolute-path
  scope, and blocks with exit 2 + the read-side recipe (previously passed — listing verbs were not
  in any read-side verb set)

#### Scenario: dir/Get-ChildItem with an out-of-tree scope is blocked

- **WHEN** the guard is active with a pinned target and the command is `Get-ChildItem D:\` or
  `dir ..\..` whose resolution climbs outside the target tree
- **THEN** the guard blocks with exit 2 + the read-side recipe

#### Scenario: in-tree listing passes

- **WHEN** the guard is active with `MGH_TARGET=D:\parent\sonA` and the agent issues
  `ls src/auth` or `Get-ChildItem D:\parent\sonA\docs`
- **THEN** the guard passes (exit 0); legitimate in-tree enumeration is unaffected

#### Scenario: listing verb with no path and cwd inside the tree passes

- **WHEN** the guard is active, the guard cwd is inside the target tree, and the command is a bare
  `ls` or `ls -la`
- **THEN** the guard passes (exit 0) — the implicit cwd scope is in-tree

#### Scenario: in-tree quoted path abutting a glob passes the listing rule

- **WHEN** an `mgh-sdr` run-domain is active with `MGH_TARGET=C:\DEV\springBootTemplate`, and the
  agent issues `ls "C:\DEV\springBootTemplate"/*.html` (the evidence false-positive shape: the
  closing quote ends the path token and the glob fragment used to be misread as a bare `/…`
  absolute path resolving to the drive root)
- **THEN** the guard joins the glob with its quoted in-tree prefix and passes (exit 0)

### Requirement: Bash interpreter script-execution confinement to the MGH_TARGET tree

When active with a pinned target, the guard SHALL block a `Bash` command that invokes an
**interpreter** (`py`, `py3`, `python`, `python3`, `python2`) leading a simple command (FIRST
token or after a delimiter) where the **first script-extension argument** (any `_SCRIPT_EXTS`
member) resolves **outside** the `MGH_TARGET` tree. The script path is judged at the
**positional-argument** face only — `--flag <path>` arguments (e.g. `--checkpoints <in-tree>`)
are NOT the executed script and SHALL NOT trip; a `py -c`/`py -m` body is NOT judged here (its
read/write shapes are already governed by the existing introspection/write-relabel rules) —
**该排除对带空格与粘连两种形态一律生效**:解释器名后出现 `-c` 或 `-m`(无论 `py -c "…"` 的空格形还是
`py-c` 粘连形)即非「执行脚本」形态,本规则 SHALL 退出,其后的 token(内联 body 的参数,如
`py -m pytest <树外 test_x.py>` 或 `py -c "…" <路径>`)SHALL NOT 被当作被执行脚本判定(修复前仅无空格
粘连形被负向前瞻排除,空格形下尾随 `.py` 参数被误当执行脚本拦截——误拦面,非漏拦面)。
This closes the bypass where `py /home/user/other/repo/script.py` (or any interpreter-run script
outside the project) executes while the no-launcher file-association rule passes it for carrying
an explicit interpreter prefix. A hit SHALL fail-loud (exit 2) + a recipe pointing at the
in-tree installed script path (`py .claude/mgh-core/scripts/<script>.py …`); in-tree interpreter
executions are unaffected. Target absent => degrade to pass.

#### Scenario: interpreter running an out-of-tree script is blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=/adhome/u/proj/sub_proj`, and the
  agent issues `py /home/someone/other/run.py` or `python3 ~/tools/scan.py`
- **THEN** the guard resolves the first script-extension argument outside the target tree and
  blocks with exit 2 + the interpreter-exec recipe (previously passed — the explicit launcher
  prefix exempted it from the file-association rule and no other rule judged the script location)

#### Scenario: interpreter running an in-tree script passes

- **WHEN** the guard is active with a pinned target and the command is
  `py .claude/mgh-core/scripts/resume_state.py --target .` (script arg resolves in-tree)
- **THEN** the guard passes (exit 0); all sanctioned deterministic-script invocations are
  unaffected

#### Scenario: --flag path arguments are not judged as the executed script

- **WHEN** the guard is active with a pinned target and the command is
  `py <target>/.mgh-core/scripts/list_clusters.py --clusters <in-tree>.json`
- **THEN** the guard judges the first positional script-extension argument (the script itself,
  in-tree) and passes — a `--flag <in-tree path>` never trips even though it names a path

#### Scenario: py -c bodies are not judged by this rule

- **WHEN** the guard is active with a pinned target and the command is
  `py -c "import json; open('/home/x/f.json').read()"`
- **THEN** this rule does not fire (no script-extension positional argument); the existing
  introspection rule blocks it with its own recipe

#### Scenario: trailing arguments after a spaced -m are not the executed script

- **WHEN** the guard is active with a pinned target, and the command is
  `py -m pytest D:\out\test_something.py`(模块调用,`.py` 是 pytest 的参数)或
  `py -c "import x" /home/x/helper.py`(内联 body 的数据参数)
- **THEN** this rule does not fire(修复前空格形 `-m`/`-c` 未被排除,尾随 `.py` 被误当执行脚本,
  树外即误拦;内省/写重标记规则照常拥有这些 body)
### Requirement: mgh-core missing-install detection stops all tasks

When active, the guard SHALL intercept a `Bash` command that references an installed mgh-core
script path (a path segment `mgh-core/scripts/` AND a script extension) whose resolved location
is **absent on disk** or **outside the `MGH_TARGET` tree**, and fail-loud (exit 2) with a
**stop-all recipe**: `mgh-core is not installed in this target — STOP ALL TASKS (do not
continue the run), report to the USER that mgh-init must be installed in the CURRENT project
directory (run install), and NEVER search other directories (parent project, /home, /adhome,
siblings) for scripts or prompts.` This encodes the observed multi-project failure shape: mgh-core
installed only in the root project while the run executes in an independent sub-project — scripts
404, and the model's natural response is cross-directory wandering. The rule SHALL fire on the
first such reference in any Bash command (the missing-install face is terminal for the run; there
is no sanctioned continuation). Non-script or non-mgh-core references are unaffected; the guard
SHALL NOT probe the filesystem beyond the referenced paths themselves.
**搜索动词的模式操作数豁免**:文件搜索动词(rg/ripgrep/grep/egrep/fgrep/findstr/find/fd/ag/ack)引导的
简单命令中,其**首个非旗标操作数**是搜索模式而非磁盘引用——`grep -n "mgh-core/scripts/run.py" notes.md`
的引号内字符串是 pattern,SHALL NOT 触发本规则(stop-all 是最重阻断,不得被字符串字面量误触);读动词
(cat/type/Get-Content/gc)的操作数是磁盘路径,照常判定(读侧不走此豁免)。

#### Scenario: mgh-core script referenced but not installed under the target is blocked with stop-all recipe

- **WHEN** mgh-core is installed only in the root project while the run's target is an
  independent sub-project (no `mgh-core/` anywhere under the target), and the agent issues
  `py .claude/mgh-core/scripts/resume_state.py --target .`
- **THEN** the guard resolves the referenced mgh-core script path, finds it absent (or outside the
  target), and blocks with exit 2 + the stop-all recipe (stop all tasks; ask the user to install
  in the current project directory; NEVER search other directories)

#### Scenario: installed mgh-core script reference passes

- **WHEN** mgh-core is installed under the target and the agent issues
  `py .claude/mgh-core/scripts/list_clusters.py …`
- **THEN** the guard passes (exit 0); the normal deterministic-script workflow is unaffected

#### Scenario: non-mgh-core missing paths do not trip this rule

- **WHEN** the guard is active and the command references an in-tree user script that happens not
  to exist (no `mgh-core/scripts` segment), or a project source file
- **THEN** this rule does not fire (existence of arbitrary non-product paths is the caller's
  concern, not the guard's)

#### Scenario: a search verb's pattern operand does not trip the stop-all rule

- **WHEN** the guard is active and the command is `grep -n "mgh-core/scripts/run.py" notes.md`
  (the quoted string is grep's PATTERN; notes.md is an in-tree operand)
- **THEN** this rule does not fire(修复前引号剥离后该字符串被当磁盘引用 → 解析缺失 → stop-all 误拦,
  最重阻断被字符串字面量触发);`notes.md` 等真实操作数照常由其它规则判定
### Requirement: sdr 域哨兵的确定性写入、存在性校验与重写

`mgh-sdr` 域哨兵 `<repo>/.mgh-sdr/.active` SHALL 由**确定性脚本副作用**写入,分**两级时序**:

- **step 0 预武装**:`resume_sdr_state.py --run-dir <abs> --repo <abs> --arm-sentinel` 在编排器首次
  调用 `sdr_context.py` **之前**写最小哨兵,JSON 为
  `{"domain":"mgh-sdr","target":"<--repo 绝对路径,Windows 原生>","out_roots":[],"read_roots":[],"v":1}`。
  幂等:哨兵已存在且 `target` 相同 → 逐字不变(NEVER 清空已被细化的 `read_roots[]`);`target` 不同 →
  退出码 2 + 报错(拒绝把守卫锚到第二棵树)。`--repo` 缺失且无法从 `<run-dir>` 布局推导 → 退出码 2 +
  recipe。
- **step 1 细化**:`sdr_context.py` 完成基线投影与外部仓检索后 co-write 完整哨兵,`read_roots[]` =
  实际检索过且存在为目录的根 ∪ 操作者 `--read-root` / `--approve-external` 确认后实际检索的根
  (最小化原则不变),SHALL NOT 透传任意路径。

两级均 SHALL NOT 依赖编排器读懂并执行 `Bash printf` 配方(脚本一跑哨兵必在)。

`mgh_sdr_launch.py` 保留的哨兵写入 SHALL 为**幂等刷新**(它在 spawn 宿主 CLI 之前,对已确认根再做一次
项目配置复核 + 并入操作者 `--read-root`,作为版本错配的第二道闸门),与 `sdr_context` 的 co-write 同语义、
同内容来源;两处均 SHALL NOT 写入未确认根。

`resume_sdr_state.py --check` SHALL 在「run 进行中而哨兵缺失」时 fail-loud:`context.json` 存在且
`step ∈ {group, fanout, render}`(已有工作产物、守卫却休眠 = 脚本只读 / 子树限定静默失效)而
`<repo>/.mgh-sdr/.active` 不存在 → 退出码 2 + re-arm recipe,NEVER 静默继续。`step == "done"`(run 已收尾)
时哨兵缺失 SHALL NOT 视为违例(守卫本就应当休眠)。`step == "not-started"`(尚无产物)时 SHALL 仅
advisory 披露,不作 gate;**预武装已发生而 `context.json` 未写出**(step 1 失败窗口)属该 advisory
分支的正常形态,`--check` SHALL NOT 因此失败。

`--rearm-sentinel` SHALL 据磁盘**确定性**重写该哨兵:`target` 取 `context.json::repo`,
`read_roots[]` 取 `context.json::external_repos[].path`(存在且为目录者),`domain` 恒为 `mgh-sdr`,
`out_roots` 为 `[]`;路径 SHALL 由 Python 叶脚本产出(Windows 原生形态),SHALL NOT 取自 shell 的 MSYS 形态
(`/c/…`)。重写 SHALL 幂等(同一磁盘状态 → 逐字相同文件)。`--arm-sentinel` 与 `--rearm-sentinel` 的
语义差异 SHALL 固定为:前者面向 run **起点**(空 `read_roots`、以 `--repo` 为 target 来源),后者面向
run **中途** re-arm(以 `context.json` 为唯一真相源);两者对同一磁盘状态 NEVER 产出互相覆盖冲突的
内容(起点覆盖中途不发生,中途重写在 context.json 缺失时退出码 2 + 指向 `--arm-sentinel`)。

#### Scenario: 预武装在 step 1 之前闭合失败窗口

- **WHEN** 编排器 step 0 执行 `resume_sdr_state.py --run-dir <abs> --repo <abs> --arm-sentinel`,随后
  首次 `sdr_context.py` 调用因未知 flag 在 argparse 即失败
- **THEN** `<repo>/.mgh-sdr/.active` 已存在(`read_roots:[]`、`target` 正确),守卫对该 run 目录树内的
  后续违规动作保持激活——此前该窗口守卫休眠

#### Scenario: sdr_context 跑完哨兵必在

- **WHEN** 编排器 step 0 预武装之后执行 `sdr_context.py --repo <abs> --run-dir <abs>`(无论经 launcher 还是经宿主会话)
- **THEN** `<repo>/.mgh-sdr/.active` 已存在,`domain="mgh-sdr"`、`target` 为 Windows 原生绝对路径、
  `read_roots[]` 为实际检索过的根;哨兵不依赖编排器执行任何 `printf` 配方

#### Scenario: 预武装幂等不覆盖已细化根

- **WHEN** step 1 已把 `read_roots[]` 细化为两个根后,编排器(压缩重入)再次执行同一 `--arm-sentinel`
- **THEN** 哨兵文件逐字不变,两个已声明根 NEVER 被清空

#### Scenario: 进行中缺哨兵即 fail-loud

- **WHEN** 某 sdr run 已有 `context.json` 与 `grouping.json`(step = fanout),但 `<repo>/.mgh-sdr/.active` 被误删
- **THEN** `resume_sdr_state.py --check --run-dir <abs>` 退出码 2,violations 载明「守卫休眠」+ re-arm recipe
  (`resume_sdr_state.py --rearm-sentinel --run-dir <abs>`);NEVER 静默继续

#### Scenario: 收尾后哨兵缺失非违例

- **WHEN** run 已收尾(`sdr_manifest.json` 在)、哨兵已在收尾步被移除
- **THEN** `--check` 退出码 0,无哨兵相关 violation

#### Scenario: re-arm 由磁盘确定性重写且幂等

- **WHEN** 对同一 run 目录连续两次执行 `--rearm-sentinel`
- **THEN** 两次写出的哨兵内容逐字相同;`target` / `read_roots[]` 全部由 Python 产出(无 MSYS `/c/…` 形态)

#### Scenario: re-arm 只认实际检索过的根

- **WHEN** `context.json::external_repos[]` 含两个根,其一在磁盘上已不存在
- **THEN** 重写后的 `read_roots[]` 只含仍然存在且为目录的那一个,NEVER 写入不存在的路径

#### Scenario: context.json 缺失时 rearm 指向 arm

- **WHEN** step 1 从未成功(`context.json` 不存在)而对某 run 目录执行 `--rearm-sentinel`
- **THEN** 退出码 2,stderr recipe 指明「run 未起步 → 用 `--arm-sentinel --repo <abs>` 预武装」,NEVER
  静默写出空 target 哨兵


### Requirement: Bash inline interpreter code blocked in all feeding forms (heredoc / here-string)

The guard's inline-code introspection judgment SHALL cover **every** form that feeds interpreter
code inline through a `Bash` command, not only the `-c` flag:

- interpreter token (`py`/`python`/`python2`/`python3`, start- or delimiter-bound) followed by
  `-c` (existing shape, unchanged);
- the same interpreter token followed by a **standalone `-`** argument (code on stdin — the
  heredoc shape `python3 - <<'EOF' … EOF`);
- the same interpreter token followed by a **here-string** (`- <<<` or `< <<` feeding stdin).

**解释器 token 的版本段 SHALL 覆盖带点形态**:`python3.11`/`python3.12`/`py3.13` 等带点(或多位)
版本号跟在 `py`/`python` 之后时,仍是同一个解释器 token——`python3.11 -c "<内省>"` 与
`python3.11 - <<'EOF'` SHALL 与无版本形态同判(修复前版本段正则不含点,带点版本绕过全部内省与
heredoc 检测)。

A hit SHALL fail-loud (exit 2) with the SAME sanctioned-primitive recipe as the `-c` shape (work
list / `describe_artifact.py --keys/--field` / producer stdout). The rule SHALL fire regardless
of whether the inline body contains introspection tokens in the heredoc form — an inline
interpreter body is ad-hoc processing by shape, and token sniffing inside heredoc payloads is
unreliable; for `-c` bodies the existing token-based discrimination is retained unchanged.
A command that merely runs a script whose stdout is piped into a **non-interpreter** consumer
(e.g. `py … | tail -5`) SHALL NOT trip this rule (piping per se is governed by the
redirect/temp-io rules). Both host faces share the single Python guard (opencode `.ts` shim
unchanged — it normalizes the event, never judges), so double-side parity is guaranteed by the
existing parity test contract; regression cases SHALL include the exact real-machine shapes
`python3 <script> --flags 2>/dev/null | python3 - <<'EOF'` and `py - <<<"$code"`.

#### Scenario: heredoc-fed introspection is blocked

- **WHEN** an mgh run-domain is active and the agent issues
  `python3 sdr_context.py --repo … | python3 - <<'EOF'\nimport sys,json; json.load(sys.stdin)\nEOF`
- **THEN** the guard blocks with exit 2 + the sanctioned-primitive recipe (previously the payload
  passed: the `-c` regex did not match a standalone `-`, so the model got negative reinforcement
  that "inline python works")

#### Scenario: here-string form is blocked

- **WHEN** the agent issues `py - <<<"import json; print(json.load(open('x.json')))"` inside an active
  run-domain
- **THEN** the guard blocks with exit 2 + the same recipe

#### Scenario: dotted-version interpreter token is covered

- **WHEN** the agent issues `python3.11 -c "import json; json.load(open('x.json'))"`(或
  `python3.12 - <<'EOF' …`)inside an active run-domain
- **THEN** the guard recognizes the interpreter token including its dotted version segment and
  blocks with exit 2 + the same recipe(修复前 `python3.11 -c` 绕过内省与 heredoc 检测)

#### Scenario: -c token discrimination unchanged

- **WHEN** the agent issues `py -c "print('hello')"` (no introspection tokens) inside an active
  run-domain
- **THEN** behavior is exactly as before this requirement (token-based rule unchanged; no new
  false positive on benign `-c` bodies)

#### Scenario: pipe to a shell utility is not an inline interpreter

- **WHEN** the agent issues `py <in-tree script> --summary | tail -5` inside an active run-domain
- **THEN** this rule does not fire (`tail` is not an interpreter receiving code); path-side rules
  still judge any path tokens as before

### Requirement: Guard payload 解码强制 UTF-8(与控制台代码页无关)

守卫读取 stdin payload SHALL 强制按 UTF-8 解码(`sys.stdin.buffer.read()` 后
`decode("utf-8", "replace")`),SHALL NOT 依赖 `sys.stdin` 的默认编码(随控制台/区域设置漂移——
中文 Windows 管道下为 cp936)。三端宿主(claude PreToolUse / opencode 插件 / dsh shim)发送的都是
UTF-8 字节;守卫按本地代码页解码会把 payload 解成乱码 → `cwd` 锚点损坏 → 哨兵向上发现失败 →
`domain is None` → **六域全部规则对该会话每次调用静默放行**(实机 A/B:同一份 UTF-8 字节,utf-8
stdin 下 exit 2 拦截、gbk stdin 下 exit 0)。解码出的 payload 仍不可解析(JSON 语法损坏)时维持既有
fail-soft(exit 0,never block);`replace` 降级只发生在 payload 本身非 UTF-8 的病态输入上
(此时锚点可能失效 → 休眠,如实披露为残余边界,优于按错误代码页静默错解)。

#### Scenario: GBK 控制台代码页下 UTF-8 payload 正确解码并拦截

- **WHEN** 中文 Windows 会话(管道编码 cp936)下,claude/dsh 面发来 UTF-8 编码的 payload
  (`cwd` 含中文用户名路径、命中运行域哨兵链),命令为应拦形态(如越树 Write)
- **THEN** 守卫按 UTF-8 解码 → 锚点正确 → 域激活 → exit 2 拦截 + recipe(修复前按 cp936 解码 →
  锚点乱码 → 哨兵未发现 → exit 0 静默放行——六域整场 run 无守卫)

#### Scenario: 无法解析的 payload 维持 fail-soft

- **WHEN** stdin 字节不是合法 JSON(空管道 / 截断)
- **THEN** 守卫 exit 0 不拦截(既有 fail-soft 语义不变;解码层修复不改变「无法检视 → 永不拦截」)

### Requirement: 哨兵发现与路径判定共用单一 cwd 源

守卫内**判定用 cwd**(`..` 相对 token 解析、listing/mutation 的 cwd 缺省锚、`Glob`/`Grep` 无 `path`
时的锚)SHALL 与**哨兵发现的锚**同源:payload `cwd` 字段(host 携带会话/工具上下文 cwd 时)优先,
回退守卫进程 cwd。SHALL NOT 判定走 `Path.cwd()` 而发现走 payload `cwd` 的双源形态——两源可错根
(claude 面 payload cwd = 发起调用的会话上下文,守卫进程 cwd 可在别处),错根时相对路径按错误根解析、
无 `path` 的读面按错误锚判定,产生系统性误判(该拦不拦 / 误拦)。payload `cwd` 存在但不可解析时回退
进程 cwd(NEVER 因锚不可用而崩溃)。**opencode 2.x 面**:插件随常驻服务进程运行,服务进程 cwd 与
被分析项目无关,shim SHALL 在 `setup` 时捕获 `ctx.location.directory`(项目根)并作为 payload
`cwd` 字段逐调用注入——「无 `cwd` 字段回退进程 cwd」不再是 opencode 面的依赖路径(claude/dsh 面
各自携带 cwd 的既有形态不变;进程 cwd 回退仅作最后兜底)。

#### Scenario: claude 面 payload cwd 同时驱动哨兵发现与相对 token 判定

- **WHEN** claude 面 payload 携带 `cwd=D:\parent\sonA\sub`(守卫进程 cwd 在别处),命令为
  `type ..\..\secret.txt` 且 `MGH_TARGET=D:\parent\sonA`
- **THEN** 守卫以 payload `cwd` 解析 `..` 相对 token(与哨兵发现同一锚)→ 落在树外 → exit 2 +
  recipe(修复前按进程 cwd 解析,错根时误判)

#### Scenario: opencode 2.x 插件注入项目根作锚

- **WHEN** opencode 2.x 常驻服务进程 cwd 在用户主目录,项目 `<项目>/.mgh-sdr/runs/…` 运行域哨兵
  在 `<项目>/.mgh-sdr/.active`,模型经 `shell` 工具发起含树外绝对路径的命令
- **THEN** shim 注入 payload `cwd=<项目根>` → 哨兵发现自项目根向上走链命中 `.active` → 守卫激活
  并以同一锚判定路径(修复前回退服务进程 cwd → 哨兵发现空转 → 守卫休眠)

#### Scenario: 无 payload cwd 的面回退进程 cwd(行为不变)

- **WHEN** 某面发来的 payload 无 `cwd` 字段(claude/dsh 均携带 cwd,此为兜底路径)
- **THEN** 判定与发现均以守卫进程 cwd 为锚(既有行为;单一来源,无双源错根面)
