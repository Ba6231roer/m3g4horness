> **人话序** 现象：企业内网 LLM 网关普遍带调用配额（如实测背景：每 10 分钟 100 次），T1 扇出的
> 单元粒度是「1 簇 1 单元」，每个单元无论多小都要烧 3–5 次调用的**固定开销**（会话启动、读任务、
> 读输入、写记录、回执）——真机 221 个小簇（单簇输入仅 1.6–4.3KB）约 900+ 次调用是纯开销，近
> 1/3 配额没花在归纳本体上。根因：小簇没有打包机制，固定开销无法摊薄；而配额是硬上界，加大
> 并发（wave）完全无法提速，唯一杠杆是减少单元数。改什么：`list_clusters.py` 新增**确定性小簇
> 打包**（`--pack-bytes`，同 category 按字节贪心装包，包 id 由成员 id 确定性派生），一个 subagent
> 上下文按序处理包内多个簇；**簇级 marker 真相源不变**（每簇仍独立 checkpoint + `.done`，crash
> 恢复粒度仍是簇，重派跳过已完成成员）；任务模板改多成员迭代契约。默认关闭（opt-in），编排器
> 调用面同步启用。怎么验证：单测覆盖打包确定性 / 包 pending 判定 / 成员跳过 / oversize 不入包；
> 契约 lint 断言新 flag；真机 T1 对比打包前后的单元数与调用数。

## Why

- **配额把瓶颈从并发换成调用数**：内网网关限流（如 100 次/10min = 10 次/min）下，吞吐上限
  = 配额 ÷ 每簇调用数；wave 调大只会更早撞墙，不会更快。每簇调用数 = 固定开销（~3–5 次）+
  归纳本体（与簇大小相关）。小簇场景固定开销占比过半，是唯一能结构性削减的成本。
- **固定开销在 runner 侧不可观测、只能在结构上消除**：子进程内部 LLM 调用数对派发器不透明，
  无法运行时节流；少派单元 = 少付固定开销。
- **真机数据**：T1 resume 事故中 221 个单元多为小簇（输入 1.6–4.3KB）；按每单元 4 次开销估算，
  打包 4 簇/单元可把 221 单元压到 ~60 单元，总调用省 ~30–40%。

## What Changes

- **`list_clusters.py` 新增确定性打包模式**（`--pack-bytes B`，默认 0 = 关闭；`--pack-max N`
  每包成员上限，默认 8）：同 category 内按 `(bytes 升序, cluster_id)` 排序、贪心装包至字节上限；
  仅「单簇 bytes ≤ `--max-unit-bytes`」的簇可入包（oversize/`::shard-n` 单元永不入包）。包 id =
  `pack::<category>::<sha8(成员 id 排序拼接)>`——分区与 id 都是 `clusters.json` + flag 的纯函数，
  同输入同包。
- **打包开启时 `pending[]` 单元 = 包**：`cluster_id` 字段载包 id（`fanout_runner.py` 与 ack
  状态机**零改动**复用），新增 `members[]`（每成员 `{cluster_id, input_path, checkpoint_path,
  done_marker, bytes}`，全绝对路径）；每包一个**合并 input 文件**（成员完整记录数组，一次 Read
  摊薄）；`total` = 包数，新增 `cluster_total`/`cluster_done` 簇级披露字段。
- **簇级 marker 真相源不变**：包 pending ⟺ ≥1 成员缺 `.done`；成员 marker 由 subagent 逐簇写，
  crash 恢复粒度仍是簇，重派时已完成成员被模板指示跳过。
- **`t1-task.md` 模板多成员迭代契约**：读合并 input → 逐成员处理（行为 stage prompt 不变）→
  逐成员写 checkpoint + touch `.done` → `done_marker` 已存在的成员跳过 → ack 单行
  `ok <包 id> <已处理成员数>`。
- **编排器调用面同步**：`init-stage/t1.md` fragment 与 `discipline_core.py` path_recipes 的
  `list_clusters.py` 调用示例增 `--pack-bytes`（配额受限场景启用）；`docs/man/mgh-init.md` 增
  打包段与配额场景建议值。
- **非目标（明确不做）**：不改 `fanout_runner.py`（包 id 走既有 `cluster_id` 字段位）；不改
  T1 record schema（记录仍每簇一份、`unit` 字段 = 成员 cluster_id，T2 记录闸门零感知）；不跨
  category 打包；不改 scout/t2/t3/sdr 各 tier；不引入调用数运行时计量。

## Capabilities

### New Capabilities

<!-- 无。全部为 control-dispatch 既有能力的要求级变更。 -->

### Modified Capabilities

- `control-discovery`: ① 「Deterministic cluster enumeration for T1 fan-out」——增打包模式：
  单元 = 包的确定性分区与 id 派生、包 pending 的成员 marker 派生、`members[]`/合并 input/
  簇级披露字段、opt-in flag 契约；② 「Isolated per-cluster induction with cross-cluster
  synthesis」——隔离单元边界语义更新：一个 T1 上下文可含同 category 的多个小簇（逐簇处理、
  逐簇出记录、仍不做 canonical 判定），T2 输入仍为每簇一份结构化记录。

## Impact

- **代码**：`core/scripts/list_clusters.py`（打包分区、包 id、合并 input、包级 pending 派生、
  `members[]`/簇级披露字段）；`core/prompts/fragments/fanout/t1-task.md`（多成员迭代模板）。
  `fanout_runner.py` **零改动**；T1 record schema、`validate_t1_records.py`、T2 记录闸门、
  `resume_state.py`（簇级 marker 计数）**零改动**。
- **测试**：`tests/test_list_clusters.py`（打包确定性/包 pending/成员跳过/oversize 排除/
  `--pack-bytes 0` 逐字节回归）；`tests/test_init_clusters.py` 回归；模板契约
  `tests/test_init_ack_contract.py` 增多成员 ack 形态。
- **调用面**：`core/prompts/fragments/init-stage/t1.md`、`core/scripts/discipline_core.py`
  path_recipes、`docs/man/mgh-init.md`；`tools/check_contracts.py` 自动断言新 flag。
- **零新依赖**（stdlib 排序/哈希即可）；默认关闭 = 既有行为逐字节不变。
