# control-discovery Specification — delta

## MODIFIED Requirements

### Requirement: Aggregate nodes enforce a hard request budget via map-reduce

T2(`init-synthesis`)与 scout-merge(`init-scout-merge`)SHALL 把 `--max-aggregate-bytes` 当作**硬闸门**(兑现
shell 既有「P0 软边界:T2/merge/T4 聚合节点目前为披露 + `--scope`/`--merge` 回退」的自认 TODO,把软边界升级为硬阈值)。
聚合输入(全部 T1 记录 / 全部 scout 批记录)≤ `--max-aggregate-bytes` 时,行为**逐字不变**(单一综合 subagent
上下文,承 "Isolated per-cluster induction with cross-cluster synthesis" / "Fan out scout across parallel isolated
byte-bounded batches" 的既有 single-context 综合语义)。聚合输入 **>** 预算时,SHALL 自动触发**两段 map-reduce**:
确定性叶脚本 `core/scripts/plan_aggregate.py` 把上一层记录(T2 按 `category` 分桶;scout-merge 按 batch 簇分桶)切成
**每桶 ≤ `--max-aggregate-bytes`** 的有界 shard 并物化 per-shard 输入。**T2 map 阶段**SHALL 由确定性 dispatcher
(`fanout_runner.py --tier t2`,见 `fanout-dispatch` 能力)波次驱动——为每 shard 一个 **partial-synthesis subagent**
(`init-synthesis-fanout`,有界输入、回传有界 ack),产出 per-shard 摘要 checkpoint;scout-merge map 阶段仍由编排器
逐 shard 手派(非目标,后续 change)。两 node 的 map 阶段完成后,由**单一 rollup subagent** 仅吞**各 shard 摘要**
(有界)产出终态产物(`controls_inventory.json` / `scout_candidates.json`)。**每个大模型请求 SHALL ≤ 预算**。
`plan_aggregate.py` SHALL 零依赖、自定位、utf-8、任意 cwd、stdout=JSON/stderr=诊断、退出码 `0/1/2`、`--help` 即契约
(承 R5.1/R5.3),并复用既有 `list_*` 的 `--materialize`/`--offset`/`--limit`/`--orch-budget-bytes` 翻页语义。`--node t2`
stdout SHALL 顶层补 `repo`(=`--init-dir` resolve 父目录)、marker 派生 `total`/`done`/`failed`,每 shard 补
`failed_marker`,且 `pending[]` SHALL **排除**已有 `.done`/`.failed` marker 的 shard(使 dispatcher 波次重列 →
pending 收缩收敛、零推进熔断信号 = marker 真值;`summary_paths`/`shards` 仍为全集供 rollup + 披露);使 dispatcher
锚树校验与 `.failed` 终态可执行;`needs_reduce=false` 路径逐字不变。降级触发与 shard 数 SHALL 在
`init_manifest.json::boundaries[]` + `report.md` 披露(无静默溢出)。本要求在「超预算」时**取代**
既有 single-context 综合条款;≤ 预算(常见小仓)时既有条款逐字生效。

**T2 partial/rollup 提示词分态**:T2 的三态行为 SHALL 由三个 stage 提示词各司其职——`init-synthesis.md`(whole,
单上下文,小仓路径,**逐字不变**)、`init-synthesis-partial.md`(per-shard 有界 partial,产结构化 shard 摘要,不跨
shard 做 canonical/competing 判定)、`init-synthesis-rollup.md`(仅吞各 shard 摘要,跨 category canonical/competing
归并 → 终态 inventory)。三态输出 schema 一致(`design_controls`-compatible),`validate_inventory.py --check` 对
map-reduce 产物同样适用。

#### Scenario: Small repo keeps single-context synthesis unchanged

- **WHEN** 全部 T1 记录序列化字节 ≤ `--max-aggregate-bytes`
- **THEN** T2 仍为单一综合 subagent 上下文(无 shard、无 rollup),行为等价于引入本要求前

#### Scenario: Large repo triggers automatic map-reduce sharding

- **WHEN** 全部 T1 记录序列化字节 > `--max-aggregate-bytes`
- **THEN** `plan_aggregate.py --node t2` 按 `category` 切成多个每桶 ≤ 预算的 shard,`fanout_runner.py --tier t2`
  波次驱动每个 shard 一个 `init-synthesis-fanout` partial-synthesis subagent(有界输入),再一个 rollup subagent
  仅吞各 shard 摘要;**每个大模型请求 ≤ 预算**

#### Scenario: T2 map phase reuses dispatcher machinery

- **WHEN** T2 map 阶段经 `--tier t2` 运行,且被宿主硬杀后残留孤儿 partial-synthesis 子进程
- **THEN** `fanout_runner.py --kill-stale --tier t2` 检出并清理孤儿;`partial:true` 时重派同一命令
  (`--time-budget-ms` 软时限先于宿主硬杀);零推进连续 N 波触发熔断(fail-loud + `stalled_pending[]`)——与
  scout/t1/t3 同一 tier 无关代码路径,无 per-tier 分支

#### Scenario: scout-merge over budget uses batch-cluster shards

- **WHEN** 全部 scout 批记录 > `--max-aggregate-bytes`
- **THEN** `plan_aggregate.py --node scout-merge` 按 batch 簇分桶,编排器逐 shard 手派一个 bounded
  partial-merge subagent,再 rollup;每请求有界(本 change 不将其切到 dispatcher)

#### Scenario: Rollup operates on summaries only

- **WHEN** map-reduce 的 rollup subagent 运行
- **THEN** 其输入为各 shard 的**结构化摘要**(非原始 T1/scout 记录全集),上下文规模远小于任一 shard

#### Scenario: Reduction is disclosed, not silent

- **WHEN** 一次运行触发了聚合 map-reduce 降级
- **THEN** `init_manifest.json::boundaries[]` + `report.md` 记录触发节点、shard 数与每 shard 预算,不静默溢出

#### Scenario: plan_aggregate is self-contained, offline, and contract-complete

- **WHEN** `py <path>/plan_aggregate.py ...` 从任意 cwd、内网无网环境执行,且 `--help` 被运行
- **THEN** 脚本成功(零依赖、自定位、utf-8),stdout 为合法 JSON(含 `--node t2` 时的 `repo`/`failed_marker`);
  `--help` flag 表被双壳 `mgh-init.md` 逐字镜像(承 R5.1)

#### Scenario: rollup inventory passes the T2 boundary validator

- **WHEN** map-reduce 的 rollup 产出 `controls_inventory.json`
- **THEN** `validate_inventory.py --check` 断言 vvah 兼容字段 + 每条 evidence 锚点 + category→kind 归一,
  失败退出码 2(与 single-context 产物同 schema,同一校验路径)
