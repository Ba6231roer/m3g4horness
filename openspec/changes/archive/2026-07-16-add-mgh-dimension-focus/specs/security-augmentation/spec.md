## MODIFIED Requirements

### Requirement: Parse arguments and guard zero-token no-op

`/mgh-sra` SHALL accept `--change <name>`(默认取 `openspec/changes/` 下最新未归档变更)、`--rules <path>`(可选,指向 mgh-init 的 `controls_inventory.json` 或其输出目录)、`--focus <inline-json|path>`(可选,维度聚焦:收窄本次扫描的安全维度及维度内 facet;不传 = 全 9 维度,见 `dimension-focus` 能力)、`--no-interactive`(澄清问用默认猜测、不暂停问用户)、`--dry-run`(仅产 `change_context.json` + stdout 摘要,不写 specs/tasks/记忆)、`--skip-consistency`(跳过 a4)、`--config <profile>`(默认 `sra`)、`--no-codegraph`(opt-out 可选 codegraph 富化,默认 `auto` 检测)。当无 actionable 参数或传 `--help` 时,系统 MUST 仅打印参数表后**停止,不消耗 token、不做任何分析**。`--no-codegraph` 语义见「Detect optional codegraph index and gate enrichment (fail-soft)」:传该 flag 或检测到 codegraph 不可用时 MUST 完整回退到引入 codegraph 前的行为(零 codegraph 调用)。`--focus` 的闭集校验在确定性 a1 阶段完成(任何 LLM subagent 之前);校验失败(未知维度/facet、维度 facet 不匹配、空维度集)MUST 以退出码 2 fail-loud 早停,不消耗 token。

#### Scenario: Help / no actionable args
- **WHEN** 用户运行 `mgh-sra --help` 或不带任何参数
- **THEN** 系统打印参数表(含 `--focus`)后停止,零 LLM 调用、零变更解析

#### Scenario: Default change resolves to latest
- **WHEN** 用户运行 `mgh-sra` 不带 `--change`,且存在一个未归档变更
- **THEN** 系统取该最新变更作为目标;无任何未归档变更时报错并停止

#### Scenario: No-codegraph opt-out listed in help
- **WHEN** 用户运行 `mgh-sra --help`
- **THEN** 参数表含 `--no-codegraph` 且标注默认 `auto`(可用即启用)

#### Scenario: Focus flag listed in help
- **WHEN** 用户运行 `mgh-sra --help`
- **THEN** 参数表含 `--focus <inline-json|path>` 并标注默认 = 全 9 维度(不传不收窄)

### Requirement: Parse the openspec change deterministically

`prepare_augment.py` SHALL 用 Python ≥3.10 标准库解析目标变更的 `proposal.md` / `design.md` /
`specs/**/*.md` / `tasks.md`,产出结构化 `change_context.json`:含变更触及的 `capabilities[]`、
各 capability 的 `requirements[]`、现有 `tasks[]`、变更文本提及的 `mentioned_files[]`、可机械抽取
的业务面信号(`endpoints[]` / `data_fields[]` / `role_hints[]`)。`change_context.json` 落在
`<change-root>/.mgh-sra/`。当传入 `--focus` 时,`prepare_augment.py` SHALL 经 sibling import 调用
`focus_scope` 解析 + 闭集校验(见 `dimension-focus` 能力),并把解析后的 `focus`(`{dimensions[],
facets{}, directive}` 或 `null`)作为 `change_context.json` 的顶层新字段嵌入;`--focus` 缺省时
`focus` 为 `null`(行为与引入聚焦前逐字一致)。

#### Scenario: Capabilities and requirements extracted from delta specs
- **WHEN** 变更含 `specs/payment-api/spec.md`(`## ADDED Requirements` 下 2 条 `### Requirement:`)
- **THEN** `change_context.capabilities[]` 含 `payment-api`,其 `requirements[]` 含那 2 条

#### Scenario: Endpoints and data fields collected mechanically
- **WHEN** 变更 `tasks.md` 提及接口 `POST /api/transfer` 与字段 `bankCardNo`
- **THEN** `change_context.endpoints[]` 含该接口、`data_fields[]` 含该字段,供维度分析使用

#### Scenario: Change with no capability specs
- **WHEN** 变更仅有 `proposal.md` + `tasks.md`,无 `specs/**`
- **THEN** `change_context` 标 `capabilities: []`,增补回退到单个 `specs/security-augmentation/spec.md`

#### Scenario: Focus field embedded when --focus given
- **WHEN** `prepare_augment.py --change foo --focus '{"dimensions":["horizontal-authz"]}'`
- **THEN** `change_context.json` 的 `focus` 为解析后对象,含 `dimensions:["horizontal-authz"]` 与一条 `directive`;无 `--focus` 时 `focus` 为 `null`

### Requirement: Dimension-driven security gap analysis

`sra-augment` subagent SHALL 在每 capability 一个独立 LLM 上下文中,用安全维度目录
(`core/prompts/fragments/security-dimensions.md`:敏感数据 / 注入 / 横向越权·IDOR / 纵向越权 /
认证 / 完整性·关键操作 / 审计 / 限流·滥用 / 密钥·配置)对该 capability 的 requirements 与业务面
**逐维度**检查,产出**具体缺口**——每条缺口 MUST 锚定一条具体的变更 requirement / 接口 / 字段
(它保护什么),并标注 `dimension` 与风险简述。无锚定的泛泛 OWASP 清单式缺口 MUST 丢弃。当编排器
传入非空 `focus.directive` 时,`sra-augment` SHALL 仅对指令列出的维度(及维度内列出的 facet)查
缺口;范围外的维度**不产缺口**;范围内缺口的锚定 / 丢弃 / 三信号匹配 / codegraph advisory 规则
**不变**(见 `dimension-focus` 能力)。无指令(`focus: null`)时逐维度扫描全 9 维度,行为与引入聚焦
前逐字一致。

#### Scenario: Each dimension checked against the capability
- **WHEN** sra-augment 分析 `payment-api`(含「发起转账」requirement),且无 focus 收窄
- **THEN** 产出覆盖横向越权 / 敏感数据 / 完整性等维度的具体缺口,每条锚定到「发起转账」或相关字段

#### Scenario: Ungrounded boilerplate gap dropped
- **WHEN** sra-augment 试图产出一条不锚定任何 requirement / 接口 / 字段的泛泛「应防 SQL 注入」缺口
- **THEN** 该缺口被丢弃,不进入 draft

#### Scenario: Focus narrows emitted dimensions
- **WHEN** sra-augment 收到仅含 `horizontal-authz` + `vertical-authz` 的 focus 指令
- **THEN** draft `gaps[]` 仅含这两个维度;其余维度(敏感数据 / 注入 / ...)缺口不产出

#### Scenario: Focus facet filter narrows within a dimension
- **WHEN** sra-augment 收到 `sensitive-data` 收窄到 facet `[id-card, bank-card]` 的 focus 指令
- **THEN** 仅对身份证号 / 银行卡号字段产 sensitive-data 缺口;手机 / 邮箱 / 密码 / token 字段的 sensitive-data 缺口不产出

### Requirement: Boundary validation via --check (R5.9)

`prepare_augment.py`、`merge_augment.py`、`merge_memory.py` SHALL 各暴露 `--check` 边界校验:
`prepare_augment --check` 校验 inventory(若给)well-formed + `change_context` 结构完整 + `focus` 字段
(若存在)shape 合法(dimensions 闭集、facets 维度匹配且闭集、`null` 合法);`merge_augment --check`
校验合并仅动受管块、块外字节不变;`merge_memory --check` 校验记忆 shape + `fact_key` 无冲突。编排器
每步后 MUST 运行之;失败 MUST 以退出码 2 fail-loud 回退重跑,**不带着破损产物继续**。

#### Scenario: Malformed inventory fails intake check
- **WHEN** `--rules` 指向的 inventory 缺 `controls[]` 或条目无 `name/evidence`
- **THEN** `prepare_augment --check` 退出码 2,编排器回退(可 advisory 以无控制继续)

#### Scenario: Merge check confirms user content untouched
- **WHEN** a5 合并完成后运行 `merge_augment --check`
- **THEN** 校验通过(退出码 0)当且仅当受管块外的用户内容字节级未变

#### Scenario: Malformed focus field fails intake check
- **WHEN** `change_context.focus` 存在但含未知维度键或 facets 与维度不匹配
- **THEN** `prepare_augment --check` 退出码 2 并指明 focus 字段违例

### Requirement: Disclose honesty boundaries in manifest

`sra_manifest.json` MUST 明示边界:(1) 增补为 **LLM 候选,需人工复核**;(2) 覆盖**取决于变更声明
+ 已记业务事实**(未声明 / 未记的看不到);(3) 引用控制**断言存在不断言有效**(承 mgh-init
CVE-2025-41248);(4) 业务记忆为**用户断言非代码真相**。manifest 另记 `change`、`rules_source`、
`memory_source`、`focus`(本次聚焦的维度列表;`null` = 全 9 维度)、`counts{capabilities, gaps,
augmented_requirements, augmented_tasks, referenced_controls, clarifications_asked}`。当 `focus` 非
`null` 时,`boundaries[]` SHALL 增一条:**本次仅扫描聚焦维度,范围外维度未覆盖**(防用户误以为全量)。

#### Scenario: Manifest carries all boundaries
- **WHEN** 一次 sra 运行完成
- **THEN** `sra_manifest.json` 含上述四条边界声明的可识别字段与各项计数

#### Scenario: Manifest discloses focus scope
- **WHEN** 一次带 `--focus`(收窄到部分维度)的运行完成
- **THEN** `sra_manifest.json` 的 `focus` 为该维度列表,且 `boundaries[]` 含一条「本次仅扫描聚焦维度」的披露;无 `--focus` 时 `focus` 为 `null` 且无该额外边界
