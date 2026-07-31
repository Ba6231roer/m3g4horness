## Context

地基 `harden-mgh-init-context-budget` 已立 per-unit 输入物化 + slim 分页 + 字节预算 横切机制(`request-context-budget`
spec + `unit-inputs.md`)+ init 参考。`/mgh-sra` a3 per-capability 扇出同构:`prepare_augment.py` 产聚合
`change_context.json` + lite `pending[]`,`sra-augment` 需 per-cap 完整输入。本 change = 照搬地基机制到 sra。hook
recipe 已由地基覆盖 `MGH_SRA_ACTIVE`。

## Goals / Non-Goals

**Goals:** sra 编排器 NEVER 整份读 `change_context.json`;`sra-augment` 读自己的 per-cap `input_path`
(≤ `--max-unit-bytes`);`pending[]` 分页 ≤ `--orch-budget-bytes`;a2/a4 聚合 `bytes` 可上报。

**Non-Goals:** 不改 `merge_augment`/`merge_memory`(确定性、无 LLM);不改 sra 产物 schema;不改 hook(地基已覆盖);
聚合 stage(a2/a4)P0 仅披露 + 分变更/`--focus` 回退,P1 分层归约留后续;不引入依赖。

## Decisions

### D1 — 逐字采纳地基机制 + sra 特化的 per-cap 切片

`prepare_augment.py` 增 `--materialize`/`--offset`/`--limit`/`--max-unit-bytes`/`--orch-budget-bytes`,物化路径
`<change-root>/.mgh-sra/inputs/<cap>.input.json`。per-cap input = 该 cap `requirements[]` + **相关** endpoints/
data_fields/role_hints + `candidate_controls` 切片 + memory。**"相关"判定**:复用既有 `_candidate_controls` 的
`file_overlap`(mentioned_files ∩ entry_points)确定性过滤——脚本内部切,不进编排器上下文。机制细节逐字对齐地基。

### D2 — oversize 不切分(capability 为 a3 原子单元)

单 cap input 超 `--max-unit-bytes` → 标 `oversize:true` + recipe(分变更跑 / `--focus` 收窄维度)。**不**切分 cap
(sra-augment 需整 cap 视图做维度缺口分析)。

## Risks / Trade-offs

- **[per-cap "相关" 切片语义]** → 复用 `_candidate_controls` 的 `file_overlap`,确定性可测;若过宽/过窄,实测后调。
- **[a2 单上下文扫全变更]** → a2 本就拿 `change_context 摘要`(非全量),P0 仅上报 `bytes` + 披露;不强行 bound。
- **[地基未落地则引用悬空]** → 本 change 须在地基 apply+archive 后 apply。

## Migration Plan

1. `prepare_augment.py` 加 flag + per-cap 物化 + slim `pending[]` + 页宽收紧(保留无 `--materialize` 旧路径)。
2. `sra-augment.md` 输入改 `input_path`;`sra-clarify.md`/`sra-consistency.md` 加聚合 `bytes` 披露护栏。
3. 两份 `mgh-sra.md` 壳:纪律/flow/flag/discard。
4. `check_contracts.py` 加 sra flag;测试(per-cap 物化切片语义/分页/oversize/纪律回归)。
5. 版本 bump;**回滚** = 还原脚本/提示词/壳,`inputs/` 可删,既有产物 schema 不变。

## Open Questions

- per-cap input 的"相关 endpoints/fields"切片粒度(全量 vs file_overlap 过滤)?(倾向:复用 file_overlap。)
- `--focus` 收窄已减小 per-cap 范围,是否与 `--max-unit-bytes` 叠加足够?(实测后定。)
