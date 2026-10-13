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

`--budget` = `--max-aggregate-bytes`(默认 96KB = 98304;按本仓 token 启发式最坏口径 ≈ 2 字节/token
换算,单派发 shard 输入 ≤ ~48K token,叠加 stage 提示词与有界回传仍远低于 150K 窗口模型的 120K 输入红线;
显式传 flag 可覆盖)。同名 flag 在各声明脚本(`plan_aggregate.DEFAULT_BUDGET`、`write_runconfig` /
`write_ut_runconfig` / `render_report` 的 `DEFAULT_MAX_AGGREGATE_BYTES`)默认值 MUST 同值(98304,
由 `tests/test_plan_aggregate.py` 对 `--help` 断言)。`--materialize` 物化每 shard 有界输入。
`--offset/--limit/--orch-budget-bytes` 复用 `list_*` 的翻页语义(单页 > `--orch-budget-bytes` → `shrunk:true`)。

## 输入记录来源

| node | 上一层记录(records) | 分桶键 |
|---|---|---|
| `t2` | `checkpoints/t1/*.json`(每簇 T1 记录;`*.done` 不读) | `category`(不跨 category 混装;单 category 自身超预算 → 按记录整条贪心再切 part,同 category 跨 part 归并归 rollup) |
| `scout-merge` | `checkpoints/scout/*.json`(reader 批记录;排除 `merge.json`/`audit.json`) | 候选粒度稳定序贪心装箱(record glob 序 × 批内候选序;批 `unresolved` 随该批最后一个候选落同 shard;每 shard **物化输入文件** ≤ 预算,硬界) |

`total_bytes` = records 序列化字节和。

## stdout shape

```json
{
  "node": "t2",
  "total_bytes": 400000,
  "budget": 98304,
  "needs_reduce": true,
  "shards": 4,
  "pending": [
    {"shard_id":"t2-authorization-part00","node":"t2","categories":["authorization"],
     "input_path":"<abs>","bytes":150000,"oversize":false,
     "part_index":0,"part_count":2,"slimmed":{},
     "checkpoint_path":"<abs checkpoints/t2/shards/t2-authorization-part00.json>",
     "done_marker":"<abs ...>.done"},
    {"shard_id":"t2-crypto","node":"t2","categories":["crypto"],
     "input_path":"<abs>","bytes":60000,"oversize":false,
     "part_index":0,"part_count":1,"slimmed":{},
     "checkpoint_path":"<abs checkpoints/t2/shards/t2-crypto.json>",
     "done_marker":"<abs ...>.done"}
  ],
  "truncated": false, "offset": 0, "limit": 4, "effective_limit": 4, "shrunk": false,
  "rollup": {"summary_paths_manifest":"<abs checkpoints/t2/shards/rollup_manifest.json>",
              "output":"<abs controls_inventory.json>",
              "done_marker":"<abs checkpoints/t2/synthesis.json.done>"},
  "note": "aggregate input 400000B > budget 98304B — 4 shard(s); per-shard partial then single rollup"
}
```

### `needs_reduce=false`(≤ 预算,常见小仓)

```json
{"node":"t2","total_bytes":80000,"budget":98304,"needs_reduce":false,"shards":0,"pending":[],
 "note":"aggregate input 80000B <= budget 98304B — use single-context init-synthesis"}
```

编排器走**既有 single-context** `init-synthesis`/`init-scout-merge`(无 shard、无 rollup),
行为等价于引入本闸门前。`rollup` 字段省略。

### `needs_reduce=true`(> 预算)

- 每 `pending[]` 项:`shard_id` + `input_path`(该 shard 有界记录,subagent 自读)+ `checkpoint_path`
  (partial-synthesis 写该 shard 摘要的绝对路径)+ `done_marker`(均绝对,编排器逐字透传)。
- **T2 shard 项另带** `part_index`/`part_count`(part 切分披露;未切分 = `0`/`1`);**两节点 shard 项均带**
  `slimmed`(原子瘦身披露;未瘦身 = 空对象)。已派发 shard 两节点均恒 ≤ 预算 ⇒ `oversize` 恒 `false`
  (字段保留、stdout 兼容;旧 scout-merge「单桶超预算 warn + 照发」路径废除)。shard 输入 envelope
  同样携带 `part_index`/`part_count`(仅 t2;partial 从输入文件自读 part 身份;`t2-task.md` 模板占位符集不变)。
- **单 category > 预算 → 自动 part 切分**:按 T1 记录(既有 glob 序)整条贪心打包成多个 ≤ 预算 part,
  `shard_id = t2-<category>-part<N>`(N 自 0 两位零填充);同 category 跨 part 的 canonical/competing
  归并由 rollup 承接(见下);marker-aware 重列 / `.done`/`.failed` / dispatcher 波次机不变
  (parts 只是更多普通 shard;旧 run 残留的单桶 marker 不匹配 part shard_id → 相应 part 重跑,无害)。
- **原子超限(单条记录/单个候选自身 > 预算)**:物化层做**确定性瘦身投影**——t2 仅截 `description`/`usage`/
  `protects`/`gaps`(str 与 list 形态均可)与 `entry_points` 至内部常量上限;scout-merge 仅截候选的
  `evidence_snippet`/`snippet` 与 `entry_points`(≤16 项)——两节点 `evidence` 锚点与其余结构字段不截
  (它们是 `merge_scout._key` 去重键与 `--check` 校验面);
  投影记录带 `_slimmed` 标记(被截字段 + 原始字节数),痕迹记入该 shard 的 `slimmed` 披露;
  `checkpoints/t1` / `checkpoints/scout` 原件 **NEVER** 改写。瘦身后仍 > 预算(结构字段本身超限 = 病态记录)→ **退出码 2**
  fail-loud(stderr 报记录文件与字节数),零派发、零物化。
- `rollup.summary_paths_manifest` = `checkpoints/<t2|scout>/shards/rollup_manifest.json` 的绝对路径
  (原子写、幂等;body = `{summary_paths[]: 各 shard checkpoint 绝对路径全集, output, done_marker}`)。
  stdout **NEVER** 携带 `summary_paths` 数组(1000 shard ≈ 100KB 会击穿 `--orch-budget-bytes` 的
  单次回复承诺)——rollup subagent 先 `Read` manifest 取全量路径再逐份吞摘要(仅吞这些**摘要**,
  非原始记录全集);编排器逐字透传 manifest 路径、**NEVER** 自读其内容(编排器黑盒纪律:叶脚本
  stdout 即工作清单,聚合产物整份读 = 内省);
  `rollup.output`/`done_marker` = 终态产物(`controls_inventory.json` / `scout_candidates.json` + 其 `.done`)。
- **scout-merge 与 t2 同构接入 dispatcher**:枚举同样 marker-aware(`.done`/`.failed` 终态 shard 移出
  `pending[]`,stdout 附 `total`/`done`/`failed`);`shard_id = scout-merge-<K>`;shard 项 `batches` 为该
  shard 覆盖的**去重 batch_id 列表**(旧 int 计数废除)。候选装箱会把大批切到相邻 shard——跨 shard
  重叠/重复候选的归并归 rollup(`merge_scout._key` 去重键语义不变)。

## 两段 map-reduce(超预算时;≤ 预算逐字不变)

```
plan_aggregate --node t2 --materialize <shards>     # 决策 + 物化有界 shard 输入
  → per shard: spawn init-synthesis(partial, 读 shard input_path, ack 回传, 写 checkpoint_path)
  → rollup: 单一 init-synthesis subagent 先 Read rollup_manifest.json 取 summary_paths 全集,
            仅吞各 shard 摘要 → 写 controls_inventory.json + checkpoints/t2/synthesis.json.done
```

rollup 输入 = 各 shard 的**结构化摘要**(非原始 T1/scout 全集),上下文 ≪ 任一 shard;跨 shard 的
canonical/competing 归并在 rollup 完成——**同 category 跨 part 与跨 category 同一组判定信号**
(partial 不做任何跨 shard 判定)。scout-merge 同构(`--node scout-merge`,
候选粒度装箱,rollup 写 `scout_candidates.json` + `checkpoints/scout/merge.json.done`)。

## 边界

- `validate_inventory.py --check`(T2 边界校验)对 map-reduce 产出的 inventory 同样适用(产物 schema 不变);
  rollup 写出的 inventory 须过 `--check`(退出码 0)。
- 触发节点 + shard 数 + 每 shard 预算进 `init_manifest.json::boundaries[]` + `report.md`(无静默溢出)。
