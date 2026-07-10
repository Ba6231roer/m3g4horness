# business-context-memory Specification

## Purpose

Project-level business context memory for the `/mgh-sra` workflow. Maintains a persistent,
structured record of business facts (roles, business domains, sensitive fields, interface
authorization patterns, business rules, clarification log) that accumulates across sra
iterations and survives across openspec changes. Memory is **user-asserted, not code truth** —
it supplements code declarations and proposal requirements as a matching hint, never overrides
them. Designed for cross-iteration reuse and to feed future `/mgh-blst` business-coupled
security test design.

## Requirements

### Requirement: Persistent project-level business context memory

系统 SHALL 维护一份**项目级**(位于 `<project>/.mgh-sra/business_context.json`,项目根 = 含
`openspec/` 的目录;**不在**任何变更内,跨变更存活)的结构化业务记忆,跨 sra 迭代累积。
记忆 SHALL 含(可逐步填充,非首跑必全):`roles[]`(角色 + 能力边界)、`domains[]`(业务域 →
代表接口,供业务域相似匹配)、`sensitive_fields[]`(业务定制必屏蔽字段 + 原因 + 屏蔽方式)、
`interface_authz[]`(已知接口 → 越权处理范式,直接答「以前类似接口怎么做」)、`business_rules[]`、
`clarifications[]`(问答日志)。每条记忆 SHALL 标 `source: user-asserted` 与 `fact_key`(幂等键)。

#### Scenario: Memory lives at project root and survives across changes
- **WHEN** 对项目 P 的变更 A 跑完 sra,随后对项目 P 的变更 B 再跑 sra
- **THEN** 变更 B 的 sra 读取同一份 `<project>/.mgh-sra/business_context.json`,含变更 A 沉淀的记忆

#### Scenario: First run starts with empty memory
- **WHEN** 项目首次运行 sra,无 `business_context.json`
- **THEN** sra 以空记忆起步,经澄清问答创建并填充该文件

### Requirement: Emit clarifications for business facts unresolvable from code

`sra-clarify` subagent SHALL 在单 LLM 上下文扫全变更,据安全维度目录识别「分析必需但
代码/proposal/inventory/记忆均判不出」的业务事实,产出结构化 `clarification`:每条含
`id`、`capability`、`dimension`、`question`、`why_it_matters`(为何影响安全分析)、
`default_guess`(默认猜测,可秒批)、`fact_key`(幂等键,决定是否已答)。clarifications SHALL
跨 capability 去重(如角色类问题跨接口只问一次)。

#### Scenario: Missing role knowledge surfaces as a clarification
- **WHEN** 横向越权分析需要「`POST /refund` 哪些角色用」,而代码/proposal/记忆均无
- **THEN** 产出一条 `clarification`(含默认猜测如「假设仅 `customer` 角色用」+ `fact_key`)

#### Scenario: Already-recorded fact is not re-asked
- **WHEN** 记忆已含 `fact_key: refund.roles` 的事实
- **THEN** sra-clarify 不再为该事实发澄清(幂等)

#### Scenario: Clarifications deduplicated across capabilities
- **WHEN** 3 个 capability 都需「系统有哪些角色」
- **THEN** 仅产出 1 条角色类澄清(跨类去重)

### Requirement: Batch-collect, pause, ask-once, resume interaction

编排器 SHALL 批量收集一轮分析的全部 `clarifications[]`,**一次性**呈现给用户(每条带
`default_guess`,用户可秒批 / 修改 / 跳过),记录答案,然后继续后续阶段。`--no-interactive`
SHALL 跳过暂停、直接用 `default_guess` 作为答案(产物标注「未确认·默认」)。记忆缺失或用户
跳过时,系统 MUST 以默认猜测 advisory 继续(**不阻断**)。

#### Scenario: Clarifications presented in one batch with defaults
- **WHEN** a2 产出 4 条澄清
- **THEN** 编排器暂停一次,一次性呈现 4 条(各带默认值),而非逐条打断

#### Scenario: --no-interactive skips the pause
- **WHEN** 用户运行 `mgh-sra --no-interactive` 且 a2 产出澄清
- **THEN** 编排器不暂停,以默认猜测填充记忆,继续 a3;产物标注这些事实为「未确认·默认」

#### Scenario: User skip does not block
- **WHEN** 用户对全部澄清选择跳过
- **THEN** 系统以默认猜测继续产增补(advisory),并在 manifest 披露「未确认业务事实数」

### Requirement: Idempotent memory accumulation by fact_key

`merge_memory.py` SHALL 把用户答案按 `fact_key` **幂等累积**进 `business_context.json`:已存在
`fact_key` 的事实原地更新(并记 `updated_at`/`source_change`),新 `fact_key` 追加。重跑同变更
不重复累积。`merge_memory --check` SHALL 校验记忆 shape 完整 + `fact_key` 无冲突(退出码 `0/1/2`)。

#### Scenario: Re-answered fact updates in place
- **WHEN** 用户对已存在的 `fact_key: refund.roles` 给了新答案
- **THEN** 该事实原地更新(非追加重复),并记录更新来源

#### Scenario: Re-run does not duplicate memory
- **WHEN** 对同一变更再次运行 sra 且澄清答案不变
- **THEN** `business_context.json` 不产生重复条目(`fact_key` 幂等)

### Requirement: Memory is user-asserted, not code truth

sra 匹配与增补时 SHALL 遵循优先级:**显式代码 / proposal 声明 > 用户记忆 > 默认猜测**。
记忆条目(标 `source: user-asserted`)MUST NOT 覆盖代码既有声明或 proposal 显式要求。当记忆与
代码冲突时,系统 SHALL 以代码为准,并在 manifest 披露冲突项。

#### Scenario: Code declaration overrides stale memory
- **WHEN** 记忆记某字段非敏感,但代码中该字段显式做了脱敏
- **THEN** sra 以代码为准(该字段敏感),并在 manifest 披露该冲突

#### Scenario: Memory used only as a hint for matching
- **WHEN** 记忆记某接口的角色边界
- **THEN** 该记忆作为信号-3 辅助匹配,推荐措辞标注「据已记业务事实」,非断言为代码真相

### Requirement: Cross-iteration reuse and downstream consumer contract

`business_context.json` SHALL 设计为可被后续 sra 迭代读取复用(累积越多,后续问得越少、业务域
匹配越准),并预留 `/mgh-blst` 消费口(`roles[]` / `interface_authz[]` / `sensitive_fields[]` 直接
喂业务耦合测试设计)。记忆 schema SHALL 含 `version` 字段以支持向前兼容校验。

#### Scenario: Subsequent iteration asks fewer questions
- **WHEN** 项目第 N 次跑 sra,记忆已累积角色 / 业务域 / 敏感字段
- **THEN** sra-clarify 产出的澄清数显著少于首次(已记事实不发问)

#### Scenario: Memory consumable by future mgh-blst
- **WHEN** 未来 `/mgh-blst` 设计越权测试
- **THEN** 它可读 `business_context.json` 的 `roles[]` / `interface_authz[]` 获取测试所需角色与既有越权范式
