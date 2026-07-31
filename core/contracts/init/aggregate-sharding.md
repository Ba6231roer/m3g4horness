# Contract: `plan_aggregate.py` stdout — aggregate-node hard-budget map-reduce gate

Producer: `core/scripts/plan_aggregate.py` (deterministic leaf, read-only sans `--materialize`).
Consumer: the `/mgh-init` orchestrator at the two aggregate nodes — T2 (`init-synthesis`) and
scout-merge (`init-scout-merge`). Decides + materializes sharding so `--max-aggregate-bytes` is a
HARD per-request gate (replaces the prior "disclose + `--scope`/`--merge` fallback" soft boundary).

> 小仓零回归:聚合输入 ≤ 预算 → `needs_reduce=false` → 既有 single-context 综合路径逐字不变。
> 超预算才触发两段 map-reduce:确定性分桶 → 每 shard 一个有界 partial-synthesis subagent → 单一 rollup
> subagent 仅吞各 shard 摘要。**每个大模型请求 ≤ 预算**。触发与 shard 数进 `init_manifest.json::boundaries[]`
> + `report.md` 披露(无静默溢出)。

## CLI

```
py plan_aggregate.py --node t2|scout-merge --init-dir <dir>
    [--budget B] [--materialize <shards-dir>] [--offset N] [--limit N] [--orch-budget-bytes B]
```

`--budget` = `--max-aggregate-bytes`(默认 256KB)。`--materialize` 物化每 shard 有界输入。
`--offset/--limit/--orch-budget-bytes` 复用 `list_*` 的翻页语义(单页 > `--orch-budget-bytes` → `shrunk:true`)。

## 输入记录来源

| node | 上一层记录(records) | 分桶键 |
|---|---|---|
| `t2` | `checkpoints/t1/*.json`(每簇 T1 记录;`*.done` 不读) | `category`(T2 canonical 判定需整 category 视图,故**不跨 category 拆**) |
| `scout-merge` | `checkpoints/scout/*.json`(reader 批记录;排除 `merge.json`/`audit.json`) | batch 簇(贪心打包,每桶 ≤ 预算) |

`total_bytes` = records 序列化字节和。

## stdout shape

```json
{
  "node": "t2",
  "total_bytes": 400000,
  "budget": 262144,
  "needs_reduce": true,
  "shards": 3,
  "pending": [
    {"shard_id":"t2-authorization","node":"t2","categories":["authorization"],
     "input_path":"<abs>","bytes":150000,"oversize":false,
     "checkpoint_path":"<abs checkpoints/t2/shards/t2-authorization.json>",
     "done_marker":"<abs ...>.done"}
  ],
  "truncated": false, "offset": 0, "limit": 3, "effective_limit": 3, "shrunk": false,
  "rollup": {"summary_paths":["<abs shard checkpoint>...", "output":"<abs controls_inventory.json>",
              "done_marker":"<abs checkpoints/t2/synthesis.json.done>"},
  "note": "aggregate input 400000B > budget 262144B — 3 shard(s); per-shard partial then single rollup"
}
```

### `needs_reduce=false`(≤ 预算,常见小仓)

```json
{"node":"t2","total_bytes":80000,"budget":262144,"needs_reduce":false,"shards":0,"pending":[],
 "note":"aggregate input 80000B <= budget 262144B — use single-context init-synthesis"}
```

编排器走**既有 single-context** `init-synthesis`/`init-scout-merge`(无 shard、无 rollup),
行为等价于引入本闸门前。`rollup` 字段省略。

### `needs_reduce=true`(> 预算)

- 每 `pending[]` 项:`shard_id` + `input_path`(该 shard 有界记录,subagent 自读)+ `checkpoint_path`
  (partial-synthesis 写该 shard 摘要的绝对路径)+ `done_marker`(均绝对,编排器逐字透传)。
- `rollup.summary_paths` = 各 shard 的 `checkpoint_path`(rollup subagent 仅吞这些**摘要**,非原始记录全集);
  `rollup.output`/`done_marker` = 终态产物(`controls_inventory.json` / `scout_candidates.json` + 其 `.done`)。
- 单 category(shard)> 预算 → `oversize:true`(无法再拆而不损整 category 视图)+ stderr 警告;
  该 shard 仍发(部分有界),`boundaries[]` 披露。

## 两段 map-reduce(超预算时;≤ 预算逐字不变)

```
plan_aggregate --node t2 --materialize <shards>     # 决策 + 物化有界 shard 输入
  → per shard: spawn init-synthesis(partial, 读 shard input_path, ack 回传, 写 checkpoint_path)
  → rollup: 单一 init-synthesis subagent 仅吞 rollup.summary_paths(各 shard 摘要)
            → 写 controls_inventory.json + checkpoints/t2/synthesis.json.done
```

rollup 输入 = 各 shard 的**结构化摘要**(非原始 T1/scout 全集),上下文 ≪ 任一 shard;跨 category 的
canonical/competing 归并在 rollup 完成(跨 category 视图保留)。scout-merge 同构(`--node scout-merge`,
按 batch 簇分桶,rollup 写 `scout_candidates.json` + `checkpoints/scout/merge.json.done`)。

## 边界

- `validate_inventory.py --check`(T2 边界校验)对 map-reduce 产出的 inventory 同样适用(产物 schema 不变);
  rollup 写出的 inventory 须过 `--check`(退出码 0)。
- 触发节点 + shard 数 + 每 shard 预算进 `init_manifest.json::boundaries[]` + `report.md`(无静默溢出)。
