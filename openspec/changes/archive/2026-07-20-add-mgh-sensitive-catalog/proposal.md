## Why

`/mgh-sra` + `/mgh-srr` 今天**只能识别 6 个硬编码的 sensitive-data 子项**(`id-card · bank-card · phone · email · password · token`,闭集真相源 `focus_scope.py::FACETS["sensitive-data"]`)。我司法务/合规
按 PIPL / GB-T 35273 强制要求一批个人信息字段(37 项:生物识别 / 健康生理 / 位置轨迹 / 设备标识 /
车辆 / 一般 PII / 法律记录 等)**全部或部分屏蔽**,但今天工具既识别不了这些字段、也表达不出
「这些字段 **MUST** 屏蔽」的策略语义——结果这些字段流经接口 / DB / 日志 / 响应体时**无人查脱敏缺口**。

把 37 项硬塞进产品级 `--focus` 闭集(方案 A)语义错位(`--focus` 是「本次只查这几类」的**收窄**,
非「这些必须屏蔽」的**策略**),且会污染所有项目。需要一份**项目隔离**的「敏感数据目录」声明
本公司必屏蔽字段 + 屏蔽级别 + 规则,被评审引擎逐项消费以**检测脱敏设计缺口**,并能与 mgh-init
发现的脱敏控制**自动关联**(复用勿重造)。

## What Changes

- **新增项目级「敏感数据目录」`<project>/.mgh-sra/sensitive_catalog.json`**:声明本公司必屏蔽字段类型,
  每项含 `label`(简体中文)+ `mask`(`full`/`partial`)+ `rule`(具体规则提示,如「保留后 4 位」「保留姓」,
  `full` 可为 `null`),按 `category` 分组(identity-doc / biometric / health / financial / location /
  communication / device / vehicle / general-pii / legal)。随分发带一份 **PIPL / GB-T 35273 37 项默认模板**。
- **新增零依赖确定性 loader/validator `core/scripts/sensitive_catalog.py`**:闭集 category 校验 +
  每项 shape 校验(`--check <inline-json|@path>`);`--list` 枚举默认模板;stdout=JSON / stderr=诊断
  严格分流;退出码 `0/1/2`(R5.3);纯标准库(R2)、自定位兄弟导入(R5.3a)。
- **`prepare_augment.py` / `ingest_requirements.py` 新增 `--sensitive-catalog <inline-json|@path|->`**:
  在确定性 a1/r1 阶段(任何 LLM 之前)读 + 校验目录,把解析后的 `sensitive_catalog`(字段类型清单 +
  屏蔽级别 + 规则,**按 category 收敛去重**)嵌进 `change_context.json` 顶层新字段。**无目录 → 字段
  为 `null` → 行为与今天逐字一致(零回归)**。`--check` 扩展校验该字段 shape。
- **subagent 提示词 `sra-augment.md` / `sra-clarify.md` 加一段「敏感数据目录」覆盖层**:目录存在时,
  sensitive-data 维度的逐项 pass 改为**对目录每个字段类型查脱敏缺口**(据 `mask`+`rule` 判「该字段
  at-rest / in-transit / log / response 是否按规则脱敏」),缺口锚定具体 requirement/接口/字段。
  srr 逐字复用这两份提示词 → 自动获得。目录缺失 = 现行 6 facet 行为不变。
- **mgh-init 脱敏控制自动关联(本 change 内)**:对目录字段类型产出的脱敏缺口,augment 据
  `change_context.candidate_controls`(`category: data-masking`)为缺口附 `recommended_control` +
  `evidence` + 「复用勿重造」(目录说「该屏蔽什么」,mgh-init 说「有什么脱敏封装」,sra 连两者)。
  **不改 mgh-init 发现行为**(sra 是消费方)。
- **报告 / manifest 披露目录**:`sra_manifest.json` / `srr_manifest.json` 增 `sensitive_catalog`(字段数 +
  category 列表)+ `boundaries[]` 一条;`security_review_report.md` 头注本次目录覆盖范围。
- **目录驱动的脱敏缺口经既有 `business_context.json` `sensitive_fields[]` 机制沉淀**(零契约变更):目录字段类型 +
  mask 规则天然映射到既有 `sensitive_fields`(「必屏蔽字段 + 原因 + 屏蔽方式」),跨迭代复用;**不改记忆契约**
  (srr 既有「memory contract SHALL NOT be modified」保持)。
- **契约文档 `core/contracts/sra/augmentation.md` + `srr/intake-report.md` + 新增 `core/contracts/sensitive-catalog.md`**
  记 `sensitive_catalog` schema + 字段语义 + mgh-init 关联语义。
- **4 个命令壳(claude/opencode × sra/srr)加 `--sensitive-catalog`**:参数表 + 编排流(读
  `change_context.sensitive_catalog` 透传给 a2/a3)+ 确定性调用示例 + 「Always disclose」增一条(目录覆盖范围)。
- **测试 + 契约 lint + 版本号 + 工作流文档**:`tests/test_sensitive_catalog.py`、扩 `test_sra_prepare.py`/
  `test_srr_ingest.py`(目录嵌入 + `--check` + 无目录回归)、`check_contracts.py` 已覆盖 4 壳(自动 lint
  `--sensitive-catalog`)、bump 受影响 `.md`/`.py` 版本、更新 `docs/mgh-sra-工作流程详解.md`。

**非目标(显式排除,防 scope 蔓延)**:

- **不**改 9 个安全维度本身;`--focus` 的 sensitive-data 闭集 6 facet **逐字不动**(目录是**独立**策略源,
  非收窄词汇;承 D5)。目录与 `--focus` 正交,可同时用。
- **不**做脱敏规则的**执行**(只识别 + 查设计缺口;执行脱敏是代码层,非本工具职责)。
- **不**改 mgh-init 的发现 / inventory schema / 出 rules 行为(sra 仅**消费** `controls_inventory.json`)。
- **不**破坏向后兼容:无目录 = `sensitive_catalog: null` = 行为逐字等价今天(硬门)。

## Capabilities

### New Capabilities

- `sensitive-catalog`: 项目级敏感数据目录契约——`sensitive_catalog.json` schema(字段类型 + `mask`
  级别 + `rule` + `category` 分组)、零依赖 loader + 闭集 `--check` 校验、`change_context.sensitive_catalog`
  字段语义、目录如何驱动 sensitive-data 维度逐项脱敏缺口发现、目录字段类型 ↔ mgh-init `data-masking`
  控制的关联语义。被 sra/srr 共享消费(与 `dimension-focus` 同构:独立策略源,非收窄)。

### Modified Capabilities

- `security-augmentation`: a1 `prepare_augment.py` 新增 `--sensitive-catalog` 并产 `sensitive_catalog` 字段;
  a3 `sra-augment` 据目录逐项查脱敏缺口 + 关联 mgh-init `data-masking` 控制;sra manifest 披露目录。
  改的是「sensitive-data 维度的脱敏检测目标可声明」,非维度本身、非 `--focus` 闭集。
- `freeform-security-review`: r1 `ingest_requirements.py` 新增 `--sensitive-catalog`(与 sra 同字段语义);
  报告 + manifest 披露目录。中间引擎零改动复用。

> 注:目录驱动的脱敏缺口经既有 `business_context.json` `sensitive_fields[]` 机制沉淀(零契约变更),
> 故 `business-context-memory` **不在本变更的 MODIFIED 列表**。

## Impact

- **新增代码**: `core/scripts/sensitive_catalog.py`(新 loader/validator);`prepare_augment.py`/
  `ingest_requirements.py` 加 `--sensitive-catalog` 分支 + `sensitive_catalog` 字段(两者经 sibling import
  共享 sensitive_catalog,DRY);随分发默认模板(`releases/**` 经 install 落地)。
- **改提示词**: `core/prompts/stages/sra-augment.md`、`sra-clarify.md` 各加一段覆盖层(srr 零新增提示词复用)。
- **改分发物**: 4 个命令壳 + 2 份契约文档 + 新增 `core/contracts/sensitive-catalog.md`(install 分发,须过 R5.10 纯净性)。
- **CLI 契约变更**(R5.1): 两脚本 `--help` 增 `--sensitive-catalog`;4 壳 bash 块镜像;`check_contracts.py` 自动断言。
- **mgh-init 关联**: 复用既有 `candidate_controls`(`category: data-masking`)+ `data-masking → sensitive-data`
  维度映射;**零改** mgh-init 侧。
- **依赖**: 零新增 `pip`(R2);sensitive_catalog 纯标准库。
- **回归面**: 无目录路径须逐字等价今天(`sensitive_catalog: null`);新测试覆盖闭集 category 校验 /
  退出码 / 嵌入 / 向后兼容 / mgh-init 关联。
- **文档**: `docs/mgh-sra-工作流程详解.md` 增条目(承 R3 简练)。
