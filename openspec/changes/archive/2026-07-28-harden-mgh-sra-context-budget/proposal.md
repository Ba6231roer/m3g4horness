## Why

`/mgh-sra` 的 a3 per-capability 扇出与 `/mgh-init` **同根**:`prepare_augment.py` 产**单一聚合** `change_context.json`
(全 cap requirements + candidate_controls + memory)+ lite `pending[]`(每 cap 只有 `capability`/`draft_path`/
`done_marker`),但 `sra-augment` 需**该 cap 的完整输入**(requirements + 相关 endpoints/data_fields/role_hints +
candidate_controls 切片 + memory)。sanctioned 出口无「按 cap 取完整记录」原语 → 编排器被推向整份读
`change_context.json`(大变更 + 大 inventory 时撑爆请求上下文)。地基变更 `harden-mgh-init-context-budget` 已立横切
`request-context-budget`。本 change 是 **sra 采纳**。

## What Changes

- **`prepare_augment.py` 采纳物化/分页/预算**:增 `--materialize <dir>`(把每 cap 完整输入切到
  `<change-root>/.mgh-sra/inputs/<cap>.input.json`:该 cap `requirements[]` + 相关 endpoints/data_fields/role_hints +
  `candidate_controls` 切片[复用既有 `_candidate_controls` 的 file_overlap 判定] + memory)、`--offset`/`--limit`、
  `--max-unit-bytes`/`--orch-budget-bytes`;`pending[]` 加 `input_path`/`bytes`/`oversize`;单页 >
  `--orch-budget-bytes` 自动收紧 `--limit` + `effective_limit`/`shrunk:true`。
- **oversize 处置**:单 cap input 超 `--max-unit-bytes` → 标 `oversize:true` + recipe(分变更 / `--focus` 收窄;**不**切分
  capability,sra-augment 需整 cap 视图)。
- **stage 提示词**:`sra-augment.md` 输入改「读 `input_path`」;`sra-clarify.md`/`sra-consistency.md` 增聚合 `bytes`
  披露护栏(a2 单上下文扫全变更、a4 全部 drafts——P0 软边界)。
- **命令壳(双端)**:`mgh-sra.md` 纪律段 + flow + flag 表 + disclose。
- **契约 lint + 测试**:`check_contracts.py` 加 `prepare_augment` flag;`tests/` 增 per-cap 物化(切片语义)/分页/oversize 测。
- **hook 复用(无改动)**:`block_adhoc_scripts` recipe 已由地基覆盖 `MGH_SRA_ACTIVE`。

**依赖**:地基 `harden-mgh-init-context-budget` 先落地。**非目标**:不改 sra 产物 schema(只加新字段 + `inputs/`);
不改 `merge_augment`/`merge_memory`(确定性合并,无 LLM);不引入依赖(承 R2);聚合 stage(a2/a4)P0 仅披露。

## Capabilities

### Modified Capabilities
- `security-augmentation`: a3 `prepare_augment` per-capability 物化(`change_context.json` 切 per-cap input)+ 分页/预算;
  编排器 NEVER 整份读 `change_context.json`;`sra-augment` 读 `input_path`;a2/a4 聚合 `bytes` 披露。

## Impact

- **代码**:`core/scripts/prepare_augment.py`(物化 + 分页 + `bytes`/`oversize`);`sra-augment.md`/`sra-clarify.md`/
  `sra-consistency.md`(输入/披露);`mgh-sra.md`(claude+opencode)。
- **契约/测试**:`check_contracts.py` 加 sra flag;`tests/` 增 `prepare_augment` per-cap 物化(切片语义)/分页/oversize 测
  + 纪律回归(整份读 `change_context.json` 被 hook 拦)。
- **依赖**:地基先行。
- **铁律对齐**:R2/R5.2/R5.3a/b/R5.5/R5.8/R5.9/R5.10。
- **诚实边界**:sra a3 per-cap + 编排器请求确定性有界;聚合(a2/a4)P0 披露软边界。
