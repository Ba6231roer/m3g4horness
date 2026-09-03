## ADDED Requirements

### Requirement: resume_state stdout 携带 stale-fanout 检出(stale_fanout)

`resume_state.py` 的 stdout SHALL 增 `stale_fanout` 字段(增量字段,基座 shape 不变):扫
`<init-dir>/fanout_runner.*.pid` liveness 文件,每份残留文件报
`{tier, pid_file, pid_alive, note}`;`pid_alive` = 该 PID 当前存活(OS 进程表查询)。
任一 `pid_alive:true` → `note` SHALL 附 `--kill-stale --dry-run` recipe(编排器 resume
第一步先杀孤儿再继续,防双跑烧 token + checkpoint 竞态)。无 liveness 文件 → `stale_fanout:
[]`(字段恒存在,shape 稳定,承 resume_state 既有空结构约定)。该字段是 resume 衍生量、非
持久态;`--check` 对 stale-fanout SHALL 仅 advisory 披露(notes[]),NEVER 作为 gate(孤儿
单元留 pending 本就是合法可重派态,杀死旧 runner 是优化而非正确性前提)。

#### Scenario: 孤儿 fanout 在 resume 时被点名

- **WHEN** 上次 t1 fanout 被硬杀、宿主子进程树仍在跑,编排器执行 `/mgh-init --resume` 第一步
  `resume_state.py --target <t>`
- **THEN** stdout `stale_fanout` 含该 tier 条目(`pid_alive:true` + kill-stale recipe),
  `notes[]` 含 advisory 披露;step/next_action 派生逻辑不受影响(仍按磁盘 marker 重派 pending)

#### Scenario: 无孤儿时字段空但不缺

- **WHEN** 运行目录无任何 `fanout_runner.*.pid` 残留
- **THEN** stdout 含 `stale_fanout: []`(字段恒存在),无 note,`--check` 无 stale 相关披露

#### Scenario: 计数口径自解释(tier 计数 ≠ 目录文件数不误读为丢数据)

- **WHEN** 用户比对 stdout `tiers.t1.done`(如 472)与 `checkpoints/t1/` 下文件数(如 491)
- **THEN** `resume_state.py` docstring/--help 注明口径差异:done = `*.json.done` marker 文件
  glob 计数(exclude tier 级 marker),目录里另有 `.failed` marker、`<id>.json` 记录体等非
  done 文件;两数字差非数据丢失(计数语义不同)。口径说明 SHALL 同时覆盖
  `list_clusters.py` 的另一 done 口径(记录体 `unit` 字段去重、shard 感知)与 resume_state
  口径(纯文件计数)的等价条件(无 shard、无 orphan marker 时相等)
