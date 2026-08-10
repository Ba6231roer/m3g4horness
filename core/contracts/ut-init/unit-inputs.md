# Contract: per-unit materialized inputs (inputs/<tier>/<unit>.input.json)

Producer: `core/scripts/list_test_groups.py --materialize <inputs-dir>` (deterministic).
Consumer: the ut subagents (`ut-extract` / `ut-rulewriter`), which read ONLY their own
`input_path` (bounded, ≤ `--max-unit-bytes`).

Path convention: `<run-dir>/inputs/<tier>/<unit>.input.json` (absolute, idempotent
overwrite, `--resume`-reused). `/mgh-ut-init` run-dir = `<target>/.mgh-ut-init/`.

| tier | unit | body |
|---|---|---|
| `extract` | `<safe(group_id)>` | group record + sampled file contents |
| `rules` | `<safe(category)>` | that category's full rules |

## extract unit body

```json
{
  "group_id": "service::MockitoExtension",
  "layer": "service", "family": "MockitoExtension", "uniformity": "uniform",
  "assert_density": 2.3, "member_count": 32,
  "all_members": ["src/test/java/com/acme/service/UserServiceTest.java", "..."],
  "sample": [
    {"file": "src/test/java/com/acme/service/UserServiceTest.java",
     "path": "<abs>", "content": "<file text>"}
  ]
}
```

## rules unit body

```json
{
  "category": "junit5",
  "rules": [<full rule records for this category>]
}
```

## Rules
- 样本字节 ≤ `--max-unit-bytes`(默认 192KB);超则减半样本;1 文件仍超 → `oversize:true` + recipe
  (`chunk_sources.py` 切片,NEVER 整文件喂 LLM)。
- `extract` 单元若 1 个文件超预算 → `oversize:true`;`rules` 单元不切分(全类视图必需)。
- 文件名经 `_safe_name`(`/` `\` `:` → `_`;`group_id`/`category` 可含 `::`,NTFS ADS 分隔符)。
- 幂等 / `--resume` 复用;`.failed` marker body `{unit,reason,tier}`(仅编排器写,subagent 失败时
  touch nothing)。
