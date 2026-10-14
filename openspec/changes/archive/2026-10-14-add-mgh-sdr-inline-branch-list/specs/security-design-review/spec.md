## ADDED Requirements

### Requirement: launcher 内联多分支清单 --branch-list

launcher `core/scripts/mgh_sdr_launch.py` SHALL 额外接受内联多分支参数
`--branch-list "<b1,b2,...>"`——值为**逗号分隔的分支名清单**,直接写在命令行上(引号
包裹),与文件喂法 `--multi-branch <file>` 覆盖同一「多分支串行 sweep」需求。解析规则:
按 `,` 切分,逐项去除首尾空白,**任一空项**(如 `a,,b`、结尾多逗号、整体为空或全空白)
→ 退出码 2 + 可操作 stderr(报出违规项序号),NEVER 静默跳过;重复分支名保序去重
(只跑一次,与 `--multi-branch` 文件模式行为一致);内联模式无注释语法(每个逗号项都是
分支名)。`--branch-list` 与 `--multi-branch` **互斥**:两者同时给出 → 退出码 2 + 可操作
stderr(二选一),NEVER 静默按优先级取其一(歧义输入 fail-loud;逗号在 git 分支名中
合法,NEVER 以「值含逗号」推断喂法)。`--branch-list` 与单分支参数 `--branch` 同给时,
内联清单优先(`--branch` 被忽略),与 `--multi-branch` 压过 `--branch` 的既有行为同形。
内联清单 SHALL 汇入与 `--multi-branch` **完全相同**的串行逐分支流程:每分支独立 run
目录 + 独立报告;单分支失败记录后后续分支照常执行;launcher 自身退出码语义不变
(0 全部分支成功 · 1 任一分支 FAILED · 2 误用)。`--help` SHALL 载明该 flag(命令壳
不展 launcher flag 表,`--help` 是该参数的唯一契约面)。

#### Scenario: 内联清单串行同语义

- **WHEN** 用户运行 `py mgh_sdr_launch.py --repo <项目> --branch-list "feat/a, feat/b"`
  (含一个带首尾空白的项),两分支在目标仓均可解析
- **THEN** launcher 串行执行两轮完整流程,产出两份独立报告 + 各自 run 目录;项首尾
  空白被去除后按分支名正常预检;退出码 0

#### Scenario: 双参数互斥拒识

- **WHEN** 同一次调用同时给出 `--multi-branch branches.txt` 与 `--branch-list "a,b"`
- **THEN** launcher 退出码 2,stderr 报出二选一的 recipe,零分支执行、零产物写入
  (fail-loud,不猜不静默取其一)

#### Scenario: 空项拒识

- **WHEN** `--branch-list "feat/a,,feat/b"`(中间空项)或 `--branch-list "feat/a,"`
  (结尾逗号)或 `--branch-list "  "`
- **THEN** launcher 退出码 2,stderr 可操作地报出违规项(序号/原因:空分支项),零
  分支执行;后续分支 NEVER 被静默吞掉
