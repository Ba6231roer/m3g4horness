# Contract: validate_test_rules.py (synthesize boundary)

Producer: `core/scripts/validate_test_rules.py` (deterministic, stdlib). Consumer: the
orchestrator (runs it after ut-synthesize, before the rules tier; fail-loud exit 2 → re-run
ut-synthesize, never proceed with a broken inventory).

CLI contract (`--help` 即契约):
```bash
py validate_test_rules.py --inventory <init-dir>/test_rules_inventory.json
```

stdout (structured JSON; stderr = diagnostics):
```json
{
  "check": "test_rules",
  "ok": true,
  "rules": 3,
  "categories": ["junit5", "mockito"],
  "violations": []
}
```

## Validation (per rule; exit 0 ok / 2 violation / 1 missing-or-malformed)
- wrapper shape `{repo, format, rules[]}`;
- `name` 非空;`category` 非空;`layer` ∈ `{controller,service,repository,config,integration,util,other}`;
- `anchor` 非空字符串(`file:class:method` / `file:line`);`evidence` 非空列表、每项非空字符串;
- `provenance` 为 dict 且携 `groups[]` 列表;`confidence` ∈ [0,1];`weak_dominated`(若在)为 bool。
