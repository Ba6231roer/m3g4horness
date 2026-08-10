# Contract: `scout_plan.json` + `scout_candidates.json`

Producer: `core/scripts/plan_scout.py` (deterministic, stdlib). Consumer: orchestrator
(fans out `init-scout` per batch) + `init-scout-merge`.

## `scout_plan.json`

```json
{
  "repo": "<abs repo root>",
  "generated_by": "plan_scout.py",
  "targets_total": 812,
  "regex_known_count": 222,
  "truncated": false,
  "batches": [<Batch>, ...]
}
```

| field | type | note |
|---|---|---|
| `targets_total` | int | scout 目标文件数(regex 盲区) |
| `regex_known_count` | int | 已被 regex 命中、排除出 scout 的文件数(产出者 emit,下游直接读,**禁自算**) |
| `truncated` | bool | 见下 |

A `Batch` (one S3 scout-reader isolation unit = resume unit):

```json
{
  "batch_id": "scout-001",
  "targets": [{"file":"...","pkg":"...","classes":[],"imports":[],
               "method_sigs":[],"fan_in":0,"bytes":0}, ...],
  "bytes": 95230,
  "needs_slice": []
}
```

| field | type | note |
|---|---|---|
| `batch_id` | str | `scout-NNN`;确定性,= checkpoint 单元(`checkpoints/scout/<batch_id>.json.done`) |
| `targets[]` | [FileSkeleton] | 本批 skeleton 行(已按 `pkg` 排序 → **包内聚**) |
| `bytes` | int | 本批累计 bytes;MUST ≤ `--scout-batch-bytes` |
| `needs_slice[]` | [file] | 单文件 `bytes > --scout-batch-bytes` 者,scout-reader 须经 `chunk_sources.py` 切片,**不整文件喂 LLM** |

- **批数涌现**:`num_batches = ceil(Σtarget_bytes / --scout-batch-bytes)`,非固定常量。
- **包内聚**:切批前按 `pkg` 排序,同目录相关文件落同批。
- **每批文件数 ≤ `--scout-batch-cap`**(防 subagent 赶进度草率)。
- `truncated`:`targets_total > --scout-budget` 时为真;编排器须建议 `--scope`+`--merge`(无静默)。

## `scout_candidates.json`

Producer: `init-scout-merge` (S4, single context, structured-only — no raw code).
Consumer: orchestrator merges with regex candidates → `form_clusters`.

```json
{
  "repo": "<abs repo root>",
  "candidates": [<Candidate subset with source:"scout">, ...],
  "unresolved": ["<file>", ...]
}
```

- 每条 candidate 是 Candidate schema 子集(`file/line/category/kind/anchor/shape/
  evidence_snippet/confidence`)且 `source:"scout"`;evidence MUST 指向真实 Read 过的锚点。
- `unresolved[]`:scout 发现的 DI/AOP/反射等文本调用图无法解析的控制(并入既有
  `unresolved[]`,标 source)。
- merge 只做跨批去重 + 命名归一;**不做 canonical 判定**(留给 T2)。
- **类别归一在 fold-in 边界**(`merge_scout.py` 调 `init_tier.normalize_category`):
  `access-control→authorization`、`auth→authentication` 等确定性别名映射在写入
  `controls_candidates.json` 前完成,T2 只见规范 8 类;未映射的非规范类在 fold-in / `--check`
  边界 fail-loud(退出码 2),**不**带漂移进 T2。
- **fold-in 级联失效**:`merge_scout.py` fold-in 实际并入候选数 > 0 时,删除下游聚合 `.done`
  (t2 `synthesis.json.done`/`.done`、t3 `*.json.done`、t4 `consistency.json.done`/`.done`),
  stderr 注明 + stdout `invalidated_tiers[]`;并入 == 0(全重复/全失败)时不删(输入没变)。
  t1 各簇 `.done` 保留(scout 簇 fold-in 后自然成新 pending)。
