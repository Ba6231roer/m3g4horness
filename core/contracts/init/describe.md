# Contract: `describe_artifact.py` (sanctioned structure-inspection primitive)

Producer/consumer: orchestrator + subagents 「瞄一眼产物结构」反射的**唯一合法出口**,跨产物通用,替代 `py -c` 内省与
`Read` 整份大 JSON。

CLI(`--help` 即契约;至少一个模式或 `--field`):
```
py describe_artifact.py --in <json>
    [--keys] [--count] [--sample N] [--shape] [--field a.b.c]
```

各模式 stdout shape(stderr 仅诊断;exit `0/1/2`):

| mode | stdout | 说明 |
|---|---|---|
| `--keys` | `{"type":"dict\|list","keys":[...] / "length":N}` | 顶层键 / 列表长度 |
| `--count` | `{"count":N}` 或 `{"counts":{<k>:len},"top_level_keys":K}` | 列表长度;wrapper dict 报**每条 list-valued 键**真实长度 + warn(防 `len({repo,clusters,truncated})==3` 误判) |
| `--sample N` | `{"sample":[<首 N 项>], "over":"<键>"?}` | 目标列表首 N 项;dict 时自动取首个 list-valued 键(记 `over`) |
| `--shape` | `{"shape":{<键>:<类型\|{type,length,element}>}}` | 轻量 schema(键→类型;列表键带元素 shape) |
| `--field a.b.c` | `{"field":"...","type":"...","value":<v>?}` | 点分路径取值;dict 键 + int 索引;可叠加上述模式 |

`--field` 先收窄 target,再对其余模式作用。组合示例:`--in scout_plan.json --field batches --count`
→ `{"count":N}`;`--in scout_plan.json --sample 1` → 自动 `over:"batches"` 的首元素(治
`py -c "...['batches'][0]"`)。
