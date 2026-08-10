# Contract: list_test_groups.py --tier rules stdout (rules pending work-list)

Producer: `core/scripts/list_test_groups.py` (deterministic, stdlib). Consumer: the
orchestrator (fans out one `ut-rulewriter` subagent per pending category).

CLI contract (`--help` 即契约):
```bash
py list_test_groups.py --tier rules --inventory <init-dir>/test_rules_inventory.json --format opencode|claude [--checkpoints <rules-dir>] [--target <dir>] [--rules-dir <dir>] [--materialize <inputs-dir>] [--offset N] [--limit N] [--max-unit-bytes B] [--orch-budget-bytes B]
```

## Output Schema

stdout (slim page; stderr = diagnostics):
```json
{
  "tier": "rules", "format": "opencode",
  "total": 3, "done": 1, "failed": 0,
  "pending": [<RuleJob>, ...],
  "offset": 0, "limit": 50, "effective_limit": 2, "shrunk": false
}
```

`RuleJob` (paths ALL absolute, passed VERBATIM to the subagent):
```json
{
  "category": "junit5", "format": "opencode",
  "rule_path": "<abs target>/docs/test-conventions/junit5.md",
  "done_marker": "<abs>/.mgh-ut-init/checkpoints/rules/junit5.opencode.json.done",
  "failed_marker": "<abs>/.mgh-ut-init/checkpoints/rules/junit5.opencode.json.failed",
  "input_path": "<abs>/.mgh-ut-init/inputs/rules/junit5.input.json",
  "bytes": 380, "oversize": false
}
```

## Rules
- **枚举**:distinct `rules[].category`(file order 收集后 sorted;每类一个 job)。
- **rule_path** 按 `--format`:`claude` → `<abs target>/.claude/rules/test-<cat>.md`;
  `opencode` → `<abs target>/<rules-dir>/<cat>.md`(`--rules-dir` 默认 `docs/test-conventions`,
  相对路径按 `--target` 解析)。
- **物化**:该 category 的全部 rules 写入 `inputs/rules/<cat>.input.json`(body 见 `unit-inputs.md`);
  超 `--max-unit-bytes` 标 `oversize:true` + recipe(`--scope`+`--merge`,**不**切分——rulewriter 需全类视图)。
- **不变式**:`total == done + failed + len(pending)`;markers = `<cat>.<fmt>.json.done` / `.failed`。
- 退出码 `0/1/2`;no TTY、只读、幂等。
