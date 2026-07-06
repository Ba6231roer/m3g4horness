# Contract: `list_rule_jobs.py` stdout (T3 pending work-list)

Producer: `core/scripts/list_rule_jobs.py` (deterministic, stdlib). Consumer: orchestrator
T3 fan-out(步骤 6)。闭合第三处扇出:T1 有 `list_clusters.py`、scout 有
`list_scout_batches.py`、T3 用本脚本。编排器取「按-category 待跑清单」MUST 走本脚本,
NEVER 手挖 `controls_inventory.json` / `py -c` 内省。

CLI(`--help` 即契约):
```
py list_rule_jobs.py --inventory <controls_inventory.json>
    --format opencode|claude [--checkpoints <t3-dir>] [--target <dir>]
```

stdout(结构化 JSON;stderr 仅诊断):
```json
{"total": N, "done": M, "pending": [<RuleJobLite>, ...], "format": "opencode"}
```

`<RuleJobLite>`:
```json
{"category": "crypto", "format": "opencode",
 "rule_path": "<target>/.mgh-init/rules-parts/crypto.md"}
```

| field | note |
|---|---|
| `total` | inventory 中 distinct category 数 |
| `done` | `#已 done` category(`checkpoints/t3/<category>.<format>.json.done` 存在) |
| `pending[]` | 未 done category;每项 `{category,format,rule_path}` |
| `rule_path` | claude→`<target>/.claude/rules/security-<cat>.md`;opencode→`<target>/.mgh-init/rules-parts/<cat>.md` |

不变式:`total == done + len(pending)`。空 inventory(0 controls)→ `total:0`,退出码仍 `0`。
退出码 `0/1/2`。
