# Contract: `list_clusters.py` stdout (T1 pending work-list)

Producer: `core/scripts/list_clusters.py` (deterministic, stdlib). Consumer: orchestrator
T1 fan-out(步骤 4)。编排器取「待跑簇清单」MUST 走本脚本,NEVER 手挖 `clusters.json`
/ `py -c` 内省(`clusters.json` 是包装字典 `{repo,clusters[],truncated}`,对顶层 `len()`
得 3 **不是**簇数;簇数真相源 = `list_clusters.py` stdout 的 `total`)。

CLI(`--help` 即契约):
```
py list_clusters.py --clusters <clusters.json> [--checkpoints <t1-dir>]
```

stdout(结构化 JSON;stderr 仅诊断):
```json
{"repo": "...", "total": N, "done": M, "failed": F, "pending": [<ClusterLite>, ...], "truncated": false}
```

`<ClusterLite>`:
```json
{"cluster_id": "authorization::Sec::<sha8>", "category": "authorization", "kind": "auth",
 "shape": "centralized", "evidence_files": ["src/.../Sec.java"], "candidate_count": 2,
 "checkpoint_path": "<abs>/checkpoints/t1/authorization__Sec__<sha8>.json",
 "done_marker": "<abs>/checkpoints/t1/authorization__Sec__<sha8>.json.done",
 "failed_marker": "<abs>/checkpoints/t1/authorization__Sec__<sha8>.json.failed"}
```
> `cluster_id` 含 `::`(NTFS ADS 分隔符)→ `checkpoint_path`/`done_marker`/`failed_marker` 的**文件名分量**经
> `_safe_name`(`/`、`\`、`:` → `_`)消毒(`::`→`__`);envelope `cluster_id` 字段保留**原始** canonical id。

| field | note |
|---|---|
| `total` | `len(clusters.json::clusters[])`(真簇数,非 wrapper key 数) |
| `done` | `#已 done` 簇(`checkpoints/t1/<safe(cluster_id)>.json.done` 存在;按记录 `unit` 字段 robust 读取) |
| `failed` | `#终态失败` 簇(`<safe(cluster_id)>.json.failed` 存在;**终态、排除出 pending、resume 不重试**)。crash 无 `failed` ack → 无 marker → 仍 `pending` → resume 重派(crash ≠ 确认失败) |
| `pending[]` | 未 done **且** 未 failed 簇,文件序;每项 `{cluster_id,category,kind,shape,evidence_files[],candidate_count,checkpoint_path,done_marker,failed_marker}` |
| `checkpoint_path` | **绝对**;由 `--checkpoints`(已 `resolve()`)拼 `<safe(cluster_id)>.json` 得出(`_safe_name` 消毒文件名分量)。编排器**逐字透传**给 T1 subagent,subagent **恰好写该绝对路径**(NEVER 自拼 `<target>/<cluster_id>`、NEVER 裸相对路径 `.mgh-init/...`、NEVER 写项目外)。 |
| `done_marker` | **绝对**;`<checkpoint_path>.done`,subagent 成功写完产物后 touch 它。 |
| `failed_marker` | **绝对**;`<checkpoint_path>.failed`(与 `.done` sibling)。**编排器**在收到 subagent `failed <reason>` ack 后 `Write` 它(body `{unit,reason,tier}`;路径取本 stdout `pending[].failed_marker` 逐字透传,NEVER 自拼)。subagent 失败路径 **touch nothing**。 |
| `truncated` | 透传 `clusters.json::truncated`(无静默截断) |

不变式(非切分簇):`total == done + failed + len(pending)`。空 clusters(0 候选)→ `total:0`,退出码仍 `0`。
退出码 `0/1/2`。`checkpoint_path`/`done_marker`/`failed_marker` **仅存在于本 stdout**,不写入磁盘产物
(磁盘 `checkpoints/t1/<safe(cluster_id)>.json` schema 不变;记录内 `unit` = canonical cluster_id)。
