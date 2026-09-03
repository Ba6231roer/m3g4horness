# fix-mgh-init-done-marker-identity — Design

## Context

见 proposal.md「Why」。当前磁盘态判定链(修复前):

```
_done_ids(checkpoints_dir):                    # list_clusters.py:164
  glob "*.json.done" → 读兄弟记录体.get("unit") # T1 记录契约无 unit 字段 → 恒 None
  → fallback: record.stem                      # = _safe_name(id) 后的文件名 stem
  → done.add(stem)                             # 与 canonical cid 比对
主循环: if cid in done: continue               # 长 id 截断 stem ≠ cid → 永不命中
```

- `MAX_UNIT_FILENAME_STEM = 200`(`list_clusters.py:94`),超长 stem 编码为
  `head + "~" + tail`(list_clusters.py:243-259)。
- `_paths(checkpoints_dir, unit_id)`(list_clusters.py:319)是 marker 路径的**唯一编码点**
  (写侧 pending[].done_marker 与读侧本可用同一函数——读侧却选择了 glob+stem 反查)。
- 磁盘事实:用户 run 中 32 个超长 id 簇已有 `.json` + `.json.done`(subagent 已完成、
  marker 已 touch),done=476/failed=5/pending=32 恒定;`_failed_ids`(list_clusters.py:189)
  同形(`unit` 字段 → stem 兜底)。
- `resume_state.py` t1 计数 = 裸 `*.json.done` glob 计数(resume_state.py:432),与
  list_clusters 口径本就不同(docstring 已披露口径差);t1 tier 完成判定
  `done+failed >= total` 用 list_clusters 语义时永远不满足。

## Goals / Non-Goals

**Goals**
- done/failed 判定免疫文件名截断与记录体字段漂移(正向 marker 路径计算,与物化同源)。
- 卡住的存量 run 修复后 `--resume` 零手工干预自愈。
- 同形状面(scout)一并修;t3 验证天然免疫、不改。
- 无限重派循环有确定性熔断,不再烧穿会话预算。
- 判定不一致从「静默口径差」升级为 `resume_state --check` 可检 violation。

**Non-Goals**
- 不改 `_safe_name` 编码本身(既有 32 个 `.json`+`.json.done` 产物路径必须继续有效——
  改编码 = 废弃存量产物,与自愈目标冲突)。
- 不改 marker 文件格式/位置(`.done` 空 touch 语义、`.failed` body 语义不变)。
- 不改 fanout 模板的任务消息结构(`unit` 字段指令除外)。
- 不动 sra/srr/sast 的枚举脚本(它们无「文件名截断编码」缺陷形状:sra/srr capability
  id 是干净 slug、sast 走 chunk 切片;若未来引入长 id 再按同 design 复制)。

## Decisions

**D1 — 正向 marker 路径计算取代 glob+stem 反查(核心)**
枚举脚本遍历计划产物中的 canonical id(clusters.json 的 `clusters[].cluster_id`、
scout_plan 的 `batches[].batch_id`),对每个 id 调与 `_write_unit`/`_paths` **同一个**
`_safe_name` → 拼 marker 文件名 → `is_file()`。done 集 = 判 done 的 canonical id 集;
孤儿审计 = glob 全量 marker − 正向计算出的文件名集,差集 stderr 告警。
*备选弃案*:(a) 只给 T1 记录体加 `unit` 字段、保留 glob 反查——新 run 可对齐,但存量
run 的 476 条历史记录无 `unit` 字段、修复前卡住的 32 条记录即便 `--check` 重派也不产生
新身份,自愈失败;(b) stem 反向解码(截断 stem 不可逆,需哈希碰撞枚举,不可行)。

**D2 — done 判定只认 marker 文件存在性,记录体降级为审计信息**
`.done` 是编排器/subagent touch 的终态凭证,marker 存在即终态——与 fanout-dispatch spec
「磁盘 marker 为唯一真相源」既有语义严格一致,不新增第二真相源。记录体 `.json` 是否可读、
`unit` 字段是否存在,**不影响**判定(修复前 32 条记录可读但字段缺失;修复后历史记录缺
`unit` 只进孤儿/审计告警面)。_done_ids 的「记录体 unit 字段优先」旧逻辑整体删除,
`--check` 面的「.done 无兄弟记录体」violation 同步取消(marker 无 body 是合法形态,
touch-only 语义)。

**D3 — 熔断锚定波次边界终态计数,`--stall-waves` 默认 2**
每波收敛(全部子进程 join)后取 `done+failed` 快照;连续 2 个快照相等且 pending 非空 →
exit 2 + `stalled_pending[]`。默认 2 而非 1:合法慢波(在飞单元 call-timeout 到点、无
ack 无 marker、下一波重派即推进)在 1 波窗口会误熔断;2 波窗口下「真卡死」必然命中
(卡死单元的 pending 集逐波恒同)。「真卡死」与「慢」区分:慢 = marker 缺席但会缺席到
什么时候不可知,熔断把它转成 fail-loud 由人/诊断裁决——宁可早熔断(重派成本一次
resume_state 诊断)不可晚熔断(烧 30min×5 并发×N 波)。
*备选弃案*:熔断放编排器纪律(靠 LLM 自觉数波次)——违反 R5.7「能用 hook/确定性闭环的
不写进 MD 靠自觉」。

**D4 — 孤儿 marker fail-soft 审计,不进任何计数**
改名/遗留 run 的 marker 与当前计划产物的 canonical id 集天然不相交。孤儿不阻断枚举
(fail-soft)、不进 done/failed/pending、stderr 告警 + `resume_state --check` notes[]
列出。319 行注释里「done detection reads the record's `unit` field, not the filename →
resume matching unaffected」的旧注释同步改写(它描述的正是本次的缺陷机制)。

**D5 — `unit` 字段为双保险,身份自洽进 validator**
t1-task.md 模板 + init-induct agent 定义 + t1-record-schema 契约加根级 `unit`(值 =
透传的 canonical 单元 id,分片即 `::shard-<n>` 形态);`validate_t1_records.py --check`
断言非空 + 与 `cluster_id` 一致。历史记录缺 `unit` 的处理:`--check` 判 violation
(外科重派)会让存量 run 重烧 32 个已完成单元——**不可接受**;故历史记录(无 `unit`)在
`--check` 报 **warning 不 violation**、done 判定不受影响,仅新产出的记录 MUST 带 `unit`。
区分依据:文件无 `unit` 字段 + 其正向 marker 已存在 = 历史合法形态;marker 不存在 + 无
`unit` = 新违例。

**D6 — scout 同形修,t3 留验证测试**
`list_scout_batches._done_ids/_failed_ids`(list_scout_batches.py:98-140+)与 list_clusters
同形状(glob → 记录体 `batch_id` → stem 兜底)。当前 scout 记录契约有 `batch_id` 字段、
恰好对齐,但**同一次截断/漂移就会翻车**(scout batch_id 当前是干净 `scout-NNN`,免疫是
巧合不是结构);一并切正向计算,消除同类面。t3 的 `_done_categories`/`_failed_categories`
按 `<category>.<fmt>.json[.done|.failed]` 文件名解码,category 是干净 slug、无截断编码,
天然免疫——不改行为,补一个「长名 category 免疫」回归测试锁形状。

## Risks / Trade-offs

- [正向计算依赖计划产物 canonical id 与写侧编码一致(同一 `_safe_name`/`_paths`)]
  → 两函数在同一文件内、单点定义;测试断言 round-trip(`_safe_name(_paths(id))` 与
  磁盘实际文件名一致,含 200+ 字符 id)。
- [孤儿审计 glob 目录大时(数千 marker)每次枚举都全扫] → glob 一次 O(n) 与现状
  `_done_ids` 同复杂度;目录规模 ~10³,negligible。
- [熔断默认 2 波对超慢在飞单元(恰在 2 波边界收敛)误熔断] → 在飞单元 call-timeout
  上限 7200s;若真有 >2 波时长(≥4h)的单单元,熔断后 resume 重派、其已有产物不受损
  (marker/记录幂等),损失一次重派而非烧穿。
- [历史 run 记录缺 `unit` 在 `--check` 报 warning,可能被误读为「该修」] → warning 文本
  明示「历史形态,marker 判定不受影响,无需处理」。
- [`resume_state --check` 新增「判 pending 但 marker 存在」violation 依赖正向计算与
  resume_state 两处同源] → 判定函数收敛到单一共享位置(见 tasks:`init_tier.py` 或
  各枚举脚本导出,resume_state import),NEVER 复制两份。

## Migration Plan

1. 落地代码 + 测试(check_contracts 无新增 flag 面;bump 版本号,承 R5.8)。
2. 受卡 run 自愈路径:用户对既有 run 直接 `/mgh-init --resume` → `resume_state` 判
   step=t1 → `list_clusters` 正向判定 32 个单元 done → pending 空 → tier 完成 →
   T2 起续跑。零磁盘手术、零数据迁移。
3. 回滚:git revert 即回 glob+stem 反查;存量 marker/记录双向兼容(两代判定都认
  `marker 存在` 这一事实,回滚后长 id 单元回到「永久 pending」旧缺陷但不损坏数据)。

## Open Questions

(无——判定语义、熔断窗口、历史记录兼容均已收敛;实现细节见 tasks.md。)
