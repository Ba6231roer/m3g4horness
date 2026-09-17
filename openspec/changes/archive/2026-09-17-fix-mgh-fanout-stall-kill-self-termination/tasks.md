# tasks — fix-mgh-fanout-stall-kill-self-termination

> 契约与措辞以 `specs/fanout-dispatch/spec.md` 的 MODIFIED requirement 为准;
> 技术选型与替代案见 `design.md` D1–D6(D6 为实施期追加的读取粒度修复)。

## 1. POSIX 单元子进程会话隔离(D1)

- [x] 1.1 `core/scripts/fanout_runner.py` 的 `_run_unit` 单元 `Popen` 增传
  `start_new_session=(os.name != "nt")`(POSIX `setsid` 使单元自成进程组;Windows 显式 `False`
  保持行为逐字不变)
- [x] 1.2 `_kill_tree` 的 docstring 更新:明确 POSIX 分支依赖单元自成会话,`killpg` 作用域
  = 该单元自己的树;删除「also hits the (already dying) runner side」的旧表述
- [x] 1.3 核对 `_kill_tree` 的 POSIX 失败回退(`os.kill(pid, SIGTERM)`)在新会话下语义仍正确
  (子进程已是会话首进程,`getpgid` 必成功;回退分支保留不删)

## 2. 退出路径清理在飞子进程(D2)

- [x] 2.1 `main` 的 `finally`:在清空 `children_now` 与删除 liveness 文件**之前**,对仍登记的
  各 PID 逐个调 `_kill_tree`(复用既有 `children_lock` / `children_now` 登记,零新状态)
- [x] 2.2 单个杀失败仅 stderr 警告,不阻断退出;`children_now` 为空时该段为 no-op
  (正常收尾路径 `pool.shutdown(wait=True)` 已收敛在飞)
- [x] 2.3 保持硬杀(SIGKILL)语义不变:`finally` 不执行 → liveness 文件留在盘上 →
  `--kill-stale` 仍能检出

## 3. 失活判据方向修正(D3)

- [x] 3.1 `_run_unit` 监控循环的静默判据:`min(out_sink["ts"], err_sink["ts"])` →
  `max(...)`(两路皆无字节才算静默)
- [x] 3.2 派发循环在飞心跳披露行的 `idle` 取值同源修正(`min` → `max`),使披露与判据一致
- [x] 3.3 两处附近补一行注释点明「空流的路 MUST NOT 使健康单元被判失活」,防回归
- [x] 3.4(实施期追加,经维护者拍板)`_tail_stream` 的 `stream.read(4096)` 改为
  `stream.buffer.read1(4096)` + `codecs.getincrementaldecoder("utf-8")(errors="replace")`:
  `TextIOWrapper.read(n)` 阻塞至满 n 字符或 EOF,`sink["ts"]` 实际按 4096 字符块推进,
  与 spec 的「字节级最后输出时刻」及本函数 docstring 均不符;低产出健康单元在此粒度下
  仍会被判失活。用例 4.1 同时锁死本项(只做 `max` 修正时 4.1 仍失败)

## 4. 回归测试(D5)

- [x] 4.1 `tests/test_fanout_runner.py` 的 `TestRunUnitTreeKill` 增用例:子进程持续写 stdout、
  **stderr 从无字节**,超过 `--stall-timeout-s` 后 MUST NOT 被判失活(`max` 语义锁)
- [x] 4.2 增用例:两路皆静默仍判失活并树杀(判据放宽 MUST NOT 变成永不判定)
- [x] 4.3 增用例(子进程内验证):一段子进程程序 import `fanout_runner`、spawn dummy 子进程、
  调 `_kill_tree`、再打印 `alive`;断言退出码 0 且 stdout 含 `alive`。Windows 上退化为恒真,
  不出现假红
- [x] 4.4 增用例:`main` 收尾路径在仍有登记子女时对其树杀(用 fake `_run_unit` 注入一个
  登记后不收敛的 PID),断言 liveness 文件被删且无该 PID 存活
- [x] 4.5 断言既有 `TestRunUnitTreeKill` 各用例在修复后仍绿(尤其「先 print 再睡」的失活用例
  在 `max` 下语义不变)
- [x] 4.6 增用例(D5 的「Windows 路径逐字不变」面):POSIX 上断言单元子进程是**会话首进程**
  (`os.getsid(0) == os.getpid() == os.getpgrp()`)且不属调用者会话——D1 修复的最小充分断言;
  Windows 上 `skipIf` 跳过(不出现假红;该平台行为由 `start_new_session=False` 默认值等价保证)

## 5. 调用面与文档同步

- [x] 5.1 `--kill-stale` 与失活段的 `--help` 文案:补「单元子进程自成会话 → 交互式中断不再
  连带终止在飞单元;退出路径已自动树杀,硬杀残留由 `--kill-stale` 清理」边界披露
- [x] 5.2 维护者私有文档区里的 `/mgh-init`、`/mgh-sdr` 命令人话说明:失活段与 `--kill-stale`
  段就近补同一披露(按现有文档结构放置,不改行为)
- [x] 5.3 fan-out 运行手册:补一条经验条目(POSIX 树杀作用域 / 静默判据取较新者 / 读取粒度);
  术语词典如需补「进程会话隔离」条目则补,否则不动
- [x] 5.4 `CHANGELOG.md` 记录两条缺陷与 Ctrl-C 传播面变化;`VERSION` bump

## 6. 全量校验

- [x] 6.1 `py tests/test_fanout_runner.py`、`py tests/test_fanout_stale.py` 全绿
- [x] 6.2 `py tools/check_contracts.py`(无新 flag,断言既有调用面未被误伤)、
  `py tools/check_distributed_purity.py`
- [x] 6.3 `py tests/test_deterministic.py` + 零依赖 AST 扫描(承 R2/R5.8,确认未引入 import)
- [x] 6.4 install 冒烟:双宿主镜像后自检无 warn
- [ ] 6.5 **真机验收(本次缺陷的原始现场)**:Linux 终端 nohup 直跑 scout 派发器,25 分钟
  (`--wave 5 --time-budget-ms 1500000 --call-timeout-s 900 --stall-timeout-s 600`),
  MUST 跑满并打印 stdout 汇总、进度侧车落 `exited-partial`/`exited-clean`、MUST NOT 在约 10 分钟
  猝死;再对该轮 run.log 抽查确认无健康单元被误判失活
- [ ] 6.6 真机验收通过后,回到维护者私有文档区里的 scout 吞吐实验记录 §5 继续跑
  实验一(wave 5/10/16)并填 §6 观察项与 §9 变更记录
