# request-context-budget Specification [MODIFIED]

## MODIFIED Requirements

### Requirement: Per-unit inputs are materialized and bounded

每条 `mgh-*` 命令的每个扇出单元 SHALL 由其确定性枚举脚本物化完整输入记录到
`<命令输出目录>/inputs/<tier>/<unit>.input.json`(init:T1 cluster/scout batch/T3 category;sast:s4 chunk/s6
verify-job;sra/srr:per-capability;绝对路径、落运行域树内、幂等、`--resume` 复用),其字节数 SHALL ≤
`--max-unit-bytes`。枚举脚本 `pending[]` 每项 SHALL 携带该单元的 `input_path`(绝对)+ `bytes` + `oversize`。
subagent SHALL **读自己的 `input_path`**(一个有界单元);编排器 SHALL 向 subagent **透传 `input_path`**
而非内联传完整记录。超 `--max-unit-bytes` 的单元 SHALL 被确定性切分(init T1:按 evidence/usage-site 组切分
子单元;sast:超 `--big-file-bytes` 文件经 `chunk_sources` 切片;sra/srr:capability 不切分)或标
`oversize:true` + recipe。

**done/failed 判定 = 正向 marker 路径计算(身份免疫)**:枚举脚本判定某单元是否已完成/终态失败
SHALL 为**正向计算**——遍历计划产物(`clusters.json`/`scout_plan.json` 等)中的 canonical 单元 id,
对每个 id 用与输入/检查点物化**同一编码函数**(文件名 sanitize + 长度截断)算出确切的
`.done`/`.failed` marker 路径,`is_file()` 即终态。done/failed 判定 SHALL **NEVER** 依赖
(i) checkpoint 记录体字段名与 canonical id 的一致性(记录体可能没有该字段、或字段名漂移),
(ii) 文件名 stem 反推(被截断的文件名 stem ≠ canonical id)。glob 反查磁盘 marker 保留 SHALL 但
降级为**孤儿审计**:磁盘存在 `.done`/`.failed` marker 而其派生路径不对应任何 canonical 单元 id
(或 canonical 单元判 pending 而其 marker 已存在——即判定不一致)→ stderr 告警列出,不改变
pending 语义。理由〔正向计算与物化同源,天然免疫文件名截断/记录体字段漂移;glob+stem 反查在
超长 id 截断场景把已完成单元永久判 pending → fan-out 无限重派(实测:32 个超长 id 簇已有
`.json`+`.json.done` 仍被反复派发,wave5 起每波 5 并发×30min 全部重烧,done=476/failed=5/
pending=32 恒定不收敛)〕。

#### Scenario: Subagent reads its own bounded input file (generic)
- **WHEN** 任一 `mgh-*` 命令扇出一个单元,编排器 spawn 对应 stage subagent
- **THEN** 该 subagent 输入含一个绝对 `input_path`,指向该命令 `inputs/<tier>/<unit>.input.json`,其
  `bytes` ≤ `--max-unit-bytes`;subagent Read 该文件而非编排器内联传记录

#### Scenario: Oversize unit is sharded or flagged, never passed whole
- **WHEN** 某 fan-out 单元完整记录 `bytes` > `--max-unit-bytes`
- **THEN** 枚举脚本将其切分子单元(init T1 `::shard-<n>`、sast 走切片)或标 `oversize:true`(sra/srr
  capability、init T3 category)+ recipe;`pending[]` 不出现超阈值整单元

#### Scenario: Materialized inputs are resumable and idempotent
- **WHEN** 同一单元在 `--resume` 下再次枚举
- **THEN** 已物化的 `<unit>.input.json` 被幂等复用(按 unit 覆盖,不重复膨胀),`pending[]` 据各自
  `done_marker` 跳过已完成单元

#### Scenario: Overlong-id unit with existing done marker is terminal
- **WHEN** 某 T1 簇的 canonical `cluster_id` 超出文件名 stem 长度上限(其 `_safe_name` 编码产生
  截断形态文件名),且磁盘已有该单元的 `<encoded>.json` 记录 + `<encoded>.json.done` marker
- **THEN** `list_clusters.py` 将其判为 done(从 `pending[]` 消失),NEVER 依赖记录体字段值或
  截断 stem 反推;`--resume` 不再重派该单元

#### Scenario: Orphan markers are audited but never silently ignored
- **WHEN** 磁盘 checkpoint 目录存在 `.done`/`.failed` marker,其编码文件名不对应任何 canonical
  单元 id(改名后的遗留 run、手工产物)
- **THEN** 枚举脚本 stderr 告警列出孤儿 marker 文件名;stdout `pending[]` 语义不受影响;
  枚举不失败、不中断

#### Scenario: Record-body unit field is consistent but never load-bearing
- **WHEN** 某 checkpoint 记录体的身份字段(`cluster_id`/`batch_id`/新增 `unit`)与 canonical id
  一致或缺失
- **THEN** done/failed 判定结果不变(判定只由正向 marker 路径决定);记录体身份字段仅作诊断
  信息与孤儿审计对照
