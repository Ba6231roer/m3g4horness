## Why

`/mgh-sra` 与 `/mgh-srr` 今天**硬编码扫全 9 类安全维度**(`core/prompts/fragments/security-dimensions.md`)。
对很多真实场景这是浪费 + 噪音:一次评审只关心某一两类(如「只查越权」「只查这次新接口的敏感数据脱敏」),
甚至只关心某维度下的特定子项(如敏感数据里**只**关心身份证号 + 银行卡号,不在乎其它字段脱没脱)。
当前没有任何入口让用户收窄范围,结果要么硬跑 9 类产一堆无关缺口要人工剔除,要么用户干脆不用工具。

需要一个**默认不动(仍扫全 9 类)、但可参数化收窄**的「维度聚焦」能力,且能下钻到维度内子项。

## What Changes

- **新增确定性脚本 `core/scripts/focus_scope.py`**:9 维度 + 维度内 facet 的**闭集 registry**(单一真相源),
  `--list`(枚举可用维度/facet 供 `--help` 发现)、`--parse <inline-json|path>`(解析 + 闭集校验 +
  渲染**简体中文 focus 指令**)、`--check <spec>`(仅校验)。闭集外键 → 退出码 2 + 可操作报错(R5.3);
  零运行时依赖(R2);stdout=JSON / stderr=诊断 严格分流。
- **`prepare_augment.py` / `ingest_requirements.py` 新增 `--focus <inline-json|path>`**:在确定性 a1/r1
  阶段(任何 LLM subagent 之前)解析 + 校验 focus,把解析后的 `focus`(`{dimensions[], facets{}, directive}`
  或 `null`)嵌进 `change_context.json` 顶层新字段。`--check` 扩展校验该字段 shape。无 `--focus` →
  `focus: null` → 行为与今天**逐字一致**(零回归)。
- **subagent 提示词 `sra-clarify.md` / `sra-augment.md` 加一小段「维度聚焦」覆盖层**:编排器传入 focus
  指令时,**只**对列出的维度(及维度内列出的 facet)查缺口/发澄清,范围外的缺口/澄清**不产出**;
  无指令 = 全 9 维度(现行行为)。锚定/丢弃规则对范围内缺口不变。srr 逐字复用这两份提示词 → 自动获得。
- **4 个命令壳(claude/opencode × sra/srr)加 `--focus`**:参数表 + 编排流(读 `change_context.focus`
  的 `directive` 逐字透传给 a2/a3)+ 确定性调用示例 + 「Always disclose」新增一条(本次聚焦范围)。
- **manifest/报告披露聚焦范围**:`sra_manifest.json` / `srr_manifest.json` 增 `focus`(维度列表)字段 +
  `boundaries[]` 一条;`security_review_report.md` 头注聚焦维度。
- **维度目录 `security-dimensions.md` 标注 facet 键**(尤其 sensitive-data 字段类型:id-card/bank-card/
  phone/email/password/token),使 focus spec 的 facet 键可发现、subagent 可映射。属本仓原创文件(R1 不涉)。
- **契约文档 `core/contracts/sra/augmentation.md` + `srr/intake-report.md`** 记 `focus` 字段 + 指令语义。
- **测试 + 契约 lint + 版本号 + 工作流文档**:`tests/test_focus_scope.py`、扩 `test_sra_prepare.py`/
  `test_srr_ingest.py`(`--focus` 嵌入 + `--check`)、`check_contracts.py` 已覆盖 4 壳(自动 lint `--focus`)、
  bump 受影响 `.md`/`.py` 版本、更新 `docs/mgh-sra-工作流程详解.md`(§6 名词 + §8 参数)。

**非目标(显式排除,防 scope 蔓延)**:

- **不**改 9 维度本身(不增删维度、不改维度语义);focus 只**收窄**,不扩展。
- **不**引入预设简写(`--focus auth`)(留作后续 nice-to-have;MVP = 显式 dimension/facet 列表)。
- **不**持久化 focus 进 `business_context.json`(focus 是单次运行参数,非跨迭代记忆)。
- **不**动 `sra-consistency`/`merge_augment`/codegraph 逻辑(它们处理 a3 已产出的范围内缺口,天然兼容)。

## Capabilities

### New Capabilities

- `dimension-focus`: 安全维度聚焦契约——9 维度 + 维度内 facet 的闭集 registry、`--focus` 解析/校验/
  渲染、`change_context.focus` 字段语义、focus 指令如何收窄 subagent 的逐维度扫描。被 sra/srr 共享消费。

### Modified Capabilities

- `security-augmentation`: a1 `prepare_augment.py` 新增 `--focus` 并产 `focus` 字段;a2/a3 subagent 据 focus
  指令收窄逐维度扫描;`sra_manifest.json` 披露聚焦维度。改的是「维度扫描的范围可控性」,非维度本身。
- `freeform-security-review`: r1 `ingest_requirements.py` 新增 `--focus`(与 sra 同字段语义);报告 + manifest
  披露聚焦维度。中间引擎零改动复用。

## Impact

- **新增代码**: `core/scripts/focus_scope.py`(新);`prepare_augment.py`/`ingest_requirements.py` 加 `--focus`
  分支 + `focus` 字段(两者经 sibling import 共享 focus_scope,DRY)。
- **改提示词**: `core/prompts/stages/sra-clarify.md`、`sra-augment.md` 各加一段覆盖层(srr 零新增提示词复用)。
- **改分发物**: 4 个命令壳 + `security-dimensions.md` + 2 份契约文档(install 分发,须过 R5.10 纯净性)。
- **CLI 契约变更**(R5.1): 两脚本 `--help` 增 `--focus`;4 壳 bash 块镜像;`check_contracts.py` 自动断言。
- **依赖**: 零新增 `pip`(R2);focus_scope 纯标准库。
- **回归面**: 无 `--focus` 路径须逐字等价今天(focus=null);新测试覆盖闭集校验/退出码/嵌入/向后兼容。
- **文档**: `docs/mgh-sra-工作流程详解.md` §6/§8 增条目(承 R3 简练)。
