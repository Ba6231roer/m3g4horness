# design — harden-mgh-init-t2-oversize-shard

## Context

实测失败:测试仓 T2 map-reduce 已正确触发,但 `authorization` 单 category 的 T1 记录达 400KB(> 256KB 默认预算),`plan_aggregate.py` 现行兜底是「`oversize:true` + stderr 告警 + **照发**」(`core/scripts/plan_aggregate.py:108-120` 分桶、`270-273` 告 warn 后仍 `_write_shard_input` 派发);`init-synthesis-partial` 携 400KB 输入请求模型 → 上下文超限 crash(exit=1)。缺口被 `core/contracts/init/aggregate-sharding.md:70-71` 记为已知容忍项(「无法再拆而不损整 category 视图……仍发 + 披露」)。

约束:①「每请求 ≤ 预算」是 spec 承诺(control-discovery),预算即产品契约,不可上调了事;② partial 的「不跨 shard 判定」与 rollup 的「不重审 within-part 判定」两条提示词不变式与分桶设计互锁(`core/prompts/stages/init-synthesis-partial.md:44-47`、`init-synthesis-rollup.md:46-48`),拆 category 必须同步改 rollup 语义,否则同 category 跨 part 的竞争判定无人负责;③ `needs_reduce=false` 小仓路径逐字不变(零回归红线);④ 零新增 flag、零新增依赖。

## Goals / Non-Goals

**Goals:**

- 任何派发给 partial-synthesis subagent 的 T2 shard 输入 MUST ≤ `--budget`(确定性保证,非披露性)。
- 单 category 超预算 → 自动 part 切分,判定语义闭环(rollup 承接跨 part 归并)。
- 原子超限(单记录 > 预算)→ 瘦身投影兜底,残余 fail-loud(退出码 2),不再派发注定崩的单元。
- 切分/瘦身痕迹全披露(stdout + `boundaries[]` + `report.md`)。

**Non-Goals:**

- scout-merge 的 dispatcher 化与其 envelope 演进(维持手派,spec 已注明后续 change)。
- `fanout_runner.py` t2 tier 结构改动(parts 即普通 shard,marker-aware 重列天然收敛)。
- T1 侧提示词/记录 schema 改动(400KB 是合法 T1 输出的聚合结果,不是 T1 漂移;源头治理属另一议题)。
- 预算默认值调整、`--budget` 语义变更。

## Decisions

**D1 — 主修复 = part 切分,不瘦身开路、不上调预算、不只 fail-loud。**
超预算 category 按 T1 记录**整条**贪心打包(与 `_shard_by_batch_cluster` 同构;记录序 = 既有 glob 序,确定性),`shard_id = t2-<category>-part<N>`(N 自 0 两位零增,保字典序稳定)。备选否决:全局 prose 先瘦身——authorization 400KB 更可能是「多簇 × 合法记录」,瘦身治不了簇多,且让全路径吃截断损失;上调预算——预算是硬契约,模型上下文是物理上限,调大只是推迟崩溃;仅 fail-loud——用户要跑通而非跑得更响。

**D2 — 同 category 跨 part 的 canonical/competing 归并归 rollup,复用既有跨 category 通路。**
partial 提示词废除「category 永不跨 shard」句,改为「本 shard 可能是某 category 的一个 part,任何跨 shard 判定不做」(「不跨 shard 判定」的实义不变);rollup step 3 从「跨 category」扩为「跨 shard(同 category 跨 part 与跨 category)」,同一组判定信号(summary 已完整携带 controls + competing 成员,rollup 有裁决所需全部材料)。备选否决:part 间互读摘要——破坏 partial 隔离,且 rollup 本就见全量摘要,零新机制。保真度代价:oversize category 的 within-category 判定从「整 category 原始记录视图」降为「rollup 摘要视图」,与今日跨 category 判定同信任级,经 `boundaries[]` 披露,不静默。

**D3 — 原子超限 = 确定性瘦身投影 → 仍超则退出码 2。**
单条记录自身 > 预算(贪心无法再切)时,仅在 `--materialize` 物化层投影:截 `description`/`usage`/`protects`/`gaps`(str 或 list 均可能)与 `entry_points` 至内部常量上限(每字段 ~4KB 量级,不新增 flag——契约面不膨胀,真需调节的杠杆已是 `--budget`);**`evidence` 锚点不截**(判定关键 + `validate_inventory` 校验对象);投影结果带 `_slimmed` 标记,截断字段与原始字节记入 shard 的 `slimmed` 披露。`checkpoints/t1` 原件 **NEVER** 改写(该层产物已过 `validate_t1_records`,层边界不破)。瘦身后仍超(结构字段本身超限 = 病态记录)→ 退出码 2 + stderr 报记录文件与字节数,零派发。备选否决:一律 fail-loud 不瘦身——可确定性恢复的不该停跑;连 evidence 也截——破坏 dedup 锚点与校验契约。

**D4 — stdout schema 演进 = 纯加法 + 恒值兼容。**
map-reduce 路径 T2 shard 项统一携带 `part_index`/`part_count`(未切分 = `0`/`1`)与 `slimmed`(未瘦身 = 空对象);`oversize` 字段保留、派发 shard 恒 `false`(消费方兼容,契约注释说明语义已由切分接管);`needs_reduce=false` 路径**逐字不加字段**。切分确定性 ⇒ 同 records ⇒ 同 part 划分,marker-aware 重列 / resume / 熔断全部机制零改动即收敛。

**D5 — shard 输入 envelope 增 `part_index`/`part_count`,不新增模板占位符。**
partial 从输入文件自读 part 身份(输入文件本就是其唯一数据源),`fanout_runner` TIERS 占位符集与 `t2-task.md` 模板不动;scout-merge envelope 不动。

**D6 — P2 诊断:fanout_runner 溢出签名分类。**
对单元 crash 的 stderr 尾部做小签名集匹配(`context length` / `prompt is too long` / `request too large` / `maximum context` 等,常量可增补),命中则 run.log 单元行与 stdout 摘要附 `reason:context-overflow` + 「收窄 `--budget` 重跑」recipe 指针。纯诊断 additive:不改成败判定,漏报 = 退回现状通用 crash 行,不误导。

## Risks / Trade-offs

- [oversize category 判定保真降级(整 category 视图 → 摘要视图)] → summary schema 完整携带 competing 成员;`boundaries[]` 披露 part 切分;与既有跨 category 判定同信任级。
- [part 边界依赖记录序(贪心打包序敏)] → 记录序 = glob 序,确定性;同 part 性不承载正确性(跨 part 由 rollup 兜底),仅影响 partial 内预归并量。
- [rollup 输入随 part 数线性增长] → 输入是摘要非原始记录,规模 ≪ 任一 shard;part 数经 `boundaries[]` 可观测,若未来 rollup 自身超限属新缺口,不在本 change 静默吞掉。
- [旧 run 残留的单桶 shard 产物(`t2-authorization.json(.done)`)] → 新分桶 shard_id 变为 part 形态,旧 marker 不计入、旧 summary 不进 `summary_paths`,自然废弃,无害。
- [溢出签名集追不上各宿主报错措辞] → 分类为 additive 诊断,漏报退化为现状,无误导;签名常量可随实测增补。
- [slim 截断丢 prose 细节] → 仅病态单记录场景触发,`_slimmed` + `boundaries[]` + `report.md` 三处留痕;对照现状 = 必崩。

## Migration Plan

无 schema 迁移、无数据回填;单 commit 粒度回滚 = revert 脚本 + 提示词 + 契约文档。对**进行中**的旧 run(残留单桶 marker):新代码重列时旧 marker 不匹配 part shard_id → 相应 part 重跑,正确性不受影响(见 Risks 第 4 条)。

## Open Questions

无。预算默认值维持 256KB;溢出签名集为可增补常量,不阻塞。
