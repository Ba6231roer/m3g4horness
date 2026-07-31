## Context

地基 `harden-mgh-init-context-budget` 已确立 per-unit 输入物化 + slim 分页待办壳 + 字节预算 的横切机制(见
`request-context-budget` spec + `core/contracts/init/unit-inputs.md`)+ init 参考实现(`list_clusters.py` 等)。
`/mgh-sast` 扇出同构:`list_chunks.py`(s4)/`list_verify_jobs.py`(s6)产 lite `pending[]`,`sast-deepdive`/`sast-verify`
需完整 per-unit 记录。本 change = 照搬地基机制到 sast。hook recipe 已由地基覆盖 `MGH_SAST_ACTIVE`,无需再改 hook。

## Goals / Non-Goals

**Goals:** sast s4/s6 编排器 NEVER 整份读 `s3_chunks.json`/`s5_filtered.json`;`sast-deepdive`/`sast-verify` 读
自己的 `input_path`(≤ `--max-unit-bytes`);待办壳分页 ≤ `--orch-budget-bytes`。

**Non-Goals:** 不改 sast 产物 schema(只加新字段 + `inputs/`);不改 hook(地基已覆盖);聚合 stage(s1 scope /
s2-s3 hypothesis)P0 仅 `bytes` 披露 + `--scope` 回退,P1 分层归约留后续;不引入依赖。

## Decisions

### D1 — 逐字采纳地基机制(参考 `list_clusters.py`)

`list_chunks.py`/`list_verify_jobs.py` 增 `--materialize`/`--offset`/`--limit`/`--max-unit-bytes`/`--orch-budget-bytes`,
物化路径 `<repo>/security-scan/inputs/{s4,s6}/<unit>.input.json`。`pending[]` slim 化 + `input_path`/`bytes`/
`oversize`。机制细节(自动收紧页宽、`effective_limit`/`shrunk`、退出码、自定位、零依赖)逐字对齐地基,不重新设计。
**备选(否决)**:复制粘贴地基共享 helper 为新模块——会漂移;优先内联为各脚本私有函数(同地基 D2/1.3 决策)。

### D2 — oversize 处置(sast 特化)

chunk 含 > `--big-file-bytes` 文件 → `needs_slice` 走 `chunk_sources`(既有);verify-job 超 `--max-unit-bytes` →
标 `oversize:true` + recipe(`--scope` 收窄 diff;不切分,s6 单 finding 为最小验证单元)。

## Risks / Trade-offs

- **[chunk 物化含多文件,单 chunk 易超预算]** → `needs_slice` 切片兜底(既有);input 文件 ≤ `--max-unit-bytes`。
- **[sast 产物在 `<repo>/security-scan/`]** → `inputs/` 落该目录,随既有产物 gitignore。
- **[地基未落地则本 change spec 引用悬空]** → 本 change 须在地基 apply+archive 后 apply;proposal/design 已声明依赖。

## Migration Plan

1. 两脚本加 flag + 物化 + slim 壳 + 页宽收紧(保留无 `--materialize` 旧路径)。
2. 两 stage 提示词输入改 `input_path`。
3. 两份 `mgh-sast.md` 壳:纪律/flow/flag/discard。
4. `check_contracts.py` 加 sast flag;测试(物化/分页/oversize/纪律回归)。
5. 版本 bump;**回滚** = 还原两脚本/提示词/壳,`inputs/` 可删,既有产物 schema 不变。

## Open Questions

- s6 verify-job oversize 是否真不切?(倾向:不切,单 finding 为原子验证单元。)
