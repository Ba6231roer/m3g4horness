## Why

`/mgh-sast` 的 s4/s6 扇出与 `/mgh-init` **同根**:枚举脚本 `list_chunks.py`/`list_verify_jobs.py` 只回 *lite*
`pending[]`(`chunk_id`+路径 / `finding_id`+路径),但 `sast-deepdive`/`sast-verify` 需**完整 per-unit 记录**
(chunk 的 `files[]`+`threat_id`+`hypothesis` / finding 的 source-sink 锚点)。sanctioned 出口无「按单元取完整记录」
原语 → 编排器被推向整份读 `s3_chunks.json`/`s5_filtered.json`,叠加上下文无阈值,大 diff/大 finding 集会撑爆请求
上下文。地基变更 `harden-mgh-init-context-budget` 已立横切能力 `request-context-budget`(机制 + 物化契约 + hook
recipe + init 参考实现)。本 change 是 **sast 采纳**:把该机制照搬到 sast 两个枚举脚本与对应 stage。

## What Changes

- **`list_chunks.py` / `list_verify_jobs.py` 采纳物化/分页/预算**:增 `--materialize <dir>`(每 chunk/finding 完整输入
  写到 `<repo>/security-scan/inputs/{s4,s6}/<unit>.input.json`)、`--offset`/`--limit`、`--max-unit-bytes`/
  `--orch-budget-bytes`;`pending[]` slim 化(完整 `files[]`/`source_ref`/`sink_ref` 下沉进 input 文件)+ 加
  `input_path`/`bytes`/`oversize`;单页 > `--orch-budget-bytes` 自动收紧 `--limit` + `effective_limit`/`shrunk:true`。
- **oversize 处置**:chunk 含 > `--big-file-bytes` 文件 → 强制 `needs_slice` 走 `chunk_sources`(既有机制);verify-job
  通常不大,超阈值标 `oversize` + recipe(不切)。
- **stage 提示词**:`sast-deepdive.md`/`sast-verify.md` 输入改「读 `input_path`」。
- **命令壳(双端)**:`mgh-sast.md` 纪律段 + flow(物化 → 分页迭代 → 透传 input_path)+ flag 表 + disclose。
- **契约 lint + 测试**:`tools/check_contracts.py` 加 sast 两脚本 flag;`tests/` 增物化/分页/oversize 测。
- **hook 复用(无改动)**:`block_adhoc_scripts` recipe 已由地基变更一次覆盖四运行域(`MGH_SAST_ACTIVE` 在列)。

**依赖**:本 change 依赖地基 `harden-mgh-init-context-budget` 先落地(它立 `request-context-budget` spec +
`unit-inputs.md` 契约 + hook recipe + `--materialize` 参考实现)。本 change 只读引用该 spec,不改跨命令代码。
**非目标**:不改 sast 既有产物 schema(只加 `input_path`/`bytes`/`oversize` + `inputs/`);不引入依赖(承 R2);
聚合 stage(s1 scope / s2-s3)P0 仅披露。

## Capabilities

### Modified Capabilities
- `sast-orchestration-discipline`: s4 `list_chunks` + s6 `list_verify_jobs` 采纳 `request-context-budget` 物化/分页/
  预算;编排器纪律增「NEVER 整份读 `s3_chunks.json`/`s5_filtered.json`」;`sast-deepdive`/`sast-verify` 读 `input_path`。

## Impact

- **代码**:`core/scripts/list_chunks.py`/`list_verify_jobs.py`(物化 + 分页 + `bytes`/`oversize`);`sast-deepdive.md`/
  `sast-verify.md`(输入改 `input_path`);`mgh-sast.md`(claude+opencode,纪律/flow/flag/discard)。
- **契约/测试**:`tools/check_contracts.py` 加 sast flag;`tests/` 增两脚本物化/分页/oversize 测 + 纪律回归
  (整份读 s3/s5 产物被 hook 拦)。
- **依赖**:地基 change 先行。
- **铁律对齐**:R2/R5.2/R5.3a/b/R5.5/R5.8/R5.9/R5.10(同地基)。
- **诚实边界**:sast s4/s6 per-unit + 编排器请求确定性有界;聚合 stage(s1/s2-s3)P0 披露软边界。
