## Context

地基 `harden-mgh-init-context-budget` 已立 per-unit 输入物化 + slim 分页 + 字节预算 横切机制。`/mgh-srr` 经 intake
适配器 `ingest_requirements.py` 产 sra-shape `change_context.json` + `pending[]`,**逐字复用 sra 引擎**
(`sra-clarify`/`sra-augment`,硬约束:不 fork)。其扇出与 sra 同根。本 change = 把物化机制落到 srr 的 intake 适配器。
hook recipe 已由地基覆盖 `MGH_SRR_ACTIVE`。

## Goals / Non-Goals

**Goals:** srr 编排器 NEVER 整份读 sra-shape `change_context.json`;per-unit stage(复用 sra 引擎)读自己的
`input_path`(≤ `--max-unit-bytes`);`pending[]` 分页 ≤ `--orch-budget-bytes`;`render_report` 聚合 `bytes` 可上报。

**Non-Goals:** 不 fork/改 sra 引擎提示词(归 sra 采纳;硬约束 middle engine reused verbatim);不改 srr 产物 schema;
不改 hook(地基已覆盖);聚合 P0 仅披露;不引入依赖。

## Decisions

### D1 — 物化落在 intake 适配器(引擎透传)

`ingest_requirements.py` 增 `--materialize`/`--offset`/`--limit`/`--max-unit-bytes`/`--orch-budget-bytes`,物化路径
`<out-dir>/inputs/<unit>.input.json`。`pending[]` 加 `input_path`/`bytes`/`oversize`。per-unit stage = 复用 sra 引擎;
`input_path` 经 sra 采纳改造的 `sra-augment.md`「读 `input_path`」被消费。机制细节逐字对齐地基。

### D2 — 依赖 sra 采纳(共享引擎提示词)

srr 不改 `sra-augment.md`(middle engine reused verbatim)。该提示词「读 `input_path`」的改造归 sra 采纳
`harden-mgh-sra-context-budget`。故本 change apply 序 = 地基 → sra → srr。srr 的 intake 物化在 sra 采纳前 apply 不会
被引擎消费(但 intake 侧改动本身独立、可先行落地)。

### D3 — oversize 不切分(unit 为评审原子)

unit input 超 `--max-unit-bytes` → 标 `oversize:true` + recipe(`--split` 切更细标题 / 收窄文档);**不**切分单元。

## Risks / Trade-offs

- **[apply 序依赖地基+sra]** → proposal/design/tasks 已声明;intake 侧独立可先落地,引擎消费待 sra。
- **[default 单元 = 整文档,大文档易超预算]** → `--split` 切标题 + `oversize` 标注兜底;input 文件 ≤ `--max-unit-bytes`。
- **[地基/sra 未落地则引用悬空]** → 本 change 须在其后 apply。

## Migration Plan

1. `ingest_requirements.py` 加 flag + per-unit 物化 + slim `pending[]` + 页宽收紧(保留无 `--materialize` 旧路径)。
2. 两份 `mgh-srr.md` 壳:纪律/flow/flag/discard。
3. `render_report.py` 聚合 `bytes` 上报 + 超限披露(P0)。
4. `check_contracts.py` 加 srr flag;测试(物化/分页/`--split`/oversize/纪律回归)。
5. 版本 bump;**回滚** = 还原脚本/壳,`inputs/` 可删,既有产物 schema 不变。

## Open Questions

- default 单元(整文档)超大时,是否默认建议 `--split`?(倾向:oversize 标注 + recipe 提示,不强制改 default。)
