# improve-mgh-sdr-zero-arg-defaults-and-py-probe

## Why

> **人话序** 现象:`/mgh-sdr` 有两个日常摩擦。其一,不带任何参数直接敲 `/mgh-sdr` 时,
> 命令壳按家族纪律打印参数表后停止——但绝大多数真实使用恰恰就是「当前分支 vs master
> 全维度复核」,底层脚本本来就有这套默认值(base 默认 master、branch 空则自动取当前分支、
> dimensions 不传即全部 6 维),用户却每次都被迫先补一个参数「骗」过停止门槛。其二,
> 命令壳里所有调用示例硬编码 Windows 的 `py` 启动器;在没有它的机器(Linux/macOS 或
> 未装 Python Launcher 的 Windows)上,宿主 agent 会 `py` 失败→换 `python3`→再试
> `python` 逐个碰运气,每错一次烧一轮上下文,实测反复发生。改什么:① `/mgh-sdr` 双壳
> (claude + opencode)无参时按默认参数直接跑完整流水线,`--help` 仍打印参数表后停止,
> 并同步修订研发手册 R5.6 允许「声明了安全默认集的命令」零参执行;② 双壳 step 0 增加
> 一条解释器探测命令(用 `;` 分隔三个候选、一次跑完全部、各自打印版本,Git Bash /
> cmd / PowerShell 通用),选中第一个可用的 ≥3.10 解释器后,本次 run 所有调用逐字用它,
> 壳内 `py` 定义为「规范占位 token = step 0 选中的解释器」。怎么验证:契约 lint 与
> 定向回归测通过;在无 `py` 的环境模拟首跑,确认探测一次成功、流水线零逐个试错。

- **问题 1(零参即停)**:家族 STOP 纪律(R5.6)对「无安全默认」的命令是对的,但
  `/mgh-sdr` 的默认集(base=master / branch=当前 / dimensions=全 6 维)恰是最高频用法,
  且已由脚本 argparse 兜底(`sdr_context.py:815`、`sdr_context.py:559`),壳层的 STOP
  只是把已有默认挡在门外。
- **问题 2(解释器试错)**:`py` 是 Windows Python Launcher 专属;壳内约 30 处调用示例
  硬编码它,非 Windows 环境每个命令首跑都可能触发「解释器不存在 → 换名重试」的
  token 浪费循环。脚本侧无此问题(launcher 用 `sys.executable`,fanout_runner 只 spawn
  宿主 CLI 不 spawn python),纯壳层文本纪律缺口。
- **为何现在**:两项都是双壳文本 + 一处手册措辞的增量,不触碰任何脚本 I/O 契约与
  产物 schema,适合作为轻量可用性 change 一并落地。

## What Changes

- **双壳零参默认执行**(claude + opencode 两份 `mgh-sdr.md` 同步):
  - 「无 actionable 参数 / `--help` → 打印参数表后 STOP」改为:`--help` → 打印参数表后
    STOP(不变);**无参** → 按 `--base master`、`--branch 当前分支`、`--dimensions`
    全部 6 维直接进入编排流程(默认值由 `sdr_context.py` / `diff_group.py` 的 argparse
    兜底,壳不自行 `git rev-parse` 猜分支);
  - 参数字段表明确标注「不传即默认」,step 1–4 示例保持 `py` 原样,`base/branch` 在
    默认路径下整体省略(与脚本默认一致,报告/run 目录命名消费 step 1 stdout 的
    `branch` 已解析值)。
- **双壳 step 0 解释器探测纪律**:
  - 新增探测配方:一条 Bash 命令依次执行 `py --version`、`python --version`、
    `python3 --version`(`;` 分隔,单命令看全三候选可用性与版本;bash/cmd/PowerShell
    均支持);取第一个成功且版本 ≥3.10 者为本次 run 的解释器;
  - 全局替换纪律:壳内示例中的 `py` 是**规范 token**,实际执行时逐字替换为 step 0
    选中的解释器;压缩/新会话后不确定时**重跑探测命令**(单条、廉价),**NEVER** 对
    流水线命令逐个换解释器名试错;
  - 探测结果不进磁盘(run_config / 哨兵 schema 不动)。
- **AGENTS.md R5.6 措辞修订**:「`--help`/无参 → 打印 flag 表并 STOP」放宽为「`--help`
  → STOP;无参默认 STOP,**除非**命令在参数表中声明安全默认集并明示零参执行」,理由
  括号保留。
- **不变项**(明确划界):`--dimensions` 收窄仍**不下发**评审单元(现状披露不变,零参
  跑全 6 维与此路径一致);launcher `mgh_sdr_launch.py` 的默认值与接口不动(其 argparse
  已有同默认);脚本 argparse 默认值不动;`block-adhoc-scripts` 守卫逻辑不动;其余
  mgh-* 壳的无参 STOP 行为不动。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `security-design-review`:新增两条需求——「零参默认执行」(双壳无参 = base master /
  branch 当前 / 全维度直接跑,`--help` 仍 STOP)与「宿主解释器一次性探测」(step 0
  探测配方 + `py` 规范 token 替换纪律,禁止逐命令试错)。

## Impact

- **分发的命令壳**:`releases/claude-code/commands/mgh-sdr.md`、
  `releases/opencode/command/mgh-sdr.md`(参数字段表、step 0、编排流示例注释、
  「Deterministic invocation」段前探测说明)。
- **研发手册**:`AGENTS.md` R5.6 一句措辞(含允许例外的声明条件)。
- **验证工具**:`tools/check_contracts.py`(flag 镜像不破坏)、壳 token 预算 lint
  (R5.6 硬上限 ≤5,000 tok,双壳各净增约百余 token,超限则按保真度优先裁剪)、
  定向回归 `tests/test_distributed_md_purity` `tests/test_plain_language` +
  `py tools/check_contracts.py`。
- **不触碰**:`core/scripts/**`、`core/contracts/**`、hooks、fanout tier 定义、
  报告渲染。
