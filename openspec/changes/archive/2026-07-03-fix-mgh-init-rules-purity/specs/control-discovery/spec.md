## ADDED Requirements

### Requirement: Inventory human-readable fields exclude tool-internal content

`controls_inventory.json` 的面向人读字段 SHALL 只描述目标项目的安全控制本身,且 MUST NOT
携带任何本工具内部信息。受约束的人读字段为 `description`、`usage`、`gaps`、`notes`、
`competing_clusters[].note`。被禁止的工具内部信息包括:本工具名、发现/归纳脚本名
(`discover_controls.py`、`chunk_sources.py`、`plan_scout.py`、`merge_scout.py`、
`list_clusters.py`、`assemble_rules.py` 等)、作为过程描述的流水线层级标签
(`T1`、`T2`、`T3`、`scout`)、内部路径(`.mgh-init/`、`checkpoints/`、`rules-parts/`),以及
任何「如何被本工具发现或归纳」的过程描述。结构/标识字段(`name`、`kind`、`category`、`role`、
`cluster_id`、`evidence`、`protects`、`entry_points`、`confidence`)与目标项目的 evidence 锚点、
文件路径 SHALL 保持原样。该约束 SHALL 同时写入 T1 `init-induct`、S3 `init-scout`、
T2 `init-synthesis` 的提示词,作为 shipped rules 纯净性的源头防线。结构字段 `source`
(取值 `regex` 或 `scout`)SHALL 保留为结构标识,供 manifest 与审计使用,不视为人读正文泄漏。

#### Scenario: usage field describes target-project invocation only

- **WHEN** T1 归纳出 Spring 方法级安全控制,写入其 `usage` 字段
- **THEN** `usage` 以「开发者如何调用/注解」陈述目标项目用法,不含 `discover_controls.py` 或「经 regex 发现」等过程描述

#### Scenario: gaps field states effectiveness caveats only

- **WHEN** T1 发现参数化类型上 `@PreAuthorize` 的绕过形态,写入 `gaps`
- **THEN** `gaps` 描述该控制的有效性缺口(目标项目语义),不含 `chunk_sources.py`、`.mgh-init/checkpoints/` 等工具内部引用

#### Scenario: source field retained as structural tag

- **WHEN** 一条控制由 scout 子阶段发现
- **THEN** 其结构字段 `source: "scout"` 保留(供 manifest/审计);该值不是人读正文,不构成泄漏

#### Scenario: T2 strips residual tool-internal references

- **WHEN** 某 T1 记录的人读字段不慎带入工具内部引用,T2 `init-synthesis` 综合该记录
- **THEN** T2 在写入 `controls_inventory.json` 前剥离这些引用,使最终 inventory 人读字段干净
