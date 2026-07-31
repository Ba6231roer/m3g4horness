## ADDED Requirements

### Requirement: Re-entrant orchestrator resume state (disk as single source of truth)

`/mgh-init` SHALL provide a deterministic leaf script `core/scripts/resume_state.py` that, given a
`<target>/.mgh-init/` directory, derives the pipeline's **current step** and **exact next action** **purely from
on-disk artifacts + `.done` markers** — independent of any conversation / session memory. It is the single
sanctioned outlet for the orchestrator reflex "which step am I on / what do I do next" (replaces relying on
remembering progress across the 8-step flow). stdout = slim structured JSON
`{target, format, step, tiers{discover, scout, t1, t2, t3, t4 each {done, total}}, next_action{kind∈bash|subagent|done,
desc, absolute_paths}, resumable, notes[]}`; stderr = diagnostics/progress only; exit codes `0/1/2`.
`step` SHALL be one of `not-started|discover|survey|scout|resolve|t1|t2|t3|assemble|t4|merge|done`, resolved by
probing product artifacts (`controls_candidates.json`/`clusters.json`/`scout_candidates.json`/`controls_inventory.json`/
rule files/`init_manifest.json`) and per-tier `.done` markers, **conditional on the persisted run config**
(see "Persisted run configuration for stateless resume") so optional/codepath branches
(`--no-scout`/`--no-codegraph`/`--skip-consistency`/`--merge`/survey-skipped/resolve-skipped) are honored.
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

- **WHEN** `run_config.json` records `mode` = `merge`
- **THEN** `resume_state.py` stdout `step` = `merge` and `next_action` directs the `--merge <partials-dir>` flow
  rather than discover/scout/t1

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

### Requirement: Persisted run configuration for stateless resume

`/mgh-init` 编排器 SHALL 在 step 0(参数解析后、花 token 前)原子写出
`<target>/.mgh-init/run_config.json`(`.tmp`+`os.replace`,承 "Discover writes are atomic"),记录**决定步骤图的本次
调用 flag**:`target`(绝对)、`format`、`scope`/`scope_mode`、`no_scout`、`no_codegraph`、`skip_consistency`、
`merge`(及 `merge_partials_dir`)、`include_dotfiles`、以及 `--max-unit-bytes`/`--orch-budget-bytes`/`--max-aggregate-bytes`
预算与 `--scout-*` 参数。该文件是**起始态**意图记录,与既有**终态** `init_manifest.json`(版本/计数/出处)边界清晰、
互不替代。`resume_state.py` SHALL 消费 `run_config.json` 解析可选/codepath 分支。`run_config.json` 缺失或破损时,
`resume_state.py` SHALL fail-loud(退出码 2)+ stderr recipe(指向重跑 `/mgh-init --<flags>` 重建),MUST NOT 静默猜测
步骤图。该文件随 `.mgh-init/` gitignore(承既有 unit-inputs gitignore 约定)。

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

### Requirement: Subagent return-to-orchestrator is a bounded ack

每份 `core/prompts/stages/init-*.md` SHALL 声明一个 **Return-to-orchestrator** 契约:subagent 的**最终回传消息**
SHALL 是**单条有界 ack**——取值之一 `ok <绝对 checkpoint_path 或 rule_path> <count>`、`oversize <绝对 path>`、
`failed <简短原因>`(聚合 stage 的 ack 额外带 `total`/`merged` 计数)——且 **MUST NOT** 回显记录体、原始源码、或
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

### Requirement: Aggregate nodes enforce a hard request budget via map-reduce

T2(`init-synthesis`)与 scout-merge(`init-scout-merge`)SHALL 把 `--max-aggregate-bytes` 当作**硬闸门**(兑现
shell 既有「P0 软边界:T2/merge/T4 聚合节点目前为披露 + `--scope`/`--merge` 回退」的自认 TODO,把软边界升级为硬阈值)。
聚合输入(全部 T1 记录 / 全部 scout 批记录)≤ `--max-aggregate-bytes` 时,行为**逐字不变**(单一综合 subagent
上下文,承 "Isolated per-cluster induction with cross-cluster synthesis" / "Fan out scout across parallel isolated
byte-bounded batches" 的既有 single-context 综合语义)。聚合输入 **>** 预算时,SHALL 自动触发**两段 map-reduce**:
确定性叶脚本 `core/scripts/plan_aggregate.py` 把上一层记录(T2 按 `category` 分桶;scout-merge 按 batch 簇分桶)切成
**每桶 ≤ `--max-aggregate-bytes`** 的有界 shard 并物化 per-shard 输入;编排器为每 shard 扇出一个 **partial-synthesis
subagent**(有界输入、回传有界 ack),产出 per-shard 摘要 checkpoint;最后由**单一 rollup subagent** 仅吞**各 shard
摘要**(有界)产出终态产物(`controls_inventory.json` / `scout_candidates.json`)。**每个大模型请求 SHALL ≤ 预算**。
`plan_aggregate.py` SHALL 零依赖、自定位、utf-8、任意 cwd、stdout=JSON/stderr=诊断、退出码 `0/1/2`、`--help` 即契约
(承 R5.1/R5.3),并复用既有 `list_*` 的 `--materialize`/`--offset`/`--limit`/`--orch-budget-bytes` 翻页语义。降级触发
与 shard 数 SHALL 在 `init_manifest.json::boundaries[]` + `report.md` 披露(无静默溢出)。本要求在「超预算」时**取代**
既有 single-context 综合条款;≤ 预算(常见小仓)时既有条款逐字生效。

#### Scenario: Small repo keeps single-context synthesis unchanged

- **WHEN** 全部 T1 记录序列化字节 ≤ `--max-aggregate-bytes`
- **THEN** T2 仍为单一综合 subagent 上下文(无 shard、无 rollup),行为等价于引入本要求前

#### Scenario: Large repo triggers automatic map-reduce sharding

- **WHEN** 全部 T1 记录序列化字节 > `--max-aggregate-bytes`
- **THEN** `plan_aggregate.py` 按 `category` 切成多个每桶 ≤ 预算的 shard,编排器每 shard 一个 partial-synthesis
  subagent(有界输入),再一个 rollup subagent 仅吞各 shard 摘要;**每个大模型请求 ≤ 预算**

#### Scenario: scout-merge over budget uses batch-cluster shards

- **WHEN** 全部 scout 批记录 > `--max-aggregate-bytes`
- **THEN** `plan_aggregate.py` 按 batch 簇分桶,每桶一个 bounded partial-merge subagent,再 rollup;每请求有界

#### Scenario: Rollup operates on summaries only

- **WHEN** map-reduce 的 rollup subagent 运行
- **THEN** 其输入为各 shard 的**结构化摘要**(非原始 T1/scout 记录全集),上下文规模远小于任一 shard

#### Scenario: Reduction is disclosed, not silent

- **WHEN** 一次运行触发了聚合 map-reduce 降级
- **THEN** `init_manifest.json::boundaries[]` + `report.md` 记录触发节点、shard 数与每 shard 预算,不静默溢出

#### Scenario: plan_aggregate is self-contained, offline, and contract-complete

- **WHEN** `py <path>/plan_aggregate.py ...` 从任意 cwd、内网无网环境执行,且 `--help` 被运行
- **THEN** 脚本成功(零依赖、自定位、utf-8),stdout 为合法 JSON;`--help` flag 表被双壳 `mgh-init.md` 逐字镜像(承 R5.1)

### Requirement: Compaction-aware orchestration

两份 `mgh-init.md` 命令壳(claude + opencode)SHALL 新增一个 **Re-entrancy & compaction** 段,声明:(1) 所有可恢复
流水线状态(checkpoints / `.done` / 产物 JSON / `run_config.json`)都在磁盘 `<target>/.mgh-init/`,**对话记忆只是缓存、
不是进度真相源**;(2) claude `/compact` 与 opencode 自动压缩(~95% 触发)是**模型生成摘要**,**可能丢掉**命令壳灌入的
编排纪律系统提示词,故续跑 SHALL **NEVER** 依赖「记得自己在第几步」;(3) **`--resume` 与任何压缩事件后,编排器第一步
SHALL 调 `resume_state.py`** 从磁盘重派生 step + next_action;(4) 上下文吃紧时编排器 **MAY** **干净停止**(跑完当前
fan-out 波次、落 `.done`、不留下半截单元)→ **新 session `/mgh-init --resume` 续**,此路径**优于**人工 `/compact`(
后者摘要可能丢编排纪律导致执行路径偏离——直击用户痛点);(5) 既有 per-call `timeout` + discover `partial:true` +
`--resume` 纪律**保持不变**。该段 SHALL 用主谓措辞(SHALL/MAY)+ recipe 句式(承 R5.5①「该做什么」优先于禁令)。

#### Scenario: Shell declares disk-as-source-of-truth

- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-init.md`
- **THEN** 两壳均含可识别的 Re-entrancy & compaction 段,声明可恢复状态在磁盘、对话记忆非真相源、压缩是模型摘要可能丢提示词

#### Scenario: Resume / post-compaction first action is resume_state

- **WHEN** 编排器在 `--resume` 或一次自动/手动压缩后继续
- **THEN** 其第一步是调用 `resume_state.py` 重派生 step + next_action,而非依赖对话记忆判步骤

#### Scenario: Stop-cleanly-and-resume preferred over manual compact

- **WHEN** 审阅 Re-entrancy & compaction 段关于上下文吃紧的 recipe
- **THEN** 该段声明编排器 MAY 干净停止 + 新 session `/mgh-init --resume` 续,并指明此路径优于人工 `/compact`(因其可能丢编排纪律)

#### Scenario: Existing timeout / partial-resume discipline preserved

- **WHEN** 审阅该段与既有「Long-running deterministic Bash calls carry a per-call timeout」段
- **THEN** per-call `timeout` + discover `partial:true` + `--resume` 纪律保持不变,本段为 additive
