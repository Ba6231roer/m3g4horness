# Contract: `clusters.json`

Producer: `core/scripts/discover_controls.py` (i1, deterministic, stdlib; written at
`discover_controls.py:489`). Consumers: `core/scripts/list_clusters.py` (T1 work-list),
`init-induct` (T1, per-cluster), `init-survey` (optional, advisory).

> **包装字典,非顶层数组。** 簇列表在 `clusters` 键下;对**顶层** `len()` 得 3(`repo`/
> `clusters`/`truncated`),**不是**簇数。簇数真相源 = `discover_controls.py` stdout 的
> `clusters` 字段,或 `list_clusters.py` stdout 的 `total`。编排器**禁手搓** `py -c` 内省。

Top-level shape:

```json
{
  "repo": "<abs repo root>",
  "clusters": [<Cluster>, ...],
  "truncated": false
}
```

A `Cluster`(one T1 isolation unit;源 `form_clusters` @ `discover_controls.py:409`):

```json
{
  "cluster_id": "authorization::SecurityConfig::<sha8>",
  "category": "authorization",
  "kind": "auth",
  "shape": "centralized",
  "evidence_files": ["src/.../SecurityConfig.java"],
  "usage_sites": ["src/.../TransferController.java"],
  "candidate_ids": ["C-0001", "C-0002"]
}
```

| field | type | note |
|---|---|---|
| `cluster_id` | str | `{category}::{anchor\|pattern}::{sha8}`;确定性 T1 隔离/resume 单元(D9=D12) |
| `category` | enum | init 8(见 `inventory.md`) |
| `kind` | enum | vvah 6(`auth`\|`input-validation`\|`sandbox`\|`aslr`\|`cfi`\|`other`);`category→kind` 归一见 `inventory.md` |
| `shape` | enum | `centralized`(util/filter/config/interceptor 定义,按 anchor 归簇)\| `distributed`(注解跨文件散落,按 `category::pattern` 归簇) |
| `evidence_files` | [file] | T1 必读文件集;centralized=成员去重,distributed=`usage_sites[:3]` |
| `usage_sites` | [file] | distributed 上限 `--sample`;centralized=证据文件 + 少量直接调用方 |
| `candidate_ids` | [`C-NNNN`] | 本簇成员候选 id(回指 `controls_candidates.json`) |

- **簇级无 `entry_points`**:`entry_points` 在 `Candidate` 上(仅 `distributed` shape 由
  `form_clusters` set 为 `usage_sites`)。T1 需入口信息时回查候选记录。
- `truncated` = discover 因 `--max-files` warn-and-continue 截断过扫描;`list_clusters.py`
  透传该标志,编排器须在 report 披露(无静默截断)。
- 大仓上 `clusters[]` 可能达数百量级——**禁止**单 subagent 一次性装载整份(见
  `init-survey` 的 optional/bounded 语义);T1 经 `list_clusters.py` 的 `pending[]` 逐簇隔离扇出。
