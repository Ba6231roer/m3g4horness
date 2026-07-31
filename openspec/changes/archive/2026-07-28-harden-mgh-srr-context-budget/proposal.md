## Why

`/mgh-srr` 经 intake 适配器 `ingest_requirements.py` 产 sra-shape `change_context.json` + `pending[]`(默认 1 单元 =
整文档;`--split` 按标题切),再**逐字复用 sra 中间引擎**(`sra-clarify`/`sra-augment`)。其扇出与 sra **同根**:
intake 产 lite `pending[]` + 聚合 `change_context.json`,subagent 需 per-unit 完整记录 → 编排器被推向整份读聚合。
地基 `harden-mgh-init-context-budget` 已立横切 `request-context-budget`。本 change 是 **srr 采纳**。

## What Changes

- **`ingest_requirements.py` 采纳物化/分页/预算**:增 `--materialize <dir>`(per-unit 完整输入写到
  `<out-dir>/inputs/<unit>.input.json`)、`--offset`/`--limit`、`--max-unit-bytes`/`--orch-budget-bytes`;`pending[]` 加
  `input_path`/`bytes`/`oversize`;单页 > `--orch-budget-bytes` 自动收紧 `--limit` + `effective_limit`/`shrunk:true`。
- **oversize 处置**:unit input 超 `--max-unit-bytes` → 标 `oversize:true` + recipe(`--split` 切更细 / 收窄文档;**不**切分单元)。
- **`render_report.py` 聚合披露**:读全部定稿(聚合输入)上报 `bytes`;超 `--max-aggregate-bytes` → 披露(P0 软边界)。
- **命令壳(双端)**:`mgh-srr.md` 纪律段 + flow + flag 表 + disclose。
- **契约 lint + 测试**:`check_contracts.py` 加 `ingest_requirements` flag;`tests/` 增物化/分页/`--split`/oversize 测。
- **hook 复用(无改动)**:`block_adhoc_scripts` recipe 已由地基覆盖 `MGH_SRR_ACTIVE`。

**依赖**:本 change 依赖地基 `harden-mgh-init-context-budget` + sra 采纳 `harden-mgh-sra-context-budget`(srr 逐字复用
`sra-augment.md`,该提示词「读 `input_path`」的改造归 sra 采纳;intake 物化的 `input_path` 须经由该改造才被引擎消费)。
**非目标**:不改 srr 产物 schema(只加新字段 + `inputs/`);不 fork sra 引擎(硬约束:middle engine reused verbatim);
不引入依赖(承 R2)。

## Capabilities

### Modified Capabilities
- `freeform-security-review`: `ingest_requirements` 采纳物化/分页/预算;`pending[]` 加 `input_path`/`bytes`/`oversize`;
  编排器 NEVER 整份读 sra-shape `change_context.json`;`render_report` 聚合 `bytes` 披露。

## Impact

- **代码**:`core/scripts/ingest_requirements.py`(物化 + 分页 + `bytes`/`oversize`);`mgh-srr.md`(claude+opencode)。
- **契约/测试**:`check_contracts.py` 加 srr flag;`tests/` 增 `ingest_requirements` 物化/分页/`--split`/oversize 测 +
  纪律回归(整份读 srr `change_context.json` 被 hook 拦)。
- **依赖**:地基 + sra 采纳先行。
- **铁律对齐**:R2/R5.2/R5.3a/b/R5.5/R5.8/R5.9/R5.10。
- **诚实边界**:srr per-unit + 编排器请求确定性有界;`render_report` 聚合 P0 披露软边界。
