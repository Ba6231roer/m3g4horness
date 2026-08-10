# test-convention-discovery Specification

## Purpose

`/mgh-ut-init` 从既有 JVM 测试源码树发现测试约定:按被测层分组分类测试文件(非逐文件 fan-out)、
对每层组抽样提炼测试约定(识别弱测试只标不删、不把弱模式当约定)、synthesize 产
`test_rules_inventory.json` 并做边界校验、按 `--format` 严格渲染 claude/opencode 两种结构不混的 rules
(含 provenance + 源码锚点)、确定性派生 pitest 默认 mutator 清单;全程经磁盘态 `--resume` 恢复
(ut 独立步骤图,init `resume_state.py` 零改动)。运行时纪律属 `runtime-hook-enforcement` 第 5 域
`mgh-ut-init`。rules 是 LLM 归纳候选(rules 是提示、非完备规约),诚实边界须对用户披露。

## Requirements

### Requirement: Parse arguments and guard zero-token no-op

`/mgh-ut-init` SHALL accept `--target <dir>`(默认 `.`)、`--format opencode|claude`(**必选**;缺失或非法 →
报错并 STOP)、`--out <path>`、`--rules-dir <path>`(opencode 详述文件目录,透传 `list_test_groups.py`/
`assemble_test_rules.py`)、`--scope path:<dir>|package:<pkg>|file:<glob>`、`--resume`、`--merge <partials-dir>`、
`--skip-consistency`、抽样预算 flag(`--uniform-sample`/`--hetero-sample`/`--subsplit-threshold`)、请求上下文
预算 flag(`--max-unit-bytes`/`--orch-budget-bytes`/`--max-aggregate-bytes`)。当无 actionable 参数或传
`--help` 时 SHALL 仅打印参数表并 STOP(零 token 消费)。ut-init **不**接受 `--language`(本版 JVM-only,无
下游消费者)或 `--config <profile>`(ut 是 LLM-first 流水线,无 profile 概念;`core/profiles/` 无 ut 条目)。

#### Scenario: No actionable args prints flag table and stops

- **WHEN** 以无参或 `--help` 调用 `/mgh-ut-init`
- **THEN** 仅打印 flag 表并 STOP,不扫描、不 spawn subagent、不产产物

#### Scenario: Missing required --format errors and stops

- **WHEN** 以 `--target .`(省略 `--format`)调用
- **THEN** 报错「`--format opencode|claude` 必选」并 STOP,退出码非 0,不产产物

### Requirement: Layer-group classification as the fan-out unit

`classify_tests.py` SHALL 用 Python ≥3.10 标准库(零运行时依赖)把 `<target>` 测试源码树的测试文件按
**被测层 / SUT 类型**分桶(controller / service / repository / config / util / …),作为 fan-out 单元
(**非逐文件**)。归类 SHALL 以**实际注解 + import + 包路径 + 文件名**综合判定,**不得**仅凭文件名猜。
当一组内检测到**混合子风格**(如 `@WebMvcTest` 切片与 `@SpringBootTest`+`TestRestTemplate` 全量共存)
SHALL **拆成不同子组**。该脚本 SHALL 输出每组的成员清单 + **均匀度提示**(同一种注解主导 = 均匀;
混杂 = 异质)+ 顺带的廉价质量提示(如组内断言密度),并暴露 `--check`(边界校验,退出码 0/2)。stdout =
结构化 JSON、stderr = 进度,退出码 0/1/2。

#### Scenario: classification groups by actual annotation/import not name alone

- **WHEN** 项目里 `FooControllerTest` 用 `@WebMvcTest`、`BarControllerTest` 用 `@SpringBootTest`
- **THEN** `classify_tests.py` 把两者分进**不同子组**(按检测到的注解,非按 `*ControllerTest` 名字合并)

#### Scenario: uniformity hint drives downstream sampling

- **WHEN** 某组由同一种注解主导(如全部 `@ExtendWith(MockitoExtension)`)
- **THEN** 该组标「均匀」;混杂组标「异质」,供抽样提炼按均匀度调样本数

#### Scenario: classify --check validates boundary

- **WHEN** 运行 `classify_tests.py --check <target>/.mgh-ut-init`
- **THEN** 校验每个测试文件归进且仅归进一个组、分组清单与磁盘文件一致;通过退出码 0,违例退出码 2

### Requirement: Sample-based per-group extraction flags weak tests, not learning them as house-style

`/mgh-ut-init` SHALL 对每个层组 fan-out 一个提炼 subagent:读该组的**代表性样本**(均匀组读少几个文件、
异质组读多一些或按子风格再分),提炼该层测试约定(框架 / mock / 断言 / 夹具 / 命名 / 依赖组件),产出
per-group 观察 JSON。提炼 SHALL **识别样本中的应付式弱测试**(零断言、同义反复断言、mock 被测对象本身、
只跑 happy-path、近重复模板等),**不把弱测试的模式当约定**;弱测试**只标记不删**;弱信号主导的约定 SHALL
标低置信。fan-out 工作清单 SHALL 经 `list_test_groups.py` 枚举(每项含样本物化输入路径 + 输出 checkpoint
路径,均绝对),编排器逐字透传、**禁手挖分组 JSON / `py -c`**。

#### Scenario: uniform group is sampled with few files

- **WHEN** 某组标「均匀」(如 30 个几乎复制的 ControllerTest)
- **THEN** 提炼 subagent 只读代表性少数样本(如 3–5 个),非全 30 个;约定从样本归纳

#### Scenario: weak tests are flagged and not promoted to conventions

- **WHEN** 样本中某测试被识别为弱测试(如零断言、`assertEquals(a,a)` 同义反复)
- **THEN** 该模式不进约定;弱测试在产物中标记(`weak:true` + 信号),**不修改/删除**被测源码

#### Scenario: weak-signal-dominated convention is marked low-confidence

- **WHEN** 某约定所归纳的样本多为弱测试
- **THEN** 该约定标低置信,并在产物 `boundaries[]` 披露「需人评」

### Requirement: Re-entrant resume on shared substrate with ut-specific step graph

ut-init SHALL 经 `resume_ut_init_state.py`(ut 步骤图副本,`--run-root` 默认 `.mgh-ut-init`)从磁盘
`<target>/.mgh-ut-init/` 重派生 `step`/`next_action`/`tiers`,纯磁盘驱动、不依赖对话记忆(把压缩 / 崩溃 /
新会话三种中断坍缩为「读磁盘状态 → 继续」一条恢复路径)。ut 步骤图 SHALL **含「归类」前置步骤**、
**无** init 的 codegraph 解析步骤;阻塞序列 = **classify→extract→synthesize→rules→assemble→consistency
→mutators→done**(与 `resume_ut_init_state.py` 步骤枚举逐字一致;`--skip-consistency` 时跳过 consistency)。
fan-out 层组「完成到可继续」= `done+failed>=total`;`.failed` = 终态(`--resume` 跳过、不重派;崩溃无 ack →
仍 pending → 重派)。`run_config.json` 缺失/不可解析 → 退出码 2 + recipe(NEVER 静默猜步骤图)。init 的
`resume_state.py` SHALL **零改动**(ut resume 是独立副本,隔离「恢复兜底」的爆炸半径)。`run_config.json`
持久化的抽样预算(`uniform_sample`/`hetero_sample`/`subsplit_threshold`)SHALL 由 `resume_ut_init_state.py`
回读,并在 extract tier 的 `next_action` 携带对应 `--sample-uniform`/`--sample-hetero` + 经 state `sampling`
字段透出——使 `--resume` **无需重输抽样 flag**(run_config 是起始态意图的唯一真相源,NEVER 静默回默认)。

#### Scenario: resume derives step purely from disk after compaction

- **WHEN** 压缩 / 崩溃 / 新会话后以 `--resume` 调用 `/mgh-ut-init`
- **THEN** 首步 `resume_ut_init_state.py --target <t>` 从磁盘重派生 `step`/`next_action`/`tiers`,不依赖对话
  记忆;据 stdout 继续 fan-out / 下一步

#### Scenario: ut step graph has classify prelude and no codegraph-resolve step

- **WHEN** 审阅 `resume_ut_init_state.py` 的步骤枚举与阻塞序列
- **THEN** 步骤集含「归类」前置步骤、不含 codegraph 解析步骤

#### Scenario: init resume_state.py is untouched

- **WHEN** 审阅 `core/scripts/resume_state.py`
- **THEN** 该脚本零改动(ut resume 在独立 `resume_ut_init_state.py`,init 的恢复兜底零回归)

#### Scenario: resume restores sampling budget from run_config

- **WHEN** 首跑 `--uniform-sample 8 --hetero-sample 16` 后中断,以 `--resume` 续跑且 extract tier 仍 pending
- **THEN** `resume_ut_init_state.py` 从 `run_config.json` 回读 uniform_sample=8/hetero_sample=16,extract
  `next_action` 携带 `--sample-uniform 8 --sample-hetero 16` + state `sampling` 透出;用户**无需**重输抽样
  flag(预算不静默回默认)

### Requirement: Synthesize-boundary inventory schema validation

`/mgh-ut-init` SHALL 在 synthesize 产 `test_rules_inventory.json` 后、rules fan-out 前,经
`validate_test_rules.py --inventory <path>`(该脚本本身即 synthesize 边界校验器,退出码 0 ok / 1 用法·IO /
2 违例;**无** `--check` 子模式)校验每条规则:含 `category`/`name`/`anchor`(指向具体文件/类/方法)/
`evidence`/`provenance`(从哪些层组样本归纳、强/弱信号计数)/`confidence`∈[0,1]/`weak_dominated` 布尔。
违例 → 退出码 2 fail-loud(回 ut-synthesize 重跑,**不**带着破损 inventory 进 rules);inventory 不可读/
非 JSON → 退出码 1。该校验是 R5.9 synthesize 边界门。

#### Scenario: valid inventory passes

- **WHEN** `test_rules_inventory.json` 每条规则字段齐全、`confidence`∈[0,1]、anchor 指向具体文件/类/方法
- **THEN** `validate_test_rules.py --inventory` 退出码 0,rules fan-out 继续

#### Scenario: broken inventory fails loud

- **WHEN** 某规则缺 anchor / `confidence` 越界 / provenance 缺失
- **THEN** `validate_test_rules.py --inventory` 退出码 2,回 ut-synthesize 修正后重跑(NEVER 带破损 inventory 继续)

### Requirement: Format-strict test-convention rules emission with provenance

`/mgh-ut-init` SHALL 按 `--format`(**必选**)渲染且仅渲染对应 Agent 的 rules 结构:claude
(`<target>/.claude/rules/test-*.md`)与 opencode(`<target>/AGENTS.md` 简洁惰性索引块 +
`<target>/docs/test-conventions/<cat>.md` 详述文件),**结构不混**。`assemble_test_rules.py` SHALL 组装
rules(opencode 建索引块 + 迁移旧块;双格式做纯净性 lint)并暴露 `--check`(fail-loud 退出码 2 = 规则
正文泄漏 ut 内部 token / 产物 schema 字段 / 过程散文 / 无源码锚点的约定)。每条 rule SHALL 指向**具体
文件/类/方法**(可索引)+ **provenance**(从哪个层组的哪些样本归纳、强/弱信号计数)。汇总阶段 SHALL 经
确定性脚本枚举的层组工作清单驱动(禁手挖聚合 JSON / `py -c`)。

#### Scenario: Claude format emits test-*.md rules only

- **WHEN** `--format claude` 完成汇总 + 组装
- **THEN** rules 仅落 `<target>/.claude/rules/test-*.md`,无 opencode 索引块;经 `assemble_test_rules.py --check`
  纯净 lint

#### Scenario: opencode format emits lazy index + detail files

- **WHEN** `--format opencode` 完成汇总 + 组装
- **THEN** `<target>/AGENTS.md` 含简洁惰性索引块,详述落 `<target>/docs/test-conventions/<cat>.md`;无 claude
  的 `.claude/rules/` 结构

#### Scenario: assemble --check fails loud on leaked internal tokens

- **WHEN** 某 rule 正文泄漏产物 schema 字段 / 工具内部 token / 无源码锚点约定
- **THEN** `assemble_test_rules.py --check` 退出码 2,回汇总修正后重跑

### Requirement: pitest mutator default derivation for downstream consumption

`/mgh-ut-init` SHALL 确定性派生 pitest 默认 mutator 清单到 `<target>/.mgh-ut-init/default_mutators.json`
(schema `{source, mutators[], parser_notes[]}`):解析 `<target>` 的 `pom.xml`/`build.gradle`/
`build.gradle.kts` 的 pitest 配置(`source:"pitest-config"`);**未发现 pitest 配置** → 用内置 pitest 标准
mutator 集(`source:"builtin-fallback"`)+ 在报告 / `boundaries[]` 披露「未发现 pitest 配置」。该清单 SHALL
作为后续 `/mgh-ut --mutators` 的默认消费口。

#### Scenario: pitest config present is parsed deterministically

- **WHEN** `<target>` 的 `pom.xml` 含 pitest-maven `<mutators>` 配置
- **THEN** `default_mutators.json` 的 `source:"pitest-config"`,`mutators[]` 取自解析的配置

#### Scenario: no pitest config falls back to builtin standard set

- **WHEN** `<target>` 无 pitest 配置
- **THEN** `default_mutators.json` 的 `source:"builtin-fallback"`,`mutators[]` = 内置标准集;
  `boundaries[]`/报告披露该 fallback

### Requirement: Distributed purity and honest boundary disclosure

`/mgh-ut-init` 的 claude/opencode 壳 + ut stage subagent 提示词(`core/prompts/stages/ut-*.md`)SHALL 经
`tools/check_distributed_purity.py`:不含研发铁律编号 / 失败或设计 ID / openspec 变更夹名 / dev-meta 措辞 /
指本研发仓时的「本仓」;**保留**操作语义与产物路径(`--check`/退出码 2/`<target>/AGENTS.md`/
`.claude/mgh-core/scripts/*.py`/阶段标签)。每个对用户输出的总结 SHALL 披露诚实边界:**rules 是 LLM 归纳
候选、是提示而非完备规约**(抽样提炼必有遗漏,后续 `/mgh-ut` 的 LLM 会自适应);弱信号测试标记不删;弱
信号主导约定需人评;pitest-config 派生 mutator 清单仅作默认;JVM-only。

#### Scenario: ut shells and stage prompts pass distributed purity lint

- **WHEN** 运行 `tools/check_distributed_purity.py` 扫描 ut-init 壳 + `core/prompts/stages/ut-*.md`
- **THEN** 不含 `R5.x`/`FDn`/`Dn`/`(add|fix|harden|improve)-mgh-*` 变更夹名/`承 R5`/`范式锚点` 等 dev-meta;
  操作性语义(`--check`/退出码 2/`NEVER`/产物路径)保留

#### Scenario: honest boundaries disclosed in every summary

- **WHEN** 审阅 `/mgh-ut-init` 壳的 Always disclose 段 + 报告模板
- **THEN** 含:rules 是提示非完备 / LLM 归纳候选需人评 / 弱信号测试标记不删 / mutator 清单仅默认 / JVM-only
