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
{"repo": "...", "total": N, "done": M, "pending": [<BatchLite>, ...], "truncated": false}
```

`<BatchLite>`:
```json
{"batch_id": "scout-001", "targets_count": 12, "bytes": 95230, "needs_slice": []}
```

| field | note |
|---|---|
| `total` | `len(scout_plan.json::batches[])`(真批数) |
| `done` | `#已 done` 批(`checkpoints/scout/<batch_id>.json.done` 存在) |
| `pending[]` | 未 done 批,文件序;每项 `{batch_id,targets_count,bytes,needs_slice[]}` |
| `truncated` | 透传 `scout_plan.json::truncated`(无静默截断) |

不变式:`total == done + len(pending)`。空 batches(`--no-scout` 或 0 target)→ `total:0`,
退出码仍 `0`。退出码 `0/1/2`。
