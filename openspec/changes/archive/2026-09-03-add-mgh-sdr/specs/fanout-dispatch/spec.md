## ADDED Requirements

### Requirement: sdr tier dispatches diff-review units through the shared wave machine

`fanout_runner.py` 的 `--tier` 闭集 SHALL 扩为 `scout|t1|t3|sdr`,新增 `sdr` 条目挂入既有 TIERS
单点映射表:枚举脚本 = `diff_group.py`(`--repo/--base/--branch/--checkpoints/--materialize` 转发)、
任务模板 = `core/prompts/fragments/fanout/sdr-task.md`、fanout agent = `sdr-review-fanout`、
占位符集 = 路径字段(`input_path`/`draft_path`/`done_marker`/`failed_marker`)+ `unit_id`/
`kind`/`route`/`repo`/`codegraph`。波次循环、ack 状态机、三级超时不变式、liveness 登记、
`--kill-stale`、零推进熔断、进度 sidecar(`<init-dir>/fanout_progress.sdr.json`)SHALL 对 sdr
tier 零改动复用(tier 无关代码路径不变);`diff_group.py` 的 gate 形退出码 2(如 base ref 不存在)
SHALL 与 t1 scout-incomplete-gate 同形透传(fail-loud + stderr recipe,NEVER 进入重派循环)。
`install.sh` 自检清单与 fanout agent 自检 SHALL 覆盖 `diff_group` 脚本、`sdr-task.md` 模板与
`sdr-review-fanout` agent 克隆;`tools/check_contracts.py` 覆盖引用 `diff_group.py` /
`render_sdr_report.py` / `sdr_context.py` 的壳调用 flag。既有 scout/t1/t3 三 tier 的调用面、模板、
agent、行为 SHALL 逐字不变。

#### Scenario: sdr tier 经共享状态机波次消化

- **WHEN** `diff_group.py --materialize` 产出 12 个 pending 单元,编排器一次调用
  `fanout_runner.py --tier sdr --repo <abs> --base master --branch X --checkpoints <dir> --inputs-dir <dir>`
- **THEN** dispatcher 以 `--wave` 并发度内部消化全部波次,每单元 spawn 一个 `sdr-review-fanout`
  subagent(任务消息 = `sdr-task.md` 模板逐字填充),stdout 摘要含 `tier:"sdr"`;软时限早退 /
  resume / 熔断行为与既有 tier 一致

#### Scenario: sdr 单元越树路径 spawn 前拦截

- **WHEN** 某 pending 项的 `draft_path` 解析后落在 `repo` 锚树外
- **THEN** dispatcher 不 spawn,直接写 `.failed` marker(reason=path-drift),后续波次不受影响
  (与既有 tier 同一 `_anchor_check` 代码路径)

#### Scenario: 既有 tier 行为零漂移

- **WHEN** 对 scout/t1/t3 各自的枚举产物运行既有调用面并比对本次变更前后的 stdout 摘要与模板
  填充结果
- **THEN** 三 tier 的枚举脚本、模板、agent、占位符集、波次行为逐字一致(TIERS 表增行不触既有行)
