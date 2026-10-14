# fix-mgh-sdr-host-error-capture

> **人话序**:`/mgh-sdr` 的 launcher(人/cron 一条命令入口)spawn opencode 时带了
> `--print-logs --log-level ERROR`,意图是「扇出期间的 provider 形失败在 launcher stderr
> 可定位」。2026-10-13 真仓复测(`openspec/changes/test-mgh-sdr-multibranch-rerun/findings.md`
> §4 问题 F1)证明该承诺在其**目标失败形态**上不成立:扇出 subagent 是 opencode 的**独立
> 子会话**(独立 run id),它们的日志(含 2 次实测 ERROR 级断连)只落用户级全局日志文件,
> **不经**父 `run` 进程的 `--print-logs` 面输出——launcher stderr 只有失败信封,没有根因;
> 对照实验还证明 ERROR 级在父进程自身无错时零输出。结果:故障定位必须脱离 run 目录去翻
> `~/.local/share/opencode/log/opencode.log`。本 change 把「失败可诊断」改成真实机制:
> launcher 保留 flags(父进程自身错误仍尽力浮出),宿主退出后**时间窗提取**全局日志中的
> `level=ERROR` 行落盘 `<run-dir>/host_error.log`,stderr 披露计数,分支失败原因携带证据
> 指针;全局日志缺失/不可解析一律 fail-soft(stderr note + recipe 指认全局路径),NEVER
> 影响退出码。验证 = 先红后绿单测(窗口过滤/证据落盘/失败指针/fail-soft/claude 跳过)+
> `test_mgh_sdr_launch` 定向面全绿 + 契约/purity/budget lint 不回归。

## Why

`/mgh-sdr` 多分支串行 launcher(0.1.59 起)以「provider 形失败在 launcher stderr 可定位,
NEVER 只有一句错误信封」作为 spec 要求落地(`security-design-review` 能力 launcher 要求第
⑧项)。真仓复测(2026-10-13,opencode 1.18.31)以同测试床、同失败探针复跑,发现该要求的
机制假设错误:

1. **子会话日志不路由到父进程**:`opencode run --print-logs` 只打印**本 run 进程**的日志;
   编排器经 Bash 派发的扇出 subagent 是独立会话,其 provider 错误(stream 断连、限流)只写
   用户级全局日志。实测 run1 sql-sensitive 分支扇出期间 2 次 `AI_APICallError: socket
   connection closed`(ERROR 级)在 launcher 捕获的 stderr 里零浮出。
2. **ERROR 级在父进程无错时零输出**:对照实验,同命令 `--log-level ERROR` 零日志行,
   换 `--log-level DEBUG` 打出 32 行——flag 机制活着,但覆盖面与目标失败形状不重合。

后果:扇出单元持续失败时,launcher 消费者看到的仍是「host CLI exited N」一句信封,根因
(网络断连 / 限流 / provider 配置)不可见,排障要脱离 run 目录人肉翻全局日志——与 R5.4
「长跑可观测」与本仓「进度真相源在磁盘、run 目录自包含」的立场相悖。上游日志路由行为
(opencode 子会话日志只进全局文件)不属本仓可修面,故修法是**下游捕获**,不是改 flag。

## What Changes

全部改动集中在 launcher `core/scripts/mgh_sdr_launch.py`(单文件)+ 其测试 + spec 第 ⑧ 项
改述;零新依赖(标准库),零三面壳改动(claude/dsh 壳不含该 flag 披露),零提示词改动。

1. **时间窗证据落盘(核心)**:`_spawn_host` 记录宿主 spawn 起止(UTC);宿主退出后,
   launcher 从 opencode 全局日志(`~/.local/share/opencode/log/opencode.log`)提取时间窗内
   `level=ERROR` 行,**逐字**落盘 `<run-dir>/host_error.log`(带 2 行来源/窗口头注);
   提取对成功与失败分支都执行(被 opencode 内部重试吸收的瞬时错误同样是报告可信度的
   证据,实测样本:2 次断连被吸收、分支仍全收敛)。
2. **stderr 披露 + 失败指针**:每次宿主退出后 stderr 披露一行证据计数与路径;分支 FAILED
   时失败原因(信封与最终 `FAILED BRANCHES` 汇总)携带证据文件指针,捕获为零时 recipe
   指认全局日志绝对路径。
3. **fail-soft 边界**:全局日志缺失/不可解析/时间戳非 ISO → stderr note(注明假定的路径,
   未来 opencode 换路由时自我暴露),证据文件不产出;**NEVER** 影响分支判定与退出码。
4. **文件三态语义(诚实边界)**:证据文件缺席 = 未提取(claude 宿主 / 全局日志缺失);
   仅头注 = 已提取、零捕获;有正文 = 窗口内 ERROR 行。三种形态可区分,「没跑提取」与
   「跑了但零错误」不混淆。
5. **spec 改述**:`security-design-review` launcher 要求第 ⑧ 项从「flags 使 provider 形失败
   在 launcher stderr 可定位」改述为真实机制(flags 仅父进程尽力 + 时间窗提取 + 失败指针 +
   fail-soft),并补场景(证据落盘、fail-soft、失败指针)。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `security-design-review`:launcher 单命令外壳要求的第 ⑧ 项「可诊断性与模型透传」改述——
  `--print-logs --log-level ERROR` 的覆盖面收窄为父进程尽力披露;新增「宿主退出后时间窗
  ERROR 证据落盘 `<run-dir>/host_error.log` + stderr 计数 + 分支失败原因携带证据指针 +
  fail-soft」为可验收行为(模型透传部分不变)。

## Impact

- **代码**:`core/scripts/mgh_sdr_launch.py`(约 +60/-15 行:`_spawn_host` 记窗、新增
  `_opencode_global_log_path` / `_extract_host_errors` 两个纯函数、`_run_one` 收尾段接线、
  失败原因拼装);随 install 分发的副本由 install 机制自然更新。
- **测试**:`tests/test_mgh_sdr_launch.py` 新增一个测试组(证据提取单测 + 假宿主/假全局日志
  集成测);既有 `test_opencode_carries_log_flags_claude_does_not` 保留(flags 不删,断言仍真)。
- **规格**:`openspec/specs/security-design-review/spec.md` launcher 要求第 ⑧ 项 + 新增 3 个
  scenario(经本 change delta 回写)。
- **不触碰**:三面命令壳、`fanout_runner.py`、提示词、claude/dsh 分发面、其余 sdr 脚本。
- **诚实边界(随实现写进代码注释与 spec)**:时间窗提取是**诊断近似**——同机并发 opencode
  会话落在窗内的 ERROR 行可能混入;全局日志路径按本机实测形态
  (`~/.local/share/opencode/log/opencode.log`)硬编码假设,opencode 未来改路由时以
  fail-soft note 自我暴露。单元级失败形态(快败冷却/限流截断/零进展熔断)仍无真机样本,
  本 change 的失败指针路径以单测覆盖,真机验收归下次复测。
