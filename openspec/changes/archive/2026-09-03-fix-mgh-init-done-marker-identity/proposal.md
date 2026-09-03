# fix-mgh-init-done-marker-identity

## Why

mgh-init T1 fan-out 出现**无限重派**：AI 编排器在 wave5 起反复派发同一批 32 个簇单元，
每个单元磁盘上已存在 `<unit>.json` 记录 + `<unit>.json.done` marker（subagent 其实已
完成），但 `list_clusters.py` 仍把它们列为 `pending`（done=476, failed=5, pending=32），
materialize 阶段 stderr 连续刷 `warn: could not read unit from …; using stem`。后果：
32 个长名单元**永远不会被认为 done** → 每波 5 并发 × 30min 全部重烧已完成工作（内网慢
接口放大浪费）→ `done + failed` 永远凑不齐 `total` → tier 永不完不成 → 后续 T2/T3/T4
全部无法启动。

根因是**身份漂移**，两层叠加：

1. **记录体字段名不匹配（主因）**：`list_clusters._done_ids` 读每个 checkpoint 记录体
   的 `unit` 字段来恢复 done 集；但 T1 checkpoint 记录的唯一契约
   （`core/contracts/init/t1-record-schema.md`）根级字段是 `cluster_id`——**没有任何
   产出者（subagent 契约、T1 提示词、fanout 模板）写过 `unit` 字段**。每个 T1 记录都
   读到 `None` → 100% 落入文件名 stem 兜底。短 id 的 stem 恰好等于 canonical id
   （stem 兜底被 476 个短簇侥幸掩盖）；超长 cluster_id（>`MAX_UNIT_FILENAME_STEM`=200）
   被 `_safe_name` 截断成 `head~tail` 形态 → stem ≠ canonical id → 永不匹配 → 永远
   pending。
2. **无收敛熔断（放大器）**：`fanout_runner` 每波从 `list_clusters` 重派生 pending，
   pending 恒非空 → `partial:true` → 编排器按纪律重派同一命令 → 无限循环。dispatcher
   对「连续 N 波 done 零推进」没有确定性熔断，编排器纪律也没有「连续零推进 → 停止重派
   → 调 resume_state/`--check` 诊断」的 recipe。

同族风险面：`list_scout_batches`（读记录体 `batch_id`——scout 记录契约里有该字段，
当前恰好对齐）、`list_rule_jobs`（按 `<category>.<fmt>.json.done` 文件名直接解码
category，无记录体回读，天然免疫）。`_failed_ids` 同形读 `unit` 字段，靠
`record.stem` 兜底，同样的漂移形状。

## What Changes

- **done/failed 判定从「glob 反查 + 记录体字段 + stem 兜底」改为「正向 marker 路径
  计算」**：枚举脚本遍历 `clusters.json`（或 scout_plan）的 canonical 单元 id，对每个
  id 用与物化**同一函数**（`_paths`/`_safe_name`）正向算出确切 marker 路径，
  `is_file()` 即终态。枚举脚本本就知道全部 canonical id——done 判定不需要从磁盘
  反查身份，天然免疫截断/改写。glob 反查保留，但**降级为孤儿审计**（磁盘上有 marker
  而 canonical id 集里没有的 → stderr 告警，不进 done/failed 集）。
- **`list_rule_jobs` 不变**（无此缺陷形状）。
- **fanout_runner 收敛熔断**：连续 N 波（默认 2）done/failed 零推进且 pending 非空 →
  退出码 2 + stderr 诊断（pending id 列表 + 每个的 marker 存在性），编排器纪律接 recipe
  （停止重派、跑 `resume_state.py` 诊断）。熔断而非硬失败：pending 语义不变，人/诊断
  工具可介入。
- **t1 记录体加 `unit` 字段**（双保险，非修复必需）：t1-task.md 模板与
  `t1-record-schema.md` 契约加「记录体根级 `unit` 字段 = canonical unit id（含
  `::shard-<n>` 形态）」；validator 断言之。这样 glob 反查也能恢复正确身份。
- **受卡 run 自愈**：修复后 `--resume` 下，32 个既有 `.json` + `.json.done` 单元由
  正向计算直接判 done（无需手工磁盘手术）；`resume_state.py` 的 t1 计数口径同步。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `request-context-budget`：per-unit materialization + resume 语义增量——done/failed
  判定 SHALL 由正向 marker 路径计算（与物化同源 `_paths`/`_safe_name`），NEVER 依赖
  记录体字段名与 canonical id 的一致性或文件名 stem 反推；孤儿 marker 审计告警。
- `fanout-dispatch`：dispatcher 收敛熔断——连续 N 波零推进且 pending 非空 → exit 2 +
  诊断，编排器纪律接「停止重派 → resume_state 诊断」recipe。
- `resume-step-discipline`：`resume_state.py` t1 口径说明与 `--check` 覆盖「canonical
  id 正向判 done」新语义。
- `t1-record-schema-gate`：T1 记录体根级 `unit` 字段（双保险）进形状契约 + validator。

## Impact

- **代码**：`core/scripts/list_clusters.py`（`_done_ids`/`_failed_ids` 重写为正向计算；
  主循环改传 canonical id 集）、`core/scripts/list_scout_batches.py`（同形重写）、
  `core/scripts/fanout_runner.py`（收敛熔断 + stdout 诊断字段）、
  `core/prompts/fragments/fanout/t1-task.md`（记录体 `unit` 字段指令）、
  `core/prompts/fragments/init-stage/t1.md`（纪律接 recipe）、
  `releases/*/mgh-init.md` 双壳（纪律段同步）、`core/contracts/init/t1-record-schema.md`
  与 `core/contracts/init/cluster-enumeration.md` 奔腾同步。
- **测试**：`tests/test_init_clusters.py`（长 id → done 正确判定 + 孤儿审计 + 熔断）、
  `tests/test_fanout_runner.py`（熔断触发/不触发/诊断字段）、
  `tests/test_resume_state.py`（口径同步）。
- **契约 lint**：`tools/check_contracts.py` 无新增 flag（正向计算不扩 CLI 面）；
  `tools/check_distributed_purity.py` 无 dev-meta 泄漏面。
- **受卡 run 自愈**：用户当前 run 在修复落地后 `/mgh-init --resume` 即解卡——32 个
  单元由正向 marker 判 done，tier 推进到完成，T2+ 得以启动。无数据迁移：既有
  `.json` + `.json.done` 产物完全保留、继续有效。
