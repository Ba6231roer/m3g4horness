# Contract: list_test_groups.py --tier extract stdout (extract pending work-list)

Producer: `core/scripts/list_test_groups.py` (deterministic, stdlib). Consumer: the
orchestrator (fans out one `ut-extract` subagent per pending group).

CLI contract (`--help` 即契约):
```bash
py list_test_groups.py --tier extract --groups <init-dir>/test_groups.json [--checkpoints <extract-dir>] [--materialize <inputs-dir>] [--sample-uniform N] [--sample-hetero N] [--offset N] [--limit N] [--max-unit-bytes B] [--orch-budget-bytes B]
```

## Output Schema

stdout (slim page; stderr = diagnostics):
```json
{
  "tier": "extract", "repo": "<abs target>",
  "total": 7, "done": 2, "failed": 1,
  "pending": [<ExtractJob>, ...],
  "offset": 0, "limit": 50, "effective_limit": 3, "shrunk": false
}
```

| field | type | note |
|---|---|---|
| `total` | int | groups in test_groups.json |
| `done` / `failed` | int | `.json.done` / `.json.failed` markers under the extract checkpoint dir |
| `pending[]` | list | groups WITHOUT a terminal marker (`--resume` 跳过) |
| `effective_limit` / `shrunk` | int / bool | page auto-tightened to `--orch-budget-bytes` |

`ExtractJob` (paths ALL absolute, passed VERBATIM to the subagent):
```json
{
  "group_id": "service::MockitoExtension",
  "layer": "service", "family": "MockitoExtension", "uniformity": "uniform",
  "member_count": 32, "sample_size": 4,
  "input_path": "<abs>/.mgh-ut-init/inputs/extract/service__MockitoExtension.input.json",
  "checkpoint_path": "<abs>/.mgh-ut-init/checkpoints/extract/service__MockitoExtension.json",
  "done_marker": "<abs>/checkpoints/extract/service__MockitoExtension.json.done",
  "failed_marker": "<abs>/checkpoints/extract/service__MockitoExtension.json.failed",
  "bytes": 2682, "oversize": false
}
```

## Rules
- **抽样**(deterministic):`uniform` 组取 sorted(members) 前 `--sample-uniform`(默认 4)个;
  `hetero` 组取 `--sample-hetero`(默认 8)个;组内成员不足则全取。
- **物化**:样本文件内容 + 组记录写入 `inputs/extract/<safe(group_id)>.input.json`
  (body 见 `unit-inputs.md`);超 `--max-unit-bytes` 减半样本直至适配;1 文件仍超 → `oversize:true`
  + recipe(切片 `chunk_sources.py`,NEVER 整文件喂 LLM)。
- **不变式**:`total == done + failed + len(pending)`;`group_id` 含 `::` → 文件名经 `_safe_name`
  (`/` `\` `:` → `_`)编码,canonical id 保留在字段。
- 退出码 `0/1/2`(0 ok 含空 groups;1 test_groups.json 缺失/畸形;2 误用)。no TTY、只读、幂等。
