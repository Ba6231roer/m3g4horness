> **人话序** 现象：在 Linux 上用 nohup 直跑 `/mgh-init` 的 scout 派发器，三次运行全部在
> **约 10 分钟处猝死**（日志末行时间戳 `+00:09:38`/`+00:09:40`，journalctl `15:29→15:39`），
> 且不留 stdout 汇总、进度侧车停在 `"running"`、`--kill-stale` 报无孤儿——「被强杀、未走正常
> 退出」的标准形状。根因两条，同在失活（stall）处置路径：① POSIX 树杀用
> `os.killpg(os.getpgid(pid))`，而子进程 spawn 时**没有新建会话**，与派发器同进程组 → 杀单元
> 等于**杀自己**，且 kill 发生在写 stall 日志之前，连留痕都来不及；② 失活判据取
> `min(stdout_ts, stderr_ts)`（较早的一路），而两个流的初始时刻都是 spawn 时刻，于是**只要有一
> 路自始至终无字节**，健康单元也会在 `spawn + --stall-timeout-s` 被判失活——`--stall-timeout-s`
> 是 600 秒，精确对上 10 分钟。改什么：① spawn 加 `start_new_session`（POSIX 生效、Windows
> 不变），使树杀作用域收在单元自己的进程组内，派发器存活；② 失活判据改 `max`，与 `--help` 的
> 「no stdout/stderr bytes for this long」语义对齐。怎么验证：单测（单路静默不误判 / 树杀后派发器
> 仍存活 / 心跳 `idle` 取值正确 / Windows 路径逐字不变）+ 真机 25 分钟长跑不再于 10 分钟猝死。

## Why

- **Linux 上 scout 长跑目前不可能成功**。派发器启动自检强制不变式 `--stall-timeout-s` <
  `--call-timeout-s` < `--time-budget-ms ÷ 1000 × 0.8`，即失活阈值**必然早于轮次结束**；只要
  缺陷 ② 存在，健康单元必被误杀，触发缺陷 ①，派发器即死。没有任何参数组合能保证跑满。
- **实测阻塞了正在进行的吞吐判别实验**。`/mgh-init` 在大仓上规划出 1052 个 scout 单元批、
  实测约 1 单元/分钟、外推 16 小时；要判明瓶颈是「模型并发」还是「网关配额」，必须先能连续
  跑满一轮 25 分钟。当前连一轮都跑不完，实验无法取得有效数据。
- **为什么不早暴露**：Windows 走 `taskkill /pid /T /F`，是树范围，不碰派发器，缺陷 ① 不存在；
  且在宿主编排下每轮只有约 8 分钟（宿主单次调用超时截断），从未跑到过 600 秒的失活阈值，
  缺陷 ② 也从未被触发。改在独立终端长跑后，两个缺陷同时命中。

## What Changes

- **POSIX 子进程树杀不再波及派发器自身**：`fanout_runner.py` 的单元 spawn 增设
  `start_new_session=(os.name != "nt")`，使 POSIX 下每个单元子进程自带会话/进程组；
  `_kill_tree` 的 `os.killpg` 因此只作用于该单元自己的树。Windows 行为逐字不变
  （`start_new_session` 为 POSIX-only，且 Windows 分支本就走 `taskkill /T /F`）。
- **失活判据方向修正**：`_run_unit` 的静默时长由 `min(out_ts, err_ts)` 改为
  `max(out_ts, err_ts)`，即「**两条流都没有新字节**」才算静默；心跳披露行的 `idle` 取值同源修正。
- **静默判据的读取粒度修正（实施期追加，经维护者拍板）**：`_tail_stream` 原用
  `TextIOWrapper.read(4096)`，该调用**阻塞到满 4096 字符或 EOF** 才返回，故「最后输出时刻」
  实际按 4096 字符块推进、而非按字节。只做上一条的 `max` 修正仍不够：两路合计不足 4096 字节
  的健康单元，两个时间戳都停在 spawn 时刻，同样会在 spawn + `--stall-timeout-s` 被误杀。
  改为 `stream.buffer.read1(4096)`（有一次可读即返回）+ 增量 UTF-8 解码器，使判据真正落回
  字节级 —— 与 `--help`/spec 的既有措辞和该函数自身 docstring 一致。
- **副作用与配套披露**：`start_new_session` 后，交互式终端按 Ctrl-C 不再连带终止在飞子进程
  （它们自成会话）。孤儿仍由既有 liveness 文件（`children[]`）登记、由既有 `--kill-stale`
  清理；nohup / 后台跑法不受影响。该边界 SHALL 写进 `--kill-stale` 与失活段的 `--help` 文案。
- **回归与版本**：`tests/test_fanout_runner.py` 增四条用例；`VERSION` bump；
  `tools/check_contracts.py` 无需新增断言（无新 flag）。
- **非目标（明确不做）**：不改失活阈值默认值（900 秒）与四级超时不变式；不改
  `--kill-stale` 的检出/清理语义；不改 Windows 树杀路径；不改 ack 状态机与 marker 语义；
  不引入「派发器自适应限速」等新机制（属另一议题）。

## Capabilities

### New Capabilities

<!-- 无。全部为 fanout-dispatch 既有 requirement 的修正。 -->

### Modified Capabilities

- `fanout-dispatch`: 修正「在飞单元失活检测与外科手术式树杀(运行留痕)」——① 「静默」的判据
  SHALL 定义为**两条输出流均无新字节**（等价于取两路最后输出时刻的较新者）；② 树杀的
  作用域 SHALL 收敛在被杀单元自身，**NEVER 终止派发器进程**（POSIX 经进程组隔离实现）；
  ③ 补 Ctrl-C 不再传播的边界披露与 `--kill-stale` 补偿路径。existing 同名 requirement 的
  其余承诺（阈值参数、`< 60` 拒识、run.log 留痕、`stall_killed[]` 披露、tier 一致）逐字不变。

## Impact

- **代码**：`core/scripts/fanout_runner.py`（`_run_unit` 的 `Popen` 与静默判据、`_kill_tree`
  的 docstring、心跳 `idle` 取值、`_tail_stream` 的读取粒度、`main` 的 `finally` 退出清理、
  `--help`/`--kill-stale` 文案）。
- **测试**：`tests/test_fanout_runner.py`（单路静默不误判 / 双路静默仍判失活 / 树杀后派发器
  存活 / Windows 路径与引入前逐字一致 / 心跳 `idle` 取较新者）。
- **文档**：维护者私有文档区里的 `/mgh-init`、`/mgh-sdr` 命令人话说明（失活段与
  `--kill-stale` 段的边界披露）、fan-out 运行手册（经验条目）、术语词典（如需补「进程会话
  隔离」条目）；`CHANGELOG.md`、`VERSION`。
- **兼容性**：无新 flag、无 stdout 字段增删、无依赖变更；退出码语义不变。POSIX 行为修正属
  缺陷修复（原行为使长跑不可能成功），Windows 行为逐字不变。Ctrl-C 传播面的变化是对外可观测
  的边界，已在上方显式披露并由既有 `--kill-stale` 补偿，不视为破坏性变更。
- **前置关系**：`harden-mgh-fanout-crash-storm-resilience`（已实现未归档）的 delta 为纯 ADDED
  requirement，与本 change 的 MODIFIED requirement 不同名，互不冲突。
