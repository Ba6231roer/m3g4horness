# Design — fix-mgh-sdr-fanout-recovery

> 修复对象:2026-10-13 评审在 `fanout_runner.py` 确认的 M4/H5/M1/M2/M3/M5/L12。
> fanout_runner 是六域共用派发基座(2792 行),修复 MUST 对非 sdr tier 无行为变化(同构受益除外)。

## D1 — M4 修法:spawn 前复查截断旗标,验收以连跑稳定性为准

- **竞态形状**:worker 线程在 storm_lock 下置 `rate_limited` 旗标;主线程 `_fill` 先查旗标
  再 pop+submit——第一个 crash future 收割后、第 wave 个记账落地前,主线程可越过旗标补派。
- **主选**:主线程 pop 之后、`pool.submit` 之前**再查一次** `_rate_limited()`;命中 → 丢弃
  本次提交(单元已出队,不再放回——截断即将整体终止,该单元自然留在磁盘 marker 语义下待
  resume)。把竞态窗口从「wave 个记账周期」缩到检查-提交间的纳秒级残留。
- **升级备选**(仅当主选后连跑仍偶发红):把派发决策纳入 storm_lock 同步域(检查+submit
  原子)。代价是给派发热路径加锁,非必要不做。
- **不选**「放宽测试断言接受有界过冲」:现文档承诺「立即停止」,测试红 + 文档承诺矛盾的
  状态不可留;修复成本远低于改语义的文档/测试/披露连锁。
- **验收硬指标**:`tests/test_fanout_runner.py::TestRateLimitStorm::test_all_rate_limit_storm_truncates_fast`
  转绿,**连跑 ≥5 次全绿**。

## D2 — H5 修法:wmic 先试 + PowerShell CIM 回退 + 双不可用 fail-loud 保全证据

- `_pid_cmdline` Windows 分支:先试既有 wmic;`FileNotFoundError`/不可执行 → 回退
  `powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter 'ProcessId=<pid>' …"`,
  带单次超时(评审对照实验实测约 731ms/次,恢复路径可接受)与确定性输出解析(取 CommandLine
  行,空串 = 未取到)。
- **关键语义变化**:「PID 活着但 cmdline 探测不可用(两种途径都失败)」不再是静默空串——
  上抛到判定链,fail-loud:stderr 披露探测不可用,退出码非 0,**不删任何 liveness 文件**。
  「孤儿被静默放过 + 证据被销毁 + 退出码 0」这个三重静默失效形态被结构性关闭。
- 回退仅包 Windows 分支;POSIX 分支(`ps -p`)不受影响。PowerShell 5.1 为 Win11 核心组件,
  零 pip 依赖(R2 合规)。
- 附带更正:评审原文称此形态报 `none:true`——有 pid 文件被删时 `none` 实为 false;spec
  delta 已把该语义写明(`removed` 非空 → `none:false`),实现按此对齐。

## D3 — M1 修法:计数取双源最大值,双消费点同改

- `failed_now = int(snap.get("failed", failed0)) + len(failed_written)` 改
  `max(int(snap.get("failed", failed0)), failed0 + len(failed_written))`:磁盘枚举(re-list
  已含本 run 写入的 marker)与本 run 写入账是同一批事实的两个视角,取最大而非相加。
- `_sidecar_payload` 同形同改(:2191)。`--retry-failed` 决策与报告缺口披露消费的是同一
  字段,无需额外改动。
- 回归:构造「re-list 含本 run 失败 marker」的场景断言计数 == 真实失败数(修复前双计)。

## D4 — M2 修法:活跃 sink 接线,恢复 idle 承诺语义

- dispatch 侧创建的 out/err sink 无 reader 更新(死数据源);`_run_unit` 自建内部 sink。
- **主选**:把活跃 sink 引用传入 `_run_unit`(签名扩展或共享注册表,实现取小),心跳
  `idle` 改读活跃 sink 的最新输出时戳 → 恢复 docstring 承诺的「距子进程上次输出的秒数」。
- **否决删除 idle 字段**:消费方存在(:2630-2638),字段在摘要中语义承重;删字段是行为
  收缩且 docstring 语义仍在被引用。
- 回归:健康单元持续输出 → 其心跳 `idle` 保持小于 stall_window(修复前恒等于距派发时长)。

## D5 — M3 修法:再锚定前移,kill-stale 扫 `plan_path.parent`

- 派发侧的 plan_path 再锚定逻辑(:1967-1980,位于 kill-stale 分支之后)挪到 kill-stale
  分支**之前**执行;kill-stale 的 `init_dirs` 改为 `[plan_path.parent]`(liveness 实际所在
  run 目录),替换「plan 参数父目录」的朴素推断。
- 对 scout/t1/t3(参数是文件)行为不变(parent 即原推断);sdr(参数是目录)与 t2/
  scout-merge(参数是 init_dir)从扫错目录修正为扫 run 目录。
- 回归:sdr 规范调用形 + liveness 在 run 目录 → 检出(修复前 `none:true`,双侧对照已证实)。

## D6 — M5 修法:恢复模式参数可选,脚本单点收口

- `--checkpoints/--inputs-dir` 去掉无条件 `required=True`,改默认 `None`;kill-stale 分支
  容忍缺失(二者在该分支仅作扫描提示)。派发模式下的既有校验语义不变(若缺参会在此后既有
  逻辑中自然报错——验证非 kill-stale 路径缺参仍得到可操作报错,不静默)。
- **否决同步修全部配方文本**:脚本侧容忍是单一收口点,仓内全部 sanctioned 配方(resume
  工具 note / init stage fragments / 三面 init 壳)即刻原样可用,零文档面联动。

## D7 — L12 修法:liveness 读回非致命化

- 写失败后立刻读回的调用包 try/except(`OSError` 族);读回失败就地重建 body(契约声明的
  仅警告不打断语义延伸到读回)。回归:只读目录场景整 run 不崩。

## 测试与验收口径

- 定向回归:`tests/test_fanout_runner.py` + `tests/test_fanout_stale.py`。harness 约定:
  in-process 调用 MUST 传 `--cooldown-s 0`(仓库既有铁律,新增用例同此约)。
- M4 验收:`TestRateLimitStorm` 转绿 + 连跑 ≥5 次全绿;其余每条修复先红后绿。
- 慢测注意:`test_fanout_runner` 全文件约 50s(真子进程与计时器),定向跑单文件可接受,
  不必拆跑单用例。
- 共用基座防回归:非 sdr tier 形态(scout/t1/t3)的既有用例零改动全绿 = 无行为漂移的
  最低证据;M3/M5 的行为变化仅 kill-stale 恢复路径。
