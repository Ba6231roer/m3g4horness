## ADDED Requirements

### Requirement: 零参默认执行(/mgh-sdr 双壳)

`/mgh-sdr` 命令壳(claude 与 opencode 双份,行为对等)SHALL 声明安全默认集并支持零参直接
执行:**无任何参数**调用时,MUST 按 `--base master`、`--branch` 当前分支、`--dimensions`
全部 6 维直接进入编排流程,NEVER 因缺参而停止索取输入;传 `--help` 时 MUST 仍仅打印
参数表后 STOP(零 token、零解析)。默认值 MUST 由确定性脚本的 argparse 兜底解析
(`sdr_context.py` / `diff_group.py` 的 `--base` 默认 `master`、`--branch` 空值时取
`git rev-parse --abbrev-ref HEAD`),编排器 NEVER 自行执行 `git rev-parse` 猜分支;
run 目录与报告的分支命名 MUST 消费 step 1 stdout 已解析的 `branch`/`base` 字段。
参数表 SHALL 逐项标注「不传即默认」,使零参与显式传默认值两条路径产物等价。本行为是
对家族纪律「无参 STOP」的显式例外,例外条件(命令声明安全默认集 + 参数表明示)MUST
同步写入研发手册 R5.6 措辞,防止后续按旧纪律「修回去」。

#### Scenario: 零参直接跑完整流水线

- **WHEN** 用户在目标仓根目录调用 `/mgh-sdr`(不带任何参数)
- **THEN** 编排器不打印参数表、不停止索取输入,按 base=master / branch=当前分支 /
  全部 6 维执行 step 0–5,产出项目根中文报告;`--base`/`--branch` 在默认路径下整体
  省略,由脚本 argparse 解析默认

#### Scenario: --help 仍零 token 早停

- **WHEN** 用户调用 `/mgh-sdr --help`(或 `/mgh-sdr -h`)
- **THEN** 壳仅打印参数表后 STOP,不执行任何流水线步骤、不写任何产物、不武装哨兵

#### Scenario: 双壳对等

- **WHEN** 同一零参调用分别发生在 claude 与 opencode 宿主
- **THEN** 两份命令壳的零参默认执行与 `--help` STOP 行为逐字一致,仅宿主路径前缀与
  超时标定差异保留(与既有双壳差异面相同)

### Requirement: 宿主解释器一次性探测(/mgh-sdr 双壳 step 0)

`/mgh-sdr` 双壳 SHALL 在 step 0 放置一条**解释器探测配方**:单条 Bash 命令以 `;` 分隔
依次执行候选探测(`py --version`、`python --version`、`python3 --version`,各候选失败
不中断后续),一次跑完即可看到全部候选的可用性与版本,候选集 MUST 覆盖 Windows Python
Launcher(`py`)与 POSIX 惯例(`python3`/`python`)。编排器 SHALL 取第一个执行成功且版本
≥3.10 的候选为**本次 run 的解释器**,此后壳内所有 `*.py` 脚本调用 MUST 逐字使用该
解释器——壳内示例中的 `py` 为**规范占位 token**,语义 = step 0 选中的解释器,示例文本
MUST NOT 因探测机制改写为其他占位符。上下文压缩 / 崩溃恢复 / 新会话后若选中解释器
不确定,MUST 重跑探测命令(单条、廉价)重建该事实,NEVER 对流水线脚本逐个换解释器名
试错。探测结果 SHALL NOT 落盘(`run_config.json` / 哨兵 schema 不变);若所有候选均
不可用或版本均 <3.10,编排器 MUST 早停并向用户披露(零派发、移除已武装哨兵,与其他
step 1 前干净停止路径同构)。

#### Scenario: 无 py 的 Linux 环境一次探测定型

- **WHEN** 宿主机器无 `py` 启动器,仅有 `python3`(≥3.10)
- **THEN** step 0 探测命令单条跑完,输出显示 `py` 不可用、`python3` 可用及版本;
  编排器选定 `python3` 并用于后续全部脚本调用,流水线全程零「解释器不存在」试错

#### Scenario: 压缩后新会话重探测

- **WHEN** run 中途上下文被压缩、新会话按「中断恢复」章节接续,编排器无法从对话记忆
  确定选中解释器
- **THEN** 编排器重跑同一条探测命令选定解释器(不从磁盘猜、不逐个试错),再继续
  resume 流程

#### Scenario: 全部候选不可用早停

- **WHEN** 探测命令显示无候选解释器存在,或全部候选版本 <3.10
- **THEN** 编排器在任何流水线步骤前 STOP,向用户披露探测输出与依赖要求,移除 step 0
  已武装哨兵,零切片物化、零派发
