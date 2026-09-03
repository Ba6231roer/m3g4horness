# diff-test-quality-gate Specification

## Purpose

`/mgh-ut` 是第二纵向(测试质量)的 diff 测试质量门:对当前分支 vs 基线 diff 中**新增/改方法行为**的
单元,**无条件**做 ① 审计既有测试质量 + ② 补缺/增强 + ③ 变异硬化。定位为 openspec apply 之后、archive
之前的质量门(亦适用其它 SDD 工具流程与无 SDD 的普通 diff)。**变异硬化 = 生成时把 mutator 清单喂 LLM
写「足以杀死变异」的测试,不实跑 pitest**(决策 A);SDD spec 是**可选富化输入、非模式开关**(决策 Q3);
补缺产出**暂存 `.mgh-ut/proposals/`** 供人/apply 评审,`src/test` **不**被直写。运行时纪律属
`runtime-hook-enforcement` 第 6 域 `mgh-ut`。测试增强是 LLM 候选需人评,诚实边界须对用户披露。

## ADDED Requirements

### Requirement: Parse arguments and guard zero-token no-op

`/mgh-ut` SHALL accept `--target <dir>`(默认 `.`)、`--base <ref>`(基线,默认 `master`)、`--head <ref>`
(比较头,默认当前分支)、`--mutators <list|config-file>`、`--rules <path>`(ut-init rules,可选)、`--change
<name>`(未归档 openspec 变更名,可选)、`--out <path>`(proposals 输出根,默认 `<target>/.mgh-ut/proposals`)、
`--scope path:<dir>|package:<pkg>|file:<glob>`、`--resume`、`--skip-consistency`、请求上下文预算 flag。
当无 actionable 参数或传 `--help` 时 SHALL 仅打印参数表并 STOP(零 token 消费)。

#### Scenario: No actionable args prints flag table and stops
- **WHEN** 以无参或 `--help` 调用 `/mgh-ut`
- **THEN** 仅打印 flag 表并 STOP,不跑 git diff、不 spawn subagent、不产产物

#### Scenario: base/head defaults are master and current branch
- **WHEN** 未传 `--base`/`--head` 调用 `/mgh-ut`
- **THEN** `extract_diff_units.py` 以 `master` 为基线、当前分支为比较头产行为变更单元

### Requirement: Deterministic diff-unit extraction (behavioral change methods only)

`extract_diff_units.py` SHALL 用 Python ≥3.10 标准库(零运行时依赖,经 `git` 子进程驱动目标仓工具链)对
`<base>..<head>` 的 diff 产出**行为变更方法单元**,排除纯 cosmetic(空白/注释/import 重排)与
delete/move/rename。判定 SHALL 用确定性启发式:方法体 diff 的非空白/非注释字符超阈值(默认 >20 字符)即
为行为变更;方法级优先,codegraph 增强(缺席时降级到类/文件级)。脚本 SHALL 暴露 `--check`(边界校验,退出
码 0/2)。stdout = 结构化 JSON、stderr = 进度,退出码 0/1/2。

#### Scenario: behavioral change crosses threshold
- **WHEN** diff 中某方法体非空白/非注释字符变更超过阈值(如改动核心逻辑 30 字符)
- **THEN** `extract_diff_units.py` 产该方法的单元(含 `file`/`class`/`method`/`diff_hunks`/行为变更标记)

#### Scenario: cosmetic-only diff is excluded
- **WHEN** 某方法仅空白/注释/import 重排变更
- **THEN** 不产单元(不计为行为变更,不触发审计/补缺)

#### Scenario: delete/move/rename do not trigger
- **WHEN** diff 含方法删除 / 文件 move / rename
- **THEN** 不产测试工作单元(决策 E:只对新增/改方法行为做测试工作)

#### Scenario: extract --check validates boundary
- **WHEN** 运行 `extract_diff_units.py --check`
- **THEN** 校验输出单元 schema(file/class/method/diff_hunks)自洽;通过退出码 0,违例退出码 2

### Requirement: Unconditional per-unit audit with weak-test and mutator-lens signals

`/mgh-ut` SHALL 对每个行为变更单元**无条件**执行 `ut-audit` subagent:定位覆盖该方法的既有测试
(codegraph 符号引用 / 命名约定),审计既有测试质量(弱测试信号 + **mutator 透镜**:「flip 某运算符这测试
还会过吗」,复用 pitest mutator 分类法一物两用),产出 per-unit 审计 findings。审计 SHALL 覆盖:断言虚弱 /
有执行无验证 / 过度 Mock / Mock 不足(mock 协作者缺失 → 真实环境耦合)/ 仅 happy-path / 变异脆弱代理 /
模板复制。既有测试缺失时审计 SHALL 照常进行(报告「无覆盖」+ 直接进入补缺)。

#### Scenario: existing tests are audited for weak signals
- **WHEN** 某变更方法已有既有测试
- **THEN** `ut-audit` 逐信号审计既有测试,产 findings(弱信号逐条列出 + mutator 透镜打分)

#### Scenario: no covering test still triggers audit and gap-fill
- **WHEN** 某变更方法无既有测试
- **THEN** 审计报告「无覆盖」,流水线照常进入补缺(无条件审计 + 补缺,非模式开关)

### Requirement: Gap-fill generates mutator-killing test proposals staged for review

`/mgh-ut` SHALL 对每个行为变更单元执行 `ut-generate` subagent:据审计 findings + 测试约定 rules +
mutator 清单,生成**增强测试提案**(新测试 / 强化断言)以杀死已配 mutator + 覆盖分支。生成的测试 SHALL
**按发现的 mock 约定 mock 协作者**(DB / HTTP / 外部服务 / 静态依赖 / 时间等;硬要求),存量「mock 不全 /
不做 mock」既是弱信号也是本步**必须修正**项。补缺产出 SHALL **暂存 `<out>/<unit>.proposal.json` +
人读 `.md`**,`src/test` **不**被直写(LLM 候选需人评)。`--rules` 缺失时 SHALL 从 diff 邻近测试惰性发现
约定(优雅降级)。

#### Scenario: proposal is staged not written to src/test
- **WHEN** `ut-generate` 产出某变更单元的增强测试
- **THEN** 写 `.mgh-ut/proposals/<unit>.proposal.json` + `.md`,`src/test` 无任何写入(LLM 候选待评审)

#### Scenario: collaborators are mocked per discovered conventions
- **WHEN** 变更方法依赖 DB / HTTP / 外部服务 / 静态依赖 / 时间协作者
- **THEN** 提案中的测试按既有 mock 约定 mock 这些协作者,不遗留对真实外部系统的隐式耦合

#### Scenario: no ut-init rules degrades to lazy neighbor discovery
- **WHEN** 未传 `--rules` 且目标仓无 ut-init 产出 rules
- **THEN** `ut-generate` 从 diff 邻近 `*Test`/`*Spec` 惰性发现 mock/断言惯例,流水线不阻断,诚实边界披露

### Requirement: Optional SDD-spec enrichment (openspec-priority, MVP openspec-only)

`/mgh-ut` SHALL 在富化步骤读取**未归档 openspec change**(`--change <name>` 显式指定,缺省取最新未归档)
的 `proposal.md`/`design.md` 取需求意图,作为审计/补缺的可选上下文。无 openspec(或指定名称不存在)→
SHALL 跳过富化、按无 spec 路径继续(非模式开关)。MVP SHALL 仅适配 openspec;其它 SDD 工具适配器留后续。

#### Scenario: un-archived openspec change enriches the audit
- **WHEN** `--change <name>` 指定的未归档 openspec change 存在,且其方法行为有需求意图
- **THEN** `ut-audit`/`ut-generate` 读其 `proposal.md`/`design.md` 作为富化输入

#### Scenario: no openspec present continues without enrichment
- **WHEN** 无未归档 openspec change 或 `--change` 指定名称不存在
- **THEN** 富化跳过,审计 + 补缺照常(openspec spec 是可选富化、非模式开关)

### Requirement: Re-entrant resume on shared substrate with mgh-ut step graph

`/mgh-ut` SHALL 经 `resume_ut_state.py`(挂共享 `resume_core`,`--run-root` 默认 `.mgh-ut`)从磁盘
`<target>/.mgh-ut/` 重派生 `step`/`next_action`/`tiers`,纯磁盘驱动、不依赖对话记忆。mgh-ut 步骤图 SHALL =
**extract→audit→generate→consistency→done**。fan-out 单元(行为变更单元)「完成到可继续」= `done+failed>=total`;
`.failed` = 终态(`--resume` 跳过、不重派;崩溃无 ack → 仍 pending → 重派)。`run_config.json` 缺失/不可解析
→ 退出码 2 + recipe(NEVER 静默猜步骤图)。

#### Scenario: resume derives step purely from disk after compaction
- **WHEN** 压缩 / 崩溃 / 新会话后以 `--resume` 调用 `/mgh-ut`
- **THEN** 首步 `resume_ut_state.py --target <t>` 从磁盘重派生 `step`/`next_action`/`tiers`,不依赖对话记忆

#### Scenario: per-unit fan-out gate uses done+failed>=total
- **WHEN** audit / generate tier 部分单元完成、部分确认失败
- **THEN** 该 tier 完成门 = `done+failed>=total`;`.failed` 单元 resume 不重派,崩溃无 ack 单元仍 pending → 重派

#### Scenario: missing run_config fails loud with recipe
- **WHEN** `<target>/.mgh-ut/run_config.json` 缺失或不可解析
- **THEN** `resume_ut_state.py` 退出码 2 + recipe,NEVER 静默猜步骤图

### Requirement: Mutation hardening at generation time without running pitest

`/mgh-ut` SHALL 以 mutator 清单为生成约束(mutator 透镜一物两用):`ut-generate` 的提示词 SHALL 携带
mutator 清单,要求生成「足以杀死这些变异」的测试。`/mgh-ut` SHALL **不实跑 pitest**(决策 A):是否真杀死
变异不可知;实跑验证 = opt-in 路2,本版不实现,诚实边界须披露「设计上抗变异、非已验证杀死变异」。

#### Scenario: mutator list feeds generation as a constraint
- **WHEN** `ut-generate` 生成增强测试,且 mutator 清单含如 `CONDITIONALS_BOUNDARY`/`INVERT_NEGS`
- **THEN** 提示词携带清单,生成目标 = 覆盖对应变异点(flip 边界/取反后测试应失败)

#### Scenario: pitest is never executed
- **WHEN** 审阅 `/mgh-ut` 流水线(无 opt-in flag 时)
- **THEN** 无任何实跑 pitest 步骤;诚实边界披露「变异硬化是设计上抗变异,非已验证杀死变异」

### Requirement: Mutator list resolution priority chain

`/mgh-ut` SHALL 解析 mutator 清单按优先级:`--mutators <file-or-list>`(显式;内联逗号清单**或**配置文件
路径——以 `.json`/`.txt` 结尾判文件、否则判内联清单)> 目标仓 `<target>/.mgh-ut-init/default_mutators.json`
(ut-init 派生,`source:"pitest-config"` 或 `"builtin-fallback"`)> 内置 pitest 标准集。无任何清单时用内置
标准集 + 诚实边界披露。

#### Scenario: explicit --mutators wins
- **WHEN** 用户传 `--mutators CONDITIONALS_BOUNDARY,INVERT_NEGS`
- **THEN** 该清单用于生成约束,忽略 ut-init 派生清单

#### Scenario: ut-init-derived default is used when no override
- **WHEN** 未传 `--mutators`,且 `<target>/.mgh-ut-init/default_mutators.json` 存在
- **THEN** 取该清单(`source:"pitest-config"` 或 `"builtin-fallback"`)为默认生成约束

#### Scenario: builtin fallback with disclosure
- **WHEN** 无 `--mutators`、无 ut-init 派生清单
- **THEN** 用内置 pitest 标准集,诚实边界披露 fallback

### Requirement: Distributed purity and honest boundary disclosure

`/mgh-ut` 的 claude/opencode 壳 + ut stage subagent 提示词(`core/prompts/stages/ut-{audit,generate,consistency}.md`) SHALL 经 `tools/check_distributed_purity.py` 校验:不含研发铁律编号 / 失败或设计 ID / openspec 变更夹名 /
dev-meta 措辞 / 指本研发仓时的「本仓」;**保留**操作语义与产物路径(`--check`/退出码 2/`<target>/AGENTS.md`/
`.claude/mgh-core/scripts/*.py`/阶段标签)。每个对用户输出的总结 SHALL 披露诚实边界:**测试增强是 LLM 候选、
需人评**;补缺提案暂存 `.mgh-ut/proposals/`、`src/test` 不直写;**变异硬化是设计上抗变异、非已验证杀死
变异**(不实跑 pitest);行为变更判定是启发式(可能漏判 refactor / 误判 cosmetic);SDD 富化可选且 MVP 仅
openspec;JVM-only。

#### Scenario: mgh-ut shells and stage prompts pass distributed purity lint
- **WHEN** 运行 `tools/check_distributed_purity.py` 扫描 `mgh-ut` 壳 + `core/prompts/stages/ut-{audit,generate,consistency}.md`
- **THEN** 不含 `R5.x`/`FDn`/`Dn`/`(add|fix|harden|improve)-mgh-*` 变更夹名/`承 R5`/`范式锚点` 等 dev-meta;
  操作性语义(`--check`/退出码 2/`NEVER`/产物路径)保留

#### Scenario: honest boundaries disclosed in every summary
- **WHEN** 审阅 `/mgh-ut` 壳的 Always disclose 段 + 报告模板
- **THEN** 含:测试增强是 LLM 候选需人评 / 提案暂存 `.mgh-ut/proposals/` 不直写 `src/test` / 变异硬化是
  设计上抗变异非已验证杀死(不跑 pitest)/ 行为变更判定是启发式 / SDD 富化可选且 MVP 仅 openspec / JVM-only
