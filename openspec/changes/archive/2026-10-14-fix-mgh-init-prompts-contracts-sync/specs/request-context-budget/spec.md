# fix-mgh-init-prompts-contracts-sync — request-context-budget delta

## MODIFIED Requirements

### Requirement: Aggregate-stage inputs are bounded or disclosed

每条 `mgh-*` 命令的聚合 stage(init T2/merge/T4、sast scope、sra a2/a4、srr render)SHALL 上报其聚合
输入字节数(产出者 stdout 字段
或 `describe_artifact --count --field`),且 MUST 在聚合输入超过 `--max-aggregate-bytes` 时被处置(切分 /
标注 / 披露之一,**NEVER** 静默整份喂入)。**P0**:编排器 SHALL 建议 `--scope`(init/sast;多次局部运行产物独立)或
分变更/分文档(sra/srr)并经命令 manifest `boundaries[]` + 人读报告披露该聚合未硬界(对标各命令既有
optional/advisory/non-fatal 语义)。**P1 目标**(后续 change)SHALL 经分层归约(per-unit summary 分组 →
逐组归约 → 归约再归约)使聚合请求亦 ≤ `--max-aggregate-bytes`。本 requirement 不声称 P0 已对聚合节点
提供硬阈值——P0 为「披露 + 回退」软边界。

#### Scenario: Aggregate input size is reported (generic)
- **WHEN** 任一聚合 stage 即将运行,编排器需知其输入大小
- **THEN** 该量可由产出者 stdout 字段或 `describe_artifact.py` 上报,编排器不 `py -c` 自算

#### Scenario: Oversize aggregate advises fallback and is disclosed
- **WHEN** 任一聚合 stage 输入 > `--max-aggregate-bytes`
- **THEN** 编排器建议对应的收窄/切分杠杆(`--scope` / 分变更 / `--split`),并在该命令 manifest
  `boundaries[]` 与人读报告披露「聚合超预算、未硬界、建议收窄」(P0 软边界)
