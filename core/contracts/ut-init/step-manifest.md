# Contract: list_ut_steps.py stdout (per-step invocation manifest)

Producer: `core/scripts/list_ut_steps.py` (deterministic, stdlib). Consumer: the
orchestrator — canonical "exact invocation line for each step". Zero disk preconditions
(does NOT read run_config or `.mgh-ut-init/`).

CLI contract (`--help` 即契约):
```bash
py list_ut_steps.py [--target <dir>] [--step <id>]
```

stdout:
```json
{
  "steps": [
    {
      "step": "classify",
      "kind": "bash",
      "script": "classify_tests.py",
      "script_abs": "<abs mgh-core>/scripts/classify_tests.py",
      "invocation": "py <abs>/classify_tests.py --repo <target> --out <init-dir>",
      "input": {"artifact": null, "shape": null},
      "output": {"artifact": "test_groups.json", "shape": "{repo,groups[]}",
                 "path_pattern": "<init-dir>/test_groups.json"}
    }
  ]
}
```

## Step → IO table
| step | kind | script | output |
|---|---|---|---|
| classify | bash | `classify_tests.py` | `test_groups.json` |
| extract | bash | `list_test_groups.py --tier extract` | `checkpoints/extract/*.json` |
| synthesize | subagent | — | `test_rules_inventory.json` |
| rules | bash | `list_test_groups.py --tier rules` | `checkpoints/rules/*.json` |
| assemble | bash | `assemble_test_rules.py` | rule files / detail files |
| consistency | subagent | — | `checkpoints/consistency/.done` |
| mutators | bash | `derive_mutators.py` | `default_mutators.json` |
| done | bash | — | `ut_manifest.json` |

## Rules
- `script_abs` 绝对(Windows 原生盘符),由 `Path(__file__).resolve().parent` 派生;宿主前缀
  (`.claude/mgh-core/` vs `.opencode/mgh-core/`)从不硬编码。
- 未知 `--step` id → 退出码 2(闭集)。零磁盘前置、只读、幂等。
