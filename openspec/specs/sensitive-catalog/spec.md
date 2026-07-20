# sensitive-catalog Specification

## Purpose

Project-level sensitive-data catalog (`sensitive_catalog.json`) declaring the company-mandated
masking policy (a policy input, not learned memory): which field types MUST be masked, at what
level (`full`/`partial`), and by which rule. Drives per-item masking-gap detection in the
sensitive-data dimension of `/mgh-sra` and `/mgh-srr`, and links gaps to mgh-init `data-masking`
controls via the existing three-signal match. Zero runtime dependencies; closed-set validation;
PIPL/GB-T 35273 default template shipped but not auto-applied.
## Requirements
### Requirement: Sensitive data catalog schema and closed-set vocabulary

系统 SHALL 支持一份**项目级**敏感数据目录 `sensitive_catalog.json`(默认位置 `<project>/.mgh-sra/sensitive_catalog.json`,
项目根 = 含 `openspec/` 的目录),声明**本公司强制脱敏清单**(policy 输入,非学到的记忆)。目录 schema:
顶层 `{"version": <int>, "items": {<key>: <entry>, ...}}`。每项 `key` 形如 `<category>/<field-type>`:
`category` MUST 取自**闭集 10 类**(`identity-doc` / `biometric` / `health` / `financial` / `location` /
`communication` / `device` / `vehicle` / `general-pii` / `legal`);`field-type` 为公司自有开放词汇(`[a-z0-9-]+`)。
每个 `entry` SHALL 含:`label`(非空简体中文)、`mask`(`full` 或 `partial` 二选一,**闭集枚举**)、
`rule`(具体脱敏规则提示串,如「保留后 4 位」「保留姓」;`full` 项可为 `null`)。`category` 与 `mask` 是受控
共享词汇(闭集);`field-type` 键与 `rule` 是公司自有开放词汇。

#### Scenario: valid catalog with grouped items accepted
- **WHEN** 目录含 `{"version":1,"items":{"biometric/iris":{"label":"虹膜","mask":"full","rule":null},"financial/card-no":{"label":"银行卡号","mask":"partial","rule":"保留后4位"}}}`
- **THEN** loader 解析通过,两项分别归入 `biometric` / `financial` 类,`mask` 分别为 `full` / `partial`

#### Scenario: unknown category rejected
- **WHEN** 目录含 key `astrology/zodiac`(category 不在闭集 10 类)
- **THEN** loader 以退出码 2 拒绝,stderr 指明 `astrology` 非法并列出 10 个允许 category

#### Scenario: invalid mask level rejected
- **WHEN** 一项 `mask` 为 `"mostly"`
- **THEN** loader 以退出码 2 拒绝,stderr 指明 `mask` 仅允许 `full` / `partial`

#### Scenario: malformed key or missing label rejected
- **WHEN** 一项 key 缺 `/`(如 `iris`)或 `entry` 缺 `label`
- **THEN** loader 以退出码 2 拒绝,stderr 指明 key 须为 `<category>/<field-type>` 且 `label` 必填

### Requirement: Zero-dependency loader with closed-set validation and CLI contract

新增确定性脚本 `core/scripts/sensitive_catalog.py` SHALL 用 Python ≥3.10 标准库实现目录加载 + 闭集校验 +
渲染,**零运行时依赖**(R2,不 `import` 任何第三方包)、自定位(`sys.path.insert(0, dir-of-__file__)`,R5.3a)、
读文件一律 `encoding="utf-8"`、任意 cwd 可直接 `py`。CLI 契约(`--help` 即契约面,R5.1):`--list`(枚举闭集
10 category + 印 PIPL/GB-T 35273 37 项默认模板)、`--parse <inline-json|@path|->`(解析 + 闭集校验 + 渲染解析后对象)、
`--check <inline-json|@path|->`(仅校验,无渲染无副作用)、`--help`。**输入判别(无歧义)**:以 `{` 起首 = inline JSON;
`-` = stdin;否则 = 文件路径(前导 `@` 可选剥离;文件缺失/不可读 exit 1)。stdout = 结构化 JSON(解析后目录 /
`--list` 模板 / `--check` 判定);stderr = 诊断/进度(R5.3b 严格分流)。退出码:`0` ok · `1` 文件缺失 / JSON 残缺 ·
`2` 误用(argparse)或闭集校验违例(未知 category / 非法 mask / key 或 shape 不合法)。幂等、无副作用(`--parse`/
`--check`/`--list` 不写盘)。该模块 SHALL 经 sibling import 被 `prepare_augment.py` / `ingest_requirements.py`
复用(单一真相源,同 `focus_scope` 范式)。

#### Scenario: list enumerates closed-set categories and default template
- **WHEN** 运行 `sensitive_catalog.py --list`
- **THEN** stdout 为 JSON,含 10 个闭集 category + PIPL/GB-T 35273 37 项默认模板(每项带 label/mask/rule)

#### Scenario: check accepts a valid catalog
- **WHEN** 运行 `sensitive_catalog.py --check <valid-catalog>`
- **THEN** stdout 为 `{"check":"sensitive-catalog","ok":true,"violations":[]}`,退出码 0

#### Scenario: check rejects and names violations
- **WHEN** 运行 `sensitive_catalog.py --check <catalog-with-unknown-category>`
- **THEN** stdout 为 `{"check":"sensitive-catalog","ok":false,"violations":[...]}`,stderr 列违例,退出码 2

#### Scenario: malformed JSON exits 1
- **WHEN** `--check` 的 inline JSON 语法残缺
- **THEN** 退出码 1 + stderr(读/解析失败,非闭集违例)

#### Scenario: zero runtime dependencies
- **WHEN** 对 `sensitive_catalog.py` 做 AST 扫描
- **THEN** 不存在非标准库 import(纯标准库)

### Requirement: Resolved catalog field in change_context.json

intake 阶段 SHALL 接受 `--sensitive-catalog <inline-json|@path|->`(`prepare_augment.py` for `/mgh-sra`,
`ingest_requirements.py` for `/mgh-srr`),经 sibling import 调用 `sensitive_catalog` 模块在**任何 LLM subagent
之前**解析 + 闭集校验(确定性 a1/r1 阶段),并把解析后的 `sensitive_catalog` 作为 `change_context.json` 顶层新字段
嵌入。字段值 SHALL 为解析后对象:`{version, source, categories[], items[], counts{items, full, partial, categories}, directive}`
或 `null`(`--sensitive-catalog` 缺省且无默认目录文件时)。`items[]` 为收敛去重、按闭集 category 顺序排序的扁平清单
(每项含 `key`/`category`/`label`/`mask`/`rule`)。`directive` 为确定性渲染的简体中文策略摘要(类别数 + 字段数 +
全/部分屏蔽计数 + 「须按 mask 规则在 at-rest/in-transit/log/response 脱敏,未脱敏记缺口」+ 「无目录时按现行 6 facet」)。
校验失败(退出码 2)SHALL 在消耗任何 token 前 fail-loud 早停(intake 阶段退出码 2,不发 `change_context.json`,
不 spawn LLM)。**向后兼容**:`--sensitive-catalog` 缺省时 `sensitive_catalog` 为 `null`,行为与引入目录前逐字一致。

#### Scenario: catalog embedded when flag given
- **WHEN** `prepare_augment.py` / `ingest_requirements.py` 以有效 `--sensitive-catalog` 运行
- **THEN** `change_context.json` 带 `sensitive_catalog` 对象,含去重排序的 `items[]` + `counts` + 一条 `directive`

#### Scenario: catalog is null when flag absent
- **WHEN** 任一脚本不带 `--sensitive-catalog` 运行
- **THEN** `change_context.json` 带 `sensitive_catalog: null`,下游行为与引入目录前逐字一致

#### Scenario: invalid catalog fails intake before any LLM token
- **WHEN** 任一脚本以无效 `--sensitive-catalog`(未知 category)运行
- **THEN** 脚本退出码 2 + 可操作 stderr,不发 `change_context.json`,不 spawn 任何 LLM subagent

### Requirement: Catalog drives per-item masking-gap detection in sensitive-data dimension

当传入非空 `sensitive_catalog` 时,`sra-clarify`(a2)/ `sra-augment`(a3)subagent SHALL 把 sensitive-data 维度
的逐项检查扩展为对 `items[]` 每个字段类型的脱敏缺口检测:据该项 `mask` + `rule` 判该字段在 at-rest / in-transit /
log / response 是否按规则脱敏;未按规则脱敏即产一条 sensitive-data 缺口,该缺口 MUST 锚定具体 requirement / 接口 /
字段并标 `catalog_key`(= 该项 key)。编排器 SHALL 把解析后的目录对象(含 `directive` + `items[]`)逐字透传进 a2/a3
task 输入,MUST NOT 重算/重拼(承 R5.2/R5.3)。`--focus` 覆盖层(既有)与目录覆盖层叠加:focus 先收窄维度(目录仅当
sensitive-data 在 focus 范围内时生效),范围外维度不产缺口(既有规则不变)。当 `sensitive_catalog` 为 `null` 时,
两 subagent SHALL 仅按现行 6 facet(`id-card`/`bank-card`/`phone`/`email`/`password`/`token`)识别敏感数据,行为与
引入目录前逐字一致。目录不改其余 8 维度的扫描。该扩展以 `core/prompts/stages/sra-clarify.md` 与 `sra-augment.md` 各
加一段叠加覆盖层实现(唯一提示词改动);`/mgh-srr` 逐字复用这两份提示词,零新增提示词获得该行为。`sra-consistency`
(a4)/ `merge_augment`(a5)/ codegraph 处理 a3 已产出的缺口,无需改动。

#### Scenario: augment emits per-item masking gaps when catalog present
- **WHEN** `sra-augment` 收到含 `biometric/iris`(full)的目录,且 capability 的某接口返回虹膜特征未脱敏
- **THEN** 产出一条 sensitive-data 缺口锚定该接口/字段、标 `catalog_key:"biometric/iris"`,风险简述指向未按 full 屏蔽

#### Scenario: catalog narrows by partial rule
- **WHEN** 目录 `financial/card-no`(partial,保留后 4 位),某响应体返回完整银行卡号
- **THEN** 产出 sensitive-data 缺口标 `catalog_key:"financial/card-no"`,风险指向未按「保留后 4 位」部分屏蔽

#### Scenario: catalog stacks with focus narrowing
- **WHEN** 传入 `--focus '{"dimensions":["sensitive-data"]}'` + 目录,或 `--focus` 排除 sensitive-data + 目录
- **THEN** focus 含 sensitive-data 时目录逐项检查生效;focus 排除 sensitive-data 时 sensitive-data 缺口(含目录项)不产出

#### Scenario: null catalog falls back to legacy 6 facets
- **WHEN** `sensitive_catalog` 为 `null`
- **THEN** sra-augment/sra-clarify 仅按现行 6 facet 识别敏感数据,行为与引入目录前逐字一致

### Requirement: Catalog field types link to mgh-init data-masking controls

目录驱动的 sensitive-data 脱敏缺口 SHALL 复用既有三信号匹配(`security-augmentation` 的「Three-signal semantic
matching」)与 mgh-init 关联:当 `change_context.candidate_controls[]` 含 `category: data-masking` 控制且经三信号
(维度契合 `data-masking → sensitive-data`、业务域相似、业务事实)命中时,`sra-augment` SHALL 为该缺口附
`recommended_control` + `evidence` + 「复用勿重造」措辞(目录说「该屏蔽什么」,mgh-init 说「有什么脱敏封装」,sra 连两者)。
关联是 **advisory**:无匹配控制时缺口仍产出(仅「应满足的安全属性」requirement,无控制锚点),MUST NOT 因无控制硬丢缺口。
本要求 MUST NOT 改 mgh-init 的发现行为 / `controls_inventory.json` schema / 出 rules(sra 仅**消费**既有 inventory,
零改 mgh-init 侧)。`data-masking → sensitive-data` 维度映射已存在于 `prepare_augment.py::DIMENSIONS_BY_CATEGORY`。

#### Scenario: catalog gap matched to a data-masking control
- **WHEN** 目录 `financial/card-no` 缺口,`candidate_controls` 含 `category: data-masking` 的 `CardMaskingFilter` 且三信号命中
- **THEN** 缺口附 `recommended_control: CardMaskingFilter` + `evidence` + 「复用,不得另起脱敏封装」

#### Scenario: no matching control still yields the gap
- **WHEN** 目录某字段缺口但无 `data-masking` 控制命中(或无 `--rules`)
- **THEN** 缺口仍产出(无控制锚点,仅「应满足的安全属性」),不被丢弃

#### Scenario: mgh-init side unchanged
- **WHEN** 本变更生效后审阅 mgh-init 的 `discover_controls` / `validate_inventory` / inventory schema
- **THEN** 与变更前逐字一致;sra 仅读 `controls_inventory.json`,不反向改它

### Requirement: PIPL/GB-T 35273 default template shipped, not auto-applied

`sensitive_catalog.py --list` SHALL 印出一份 PIPL / GB-T 35273 个人敏感信息分类的 **37 项默认模板**(承 task §三,
按 10 category 分组,每项带 label/mask/rule)。`install.sh` SHALL 在目标项目落地一份 `.example` 模板(如
`.mgh-sra/sensitive_catalog.json.example`)供公司裁剪。模板 MUST NOT 自动应用为生效目录(自动应用会改默认行为、违
向后兼容硬门);公司显式 `cp` 为 `sensitive_catalog.json` 或经 `--sensitive-catalog @<path>` 指定才生效。模板 SHALL
带 `version` 与来源注释(provenance)。

#### Scenario: list prints the 37-item template
- **WHEN** 运行 `sensitive_catalog.py --list`
- **THEN** stdout 含 37 项默认模板,按 10 category 分组,每项 label/mask/rule 齐备

#### Scenario: install lands a non-applied example
- **WHEN** `install.sh` 装入目标项目
- **THEN** 目标项目得到 `sensitive_catalog.json.example`(模板),但无生效的 `sensitive_catalog.json`;默认 sra/srr 行为不变(目录为 null)

#### Scenario: template must be explicitly activated
- **WHEN** 项目仅有 `.example`,未 `cp` 为 `sensitive_catalog.json` 也未传 `--sensitive-catalog`
- **THEN** `change_context.sensitive_catalog` 为 `null`,行为逐字等价引入目录前
