# fix-mgh-init-done-marker-identity — Tasks

## 1. T1 枚举正向 done 判定(核心修复)

- [x] 1.1 `core/scripts/list_clusters.py`:`_done_ids`/`_failed_ids` 重写为正向计算——入参从
  `checkpoints_dir` 改为 `(checkpoints_dir, canonical_ids: list)`;对每个 id 复用既有
  `_safe_name` + `_paths` 编码出 marker 路径,`Path.is_file()` 判终态;删除「记录体 `unit`
  字段优先 + stem 兜底」旧逻辑与 `could not read unit from …; using stem` 告警路径
- [x] 1.2 `core/scripts/list_clusters.py` 主循环:canonical id 集从 `clusters[].cluster_id`
  (+ oversize 簇的 `::shard-<n>` 派生 id)收集后一次传入;孤儿审计 = glob
  `*.json.done`/`*.json.failed` 全集 − 正向文件名集,差集 stderr `warn: orphan marker …`
  逐个列出(fail-soft,不阻断)
- [x] 1.3 round-trip 回归测试(`tests/test_init_clusters.py`):≥200 字符 cluster_id 的
  簇写 `<encoded>.json` + `<encoded>.json.done` → `list_clusters` 判 done(pending 不含、
  done 计数含);分片 id `::shard-<n>` 同测;孤儿 marker → stderr 告警 + 语义不变;
  记录体无 `unit` 字段不影响判定

## 2. scout 同形修 + t3 免疫锁定

- [x] 2.1 `core/scripts/list_scout_batches.py`:`_done_ids`/`_failed_ids` 同形重写为正向计算
  (canonical id = `scout_plan.batches[].batch_id`),孤儿审计同 1.2;删 stem 兜底
- [x] 2.2 回归测试(`tests/test_scout_batches.py`,无则新建):batch_id 正常/超长两形态 +
  孤儿 marker 审计
- [x] 2.3 `list_rule_jobs.py` 不改行为;补「长名 category 免疫」回归测试锁形状
  (`_done_categories` 文件名解码 + slug id 不经截断)

## 3. dispatcher 收敛熔断

- [x] 3.1 `core/scripts/fanout_runner.py`:每波收敛后快照 `done+failed`;连续
  `--stall-waves`(默认 2)个快照相等且 pending 非空 → 停止派发,exit 2,stdout 增
  `stalled:true` + `stalled_pending[]`(每项 `{id, done_marker_exists, failed_marker_exists}`),
  stderr 诊断 recipe(resume_state 诊断;停止重派)
- [x] 3.2 `--help` 契约面补 `--stall-waves`(`tools/check_contracts.py`
  FANOUT_RUNNER_REQUIRED_FLAGS 增补;双壳 mgh-init.md 同步 flag 表——若壳 flag 表列了它)
- [x] 3.3 回归测试(`tests/test_fanout_runner.py`):2 波零推进触发(exit 2 + stalled 字段);
  1 波零推进+次波推进不触发;正常 `partial:true` 路径行为逐字不变

## 4. resume_state 口径 + --check 一致性校验

- [x] 4.1 `core/scripts/resume_state.py`:t1/scout tier done 计数与正向判定同源(共享判定
  函数 import 自枚举脚本或 `init_tier`,NEVER 复制);docstring/--help 口径说明更新
  (done = canonical id 正向判定;目录条目数差异说明保留)
- [x] 4.2 `resume_state.py --check` 新增:canonical 单元判 pending 但其 marker 文件已存在 →
  violation(退出码 2,列 id + 磁盘路径 + recipe);孤儿 marker → notes[] advisory;
  「`.done` 无兄弟记录体」不再 violation(touch-only 合法形态)
- [x] 4.3 回归测试(`tests/test_resume_state.py`):判 pending + marker 存在 → exit 2;
  孤儿 → note;口径说明存在于 --help

## 5. unit 字段双保险(记录体 + 契约 + validator)

- [x] 5.1 `core/prompts/fragments/fanout/t1-task.md` + `releases/claude-code/agents/init-induct.md`
  (+ `init-induct-fanout` 若独立):记录指令加「根级 `unit` = 透传的 canonical 单元 id
  (分片 = `::shard-<n>` 形态)」
- [x] 5.2 `core/scripts/validate_t1_records.py`:`--check` 断言 `unit` 非空字符串 +
  `unit == cluster_id`;历史形态区分——无 `unit` + 正向 marker 已存在 = warning(明示
  「历史形态,无需处理」),无 `unit` + marker 不存在 = violation;`core/contracts/init/t1-record-schema.md`
  契约表补 `unit` 行
- [x] 5.3 回归测试:新形态记录(带 `unit`)通过;`unit` ≠ `cluster_id` violation;
  无 `unit` + marker 存在 warning;无 `unit` + 无 marker violation

## 6. 双壳纪律 + 文档 + lint 收口

- [x] 6.1 `releases/claude-code/commands/mgh-init.md` + `releases/opencode/command/mgh-init.md`:
  T1/scout fan-out 段补「连续零推进 exit 2 → 停止重派、跑 resume_state 诊断」recipe;
  flag 表同步 `--stall-waves`
- [x] 6.2 `core/prompts/fragments/init-stage/t1.md` + `scout.md`(若引用 done 判定语义):
  同步正向判定语义;`core/contracts/init/cluster-enumeration.md`/`scout-enumeration.md`/
  `resume-state.md` 契约文档同步
- [x] 6.3 lint 全绿:`py tools/check_contracts.py`、`py tools/check_distributed_purity.py`
  (确认无 R5.x/FDn/Dn dev-meta 泄漏进双壳)、`py tools/measure_prompts.py`(壳/fragment
  预算不超);受影响单测全跑(`py tests/test_init_clusters.py tests/test_scout_batches.py
  tests/test_fanout_runner.py tests/test_resume_state.py`,无 pytest 依赖按仓库惯例)
- [x] 6.4 bump 版本号(`VERSION`)+ `CHANGELOG.md` 条目(承 R5.8:任何脚本改动 bump)

## 7. 受卡 run 自愈验证

- [x] 7.1 用用户真实受卡 run 目录(或等价 fixture:476 短 id done + 5 failed + 32 超长 id
  含 `.json`+`.json.done`)端到端验证:`resume_state.py --target <run>` 判 step=t1 →
  `list_clusters --materialize` pending=0/done=508 → tier 完成、T2 可启动;全程零手工
  磁盘操作
