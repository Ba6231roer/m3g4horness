## Context

`/mgh-sra` 与 `/mgh-srr` 共享一条中间引擎:`prepare_augment.py`(sra a1)/ `ingest_requirements.py`(srr r1)
产同 shape 的 `change_context.json` → 编排器 spawn `sra-clarify`(a2)/ `sra-augment`(a3) subagent,后者按
`core/prompts/fragments/security-dimensions.md` **逐维度**扫全 9 类。sensitive-data 维度今天能识别的字段类型
是**闭集 6 项**(`focus_scope.py::FACETS["sensitive-data"]` = `id-card/bank-card/phone/email/password/token`,
镜像 `security-dimensions.md` 「检查什么」列,设计决策 D5 锁步)。我司法务/合规按 PIPL / GB-T 35273 强制
要求 37 项个人信息字段全部/部分屏蔽——这些字段(生物识别 / 健康生理 / 位置 / 设备 / 车辆 / 一般 PII /
法律记录)今天工具**既识别不了,也表达不出「MUST 屏蔽」的策略语义**。把 37 项塞进产品级 `--focus` 闭集
(方案 A)语义错位(收窄 ≠ 必屏蔽策略)且污染全产品。

本设计加一个**项目隔离、默认不动、与 `--focus` 正交**的「敏感数据目录」层:公司级策略声明**该屏蔽什么 +
怎么屏蔽**,被 a3 逐项消费以**检测脱敏设计缺口**,并与 mgh-init 发现的 `data-masking` 控制自动关联。

约束:R2(零运行时依赖)、R5(CLI 契约 = `--help`、`--check` 边界校验、双端壳镜像、确定性脚本闭集)、
R3(文档简练)、R5.10(分发物纯净)。向后兼容是硬门(R5 稳定性):无目录须逐字等价今天。

## Goals / Non-Goals

**Goals:**
- 默认行为零回归(无目录 = `sensitive_catalog: null` = 今天逐字一致)。
- 公司可在项目级声明必屏蔽字段类型(37 项 PIPL 默认模板)+ 屏蔽级别 + 规则;确定性闭集校验、零 token 早停。
- sra/srr 共享同一目录契约;srr **零新增提示词**复用(sra-clarify/sra-augment 加一段共享覆盖层)。
- 目录与 `--focus` **正交**(目录 = 识别范围扩展 + 策略;focus = 本次扫描收窄);两者可同时用。
- 目录字段类型 ↔ mgh-init `data-masking` 控制自动关联(复用勿重造),**不改 mgh-init 侧**。
- 目录覆盖范围在 manifest/报告明示(诚实边界)。

**Non-Goals:**
- 不改 9 维度本身;`--focus` 的 sensitive-data 闭集 6 facet **逐字不动**(目录是独立策略源,非收窄词汇)。
- 不做脱敏**执行**(只识别 + 查设计缺口;执行脱敏是代码层)。
- 不改 mgh-init 发现 / inventory schema / 出 rules(sra 仅**消费** `controls_inventory.json`)。
- 不做目录的「项目级自动加载默认」(MVP 显式 `--sensitive-catalog`,或手动放 `.mgh-sra/`;自动加载留后续)。

## Decisions

### D1 — 目录是独立文件,不并入 `business_context.json`(生命周期不同)
`sensitive_catalog.json` 是**公司级策略输入**(法务写一次、稳定、声明「该屏蔽什么」);`business_context.json` 的
`sensitive_fields[]` 是**学到的跨迭代记忆**(引擎产出、用户断言)。两者生命周期 / 写入方 / 优先级均不同 → 分文件。
两者同放 `<project>/.mgh-sra/`(目录 = policy 输入、记忆 = 输出,记忆可**引用**目录字段类型,见 D10)。
**替代(否决)**:目录折叠进 `business_context.sensitive_fields[]`——把静态策略与动态记忆混在一个文件,
写入方/更新频率不同,且记忆是「用户断言非代码真相」语义,与「公司强制策略」语义冲突。

### D2 — 目录项 key = `<category>/<field-type>`(英文 kebab,分组);label 简体中文
沿用现行 facet 命名约定(`id-card`/`bank-card`,英文键 + 中文 label):闭集校验 / 正则匹配 / 跨工具引用更稳。
分组键(承 task §三 10 类):`identity-doc` / `biometric` / `health` / `financial` / `location` / `communication` /
`device` / `vehicle` / `general-pii` / `legal`。示例:`biometric/iris` {label: 虹膜, mask: full}、
`financial/card-no` {label: 银行卡号, mask: partial, rule: 保留后 4 位}。
**替代(否决)**:扁平 37 键(可维护性差)/ 中文键(闭集正则不稳)。

### D3 — 目录与 `--focus` 正交;`--focus` 6 facet 闭集不动
目录 = **识别范围扩展 + 策略**(把 sensitive-data 能识别的字段类型从 6 项扩到目录声明的 N 项 + 每项屏蔽规则);
`--focus` = **本次扫描收窄**(哪些维度/facet 查)。二者独立:`--focus '{"dimensions":["sensitive-data"]}'` +
目录 = 只扫敏感数据维度,但用目录的 N 项清单逐项查脱敏。无目录时 sensitive-data 仍只认 6 facet(逐字今天)。
**替代(否决)**:方案 C(双词汇统一索引)——用户已选 B,复杂度更低。

### D4 — 新增共享模块 `sensitive_catalog.py`(loader + 闭集校验 + `--check` + `--list`),sibling 导入
两适配器需**逐字相同**的 parse/validate/render;`focus_scope.py` 已立此范式(`sys.path.insert` 自定位,R5.3a)。
`sensitive_catalog.py` 同模式:闭集 category registry(单一真相源)+ `--check <json|path>`(闭集 + shape 校验,
退出码 2)+ `--list`(枚举 10 category + PIPL 37 项默认模板)。纯标准库(R2)。
**替代(否决)**:逻辑抄进两适配器——闭集 category registry 漂移、双份维护。

### D5 — 闭集边界:category(10)与 `mask`({full,partial})硬闭集;field-type 键 / rule 开放
承 R5.3b 闭集纪律:**category** 与 **mask 级别**是共享受控词汇 → 硬闭集(未知 → 退出码 2 + 可操作 stderr,
同 `focus_scope` 未知 facet)。**field-type 键**是公司自有词汇(每家不同)→ 开放(校验 `<category>/<type>` 格式
+ `label` 必填)。**rule** 是自由提示串(可 null)。这平衡了确定性与公司策略灵活性。
**替代(否决)**:category 也开放 → 失去受控词汇 + `--list` 权威性。

### D6 — 校验落在确定性 a1/r1(任何 LLM 之前);解析后目录嵌 `change_context.sensitive_catalog`
a1/r1 是确定性、零 token 的 choke point。`--sensitive-catalog <inline-json|@path|->` 在此解析 + 闭集校验(承 R5.9
边界校验范式 + validate BEFORE tokens)。解析后嵌入 `change_context.sensitive_catalog`(收敛去重的 items 清单 +
categories + counts + 渲染好的简体中文 **policy directive**)。编排器读 `sensitive_catalog.directive` **逐字透传**
给 a2/a3(零重算、零拼装,承 R5.2/R5.3)。`null` = 无目录(向后兼容信号)。
**输入判别**(无歧义,同 `--focus`):`{` 起首 = inline JSON;`-` = stdin;否则 = 文件路径(前导 `@` 可选剥离)。

### D7 — 提示词覆盖层在 sra-augment / sra-clarify;policy directive 逐字透传(srr 零新增提示词)
两提示词各加**一小段覆盖层**(「传入 policy directive 时 SHALL 对目录每个字段类型查脱敏缺口:据 `mask`+`rule`
判该字段 at-rest/in-transit/log/response 是否按规则脱敏;缺口锚定具体 requirement/接口/字段,标 `catalog_key`;
无 directive = 现行 6 facet 行为」)。`--focus` 覆盖层(既有)与目录覆盖层**叠加**:focus 先收窄维度,目录再在
sensitive-data 维度内逐项查。srr 逐字复用这两份提示词 → 自动获得,零新增提示词。
**替代(否决)**:传原始目录 JSON 给 subagent 自行解释——LLM 解释嵌套结构易漂移;渲染成自然语言指令更稳。

### D8 — mgh-init 关联复用既有 `candidate_controls`(category `data-masking`);不改 mgh-init 侧
`prepare_augment` 已产 `candidate_controls[]`,每条带 `category` + `dimensions`(`data-masking → [sensitive-data]`
映射已存在)。目录驱动的脱敏缺口 SHALL 在 `data-masking` 类控制存在时附 `recommended_control` + `evidence` +
「复用勿重造」(目录说「该屏蔽什么」,mgh-init 说「有什么脱敏封装」,sra 连两者)。关联是 **advisory**
(从不因无控制硬丢缺口;三信号匹配仍适用)。**零改 mgh-init 发现 / inventory / rules**。

### D9 — `sensitive_catalog: null` 向后兼容硬门
无 `--sensitive-catalog` 且 `.mgh-sra/sensitive_catalog.json` 不存在 → 字段 `null` → 无 directive 注入 →
sensitive-data 维度行为逐字等价今天(只认 6 facet)。字段恒在 = schema 稳定。既有 `test_sra_prepare.py`/
`test_srr_ingest.py` 须全绿不改。承 R5(稳定性是产品特性)。

### D10 — 目录缺口经既有 `sensitive_fields[]` 沉淀(零记忆契约变更)
目录驱动的脱敏缺口经既有 `business_context.json` `sensitive_fields[]` 机制沉淀(该字段已是「必屏蔽字段 +
原因 + 屏蔽方式」语义,目录字段类型 + mask 规则天然映射),跨迭代复用。**不改记忆契约 / schema / 语义**
(srr 既有「memory contract SHALL NOT be modified」保持;`business-context-memory` 不在本变更 MODIFIED 列表)。
**替代(否决)**:给 `sensitive_fields[]` 加 `source: catalog-policy` 显式溯源字段——改记忆契约、扩 scope;
provenance 标记可作后续 follow-up,本变更保守不动契约。

### D11 — 随分发 PIPL/GB-T 35273 37 项**模板**(非自动应用)
`sensitive_catalog.py --list` 印出 37 项默认模板(承 task §三);install 落地一份 `.example`(如
`.mgh-sra/sensitive_catalog.json.example`)供公司裁剪。**不自动应用**(自动应用会改默认行为、违 D9);
公司显式 `cp` 为 `sensitive_catalog.json` 或 `--sensitive-catalog @...` 指定才生效。模板版本化。

## Risks / Trade-offs

- **[覆盖层可能泄漏目录外 sensitive-data 缺口 / 漏目录内]**(提示词护栏非确定性)→ 缓解:指令用规定性措辞
  (`SHALL 逐项查…;无 directive SHALL 用现行 6 facet`);承 R5.7 评估驱动:改提示词前 baseline ≥5 次 capture
  失败模式,A/B 对比 pass rate;测试断言目录缺口带 `catalog_key`、缺口的 dimension=sensitive-data 仍锚定具体字段。
- **[目录 ↔ 控制关联误报]** → 缓解:关联 advisory(`recommended_control` 从不硬丢缺口);`data-masking` 是窄、
  高精度 category;三信号(维度契合 / 业务域相似 / 业务事实)仍叠加判定。
- **[category 硬闭集拒掉合理新类]** → 缓解:10 类 PIPL/GB-T 35273 已覆盖个人信息主类;新增 = registry 协同改
  (受控扩展,同 facet);这是有意设计非缺陷。
- **[37 项默认模板随法规更新漂移]** → 缓解:模板版本化 + provenance 注释;公司可裁剪;`--list` 明示来源。
- **[srr 提示词复用假设]** → 缓解:覆盖层在共享 sra-clarify/sra-augment;srr 零新增提示词;既有 srr 复用断言
  (codegraph/focus)同模式可参照新增目录复用断言。
- **[目录膨胀拖慢 sensitive-data pass]** → 缓解:目录收敛去重后通常 ≤ 数十项;逐项检查是单 LLM 上下文内遍历,
  非扇出;`--focus` 可进一步收窄到 sensitive-data 单维度。

## Migration Plan

纯增量,无数据迁移。目录是项目级策略输入(用户写),**不**自动生成(区别于学到的记忆)。部署:新增
`sensitive_catalog.py` + 改两适配器 / 两提示词 / 四壳 / 两契约文档 + 新增 `core/contracts/sensitive-catalog.md`
+ 随分发 `.example` 模板 + 测试 + 版本号。回滚:revert 受影响文件即可(无持久状态变更;`sensitive_catalog: null`
路径天然兼容)。install 分发物须过 `check_distributed_md_purity`(R5.10)。

## Open Questions

- **项目级自动加载默认**(`.mgh-sra/sensitive_catalog.json` 存在时自动读,免 `--sensitive-catalog`)?MVP 不做
  (显式 flag);但 `--sensitive-catalog @.mgh-sra/sensitive_catalog.json` 的 `@path` 已让用户手动达成。是否「自动
  加载项目默认」留后续(同 `--focus` 的对应 open question)。
- **rule 的结构化**(保留几位 / 掩码字符)?MVP = 自由提示串(法务自然语言);若后续要机器可判,可演进成
  `{keep_prefix, keep_suffix, mask_char}` 结构化 schema(届时 bump version)。
- **目录与 `business_context.sensitive_fields[]` 的去重/合并策略**?MVP = 目录溯源标记 + 幂等键;更深的双向同步
  (记忆回填目录)留后续。
