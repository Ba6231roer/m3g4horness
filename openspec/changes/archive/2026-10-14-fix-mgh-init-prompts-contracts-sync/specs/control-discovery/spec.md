# fix-mgh-init-prompts-contracts-sync — control-discovery delta

## MODIFIED Requirements

### Requirement: Scoped and partial-merge analysis

`--scope path:<dir>|package:<pkg>|file:<glob>` SHALL 限定分析种子。`--scope-mode`
SHALL 区分:`defined`(默认,控制定义点在 scope 内)与 `applicable`(控制调用方/入口
触及 scope)。跨模块但定义点在 scope 外的控制 SHALL 记入 `out_of_scope[]`(披露不丢)。
`--merge` 模式 SHALL 被显式拒绝(无确定性合并实现):三面壳参数表 SHALL NOT 声明该 flag,
`write_runconfig.py` 对传入的 `--merge` SHALL 退出码 2 + 可操作 recipe(指认「无确定性合并
出口;多次局部运行产物独立,跨模块对照由人工/下游完成」),NEVER 静默吞参或路由到不存在的
合并脚本。多次局部(分模块)运行的产物 SHALL 各自独立落盘,跨模块对照由人工完成——编排器
SHALL NOT 即兴 LLM 合并 inventory(无 gate、无确定性去重)。

**scope 歧义输入 fail-loud**:`--scope path:<不存在路径>` 与 `--package:<无任何匹配目录>`
SHALL 退出码 2 + stderr recipe(指认路径/包名),NEVER 以「空种子集 + 退出码 0」静默成功——
拼错路径产出「该模块无存量控制」的**错误安全结论**(mgh-sast 侧丢全部 findings 同形态)。
「scope 目录存在但确无源文件」是合法空集:保持退出码 0 + 空集 note(与「路径不存在」
不可混淆的是二者 MUST 可区分)。

#### Scenario: Scoped run bounds to a module
- **WHEN** `mgh-init --scope path:src/payment --scope-mode defined`
- **THEN** 仅分析定义点在 `src/payment` 内的控制;跨模块控制入 `out_of_scope[]`

#### Scenario: Partial runs merge by evidence anchor
- **WHEN** 对模块 A、B 各跑一次局部 init(分模块多次运行形态)
- **THEN** 两次产物各自独立落盘(两份 candidates/clusters/inventory,互不覆写);不存在自动
  合并步骤(`--merge` 被拒绝),跨模块对照由人工完成;传 `--merge` 一律退出码 2 + recipe

#### Scenario: 拼错的 scope 路径 fail-loud 而非空集假成功

- **WHEN** `expand_scope.py --path src/paymant`(目录不存在,typo)运行
- **THEN** 退出码 2 + stderr 指认该路径;NEVER 输出 `{"in_scope": [], "count": 0}` + 退出码 0
  (修复前与「目录存在但无源文件」不可区分,下游产出「该模块无存量控制」的错误结论);
  `--package com.acme.nomatch`(零匹配目录)同判退出码 2;目录存在但无源文件保持 exit 0 + note

### Requirement: Persisted run configuration for stateless resume

`/mgh-init` 编排器 SHALL 在 step 0(参数解析后、花 token 前)原子写出
`<target>/.mgh-init/run_config.json`(`.tmp`+`os.replace`,承 "Discover writes are atomic"),记录**决定步骤图的本次
调用 flag**(`--merge` 除外——该模式被显式拒绝、不接受、不记录,见
「Scoped and partial-merge analysis」):`target`(绝对)、`format`、`scope`/`scope_mode`、`no_scout`、`no_codegraph`、`skip_consistency`、
`include_dotfiles`、以及 `--max-unit-bytes`/`--orch-budget-bytes`/`--max-aggregate-bytes`
预算与 `--scout-*` 参数。该文件是**起始态**意图记录,与既有**终态** `init_manifest.json`(版本/计数/出处)边界清晰、
互不替代。`resume_state.py` SHALL 消费 `run_config.json` 解析可选/codepath 分支。`run_config.json` 缺失或破损时,
`resume_state.py` SHALL fail-loud(退出码 2)+ stderr recipe(指向重跑 `/mgh-init --<flags>` 重建),MUST NOT 静默猜测
步骤图。该文件随 `.mgh-init/` gitignore(承既有 unit-inputs gitignore 约定)。

**崩溃恢复锚点的持久性(fsync)**:`write_runconfig.py` 的原子写 SHALL 在 `os.replace` 前对
tmp 文件 `flush` + `os.fsync`(run_config 与哨兵、gitignore co-write 同治)——仅 `os.replace`
的原子性不保证**内容**已落盘,掉电后可能出现「replace 完成、内容零长度」的 run_config,
恰好毒化崩溃恢复的唯一锚点。

**哨兵 domain 与位置单一来源**:`--init-dir` 显式传入且其基名为**规范运行目录名**
(`.mgh-init`/`.mgh-ut-init`)时,该位置承载的哨兵 domain SHALL 与目录名一致——与
`--run-root` 派生的域冲突的错组 → 退出码 2 + recipe(修复前显式错组如
`--init-dir <t>/.mgh-init --run-root .mgh-ut-init` 会把 mgh-ut-init 域的受信子树写进
mgh-init 的哨兵,激活错误域的写允许集);custom 名 `--init-dir` 保留既有「覆盖」旗标语义
(`--init-dir wins`,既有测试钉死);默认组合(不显式传参)行为零变化。

#### Scenario: Run config written atomically at start

- **WHEN** `/mgh-init --target <t> --format opencode --no-scout` runs and reaches step 0
- **THEN** `<t>/.mgh-init/run_config.json` is written atomically (no truncated half-write survives a mid-write kill) and
  records `format`/`no_scout`/absolute `target` verbatim from the invocation

#### Scenario: Resume consumes run config

- **WHEN** `resume_state.py` runs against a `.mgh-init/` whose `run_config.json` records `no_scout=true`
- **THEN** it reports the scout tier as skipped and never directs scout fan-out, matching the original invocation intent

#### Scenario: Missing run config fails loud, not silent

- **WHEN** `resume_state.py` runs and `run_config.json` is absent or unparseable
- **THEN** it exits code `2` with a stderr recipe telling the user to re-run `/mgh-init --<flags>` to rebuild it, rather
  than silently guessing a step graph that could diverge from the original intent

#### Scenario: 原子写内容经 fsync 持久

- **WHEN** 审阅 `write_runconfig.py` 的原子写实现并对一次正常 step 0 后的文件做崩溃恢复演练
- **THEN** tmp 写入后先 `flush` + `os.fsync` 再 `os.replace`(run_config/哨兵/gitignore 三处同治);
  掉电场景下 replace 完成则内容完整,NEVER 出现零长度 run_config

#### Scenario: 错组的 init-dir/run-root 被 fail-loud 拒识

- **WHEN** 调用 `write_runconfig.py --target <t> --init-dir <t>/.mgh-init --run-root .mgh-ut-init`
  (规范名目录与域来源冲突)
- **THEN** 退出码 2 + stderr recipe 指认冲突;NEVER 写出 domain=mgh-ut-init 而落在 .mgh-init
  的哨兵;custom 名 `--init-dir` 组合与默认组合行为不变

### Requirement: Re-entrant orchestrator resume state (disk as single source of truth)

`/mgh-init` SHALL provide a deterministic leaf script `core/scripts/resume_state.py` that, given a
`<target>/.mgh-init/` directory, derives the pipeline's **current step** and **exact next action** **purely from
on-disk artifacts + `.done` markers** — independent of any conversation / session memory. It is the single
sanctioned outlet for the orchestrator reflex "which step am I on / what do I do next" (replaces relying on
remembering progress across the 8-step flow). stdout = slim structured JSON
`{target, format, step, tiers{discover, scout, t1, t2, t3, t4 each {done, total}}, next_action{kind∈bash|subagent|done,
desc, absolute_paths}, resumable, notes[]}`; stderr = diagnostics/progress only; exit codes `0/1/2`.
`step` SHALL be one of `not-started|discover|survey|scout|resolve|t1|t2|t3|assemble|t4|done`, resolved by
probing product artifacts (`controls_candidates.json`/`clusters.json`/`scout_candidates.json`/`controls_inventory.json`/
rule files/`init_manifest.json`) and per-tier `.done` markers, **conditional on the persisted run config**
(see "Persisted run configuration for stateless resume") so optional/codepath branches
(`--no-scout`/`--no-codegraph`/`--skip-consistency`/survey-skipped/resolve-skipped) are honored
(`--merge` 不再是可持久化的 codepath——该模式在 step 0 即被拒绝,见「Scoped and partial-merge
analysis」)。
`next_action.absolute_paths` SHALL reuse the same `Path.resolve()` absolute values the `list_*`/`describe_artifact`
producers emit (承 "Fan-out checkpoint paths are deterministic absolute values"); the script MUST NOT invent paths or
template `<target>`. The script MUST be zero-runtime-dependency (承 R2), self-locate `sys.path`, read utf-8, run from
any cwd, and expose `--help` as its CLI contract (承 R5.1/R5.3). The orchestrator SHALL call `resume_state.py` as the
**first action** on `--resume` and **after any host context compaction** (claude `/compact` / opencode auto-compact),
and SHALL NOT determine "current step" from conversation memory.

#### Scenario: Fresh session resumes mid-T1 purely from disk

- **WHEN** a run halted with some `<target>/.mgh-init/checkpoints/t1/*.done` present but
  `controls_inventory.json` absent, and a **new session** runs
  `py <path>/resume_state.py --target <target>`
- **THEN** stdout `step` = `t1`, `tiers.t1` = `{total, done}` reflecting real `.done` count,
  `next_action.kind` = `subagent` with `desc` naming `init-induct` for the pending units and `absolute_paths`
  carrying the real `input_path`/`checkpoint_path` from `list_clusters.py`, `resumable` = true — and the orchestrator
  obtained this **without consulting any prior conversation memory**

#### Scenario: Run config makes resume stateless of re-typed flags

- **WHEN** the original invocation passed `--format opencode --no-scout` and then halted, and a fresh session runs
  `/mgh-init --resume` **without** re-passing `--format`/`--no-scout`
- **THEN** `resume_state.py` reads `<target>/.mgh-init/run_config.json`, reports `format` = `opencode` and the scout
  tier as skipped (not pending), and `next_action` respects `--no-scout` (it does NOT direct spawning scout readers)

#### Scenario: Completed run reports done

- **WHEN** all terminal artifacts exist (`controls_inventory.json` + rule/detail files + `init_manifest.json`) and the
  final tier `.done` markers are present
- **THEN** `resume_state.py` stdout `step` = `done`, `next_action.kind` = `done`, `resumable` = false

#### Scenario: --merge short-circuit reflected

- **WHEN** 磁盘上存在历史 run(本要求修订前产物)的 `run_config.json` 遗留 `mode` = `merge`
- **THEN** `resume_state.py` 仍按磁盘产物正常派生步骤图(`step` 词表已无 `merge`);新版 step 0
  对 `--merge` 一律退出码 2,该形态不再有新产出

#### Scenario: Scout-merge sub-step is not skipped on resume

- **WHEN** all scout batch `.done` markers exist but `scout_candidates.json` (and
  `checkpoints/scout/merge.json.done`) are absent — i.e. a prior, context-pressured session fanned out the scout
  readers but never ran `init-scout-merge`
- **THEN** `resume_state.py` stdout `step` = `scout` (NOT `t1`/`resolve`), `next_action.kind` = `subagent` naming
  `init-scout-merge` to produce `scout_candidates.json` first — preventing the orchestrator from skipping straight
  to `merge_scout.py` / T1 and hand-rolling a malformed aggregate (real-machine failure shape: orchestrator lost the
  step sequence, read `merge_scout.py` source to reverse-engineer the expected wrapper format, then fabricated it)

#### Scenario: resume_state is self-contained, offline, and contract-complete

- **WHEN** `py <path>/resume_state.py --target <dir>` is executed from an arbitrary cwd in an offline environment, and
  `py <path>/resume_state.py --help` is run
- **THEN** it succeeds (self-located `sys.path`, utf-8 read, zero third-party imports) emitting valid JSON; and `--help`
  prints a flag table whose flags the dual `mgh-init.md` shells mirror verbatim (承 R5.1)

#### Scenario: Orchestrator routes "where am I" to the sanctioned primitive

- **WHEN** the orchestrator (on `--resume` or post-compaction) needs to know the current step / next action
- **THEN** it calls `resume_state.py`, MUST NOT `py -c`/`python -c` introspect `.mgh-init/**`, MUST NOT `Read` whole
  aggregate JSON to reconstruct progress, and MUST NOT rely on remembered step state from conversation

### Requirement: Bounded single-pass scan performance on large repos

`discover_controls.py` SHALL 对每个源文件**至多读一次磁盘**(读入后缓存文本,供调用图两遍与候选
扫描共用);`walk_sources(repo)` 在单次运行中**只遍历一次**仓库并物化文件清单,供调用图构建与候选
扫描复用;每文件**仅调用一次 `splitlines()`**;候选的 enclosing 锚点 SHALL 通过**每文件预排序的
结构节点列表 + 按行二分**求解,而非「每候选对全文反复 `finditer`」。系统 SHALL 在扫描期间向
**stderr** 周期输出进度(每 N 个文件),stdout 仅在末尾输出既有 JSON 摘要(契约不变)。在 i0 阶段
SHALL 以低成本统计源文件数,命中大仓阈值时**在开始全量扫描前**主动建议 `--scope` 分模块(多次局部运行,产物独立披露)。

**文件配额只数源文件 + 截断显式上浮**:`walk_sources` 的 `limit_files` 配额 SHALL 仅对
**源扩展名文件**计数(`SOURCE_EXT` 命中者),非源文件(.txt/.xml/.sql/资产等)MUST NOT 消耗
配额;配额触顶时 SHALL stderr 告警并经可选 accumulator 形参(镜像 `dot_skipped`/`tests_skipped`
家族形态)向调用方上浮截断信号,NEVER 静默 return。理由〔配额被非源文件消耗时,大仓的截断
位置随枚举序不可预测;且 discover 侧的 `max_files+1` 截断哨兵(多 yield 一个源文件即判
truncated)建立在「配额只数源文件」的假设上——配额混计时哨兵永不触发,截断静默〕。

本要求**不再假设 discover 在单次宿主调用内必然完成**:当目标仓大到单次调用超过宿主 shell 超时
(claude Bash / opencode shell 工具默认 120s,可被强杀于更早),discover SHALL 经 callgraph 缓存 +
scan 续点 + 软时限干净早退(见「Discover call-graph cache survives re-runs」「Discover scan resumes
from a checkpoint」「Discover soft time-budget clean exit」「Discover writes are atomic」)**跨多次
编排器调用推进且零全损**,而非依赖「5 分钟内一发跑完」。

#### Scenario: Large repo completes across re-invocations without total loss
- **WHEN** 对一个单次调用即超过宿主 shell 超时的大目标仓运行 `/mgh-init`,且某次 discover 调用被宿主
  在超时处强杀
- **THEN** 已建成的 callgraph 缓存与 scan 续点**留存可用**,编排器 Bash 重派 `discover ... --resume`
  复用缓存、从续点继续,**不**从零重跑;经有限次重派后产物完整,期间**无**「`(no output)` 全损」形态

#### Scenario: Each source file read at most once
- **WHEN** 对任意目标仓运行发现脚本(单次调用内)
- **THEN** 每个源文件的磁盘读取次数为 1(调用图两遍与候选扫描共用同一缓存文本)

#### Scenario: Progress emitted to stderr only
- **WHEN** 扫描持续进行且尚未完成
- **THEN** stderr 周期性打印已扫描文件数;stdout 不在中途打印非 JSON 内容,末尾 JSON 摘要契约不变

#### Scenario: Large repo advised to scope before scanning
- **WHEN** i0 阶段统计的源文件数超过阈值
- **THEN** 系统在开始全量扫描前提示建议 `--scope` 分模块(多次局部运行,产物独立披露),而非静默跑到超时

#### Scenario: 非源文件不耗配额,触顶显式截断

- **WHEN** 一个仓含 2 万个 `.txt`/`.xml` 资产与 2 个 `.java` 源文件,以默认 `limit_files=20000`
  运行 `walk_sources`
- **THEN** 两个 `.java` 均被 yield(非源文件不耗配额);对一个真超配额的源文件仓,触顶时 stderr
  告警 + 调用方 accumulator 收到截断信号(修复前 `.txt` 先把配额吃完、`.java` 静默丢失且零信号)

#### Scenario: discover 截断哨兵在混合仓下如实触发

- **WHEN** 源文件数超过 `--max-files` 的仓运行 `discover_controls.py`
- **THEN** stdout 摘要 `truncated:true`(哨兵 = 多 yield 一个源文件即判);混合扩展名仓下配额
  语义同判(修复前配额被非源文件消耗,哨兵永不触发,截断静默)

### Requirement: Disclose scout coverage and residual blind spot

`init_manifest.json` SHALL 增 `scout` 段,记录:`skeleton_total`、`scout_targets`、
`batches`、`deep_read_files`、`audit_sampled`、`audit_found`、`scout_merged`(fold-in 实际并入
`controls_candidates.json` 的 scout 候选数,取值于 `merge_scout.py` 写入的
`provenance.scout_merged`;scout 未启用时该字段 SHALL 缺省/为空)、`truncated`(目标超预算时为真
并建议 `--scope`)。`report.md` 与 `init_manifest.json` 的 `boundaries[]` SHALL
新增披露:(1) scout 实际审视了 `skeleton_total` 中的多少、深度 Read 了多少、自检了多少
(**不声称全仓覆盖**);(2) scout 非确定,簇数 run-to-run 可能变化(regex 来源簇仍确定);
(3) 残留盲区——泛型包 + 泛型类名 + 泛型签名 + 无安全导入 + 低扇因的控制,规则与骨架均
无法识别,可能漏报。既有三条诚实边界(存在≠有效 / 调用图盲点 / 需人工复核)保持不变。

#### Scenario: Manifest reports real scout coverage numbers
- **WHEN** 一次含 scout 的运行完成
- **THEN** `init_manifest.json` 的 `scout` 段含可识别的真实计数字段(含 `scout_merged`),且不出现
  「全仓覆盖」之类断言

#### Scenario: Manifest omits scout_merged when scout disabled
- **WHEN** `--no-scout` 运行完成
- **THEN** `init_manifest.json` 的 `scout` 段不含 `scout_merged`(或为空),不声称 scout 并入量

#### Scenario: Residual blind spot is disclosed
- **WHEN** 审阅 `report.md` / `init_manifest.json` 的 `boundaries[]`
- **THEN** 其中明示「泛型命名 + 低扇因控制可能漏报」这一残留盲区,以及 scout 的非确定性

### Requirement: Fan-out waves run to completion without scale-driven user interruption

`/mgh-init` 的编排器(宿主 agent)SHALL 把每个 fan-out 波次跑到完成,且 MUST NOT 因规模大而中途停下征求用户拆分 / 跳过 / 终止。具体到 scout reader batches / T1 per-cluster induction / T3 per-category rule writing 任一波次:编排器迭代 `list_*` 的 `pending` 工作清单、以 `max_concurrent` 并发起 subagent、跑完一波起下一波,直至无 pending 单元剩余;规模大(数百至 ~1000 单元)本身 NEVER 构成停下征求的理由。规模与边界事实 SHALL 流入既有披露渠道——`init_manifest.json::boundaries[]`、`report.md`、`resume_state.py` `notes[]`——NEVER 作为运行中的阻塞式提问;披露所用计数 SHALL 自磁盘读取(`resume_state.py` / `list_*` stdout),NEVER 据对话记忆编造。

本要求**不改动**既有 **pre-run** 建议:i0 阶段统计源文件数命中 `--large-repo-threshold` 时、
**在花 token 之前**主动建议 `--scope` 分模块(多次局部运行,产物独立披露) 的行为(承「Bounded single-pass scan
performance on large repos」)保持不变。本要求的禁止范围仅限**运行已提交之后**(波次进行中)的
打断行为。

该指令 SHALL 以规范性措辞(RFC-2119 `MUST NOT`/`SHALL`)写入 claude-code 与 opencode 两份
`mgh-init.md`(逐字镜像),落在 fan-out / Re-entrancy & compaction 区。这是编排器对话行为约束
(非工具调用约束),runtime hook 管不到「agent 是否停下来问用户」;确定性可测部分 = 披露侧
(规模/边界进 `init_manifest.json`/`report.md`/`resume_state.py`,计数来自磁盘)。

#### Scenario: A large fan-out wave runs to completion without a blocking question

- **WHEN** 编排器进入一个 fan-out 波次,且该波次 `pending` 单元数很大(如 ~1000 个 scout batch),
  用户期望全面、稳定执行到底
- **THEN** 编排器迭代 `list_*` stdout `pending[]`、以 `max_concurrent` 并行跑完所有单元,**不**
  中途停下征求用户「是否拆分 / 跳过 / 终止」;波次跑到 `pending` 为空

#### Scenario: Scale and boundaries are disclosed, not asked

- **WHEN** 一个 fan-out 波次规模大或覆盖部分(含 `.failed`/跳过单元 / 残留盲区)
- **THEN** 规模与边界事实出现在 `init_manifest.json::boundaries[]` 和/或 `report.md` 和/或
  `resume_state.py` `notes[]`(计数自磁盘 `resume_state.py`/`list_*` stdout),且编排器**不**就
  规模提出运行中的阻塞式提问

#### Scenario: The pre-run scope advisory is preserved

- **WHEN** i0 阶段统计的源文件数超过 `--large-repo-threshold`,且尚未花 token 进入全量扫描
- **THEN** 系统在开始全量扫描前建议 `--scope` 分模块 + `--merge`(行为等价于本要求引入前);
  该 pre-token 建议不受「运行中不打断」指令影响

#### Scenario: Both shells declare the run-to-completion directive

- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-init.md` 的 fan-out / Re-entrancy & compaction 区
- **THEN** 两壳均含一条规范性措辞,声明编排器 MUST NOT 因规模在波次进行中停下征求拆分/跳过/终止、
  SHALL 把规模与边界流入既有披露渠道(双壳逐字镜像)

#### Scenario: Disclosed counts come from disk, not conversation memory

- **WHEN** 编排器在摘要/披露中陈述 fan-out 规模、失败数、跳过数或覆盖率
- **THEN** 这些计数取自 `resume_state.py` / `list_*` stdout 的结构化字段(磁盘真相),NEVER 据对话
  记忆编造

### Requirement: Subagent return-to-orchestrator is a bounded ack

每份 `core/prompts/stages/init-*.md` SHALL 声明一个 **Return-to-orchestrator** 契约:subagent 的**最终回传消息**
SHALL 是**单条有界 ack**——取值之一 `ok <绝对 checkpoint_path 或 rule_path> <count>`、`failed <简短原因>`(oversize
不是 ack 取值——超预算单元由枚举器以 `oversize` 标注 + recipe 处置,stage 提示词与 agent
定义 SHALL NOT 枚举 oversize ack;dispatcher 对历史 `oversize` 字样保持容错解析)(聚合 stage 的 ack 额外带 `total`/`merged` 计数)——且 **MUST NOT** 回显记录体、原始源码、或
检查点文件内容(治「subagent 回传随 fan-out 单调膨胀编排器上下文」,承审计发现:9 份提示词此前对回传消息集体沉默)。
该 ack 是**存活/成功信号**,非数据载体。编排器 SHALL 仅据 ack 判断该单元成败、并以 `.done` 标记 + `resume_state.py`
确认进度;MUST NOT 为「继续流水线」而内联 `Read` 检查点文件回编排器上下文。聚合节点(T2/scout-merge)的检查点文件
本身即全量聚合记录,编排器 SHALL 通过 `resume_state.py`/`describe_artifact.py` 的有界摘要接触之,NEVER 整份读回。
本要求同时写入双壳 `agents/init-*.md` 的 Hard-constraints 段(双重防线)。

#### Scenario: Each stage prompt declares the bounded ack contract

- **WHEN** 审阅 `core/prompts/stages/init-scout.md`/`init-induct.md`/`init-synthesis.md`/`init-scout-merge.md`/
  `init-survey.md`/`init-scout-audit.md`/`init-resolve.md`/`init-rules-consistency.md`
- **THEN** 每份含一个可识别的 Return-to-orchestrator 段,声明最终消息为单条有界 ack、NEVER 回显记录体/源码

#### Scenario: Orchestrator does not echo checkpoint content to continue

- **WHEN** 一个 init-induct subagent 完成并回传 `ok <abs path> <count>`,编排器进入下一单元
- **THEN** 编排器仅记 ack 为成功信号 + 探 `.done`;它 **不** `Read` 该 checkpoint 内联回上下文,也 **不** 把记录体
  透传给后续 subagent(后续 subagent 经自己的 `input_path` 自读)

#### Scenario: Aggregate checkpoint accessed via bounded summary, not inline read

- **WHEN** 编排器在 T2 完成后需要确认 inventory 落盘
- **THEN** 它经 `resume_state.py`(或 `describe_artifact.py --count/--keys`)取得有界摘要,**不** 整份 `Read`
  `controls_inventory.json` 进编排器上下文
