# security-augmentation Specification

## Purpose

Deterministic + agentic pipeline for the `/mgh-sra` command: parse an openspec change
deterministically, perform dimension-driven security gap analysis against each capability,
match gaps to existing mgh-init controls via three signals (dimension fit, business-domain
similarity, business fact), and merge augmentation requirements + tasks back into the change
non-destructively via managed sentinel blocks. Zero runtime dependencies, decoupled from
sibling command internals, with boundary validation (`--check`) at every step and honesty
boundaries disclosed in the manifest.
## Requirements
### Requirement: Parse arguments and guard zero-token no-op

`/mgh-sra` SHALL accept `--change <name>`(默认取 `openspec/changes/` 下最新未归档变更)、`--rules <path>`(可选,指向 mgh-init 的 `controls_inventory.json` 或其输出目录)、`--focus <inline-json|path>`(可选,维度聚焦:收窄本次扫描的安全维度及维度内 facet;不传 = 全 9 维度,见 `dimension-focus` 能力)、`--sensitive-catalog <inline-json|@path|->`(可选,公司强制脱敏目录:声明本次须逐项查脱敏缺口的必屏蔽字段类型 + 屏蔽级别 + 规则;不传 = 仅按现行 6 facet 识别敏感数据,见 `sensitive-catalog` 能力)、`--no-interactive`(澄清问用默认猜测、不暂停问用户)、`--dry-run`(仅产 `change_context.json` + stdout 摘要,不写 specs/tasks/记忆)、`--skip-consistency`(跳过 a4)、`--config <profile>`(默认 `sra`)、`--no-codegraph`(opt-out 可选 codegraph 富化,默认 `auto` 检测)。当无 actionable 参数或传 `--help` 时,系统 MUST 仅打印参数表后**停止,不消耗 token、不做任何分析**。`--no-codegraph` 语义见「Detect optional codegraph index and gate enrichment (fail-soft)」:传该 flag 或检测到 codegraph 不可用时 MUST 完整回退到引入 codegraph 前的行为(零 codegraph 调用)。`--focus` 与 `--sensitive-catalog` 的闭集校验均在确定性 a1 阶段完成(任何 LLM subagent 之前);校验失败(未知维度/facet、维度 facet 不匹配、空维度集;或未知 category、非法 mask、key/shape 不合法)MUST 以退出码 2 fail-loud 早停,不消耗 token。`--focus`(收窄本次扫描范围)与 `--sensitive-catalog`(声明必屏蔽策略、扩展 sensitive-data 识别)**正交**,可同时传。

#### Scenario: Help / no actionable args
- **WHEN** 用户运行 `mgh-sra --help` 或不带任何参数
- **THEN** 系统打印参数表(含 `--focus` 与 `--sensitive-catalog`)后停止,零 LLM 调用、零变更解析

#### Scenario: Default change resolves to latest
- **WHEN** 用户运行 `mgh-sra` 不带 `--change`,且存在一个未归档变更
- **THEN** 系统取该最新变更作为目标;无任何未归档变更时报错并停止

#### Scenario: No-codegraph opt-out listed in help
- **WHEN** 用户运行 `mgh-sra --help`
- **THEN** 参数表含 `--no-codegraph` 且标注默认 `auto`(可用即启用)

#### Scenario: Focus flag listed in help
- **WHEN** 用户运行 `mgh-sra --help`
- **THEN** 参数表含 `--focus <inline-json|path>` 并标注默认 = 全 9 维度(不传不收窄)

#### Scenario: Sensitive-catalog flag listed in help
- **WHEN** 用户运行 `mgh-sra --help`
- **THEN** 参数表含 `--sensitive-catalog <inline-json|@path|->` 并标注默认 = 不传则仅按现行 6 facet 识别敏感数据

#### Scenario: Focus and sensitive-catalog are orthogonal
- **WHEN** 用户同时传 `--focus '{"dimensions":["sensitive-data"]}'` 与 `--sensitive-catalog @.mgh-sra/sensitive_catalog.json`
- **THEN** 两者各自闭集校验通过后同时生效(focus 收窄到敏感数据维度,目录在该维度内逐项查脱敏缺口);无冲突

### Requirement: Parse the openspec change deterministically

`prepare_augment.py` SHALL 用 Python ≥3.10 标准库解析目标变更的 `proposal.md` / `design.md` /
`specs/**/*.md` / `tasks.md`,产出结构化 `change_context.json`:含变更触及的 `capabilities[]`、
各 capability 的 `requirements[]`、现有 `tasks[]`、变更文本提及的 `mentioned_files[]`、可机械抽取
的业务面信号(`endpoints[]` / `data_fields[]` / `role_hints[]`)。`change_context.json` 落在
`<change-root>/.mgh-sra/`。当传入 `--focus` 时,`prepare_augment.py` SHALL 经 sibling import 调用
`focus_scope` 解析 + 闭集校验(见 `dimension-focus` 能力),并把解析后的 `focus`(`{dimensions[],
facets{}, directive}` 或 `null`)作为 `change_context.json` 的顶层新字段嵌入;`--focus` 缺省时
`focus` 为 `null`(行为与引入聚焦前逐字一致)。当传入 `--sensitive-catalog` 时,`prepare_augment.py`
SHALL 经 sibling import 调用 `sensitive_catalog` 模块解析 + 闭集校验(见 `sensitive-catalog` 能力),
并把解析后的 `sensitive_catalog`(`{version, source, categories[], items[], counts{}, directive}` 或
`null`)作为 `change_context.json` 的顶层新字段嵌入;`--sensitive-catalog` 缺省时 `sensitive_catalog`
为 `null`(行为与引入目录前逐字一致)。

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

#### Scenario: Sensitive-catalog field embedded when flag given
- **WHEN** `prepare_augment.py --change foo --sensitive-catalog @.mgh-sra/sensitive_catalog.json`(含 37 项)
- **THEN** `change_context.json` 的 `sensitive_catalog` 为解析后对象,含去重排序的 `items[]`(37 项)+ `counts` + 一条 `directive`;无 `--sensitive-catalog` 时 `sensitive_catalog` 为 `null`

### Requirement: Zero runtime dependencies

`prepare_augment.py`、`merge_augment.py`、`merge_memory.py` 及所有新增脚本 MUST 仅用 Python 标准库
(`argparse/ast/collections/json/pathlib/re/sys` 同类)。MUST NOT `import` 任何 `vvaharness` 模块;
MUST NOT 要求任何 `pip install`。

#### Scenario: AST scan finds no third-party imports
- **WHEN** 对新增 `.py` 做 AST 扫描
- **THEN** 不存在非标准库 import,且无 `import vvaharness` / `from vvaharness import`

#### Scenario: Runs fully offline
- **WHEN** 在无网络内网环境对样例变更运行
- **THEN** a1 解析阶段正常产出 `change_context.json`

### Requirement: Dimension-fit pre-filter of candidate controls (signal-1)

当传入 `--rules` 时,`prepare_augment.py` SHALL 读取 mgh-init 的 `controls_inventory.json`,按
**安全维度契合**(信号-1)收窄候选:每控制标其能治的 `dimension(s)`(由 `category` 派生,如
`authorization`→{横向越权,纵向越权}),并标注其 `entry_points` / `protects` / `evidence` 与变更
`mentioned_files[]` 的文件重叠(相关性 hint)。`change_context.candidate_controls[]` SHALL 含每控制
的 `name/category/dimensions/entry_points/evidence` + 文件重叠 flag(供 D2 信号-2/3 语义匹配),
MUST NOT 硬切丢弃控制(只标维度 + 保留)。未传 `--rules` 时 `candidate_controls` 为空,系统继续做
**通用维度分析**。

#### Scenario: Control dimension tags derived from category
- **WHEN** inventory 一条 `category: authorization` 控制
- **THEN** 其 `dimensions` 含「横向越权·IDOR」「纵向越权」,供缺口匹配时信号-1 命中

#### Scenario: No rules degrades to dimension analysis without control matching
- **WHEN** 用户运行 `mgh-sra --change foo` 不带 `--rules`
- **THEN** `candidate_controls` 为空,系统仍逐维度查缺口产 requirements/tasks(缺口无控制锚点)

### Requirement: Enumerate per-capability augmentation jobs with absolute draft paths

`prepare_augment.py` SHALL 输出 `pending[]`(每 capability 一个增补工作单元),每项 MUST 含
`capability`、`draft_path`(绝对路径,`<change-root>/.mgh-sra/drafts/<cap>.md`,`Path.resolve()`)
与 `done_marker`。变更无 capability specs 时 `pending[]` 含单个整体增补单元。所有 draft 路径
MUST 落在 `MGH_TARGET`(项目根)子树内。

#### Scenario: Pending lists one job per capability with absolute draft path
- **WHEN** 变更触及 3 个 capability
- **THEN** `pending[]` 含 3 项,各自 `draft_path` 为绝对路径且位于 `<change-root>/.mgh-sra/drafts/`

#### Scenario: Draft path stays under the project subtree
- **WHEN** 编排器把 `draft_path` 透传给 subagent 写入
- **THEN** 该路径解析后位于 `MGH_TARGET`(项目根)子树内;漂出子树触发 hook 拦截(退出码 2)

### Requirement: Dimension-driven security gap analysis

`sra-augment` subagent SHALL 在每 capability 一个独立 LLM 上下文中,用安全维度目录
(`core/prompts/fragments/security-dimensions.md`:敏感数据 / 注入 / 横向越权·IDOR / 纵向越权 /
认证 / 完整性·关键操作 / 审计 / 限流·滥用 / 密钥·配置)对该 capability 的 requirements 与业务面
**逐维度**检查,产出**具体缺口**——每条缺口 MUST 锚定一条具体的变更 requirement / 接口 / 字段
(它保护什么),并标注 `dimension` 与风险简述。无锚定的泛泛 OWASP 清单式缺口 MUST 丢弃。当编排器
传入非空 `focus.directive` 时,`sra-augment` SHALL 仅对指令列出的维度(及维度内列出的 facet)查
缺口;范围外的维度**不产缺口**;范围内缺口的锚定 / 丢弃 / 三信号匹配 / codegraph advisory 规则
**不变**(见 `dimension-focus` 能力)。当编排器传入非空 `sensitive_catalog`(对象)时,`sra-augment`
SHALL 据 `items[]` 对每个字段类型逐项查脱敏缺口(据 `mask`+`rule` 判 at-rest/in-transit/log/response
是否按规则脱敏),缺口标 `catalog_key`,并经三信号匹配关联 mgh-init `data-masking` 控制(见
`sensitive-catalog` 能力);`--focus` 覆盖层与目录覆盖层叠加(focus 先收窄维度,目录仅在 sensitive-data
在范围内时生效)。`sensitive_catalog` 为 `null` 时仅按现行 6 facet 识别敏感数据。无 focus 指令
(`focus: null`)时逐维度扫描全 9 维度,行为与引入聚焦前逐字一致。

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

#### Scenario: Catalog drives per-item masking gaps
- **WHEN** sra-augment 收到含 `biometric/iris`(full)的 `sensitive_catalog`,capability 某接口返回虹膜特征未脱敏
- **THEN** 产出一条 sensitive-data 缺口锚定该接口/字段、标 `catalog_key:"biometric/iris"`;并当存在命中的 `data-masking` 控制时附 `recommended_control`

### Requirement: Three-signal semantic matching of gaps to existing controls

对每条缺口,`sra-augment` SHALL 用**三个信号**匹配该用的存量控制:(1) **维度契合**——控制 `dimensions` 含该缺口维度(必要条件);(2) **业务域相似**——控制 `entry_points`/`protects` 守护的是否为**同业务域类似接口**(据记忆 `domains[]` + 接口路径语义);(3) **业务事实**——该接口的角色 / 资源归属(据 `business_context.json`,缺失则该缺口触发澄清,见 `business-context-memory`)。匹配产物 = 推荐控制 + 其 `evidence`(`file:class:method`)+ 派生规则文件路径(claude `.claude/rules/security-<cat>.md` / opencode `AGENTS.md` 节)+ 「复用勿重造」措辞 + 业务域相似理由。无 `--rules` 时跳过匹配,缺口仅产「应满足的安全属性」requirement(无控制锚点)。三信号须同时命中才推荐;仅文件重叠(非业务域语义相似)MUST NOT 单独作为推荐依据。

当编排器信号 `codegraph=on` 时,每条**已命中三信号、已产出 `recommended_control`** 的推荐 SHALL 额外进行 **codegraph 结构证据确认**(见「Refine control-reuse recommendation via codegraph structural-evidence confirmation」):用 codegraph(call-path 首要,另含 data-flow 可达性 / 控制存活 liveness / domain-sibling 聚类三 advisory facet)把三信号语义判定里文本/AST 解不动的结构性问题补成 advisory 结构证据。**首要 facet(call-path)** 在 draft 的 `recommended_control.call_path` 记 `confirmed`/`path[]`/`source:"codegraph"`/`note`(advisory,不替代上述三信号,不覆盖代码 evidence);其余三 facet 以改善既有 `evidence`/`risk`/`reason` 的 advisory 形式体现,不新增 draft schema。`codegraph=off` 时本段行为与引入 codegraph 前逐字一致(无 call_path 字段、无 advisory 增强)。

#### Scenario: Gap matched to control via all three signals
- **WHEN** 缺口「`POST /refund` 横向越权」,存在 `category: authorization` 控制且其 `entry_points` 含同业务域的 `OrderController.cancel`,记忆记该域接口的归属模型
- **THEN** 推荐该控制(带 `evidence` + 业务域相似理由 + 角色锚点),措辞「复用,不得另起」

#### Scenario: File overlap alone is not a match
- **WHEN** 一条控制仅因 `protects` 文件路径与变更重叠,但守护的是**不同业务域**接口
- **THEN** 该控制不被推荐(文件重叠非充分条件)

#### Scenario: Missing business fact triggers clarification
- **WHEN** 缺口匹配需要「该接口哪些角色用」,而代码/proposal/inventory/记忆均无
- **THEN** 该缺口产出推荐的同时触发一条澄清(详见 `business-context-memory` 能力),暂以默认猜测标注

#### Scenario: Call-path confirmation is advisory and codegraph-gated
- **WHEN** `codegraph=on` 且某缺口的推荐控制已三信号命中
- **THEN** `sra-augment` 在该推荐的 `call_path` 记结构确认结果(advisory);`codegraph=off` 时该字段缺省,三信号匹配主流程不受影响

#### Scenario: Off behaves identically to pre-codegraph
- **WHEN** `codegraph=off` 运行 sra-augment
- **THEN** 三信号匹配的工具使用与产出与引入 codegraph 前逐字一致(无 codegraph 调用、无 call_path 字段)

### Requirement: Non-destructive idempotent merge into change specs and tasks

`merge_augment.py` SHALL 把增补以哨兵受管块 `<!-- mgh-sra:begin --> … <!-- mgh-sra:end -->`
**追加**进变更的 `specs/<cap>/spec.md`(在 `## ADDED Requirements` 下追加 `### Requirement:`
条目)与 `tasks.md`(追加安全 task 条目)。MUST NOT 重写、删除或改动受管块**之外**的用户内容。
重跑(幂等)SHALL 仅原地替换受管块,保留块外内容字节级不变。变更无 capability specs 时 SHALL
创建单个 `specs/security-augmentation/spec.md`。所有写入 MUST 落在 `MGH_TARGET`(项目根)子树内。

#### Scenario: Managed block appended, user content preserved
- **WHEN** 变更 `specs/payment-api/spec.md` 已有用户手写的 2 条 requirement
- **THEN** 合并后该文件保留原 2 条字节不变,仅追加一个 `<!-- mgh-sra:begin -->` 受管块

#### Scenario: Re-run is idempotent
- **WHEN** 对同一变更再次运行 `mgh-sra`
- **THEN** 受管块被原地替换(不重复追加),块外内容不变

### Requirement: Decouple from sibling command internals

sra 的脚本 MUST NOT `import` sast 的 `load_controls.py` 或 init 的 `validate_inventory.py`。
读取 `controls_inventory.json` SHALL 由 `prepare_augment.py` 自持轻量实现(`json.load` + 最小
shape 校验)。sra 与兄弟命令之间无运行时反向依赖。

#### Scenario: No cross-command import
- **WHEN** 对 sra 新增脚本做 AST 扫描
- **THEN** 不存在 `from load_controls import` / `from validate_inventory import` 等兄弟命令内部 import

### Requirement: Boundary validation via --check (R5.9)

`prepare_augment.py`、`merge_augment.py`、`merge_memory.py` SHALL 各暴露 `--check` 边界校验:
`prepare_augment --check` 校验 inventory(若给)well-formed + `change_context` 结构完整 + `focus` 字段
(若存在)shape 合法(dimensions 闭集、facets 维度匹配且闭集、`null` 合法)+ `sensitive_catalog` 字段
(若存在)shape 合法(items[] 各项 category 闭集、mask 枚举、key/label 合法、`null` 合法);`merge_augment --check`
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

#### Scenario: Malformed sensitive-catalog field fails intake check
- **WHEN** `change_context.sensitive_catalog` 存在但某项 category 不在闭集 10 类、或 `mask` 非 `full`/`partial`、或 key/label 不合法
- **THEN** `prepare_augment --check` 退出码 2 并指明 sensitive_catalog 字段违例

### Requirement: Disclose honesty boundaries in manifest

`sra_manifest.json` MUST 明示边界:(1) 增补为 **LLM 候选,需人工复核**;(2) 覆盖**取决于变更声明
+ 已记业务事实**(未声明 / 未记的看不到);(3) 引用控制**断言存在不断言有效**(承 mgh-init
CVE-2025-41248);(4) 业务记忆为**用户断言非代码真相**。manifest 另记 `change`、`rules_source`、
`memory_source`、`focus`(本次聚焦的维度列表;`null` = 全 9 维度)、`sensitive_catalog`(本次生效目录的
`counts{items, full, partial, categories}` + `source`;`null` = 未用目录,仅 6 facet)、`counts{capabilities, gaps,
augmented_requirements, augmented_tasks, referenced_controls, clarifications_asked}`。当 `focus` 非
`null` 时,`boundaries[]` SHALL 增一条:**本次仅扫描聚焦维度,范围外维度未覆盖**。当 `sensitive_catalog`
非 `null` 时,`boundaries[]` SHALL 增一条:**本次据公司敏感数据目录逐项查脱敏,目录外字段类型仅按现行
6 facet 识别**(防用户误以为目录穷尽所有敏感字段)。

#### Scenario: Manifest carries all boundaries
- **WHEN** 一次 sra 运行完成
- **THEN** `sra_manifest.json` 含上述四条边界声明的可识别字段与各项计数

#### Scenario: Manifest discloses focus scope
- **WHEN** 一次带 `--focus`(收窄到部分维度)的运行完成
- **THEN** `sra_manifest.json` 的 `focus` 为该维度列表,且 `boundaries[]` 含一条「本次仅扫描聚焦维度」的披露;无 `--focus` 时 `focus` 为 `null` 且无该额外边界

#### Scenario: Manifest discloses sensitive-catalog coverage
- **WHEN** 一次带 `--sensitive-catalog`(37 项)的运行完成
- **THEN** `sra_manifest.json` 的 `sensitive_catalog` 含 `counts{items:37,...}` + `source`,且 `boundaries[]` 含一条「据目录逐项查脱敏,目录外仅 6 facet」的披露;无 `--sensitive-catalog` 时 `sensitive_catalog` 为 `null` 且无该额外边界

### Requirement: Detect optional codegraph index and gate enrichment (fail-soft)

`/mgh-sra` 编排器 SHALL 在 a1(`prepare_augment`)完成后、发起任何 LLM subagent 之前,以 Bash 检测目标项目是否具备 codegraph:`test -d <MGH_TARGET>/.codegraph` **且** `command -v codegraph`(二者皆真才视为可用;`<MGH_TARGET>` 取 a1 stdout 的 `project_root`,编排器已 `export`)。检测结果 SHALL 作为 `codegraph=on|off` 信号逐字透传进后续 sra-clarify / sra-augment subagent task 输入。codegraph 富化 SHALL 默认 `auto`(可用即启用);SHALL 提供 `--no-codegraph` opt-out(语义对齐既有 `--rules`/`--skip-consistency` 可选 flag),传该 flag 或检测为不可用时 MUST 完整回退到引入 codegraph 前的行为(零 codegraph 调用)。检测 MUST NOT 引入任何 `pip` 依赖或对 codegraph 的 Python `import`(codegraph 是宿主 MCP 工具 / 外部 CLI,非运行时依赖,承 R2)。`--help` / 无 actionable 参数的零 token 早停行为保持不变;检测本身不消耗 LLM token。

#### Scenario: Index present enables enrichment
- **WHEN** 目标项目根存在 `.codegraph/` 且 PATH 上有 `codegraph`,未传 `--no-codegraph`
- **THEN** 编排器置 `codegraph=on` 并把该信号透传给 sra-clarify/sra-augment subagent

#### Scenario: Index absent falls back to legacy behavior
- **WHEN** 目标项目无 `.codegraph/`(或 PATH 无 `codegraph`)
- **THEN** 编排器置 `codegraph=off`,全流程不发起任何 codegraph 调用,行为等价于引入 codegraph 前

#### Scenario: Opt-out flag forces legacy behavior
- **WHEN** 运行 `mgh-sra --no-codegraph`(即使 `.codegraph/` 存在)
- **THEN** codegraph 富化(外科式上下文 + call_path 确认 + a2 callers 预解析)均不执行,行为等价于引入 codegraph 前

#### Scenario: Detection introduces no runtime dependency
- **WHEN** 对本变更新增/改动的任何 `.md` 或既有 `.py` 做 AST/文本扫描
- **THEN** 不存在 `import codegraph` 或对 codegraph 的 Python 运行时依赖;codegraph 仅经 MCP/Bash 消费

#### Scenario: Detection runs before any LLM subagent
- **WHEN** 编排器完成 a1 prepare
- **THEN** 它先完成 codegraph 检测并透传信号,**之后**才 spawn sra-clarify(检测本身零 LLM token)

### Requirement: Optional codegraph context backend for sra-clarify/sra-augment subagents

当编排器信号 `codegraph=on` 时,`sra-clarify` / `sra-augment` subagent **SHALL 优先**用 MCP `codegraph_explore`(主)/ CLI `codegraph explore`(Bash,回退)取得目标符号的**逐字源码 + 调用路径 + blast radius**,**仅**对 codegraph 未覆盖项(非索引语言、超 `--big-file-bytes` 的文件、索引未含项、或 codegraph `⚠️ pending sync` banner 点名的文件)回退 `Read`/`Glob`/`Grep`。该指引 SHALL 以**主谓**措辞(「SHALL 优先 …,仅 … 回退 Read」)写入共享片段 `core/prompts/fragments/codegraph-hint.md`(由姊妹变更 `improve-mgh-init-codegraph-enrichment` 引入,本变更复用;若该片段尚未存在则创建之,内容一致),由上述两份 stage 提示词在 `codegraph=on` 时引用;**MUST NOT** 用「you may」式可选措辞(规避 subagent 仍自行 Read、使 codegraph 沦为纯开销的已知陷阱)。`codegraph=off` 时两份 stage 行为与引入 codegraph 前逐字一致。本要求 MUST NOT 改动任一确定性 `.py` 的契约(R5.3);codegraph 调用 SHALL 由 subagent(经 MCP)或编排器(经 Bash)发起,NEVER 由 `.py` `import`/`subprocess` 发起。a2 `sra-clarify` 额外 MAY 用 codegraph **预解析**可从代码派生的业务事实以减少澄清问:(a) `callers` →「谁调用该接口」→ 角色/归属(仅当 caller 能明确映射到记忆 `roles[]` 已知角色时减问);(b) `callees`/data-flow →「该字段是否敏感且被该接口流转」→ 敏感字段判定;(c) domain-sibling →「同域既有鉴权范式」。codegraph-sourced 事实优先级**低于**用户断言/代码声明,**MUST NOT** 覆盖 `business_context.json`;仅**减问**(预解析后判得的事实不发澄清),**MUST NOT** 增写 codegraph 派生记忆条目(自动播种 `business_context.json` 属后续 Tier C 变更)。

#### Scenario: Augment uses codegraph for surgical context when on
- **WHEN** `codegraph=on` 且 sra-augment subagent 核验候选控制 `PermGuard` 的 evidence 是否真实
- **THEN** subagent 先 `codegraph_explore "PermGuard"` 取其源码+调用方+blast radius,而非整文件 Read;仅对 codegraph 未覆盖的文件回退 Read

#### Scenario: Read fallback for codegraph-uncovered files
- **WHEN** `codegraph=on` 但某目标文件是非索引语言(或超 `--big-file-bytes`,或被 codegraph `⚠️ pending` 点名)
- **THEN** subagent 对该文件回退 `Read`/`Glob`/`Grep`,不因 codegraph 未覆盖而丢覆盖

#### Scenario: Off behaves identically to pre-codegraph
- **WHEN** `codegraph=off` 运行 sra-clarify/sra-augment
- **THEN** 两份 stage 的工具使用与产出与引入 codegraph 前逐字一致(无 codegraph 调用)

#### Scenario: Hint steering is prescriptive not permissive
- **WHEN** 审阅 `core/prompts/fragments/codegraph-hint.md`
- **THEN** 其措辞为「codegraph 在场 SHALL 优先 codegraph_explore,仅 … 回退 Read」,而非「you may use codegraph」

#### Scenario: No deterministic-script contract change
- **WHEN** 本变更生效后审阅 `prepare_augment.py` / `merge_augment.py` / `merge_memory.py` 的 CLI 与 I/O 契约
- **THEN** 与变更前逐字一致;codegraph 从不被 `.py` import 或 subprocess 调用

### Requirement: Refine control-reuse recommendation via codegraph structural-evidence confirmation

当 `codegraph=on` 且某缺口已三信号命中、已产出 `recommended_control`(或已锚定缺口)时,`sra-augment` SHALL 额外用 codegraph 把三信号语义判定里**文本/AST 解不动**的结构性问题补成 **advisory 结构证据**。共四个 facet,共用同一 codegraph 机制(`codegraph_explore` 调用路径 / `callers` / `callees` + 框架路由):

- **(1) call-path(首要,唯一入 draft 结构字段)**——确认该控制是否接在该缺口接口的**请求路径上**(接口请求入口 → 受保护资源)。结果写入 draft `recommended_control.call_path`:`{confirmed: true|false|null, path: [{file, line, edge}, ...], source: "codegraph", note: "<简体中文>"}`,`confirmed:true` = 在请求路径上(强化「复用」措辞);`confirmed:false` = 控制存在但未确认接入此接口(降级置信 + 注明);`confirmed:null` = codegraph 未能判定(反射/DI/运行时分派,或 bounded 裁剪未覆盖)。
- **(2) data-flow 可达性(advisory,改善 `risk`/锚点,非新字段)**——缺口的敏感字段是否真被该接口流向/返回/落日志(`callees`);不可达 → 该 sensitive-data/injection 维度缺口降级或丢弃(治伪缺口)。
- **(3) 控制存活 liveness(advisory,入 `call_path.note`)**——推荐控制是否有 caller、还是近乎死代码(`callers`/blast radius);强化「存在≠有效」。
- **(4) domain-sibling 聚类(advisory,改善信号-2 `reason`,非新字段)**——枚举该接口同业务域兄弟接口及其守卫控制(`callers`/`callees` 聚类),把信号-2「业务域相似」从文本路径相似升级为结构聚类。

facet 2–4 的产物以**改善既有 `evidence`/`risk`/`reason` 质量的 advisory** 形式体现,**MUST NOT** 新增 draft schema 字段(契约最小化);仅 call-path 入结构字段 `call_path`。该解析 SHALL **bounded**:每 capability 的 a3 隔离上下文内,subagent 仅对该上下文**已推荐控制 / 已锚定缺口**做(非全部候选);当 (缺口×控制×facet) 对过多超出单上下文预算时,subagent 解析**每缺口 top-1 推荐的 call-path facet**(按 `matched_signals` 强度 + evidence 置信),其余记 `confirmed:null`,并在 draft 标注「部分未确认」;facet 2–4 在预算紧张时**先于** call-path 被裁剪。该 stage SHALL **fail-soft**:codegraph off / 无 `recommended_control`(无 `--rules`)/ 超预算 → 跳过结构证据解析,流程不阻断、不报致命错。结构证据是 LLM+codegraph **advisory**,MUST NOT 覆盖代码 evidence 与用户 `business_context.json` 断言;`sra-consistency`(a4)SHALL 透传并归一同控制多 cap 引用的 `call_path` 措辞,但 MUST NOT 重算(不跑 codegraph)。`call_path` 不改 a5 `merge_augment.py` 契约(渲染时仅影响推荐措辞/置信标注,不增删受管块结构)。

#### Scenario: Control on request path strengthens reuse wording
- **WHEN** `codegraph=on`,缺口的推荐控制经 codegraph 解析确认接在该接口请求路径上
- **THEN** draft 该推荐的 `call_path.confirmed=true` 且带真实 `path[]`(`source:"codegraph"`),rendered 措辞强化「复用,经确认接入此接口请求路径」

#### Scenario: Control not on path downgrades confidence
- **WHEN** `codegraph=on`,缺口的推荐控制经 codegraph 解析判其未接入该接口请求路径
- **THEN** draft 该推荐的 `call_path.confirmed=false` + `note` 注「控制存在但未确认接入此接口」,rendered 措辞降级置信(不删推荐,但标注 caveat)

#### Scenario: Unresolvable control recorded as null
- **WHEN** codegraph 亦无法判定某控制的接入(纯运行时反射分派 / DI 容器)
- **THEN** draft 该推荐的 `call_path.confirmed=null`,计入 `call_path_residual`,不被伪造成 confirmed:true

#### Scenario: Data-flow advisory sharpens or drops a false sensitive-data gap
- **WHEN** `codegraph=on`,某缺口锚定字段 `idCardNo`(sensitive-data 维度),codegraph `callees` 判该字段根本不被该接口流向/返回
- **THEN** subagent 据 advisory 降级或丢弃该伪缺口(改善 `risk`/锚点),不新增 draft schema 字段

#### Scenario: Domain-sibling advisory strengthens business-domain reason
- **WHEN** `codegraph=on`,缺口的推荐控制经 codegraph 聚类发现该接口同域兄弟接口均由该控制守卫
- **THEN** subagent 在该推荐的 `reason` 附结构聚类依据(业务域相似理由增强),不新增 schema 字段、不改三信号命中判据

#### Scenario: Bounded resolution under budget pressure
- **WHEN** 单 capability 的 (缺口×推荐控制) 对过多超 a3 单上下文预算
- **THEN** subagent 仅解析每缺口 top-1 推荐,其余记 `confirmed:null`,draft 标注「部分未确认」,摘要披露,流程不阻断

#### Scenario: No rules or codegraph off skips call-path entirely
- **WHEN** `codegraph=off`,或无 `--rules`(无 `recommended_control`)
- **THEN** sra-augment 不发起 call_path 解析,draft 不含 `call_path` 字段,主三信号流程不受影响

#### Scenario: Call-path is advisory, never overrides code evidence
- **WHEN** codegraph call_path 与代码 evidence / 用户 business_context 断言冲突
- **THEN** 以代码 evidence / 用户断言为准,call_path 仅作 advisory 标注,不覆盖

### Requirement: Disclose codegraph enrichment coverage in sra manifest

`sra_manifest.json` 的 `counts` SHALL 增 `call_path_confirmed`(`recommended_control` 中 `call_path.confirmed=true` 的条数)与 `call_path_residual`(`confirmed=false` 或 `null` 的条数;`codegraph=off` 时二者均为 0)。`boundaries[]` SHALL 新增披露:(1) codegraph 是否辅助、call_path 确认了多少、残留多少未确认(**不声称全确认**);(2) codegraph 自身静态分析上限——反射/DI 容器/运行时分派,缩小但不归零「误接」,call_path 为 LLM+codegraph advisory,需人工复核。既有四条诚实边界(LLM 候选需复核 / 覆盖取决于声明+已记事实 / 引用控制断言存在不断言有效 / 业务记忆为用户断言非代码真相)**保持不变**(语义匹配仍真;codegraph 是其上的可选结构确认)。

#### Scenario: Manifest reports real call-path coverage numbers
- **WHEN** 一次 `codegraph=on` 的运行完成
- **THEN** `sra_manifest.json::counts` 含 `call_path_confirmed`/`call_path_residual` 真实计数,`boundaries[]` 含 codegraph 披露,且不出现「全确认」之类断言

#### Scenario: Off run reports zero call-path counts
- **WHEN** `codegraph=off` 运行完成
- **THEN** `sra_manifest.json::counts` 的 `call_path_confirmed`/`call_path_residual` 均为 0(或字段缺省),`boundaries[]` 记 codegraph 未辅助

#### Scenario: Residual blind spot is disclosed
- **WHEN** 审阅 `sra_manifest.json` 的 `boundaries[]`
- **THEN** 其中明示「codegraph 静态分析上限致 call_path 未确认残差不归零,残留需人工复核」,且既有四条诚实边界仍在

