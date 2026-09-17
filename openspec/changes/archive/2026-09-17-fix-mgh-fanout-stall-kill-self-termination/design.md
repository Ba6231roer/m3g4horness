# design — fix-mgh-fanout-stall-kill-self-termination

## Context

动机与现象见 `proposal.md`「Why」。这里只记技术现状与约束。

现状(逐条源码核实,行号以本 change 实施时的 `core/scripts/fanout_runner.py` 为准):

| 环节 | 事实 | 锚点 |
|---|---|---|
| 单元 spawn 不隔离 | `subprocess.Popen(...)` 未传 `start_new_session` → 子进程与派发器同进程组/会话 | `_run_unit` 的 `Popen` |
| POSIX 树杀杀整组 | `os.killpg(os.getpgid(pid), signal.SIGTERM)` | `_kill_tree` |
| 杀在留痕之前 | 失活判定命中后先 `_kill_tree(proc.pid)`,再 `break`,随后才 `proc.wait` + 写 run.log | `_run_unit` 监控循环 |
| 静默判据取旧值 | 两个 sink 均以 `ts = t_start` 初始化,`_tail_stream` 仅在读到字节时更新 `ts`;判据取 `min(out_sink["ts"], err_sink["ts"])` | `_run_unit` 与 `_tail_stream` |
| 心跳披露同源 | 在飞披露行的 `idle` 同样取 `min` | 派发循环心跳块 |
| 退出路径不杀孩子 | `finally` 只清 `children_now`、清空并删除 liveness 文件 | `main` 的 `finally` |

**约束**:

- 四级超时不变式 `--stall-timeout-s` < `--call-timeout-s` < `--time-budget-ms ÷ 1000 × 0.8`
  < 宿主 per-call `timeout` 是 spawn 时 fail-loud 校验的,本 change 不动。
- `--stall-timeout-s < 60` 的拒识在 **argparse 层**;`_run_unit` 是纯函数边界,测试可直接传
  小阈值(既有 `TestRunUnitTreeKill` 就传 2 秒),故回归测试无需等待分钟级。
- Windows 分支走 `taskkill /pid /T /F`(树范围),不走 `killpg`,缺陷 1 在 Windows 上不存在;
  Windows 行为 MUST 逐字不变。

## Goals / Non-Goals

**Goals:**

- POSIX 下失活/超时树杀的作用域收敛在被杀单元自身,派发器 MUST 存活并继续补位。
- 失活判据与 `--help` 的「no stdout/stderr bytes for this long」语义一致——**两路都无字节**才算静默。
- 修复 MUST NOT 在交互式退出路径上引入「子进程变孤儿且不可追踪」的新缺口。
- Windows 行为逐字不变;无新 flag、无 stdout 字段增删、零新依赖。

**Non-Goals:**

- 不改失活阈值默认值(900)与四级不变式;不引入自适应限速/token-bucket;不改 `--kill-stale`
  的检出/清理算法;不改 ack 状态机与 marker 语义;不改 tier 表与任务模板。

## Decisions

**D1 用 `start_new_session=(os.name != "nt")` 让单元子进程自成会话,而不是给 `_kill_tree` 加守卫。**

`start_new_session` 触发 `setsid()`,子进程成为新会话与会话首进程 → `os.getpgid(child) == child_pid`,
`killpg` 因此只覆盖该单元自己的树。

- 替代案 A(在 `_kill_tree` 里比较 `pgid == os.getpgrp()` 则退化为只杀直接子进程):**否**——
  丢失孙进程(host-CLI 自身派生的进程),直接违反既有 requirement「NEVER 留孤儿继续烧 token」。
- 替代案 B(遍历 `/proc` 收集后代逐个杀):**否**——平台特化、代码量更大、易被进程状态竞态咬。

Windows 侧显式传 `False`(该参数为 POSIX-only,Windows 上本就不生效),使「Windows 行为逐字不变」
在代码上可见且可断言。

**D2 `finally` 在注销 liveness 之前杀掉仍登记的子女,补偿 Ctrl-C 传播面的变化。**

`start_new_session` 之后,Ctrl-C 不再随前台进程组抵达子进程。而既有 `finally` 会**清空 `children_now`
并删除 liveness 文件**——若此时子进程还活着,它们就变成**不可追踪**的孤儿(下次 `--kill-stale`
扫不到)。所以只改 D1 会引入一个真实缺口。

修法:复用既有 `children_now` 登记(有锁、spawn 时 `on_spawn` 追加、终态时移除),在 `finally` 里
对仍登记的 PID 逐个调 `_kill_tree`(**D1 之后此调用已不会波及自身**),再清登记与删文件。

- 正常收尾时 `children_now` 为空(`pool.shutdown(wait=True)` 已收敛在飞),该路径为 no-op。
- 硬杀(SIGKILL)时 `finally` 不执行,行为与今天一致——liveness 文件留在盘上,`--kill-stale` 可清。
- 替代案(退出时保留 liveness 文件让用户自行 `--kill-stale`):**否**——把清理责任推给下一次
  派发前的人工步骤,而配额正在被孤儿消耗;显式杀更符合「Ctrl-C 就是停」的直觉。

**D3 失活判据 `min` → `max`,心跳 `idle` 同源修正。**

`sink["ts"]` 初值为 `t_start`,`_tail_stream` 仅在有字节时更新。因此 `min` 的语义是「**至少一路**
静默达到阈值」,`max` 才是「**两路都**静默达到阈值」。`--help` 对 `--stall-timeout-s` 的原文是
「no stdout/stderr bytes for this long」,与 `max` 一致;`min` 是缺陷。

- 替代案(`out_ts or err_ts` / 只在有字节后参与比较):**否**——两路皆静默时语义含混,
  且 `min`→`max` 已能同时覆盖「一路从未有字节」与「两路都静默」。
- 既有 `TestRunUnitTreeKill` 的失活用例(子进程先 print 一次再睡)在 `max` 下**仍然通过**
  (两路皆静默),故不构成回归;新增「一路持续输出、另一路从无字节」的用例专门锁死本修复。

**D4 不动 `--stall-timeout-s` 默认值与四级不变式。**

缺陷是判据方向与杀的作用域,不是阈值大小。调阈值只会把猝死从 10 分钟推迟到别处(见 proposal
「Why」),属于治标。

**D5 回归测试落在 `_run_unit` 函数边界 + 一个显式子进程存活断言。**

- 单路静默不误判 / 双路静默仍判失活 / 心跳值取较新者 → 直接调 `_run_unit`(阈值可给 2 秒)。
- 「树杀不终止调用者」→ 起一个**子进程**跑一段小程序:import `fanout_runner`、spawn 一个 dummy
  子进程、调 `_kill_tree`、再打印 `alive`;断言退出码 0 且 stdout 含 `alive`。用子进程而非当前
  测试进程,避免断言失败的表现形式是「测试进程自己被杀」这种无法报错的形状。
- 「Windows 路径逐字不变」→ 断言非 nt 分支不受影响(spawn 的 argv 与引入前一致)。

**D6(实施期追加,经维护者拍板)`_tail_stream` 必须改用 `read1()`,否则「字节级」是空话。**

D1–D5 评审时未识别:spawn 用 `text=True`,故 `proc.stdout` 是 `TextIOWrapper`,而
`TextIOWrapper.read(n)` **阻塞到满 n 字符或 EOF** 才返回 —— 于是 `sink["ts"]` 实际按
4096 字符块推进,不是按字节。后果:两路合计不足 4096 字节的健康单元,两个 sink 都停在
`t_start`,**只做 D3 的 `max` 修正仍会在 spawn + `--stall-timeout-s` 被判失活** ——
与本次要治的现象同形,只是走另一条通路。实测(本机 Windows):

| reader 写法 | 子进程每 0.5s 写 6 字节、共 50 字节 |
|---|---|
| `stream.read(4096)`(改前) | 只有 1 次更新,在 t=5.19s(EOF) |
| `stream.buffer.read1(4096)`(改后) | 10 次更新,逐 tick(t=0.18/0.68/1.18/…) |

`read1()` 有一次可读即返回,正是失活判据需要的粒度;配
`codecs.getincrementaldecoder("utf-8")(errors="replace")` 使跨读取边界拆开的多字节序列
不被打散(纯标准库,零新依赖)。这与函数既有 docstring「ts of the last byte on this
stream」及 requirement 的「字节级最后输出时刻」一致 —— 属**对齐既有契约**,不是新增能力。

- 影响面:`ts` 更新更频繁 → 失活判定更贴合真实最后输出时刻(只会更准,不会更钝);
  `--call-timeout-s` 绝对兜底与四级不变式不变。
- 暴露路径:任务 4.1 按字面写就失败,才定位到此。该函数此前不在本 change 的 Impact
  清单内,经维护者拍板就地修复(而非另开 change)。

## Risks / Trade-offs

- [Ctrl-C 不再连带终止在飞子进程] → D2 的 `finally` 显式树杀补偿;硬杀路径由既有 liveness +
  `--kill-stale` 覆盖,语义不变。
- [`max` 会放过「一路持续输出、另一路已死」的子进程] → **接受**。该形状意味着子进程仍在产出,
  不属失活;总时长仍由 `--call-timeout-s` 绝对兜底,最坏多占用一个槽位到该上限。
- [进程级测试在不同平台表现不一(Windows 无 `killpg`)] → 测试对平台分支断言各自路径;Windows
  上「树杀不终止调用者」的用例退化为恒真(断言仍通过,不出现假红)。
- [D2 在退出路径新增一次杀操作] → 只作用于 `children_now` 中**仍登记**的 PID,正常收尾为空集;
  单个杀失败仅 stderr 警告,不阻断退出(与既有 `--kill-stale` 的失败处理同形)。
- [既有测试在 Linux 上本就跑不完] → 这正是缺陷 1 的证据:现有 `TestRunUnitTreeKill` 会调
  `killpg`,若子在调用者进程组则测试进程自身被杀。修复后该套件在 Linux 上应能完整跑绿,
  这本身就是验收的一部分。

## Migration Plan

纯代码修复,无数据/配置迁移。安装方重新 `./install.sh` 覆盖 `mgh-core/scripts/` 即生效;
运行中的 run 不可热升级,需在下一轮派发前替换。回滚 = git revert 单点,无残留状态
(marker / run.log / liveness 契约零改动)。

`VERSION` bump(R5.8:脚本改动必须 bump);`CHANGELOG.md` 记录两条缺陷与 Ctrl-C 边界变化。

## Open Questions

- 交互式 Ctrl-C 的清理是否还要额外挂 `signal` handler(而非只靠 `finally`)?——`finally` 已覆盖
  KeyboardInterrupt,`signal` handler 仅对不触发异常的信号有意义;若无实际场景,先不加。
  可在真机交互验证后再定。
- 维护者私有文档区里 `/mgh-init` / `/mgh-sdr` 命令人话说明的边界披露,放在失活段还是
  `--kill-stale` 段——实施时按现文档结构就近放置,不影响行为。
