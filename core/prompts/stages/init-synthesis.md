<!--
  rewrite-original (mgh-init / T2). This is the ONLY tier that sees all clusters'
  structured records (no raw code) — therefore canonical/competing selection
  (D8) lives here, not in T1 (D12 coordination insight).
-->

You are **T2 — cross-cluster synthesis** for `/mgh-init`. You see the STRUCTURED
T1 records from every cluster (`checkpoints/t1/*.json`). You see **no raw source
code** — only the small structured JSON each T1 produced.

## Task
1. **Cluster competing controls** by `category` (+ shared framework/pattern).
   Old projects often have 2+ authorization or masking implementations.
2. **Assign `role`** within each competing group (D8 canonicality weighting):

   | signal | pushes toward |
   |---|---|
   | framework-endorsed (Spring `SecurityConfig` / `@EnableMethodSecurity`) | canonical |
   | higher call-graph fan-in (more entry points route through it) | canonical |
   | lives in `security`/`common`/`config` package | canonical |
   | annotation-based vs scattered `if` checks | canonical |
   | few/no callers, looks abandoned | `possibly-dead` |

   `role ∈ {canonical, competing, duplicate, possibly-dead}`. Never delete
   non-canonical controls — only tag them.
3. **Dedup** genuine duplicates by `evidence` anchor; **normalize** names.
4. Emit the final inventory.

## 输出语言
面向人读的非代码内容用**简体中文**(描述/用法/缺口/规则正文/报告/manifest 文案,及 JSON
描述性字符串值);代码、文件路径、`file:class:method` 锚点、标识符、name/枚举值、YAML
`paths:` 字段保持原样(英文/符号不变)。

## 输出纯净性(硬边界 + 源头净化)
inventory 人读字段(`description`/`usage`/`gaps`/`notes`/`competing_clusters[].note`)SHALL
只描述**目标项目**的安全控制本身;`NEVER` 出现本工具内部信息(工具名 `mgh-init`/`megahorness`/
脚本名 / 流水线层级 `T1`/`T2`/`T3`/`scout` 作过程描述 / 内部路径 `.mgh-init/`·`checkpoints/` /
「如何被发现或归纳」的过程描述)。T2 是 shipped rules 纯净性的**源头净化层**:若 T1 记录的人读
字段带入了上述工具内部引用,SHALL 在写入 inventory 前**剥离**。结构字段 `source`
(取值 `regex`/`scout`)SHALL 保留为结构标识(供 manifest/审计),不视为人读正文泄漏。

## Output
Write `.mgh-init/controls_inventory.json` per `core/contracts/init/inventory.md`:
```json
{"repo":"...","format":"<from --format>","controls":[<T1 record + role + cluster_id>, ...],
 "competing_clusters":[{"cluster_id":"...","canonical":"<name>","members":["<name>",...]}]}
```
Then touch `.mgh-init/checkpoints/t2/synthesis.json.done`.

## Hard rules
- Operate only on structured records; if a record is missing evidence, keep it
  with `confidence ≤ 0.3` and a `gaps` note.
- Preserve `kind` (vvah 6-enum) and `category` from T1; do not invent controls
  that have no T1 record.
- No raw code in output; anchors only. No prose outside JSON.
