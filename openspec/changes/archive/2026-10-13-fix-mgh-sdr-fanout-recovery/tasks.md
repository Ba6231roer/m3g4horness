# Tasks — fix-mgh-sdr-fanout-recovery

> 单文件收口:`core/scripts/fanout_runner.py`(六域共用基座)。每组先红后绿;in-process
> harness MUST 传 `--cooldown-s 0`(仓库既有约定)。

## 1. M4 — 限流截断竞态(CI 红修复,最高优先)

- [x] 1.1 主线程补位循环:pop 之后、`pool.submit` 之前复查 `_rate_limited()`;命中则丢弃本次提交(design D1)
- [x] 1.2 验收:`TestRateLimitStorm::test_all_rate_limit_storm_truncates_fast` 转绿,连跑 ≥5 次全绿(修复前本机 5/5 红)
- [x] 1.3 若连跑仍偶发红 → 升级 storm_lock 同步域方案(design D1 备选),同验收口径

## 2. H5 — cmdline 探测回退与证据保全

- [x] 2.1 `_pid_cmdline` Windows 分支:wmic 先试,失败回退 PowerShell `Get-CimInstance`(单次超时 + 确定性解析)
- [x] 2.2 两种探测均不可用且 PID 存活 → fail-loud(stderr 披露)、不删 liveness 文件、退出码非 0
- [x] 2.3 回归:伪造孤儿(runner + child 形态)+ 模拟 wmic 缺失 → CIM 回退检出并正确分类;探测全不可用 → 证据保留 + 非 0 退出;`removed` 非空时 `none:false`

## 3. M1 — 退出摘要 failed 双计

- [x] 3.1 退出摘要计数改 `max(磁盘快照, 起始 + 本 run 写入)`;`_sidecar_payload` 同改
- [x] 3.2 回归:re-list 含本 run 失败 marker 的场景 → 计数 == 真实失败数(修复前全败 10 单元报 20)

## 4. M2 — 心跳 idle 接线

- [x] 4.1 活跃 sink 引用传入 `_run_unit`(签名扩展或共享注册表,取小);心跳 `idle` 改读活跃 sink 最新输出时戳
- [x] 4.2 回归:持续输出的健康单元 → 心跳 `idle` < stall_window(修复前恒等于距派发时长);心跳行字段名与 stdout 契约零变化

## 5. M3 — kill-stale 扫描根锚定

- [x] 5.1 plan_path 再锚定逻辑前移到 kill-stale 分支之前;kill-stale 扫 `plan_path.parent`
- [x] 5.2 回归:sdr 规范调用形 + liveness 在 run 目录 → 检出(修复前 `none:true`);scout/t1/t3 文件参数形态行为不变

## 6. M5 — 恢复模式参数可选

- [x] 6.1 `--checkpoints/--inputs-dir` 改默认 `None`;kill-stale 分支容忍缺失;非 kill-stale 路径缺参仍可操作报错
- [x] 6.2 回归:`--kill-stale --tier <t>` 无 artifact 参数原样可跑(修复前 argparse 退出 2)

## 7. L12 — liveness 读回非致命

- [x] 7.1 liveness 读回包 try/except,失败就地重建 body
- [x] 7.2 回归:只读目录场景整 run 不崩(修复前 FileNotFoundError traceback)

## 8. 收口

- [x] 8.1 定向回归:`python tests/test_fanout_runner.py`、`python tests/test_fanout_stale.py`;顺手 `python tests/test_zero_deps.py`、`python tests/test_no_compile_warnings.py`
- [x] 8.2 `python tools/check_contracts.py`(M5 参数可选化后确认壳内调用形断言仍一致)、`python tools/check_distributed_purity.py`
- [x] 8.3 `CHANGELOG.md` + `VERSION` bump
