## ADDED Requirements

### Requirement: Parse arguments and guard zero-token no-op

`/mgh-sra` SHALL accept `--change <name>`(默认取 `openspec/changes/` 下最新未归档变更)、
`--rules <path>`(可选,指向 mgh-init 的 `controls_inventory.json` 或其输出目录)、
`--no-interactive`(澄清问用默认猜测、不暂停问用户)、`--dry-run`(仅产 `change_context.json`
+ stdout 摘要,不写 specs/tasks/记忆)、`--skip-consistency`(跳过 a4)、`--config <profile>`
(默认 `sra`)。当无 actionable 参数或传 `--help` 时,系统 MUST 仅打印参数表后**停止,不消耗
token、不做任何分析**。

#### Scenario: Help / no actionable args
- **WHEN** 用户运行 `mgh-sra --help` 或不带任何参数
- **THEN** 系统打印参数表后停止,零 LLM 调用、零变更解析

#### Scenario: Default change resolves to latest
- **WHEN** 用户运行 `mgh-sra` 不带 `--change`,且存在一个未归档变更
- **THEN** 系统取该最新变更作为目标;无任何未归档变更时报错并停止

### Requirement: Parse the openspec change deterministically

`prepare_augment.py` SHALL 用 Python ≥3.10 标准库解析目标变更的 `proposal.md` / `design.md` /
`specs/**/*.md` / `tasks.md`,产出结构化 `change_context.json`:含变更触及的 `capabilities[]`、
各 capability 的 `requirements[]`、现有 `tasks[]`、变更文本提及的 `mentioned_files[]`、可机械抽取
的业务面信号(`endpoints[]` / `data_fields[]` / `role_hints[]`)。`change_context.json` 落在
`<change-root>/.mgh-sra/`。

#### Scenario: Capabilities and requirements extracted from delta specs
- **WHEN** 变更含 `specs/payment-api/spec.md`(`## ADDED Requirements` 下 2 条 `### Requirement:`)
- **THEN** `change_context.capabilities[]` 含 `payment-api`,其 `requirements[]` 含那 2 条

#### Scenario: Endpoints and data fields collected mechanically
- **WHEN** 变更 `tasks.md` 提及接口 `POST /api/transfer` 与字段 `bankCardNo`
- **THEN** `change_context.endpoints[]` 含该接口、`data_fields[]` 含该字段,供维度分析使用

#### Scenario: Change with no capability specs
- **WHEN** 变更仅有 `proposal.md` + `tasks.md`,无 `specs/**`
- **THEN** `change_context` 标 `capabilities: []`,增补回退到单个 `specs/security-augmentation/spec.md`

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
(它保护什么),并标注 `dimension` 与风险简述。无锚定的泛泛 OWASP 清单式缺口 MUST 丢弃。

#### Scenario: Each dimension checked against the capability
- **WHEN** sra-augment 分析 `payment-api`(含「发起转账」requirement)
- **THEN** 产出覆盖横向越权 / 敏感数据 / 完整性等维度的具体缺口,每条锚定到「发起转账」或相关字段

#### Scenario: Ungrounded boilerplate gap dropped
- **WHEN** sra-augment 试图产出一条不锚定任何 requirement / 接口 / 字段的泛泛「应防 SQL 注入」缺口
- **THEN** 该缺口被丢弃,不进入 draft

### Requirement: Three-signal semantic matching of gaps to existing controls

对每条缺口,`sra-augment` SHALL 用**三个信号**匹配该用的存量控制:(1) **维度契合**——控制
`dimensions` 含该缺口维度(必要条件);(2) **业务域相似**——控制 `entry_points`/`protects` 守护的
是否为**同业务域类似接口**(据记忆 `domains[]` + 接口路径语义);(3) **业务事实**——该接口的
角色 / 资源归属(据 `business_context.json`,缺失则该缺口触发澄清,见 `business-context-memory`)。
匹配产物 = 推荐控制 + 其 `evidence`(`file:class:method`)+ 派生规则文件路径(claude
`.claude/rules/security-<cat>.md` / opencode `AGENTS.md` 节)+ 「复用勿重造」措辞 + 业务域相似理由。
无 `--rules` 时跳过匹配,缺口仅产「应满足的安全属性」requirement(无控制锚点)。三信号须同时
命中才推荐;仅文件重叠(非业务域语义相似)MUST NOT 单独作为推荐依据。

#### Scenario: Gap matched to control via all three signals
- **WHEN** 缺口「`POST /refund` 横向越权」,存在 `category: authorization` 控制且其 `entry_points`
  含同业务域的 `OrderController.cancel`,记忆记该域接口的归属模型
- **THEN** 推荐该控制(带 `evidence` + 业务域相似理由 + 角色锚点),措辞「复用,不得另起」

#### Scenario: File overlap alone is not a match
- **WHEN** 一条控制仅因 `protects` 文件路径与变更重叠,但守护的是**不同业务域**接口
- **THEN** 该控制不被推荐(文件重叠非充分条件)

#### Scenario: Missing business fact triggers clarification
- **WHEN** 缺口匹配需要「该接口哪些角色用」,而代码/proposal/inventory/记忆均无
- **THEN** 该缺口产出推荐的同时触发一条澄清(详见 `business-context-memory` 能力),暂以默认猜测标注

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
`prepare_augment --check` 校验 inventory(若给)well-formed + `change_context` 结构完整;
`merge_augment --check` 校验合并仅动受管块、块外字节不变;`merge_memory --check` 校验记忆 shape
+ `fact_key` 无冲突。编排器每步后 MUST 运行之;失败 MUST 以退出码 2 fail-loud 回退重跑,**不带着
破损产物继续**。

#### Scenario: Malformed inventory fails intake check
- **WHEN** `--rules` 指向的 inventory 缺 `controls[]` 或条目无 `name/evidence`
- **THEN** `prepare_augment --check` 退出码 2,编排器回退(可 advisory 以无控制继续)

#### Scenario: Merge check confirms user content untouched
- **WHEN** a5 合并完成后运行 `merge_augment --check`
- **THEN** 校验通过(退出码 0)当且仅当受管块外的用户内容字节级未变

### Requirement: Disclose honesty boundaries in manifest

`sra_manifest.json` MUST 明示边界:(1) 增补为 **LLM 候选,需人工复核**;(2) 覆盖**取决于变更声明
+ 已记业务事实**(未声明 / 未记的看不到);(3) 引用控制**断言存在不断言有效**(承 mgh-init
CVE-2025-41248);(4) 业务记忆为**用户断言非代码真相**。manifest 另记 `change`、`rules_source`、
`memory_source`、`counts{capabilities, gaps, augmented_requirements, augmented_tasks,
referenced_controls, clarifications_asked}`。

#### Scenario: Manifest carries all boundaries
- **WHEN** 一次 sra 运行完成
- **THEN** `sra_manifest.json` 含上述四条边界声明的可识别字段与各项计数
