# Contract: `list_scout_batches.py` stdout (scout pending work-list)

Producer: `core/scripts/list_scout_batches.py` (deterministic, stdlib). Consumer:
orchestrator scout fan-out (步骤 3b). Closes the fan-out asymmetry: scout now has a
`list_clusters.py`-equivalent — 编排器取「待跑批清单」MUST 走本脚本,NEVER 手挖
`scout_plan.json` / `py -c` 内省。

CLI(`--help` 即契约):
```
py list_scout_batches.py --scout-plan <scout_plan.json> [--checkpoints <scout-dir>]
```

stdout(结构化 JSON;stderr 仅诊断):
```json
{"repo": "...", "total": N, "done": M, "failed": F, "pending": [<BatchLite>, ...], "truncated": false}
```

`<BatchLite>`:
```json
{"batch_id": "scout-001", "targets_count": 12, "bytes": 95230, "needs_slice": [],
 "checkpoint_path": "<abs>/checkpoints/scout/scout-001.json",
 "done_marker": "<abs>/checkpoints/scout/scout-001.json.done",
 "failed_marker": "<abs>/checkpoints/scout/scout-001.json.failed"}
```

| field | note |
|---|---|
| `total` | `len(scout_plan.json::batches[])`(真批数) |
| `done` | `#已 done` 批(`checkpoints/scout/<batch_id>.json.done` 存在;排除 `merge.json`/`audit.json` tier 级标记) |
| `failed` | `#终态失败` 批(`<batch_id>.json.failed` 存在;**终态、排除出 pending、resume 不重试**;同样排除 `merge.json.failed`/`audit.json.failed`)。crash 无 `failed` ack → 无 marker → 仍 `pending` → resume 重派 |
| `pending[]` | 未 done **且** 未 failed 批,文件序;每项 `{batch_id,targets_count,bytes,needs_slice[],checkpoint_path,done_marker,failed_marker}` |
| `checkpoint_path` | **绝对**;由 `--checkpoints`(已 `resolve()`)拼 `<batch_id>.json` 得出。编排器**逐字透传**给 scout subagent,subagent **恰好写该绝对路径**(NEVER 自拼 `<target>/<batch_id>`、NEVER 发明文件名、NEVER 相对路径)。 |
| `done_marker` | **绝对**;`<checkpoint_path>.done`,subagent 成功写完产物后 touch 它。 |
| `failed_marker` | **绝对**;`<checkpoint_path>.failed`(与 `.done` sibling)。**编排器**在收到 subagent `failed <reason>` ack 后 `Write` 它(body `{unit,reason,tier}`;路径取本 stdout `pending[].failed_marker` 逐字透传,NEVER 自拼)。subagent 失败路径 **touch nothing**。 |
| `truncated` | 透传 `scout_plan.json::truncated`(无静默截断) |

不变式:`total == done + failed + len(pending)`。空 batches(`--no-scout` 或 0 target)→ `total:0`,
退出码仍 `0`。退出码 `0/1/2`。`checkpoint_path`/`done_marker`/`failed_marker` **仅存在于本 stdout**,不写入磁盘
产物(磁盘 `checkpoints/scout/<batch_id>.json` schema 不变)。
