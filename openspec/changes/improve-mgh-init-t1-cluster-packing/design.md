# design — improve-mgh-init-t1-cluster-packing

## Context

T1 现状:1 簇 = 1 单元(`list_clusters.py --materialize`,oversize 另切 `::shard-n`)。每个单元
的 LLM 调用 = 固定开销(~3–5 次:会话启动/读任务消息/读 input/写记录/回执)+ 归纳本体。真机
(2026-09 T1 resume)221 单元多为小簇(input 1.6–4.3KB),固定开销估算 ≈900 次调用。

新约束:企业内网网关按调用数限流(实测背景 100 次/10min)。限流下吞吐上限 = 配额 ÷ 每簇调用
数,**加大 wave 不改变吞吐**;每单元调用数在 runner 侧不可观测(子进程内部不透明,`maxRetries`
等行为在子会话内),唯一结构性杠杆 = 减少单元数 = 打包。

T2 分块综合已存在(`plan_aggregate.py --node t2` 预算分片 + rollup),本 change 不涉 T2。

## Goals / Non-Goals

**Goals:**

- 小簇场景 T1 总调用数下降 ~30–40%(221 簇 → ~60 包,4 簇/包)。
- 恢复粒度保持簇级:crash 重派跳过已完成成员,零重复归纳。
- `fanout_runner.py`/ack 状态机/T1 record schema/T2 记录闸门/`resume_state.py` 零改动。
- 默认关闭,既有路径逐字节不变(回归可证)。

**Non-Goals:**

- 不做运行时调用数计量/限流(网关侧事实,runner 不可见)。
- 不跨 category 打包(T3 per-category 对齐 + 隔离语义依赖 category 单一性)。
- 不改 scout/t2/t3/sdr(同款打包若证实有益另立 change)。

## Decisions

**D1 默认关(opt-in),编排器调用面启用。** `--pack-bytes 0` = 既有路径逐字节不变(无新字段)。
**替代案(默认开)否**:非配额环境无收益还改行为;丢「关闭路径逐字节回归」这条最强验证线。
配额场景建议值写 man page(如 `--pack-bytes 16384`)。

**D2 上下文边界 = 包,恢复边界 = 簇,跳过逻辑放任务模板。** 成员级 marker 真相源不变;模板
新增「`done_marker` 已存在的成员跳过」指令(subagent 一次 `Bash` 批量探测或逐成员探测)。
**替代案 A(包级 marker)否**:crash 中途全包重做,配额下重复归纳 = 烧配额,正中要害;**替代案
B(runner 感知成员、逐成员派发)否**:runner 改 ack 状态机,触最稳定面,违背零改动目标。

**D3 确定性分区:同 category 内 `(bytes 升序, cluster_id)` 排序 + 贪心装包;包 id sha8 派生。**
排序键含 `cluster_id` 保证全序稳定(同 bytes 无歧义);包 id =
`pack::<category>::<sha8(成员 id 排序拼接)[:8]>`,分区与 id 是 `(clusters.json, flag)` 纯函数。
**替代案(首次枚举顺序装包)否**:分页 offset 变化或上游 clusters.json 重排会改变包成员集,
包 id 漂移 → 重派身份不一致。`--pack-bytes` 为主(摊薄与上下文规模同锚 request-context-budget
字节预算)、`--pack-max 8` 为护栏(防单包成员过多导致模板迭代膨胀)。

**D4 合并 input 单文件。** 每包一个 `<safe(pack_id)>.input.json` = `{repo, pack_id, members:[
{cluster_id, ...簇完整记录, hits}]}`,subagent 一次 Read 摊薄 N 簇;成员级 checkpoint/done 路径
列在文件头(模板逐字引用)。**替代案(成员级 input N 个)否**:N 次 Read = N 次调用,固定开销
省不下来。文件名 stem 同受 `_safe_name` 长度上限(NTFS ADS 教训,`::` 消毒同源)。

**D5 `cluster_id` 字段位载包 id。** `fanout_runner.py` TIERS["t1"] 的字段映射/占位符/ack 契约
原样消费。**替代案(新增 `unit_id` 字段)否**:runner 需改字段映射与模板占位符集,触 R5.3(b)
稳定契约;字段位复用零改动。包 id 长度有界(`pack::<category 前缀截断>::<sha8>`,≤ 簇 id 同款
160 上限),`_safe_name` 消毒路径既有逻辑覆盖。

**D6 失败语义:failed ack = 包级终态,缺失成员走人工 recipe。** 模板指示:成员失败时**先完成
其余成员**(逐簇写 marker),最后 ack `failed <成员 id 列表>:<原因>`;runner 照既有状态机写包级
`.failed`(终态、不自动重试)。恢复 recipe(进 man + discipline path_recipes):删除包级 `.failed`
→ 重列 → 包回 pending → 已 done 成员被模板跳过,仅缺失成员重归纳。**替代案(failed 即时中断
整包)否**:放弃已归纳成员的 marker,重派重复烧配额。

**D7 页预算交互零特判。** 包壳含 `members[]`,单页序列化字节天然变大——既有
`--orch-budget-bytes` 自动收紧 `effective_limit` 逻辑原样覆盖,无新增分支。

## Risks / Trade-offs

- [包上下文过大冲垮 T1 单元质量] → `--pack-bytes` 字节上限 + `--pack-max` 双护栏;建议值
  16KB(≈4–8 小簇)从真机数据反推,man 披露校准方法。
- [同上下文多簇记录互相污染] → 模板逐簇处理纪律(每簇独立写) + 记录 `unit` 字段 MUST =
  成员 id(既有 schema gate 机械校验)+ `validate_t1_records.py` 零改动即拦截串写。
- [包级 `.failed` 搁浅缺失成员] → D6 recipe 披露;`stalled`/`failed` 摘要已含 marker 存在性,
  诊断面不变。
- [单元数下降影响熔断窗口粒度] → 熔断按**派发单元数**计数(包即单元),窗口变小但语义不变;
  零推进判据仍是磁盘 marker 计数(簇级),不受打包影响。
- [合并 input 写失败] → 物化失败簇隔离语义照旧(排除出包、写簇级 `.failed`);包物化整体失败
  → 该包不进 `pending[]` + stderr 告警,退出码不变。

## Migration Plan

默认关 → install 即生效、零行为变化。启用 = 编排器调用行加 `--pack-bytes <B>`(fragment/
discipline 同步);回滚 = 去掉 flag(磁盘上两类 marker/记录形态完全一致,混跑安全:已 done 的
簇无论打包与否都跳过)。

## Open Questions

- `--pack-bytes` 产品默认建议值:16KB 起步,待真机按「包大小 vs 归纳质量(vs 调用数)」校准。
- scout/t3 是否同款打包(scout 批已有 batch 聚合;t3 每 category 天然粗粒度)——预期收益小,
  留待配额实测数据回来再评估。
