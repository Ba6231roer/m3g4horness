> **人话序** 现象:2026-10-13 深度评审在派发器(六域共用基座)确认 7 条缺陷,最重的三条:① `--kill-stale` 恢复路径在 Windows 11 24H2+ 上**永远杀零个孤儿进程却照删证据文件、退出码 0 假成功**——它依赖的 `wmic` 工具已被系统移除,孤儿宿主 CLI 继续烧 token 且无从发现;② 限流截断与派发补位之间存在竞态,回归测试在干净主干上**确定性红**(CI 必挂);③ 退出摘要把失败单元数报成两倍(全败 10 单元的 run 报 20),而失败重派决策与报告缺口披露都消费这个数字。另有心跳读死数据源(健康单元显示"疑似卡死")、kill-stale 对 sdr 场景扫错目录、仓内恢复配方因参数必填而根本跑不起来、心跳文件读回崩溃。根因:平台工具失效未设回退、两线程无同步、计数双源、未接线的半成品特性。改什么:每条小修 + 回归;限流竞态修复后回归测试转绿。怎么验证:伪造孤儿进程可被杀且证据不误删、测试 5 连绿、摘要计数正确、恢复配方原样可跑,定向回归全绿。

## Why

- 评审(2026-10-13,基线 main HEAD `6e6ac63`)在 `core/scripts/fanout_runner.py` 确认 7 条缺陷。恢复路径(`--kill-stale`)恰是最坏状态下的调用场景(宿主已死、token 在烧),其静默失效方向全部是「看起来成功」:
  - **H5**:进程命令行探测依赖 `wmic`(Win11 24H2+ 已移除,本机实测不存在),`FileNotFoundError` 被 `except OSError` 静默吞、返回空串 → cmdline 恒空 → 永远零 targets、孤儿 100% 存活、liveness 证据文件被无条件删除、退出码 0 假成功。对照实验证实 PowerShell `Get-CimInstance` 回退可行(约 731ms/次,恢复路径可接受;PowerShell 5.1 是 Win11 核心组件,零 pip 依赖不破)。
  - **M4**:限流截断旗标(worker 置位)与主线程补位派发之间无同步——第一个 crash 收割后、记账落地前,主线程可向已限流网关补派新单元。**本机实跑回归 `TestRateLimitStorm` 连续 5/5 失败,干净 HEAD 的测试套件确定性红、CI 必挂**(生产影响有界:截断落地前最多多派一个单元)。
  - **M1**:退出摘要 `failed` 计数把同一批失败 marker 计两次(磁盘枚举 + 本 run 写入双源相加),全败 10 单元报 20;`--retry-failed` 决策与报告缺口披露消费该字段。
  - **M2**:心跳 `idle` 读的是从未接线的 dispatch 侧 sink(无 reader 更新,`_run_unit` 自建内部 sink)——idle 恒等于距派发时刻的流逝时间,持续输出的健康单元也显示「疑似卡死」,与 docstring 承诺语义相反。git 考古确认自引入起未接线(未完成特性)。
  - **M3**:kill-stale 扫描根按「plan 参数的父目录」推断;sdr 的参数是目录、t2/scout-merge 的参数是 init_dir → 扫到仓库父目录/仓根,而 liveness 实际住在 run 目录(派发侧的再锚定逻辑在 kill-stale 分支之后未被复用)——规范调用形报 `none:true`(双侧对照实验证实)。
  - **M5**:`--checkpoints/--inputs-dir` 无条件必填,而 kill-stale 恢复模式的功能性输入只是扫描提示——仓内全部恢复配方按原样调用都会 argparse 退出 2,恢复路径首跑必失败。
  - **L12**:liveness 写失败(契约声明仅警告不打断)后立刻读回,目录只读场景未捕获 `FileNotFoundError` → 整 run traceback 崩,违反同文件声明的非致命契约。

## What Changes

- **M4**:消除截断旗标与补位派发的竞态窗口——取单元后、提交 spawn 前复查截断状态(或把派发决策纳入截断同步域,实现取小);**验收硬指标:`TestRateLimitStorm` 转绿且连跑 ≥5 次全绿**。
- **H5**:cmdline 探测改「wmic 先试 + PowerShell CIM 回退」;两种探测均不可用且 PID 存活时 fail-loud(stderr 披露)、**不删任何 liveness 文件、不报成功**——证据在无法判定孤儿归属时保留。
- **M1**:退出摘要 `failed` 计数改 `max(磁盘快照, 起始 + 本 run 写入)` 形态,消除双计;`_sidecar_payload` 同改。
- **M2**:把活跃输出 sink 接线到心跳(传入 `_run_unit` 或暴露活跃引用,实现取小),`idle` 恢复「距子进程上次输出的秒数」承诺语义。
- **M3**:派发侧的 liveness 位置再锚定逻辑挪到 kill-stale 分支**之前**,kill-stale 扫描 `plan_path.parent`(与写入根同一锚定)。
- **M5**:`--checkpoints/--inputs-dir` 改可选(默认 None),kill-stale 分支容忍缺失——仓内恢复配方原样可跑,配方文本零改动。
- **L12**:liveness 读回包 try/except,读回失败就地重建 body(维持非致命契约)。
- 版本收口:`CHANGELOG.md` + `VERSION` bump。

## Capabilities

### New Capabilities

<!-- 无。 -->

### Modified Capabilities

- `fanout-dispatch`:MODIFIED「`--kill-stale` 检出并清理孤儿 runner 进程树(含 runner 已死的存活子进程)」——新增探测跨版本可用性(CIM 回退)、探测不可用时的 fail-loud 与证据保全、扫描根锚定 liveness 实际位置、恢复模式参数可选;MODIFIED「crash 原因分类与限流 crash 风暴截断」——精确化「立即停止派发」:补位循环取单元与提交 spawn 之间的窗口 SHALL NOT 越过已生效的截断旗标。M1/M2/L12 为实现违约修复(计数正确性、心跳承诺语义、非致命契约),由回归测试兑现,不改 requirement 文本。

## Impact

- **代码**:`core/scripts/fanout_runner.py`(单文件;六域共用基座,修复对全部 tier 生效或同构)。
- **测试**:`tests/test_fanout_runner.py`(M4 修复后 `TestRateLimitStorm` 转绿;新增 CIM 回退/探测不可用、扫描根锚定、配方缺省可跑、liveness 读回失败用例)、`tests/test_fanout_stale.py`(kill-stale 面回归)。注意 harness 约定:in-process 调用 MUST 传 `--cooldown-s 0`(仓库既有约定)。
- **契约**:CLI 面变化仅 M5(`--checkpoints/--inputs-dir` 由必填改可选——向后兼容,已有调用形不受影响);stdout 摘要 schema 零变化(M1 只改计数值);心跳行字段零变化(M2 只改 idle 取值来源)。
- **分发面**:零改动(fanout_runner 为已分发叶脚本;三面壳调用行不变;`core/contracts/fanout/runtime.md` 与实现逐条吻合、零 finding,无需回改)。
- **风险与回滚**:fanout_runner 是六域共用基座,修复 MUST 对非 sdr tier 无行为变化(除同构受益);定向回归覆盖 scout/sdr 两 tier 形态。
- **版本**:`CHANGELOG.md` + `VERSION` bump。
