# Contract: `list_rule_jobs.py` stdout (T3 pending work-list)

Producer: `core/scripts/list_rule_jobs.py` (deterministic, stdlib). Consumer: orchestrator
T3 fan-out(步骤 6)。闭合第三处扇出:T1 有 `list_clusters.py`、scout 有
`list_scout_batches.py`、T3 用本脚本。编排器取「按-category 待跑清单」MUST 走本脚本,
NEVER 手挖 `controls_inventory.json` / `py -c` 内省。

CLI(`--help` 即契约):
```
py list_rule_jobs.py --inventory <controls_inventory.json>
    --format opencode|claude [--checkpoints <t3-dir>] [--target <dir>]
    [--rules-dir <dir>]
```

stdout(结构化 JSON;stderr 仅诊断):
```json
{"total": N, "done": M, "pending": [<RuleJobLite>, ...], "format": "opencode"}
```

`<RuleJobLite>`:
```json
{"category": "crypto", "format": "opencode",
 "rule_path": "<abs target>/docs/security-controls/crypto.md",
 "done_marker": "<abs checkpoints>/crypto.opencode.json.done"}
```

| field | note |
|---|---|
| `total` | inventory 中 distinct category 数 |
| `done` | `#已 done` category(`checkpoints/t3/<category>.<format>.json.done` 存在) |
| `pending[]` | 未 done category;每项 `{category,format,rule_path,done_marker}` |
| `rule_path` | **绝对**(`--target` 经 `Path.resolve()`,即便缺省 `.` 也是绝对);claude→`<abs target>/.claude/rules/security-<cat>.md`;opencode→`<abs target>/<rules-dir>/<cat>.md`(`--rules-dir` 默认 `docs/security-controls`,相对 `--target` 解析后再 `Path.resolve()`)。编排器**逐字透传**给 rulewriter subagent,subagent **恰好写该绝对路径**(NEVER 自拼 `<target>/<category>`、NEVER 相对路径、NEVER 写项目外)。 |
| `done_marker` | **绝对**;`<abs checkpoints>/<cat>.<format>.json.done`,subagent 写完详述文件后 touch 它。 |

不变式:`total == done + len(pending)`。空 inventory(0 controls)→ `total:0`,退出码仍 `0`。
退出码 `0/1/2`。`rule_path`/`done_marker` **仅存在于本 stdout**,不写入磁盘产物。
