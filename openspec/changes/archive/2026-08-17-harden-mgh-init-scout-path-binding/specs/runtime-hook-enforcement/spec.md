## MODIFIED Requirements

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
`{"domain":"mgh-<d>","target":"<abs target>","out_roots":["<abs>..."],"v":1}`, written by the
orchestrator at step 0 via `Bash` and removed at run completion / clean-stop. `MGH_TARGET` for the
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
- **THEN** step 0 含写 `<target>/.mgh-<domain>/.active` 的 Bash 步;run 完成 / 干净停止含移除该哨兵的步

#### Scenario: mgh-ut-init activates via env or sentinel as the fifth domain
- **WHEN** `MGH_UT_INIT_ACTIVE=1` env 已设,**或**锚起向上 walk 链上某级 `<dir>/.mgh-ut-init/.active` 哨兵存在
- **THEN** 守卫在 `mgh-ut-init` 运行域激活(第 5 域,与既有 4 域同机制);哨兵 `domain:"mgh-ut-init"`、run-root `.mgh-ut-init`

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

## ADDED Requirements

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
