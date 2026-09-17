# plain-language-doctrine Specification

## Purpose

定义本仓「双层产物制度」——按受众把产物分成人类面与 agent 操作面,人类面强制大白话、agent 操作面字节不动,使维护者与目标项目用户能读懂每个迭代与每件工具。

## Requirements

### Requirement: Every artifact declares its audience

每份文档/工件 SHALL 显式声明其受众,受众 ∈ {人类 / agent / 双受众}。人类面产物走「人话规范」(见下条);agent 操作面产物(命令壳纪律段、stage 提示词、JSON schema、NEVER 链、`core/contracts/**`)走 R5.5 措辞纪律。**R5.5 措辞纪律 SHALL 只辖 agent 操作面,不蔓延到人类面**。`proposal.md` 是唯一显式**双受众**文件:其人话序对维护者讲 why,对 `opsx:apply` agent 亦提供「为何」背景(~200–300 tok,低成本 + 双赢)。

#### Scenario: Agent-facing discipline does not leak into human prose

- **WHEN** 维护者写一份人类面文档(man 说明 / 词典 / proposal 人话序)
- **THEN** 该文档不套用 RFC-2119 动词链、`NEVER` 禁令、fan-out 路径配方等 agent 指令语域,只做现象→原因→改法式的说明

#### Scenario: Proposal is a sanctioned dual-audience file

- **WHEN** 一份 `proposal.md` 既被维护者阅读、又被 `opsx:apply` 读入上下文
- **THEN** 其人话序(~200–300 字)作为既便宜又对两方有益的内容保留,不因「人读」而被排除出 apply 上下文

### Requirement: Human-facing artifacts follow the plain-language norm

人类面产物(man 说明 / 词典 / proposal 人话序 / 终端报告)SHALL 遵守:现象→原因→改法、术语首次出现给一句解释、允许同义复述(冗余是读者的锚点)。SHALL NOT 出现:无定义的生造压缩词、英文原词裸嵌中文当语义原子、删光主谓宾的「名词化等式句」。

#### Scenario: Jargon is defined on first use

- **WHEN** 一份 man 说明首次使用「哨兵」「运行域」等术语
- **THEN** 该术语 SHALL 在该处或词典中有一句释义,读者无需读源码即可理解

#### Scenario: Nominalized equation is rejected

- **WHEN** 一份人话文件出现形如「来源层 = producer 物化 repo 锚 + reader 统一拒识 recipe」的等式句
- **THEN** 该句 SHALL 改写为有主谓宾、有因果的人话(如:生成任务清单的脚本把仓库根绝对路径写进每个任务输入;干活的子 agent 拿到输入后先检查路径是否在仓库目录内,不在则报失败)

### Requirement: Terminology glossary precedes usage

仓库 SHALL 维护一份**面向维护者本人**的术语词典(住在维护者私有文档区,不随包分发、不在任何分发产物里出现路径),种子含 ~30–50 条(取自 AGENTS.md 与 R5 大白话配套文档的术语表)。人类面产物使用的术语 SHALL 在词典中有条目;缺则先补词典再使用。词典 SHALL 允许自由增补,不做准入审批。

#### Scenario: New term requires a glossary entry

- **WHEN** 作者在人类面产物中引入一个新术语(如「锚」)
- **THEN** 该词典 SHALL 新增该术语的中文释义,之后产物方可使用

#### Scenario: Glossary is a living seed

- **WHEN** 词典初次创建
- **THEN** 至少覆盖 AGENTS.md 与 R5 大白话配套文档中反复出现的核心术语,后续可随迭代自由增补

### Requirement: Each command has a maintainer-facing plain-language walkthrough

每个命令(mgh-sast / mgh-init / mgh-sra / mgh-srr / mgh-ut-init / mgh-sdr)SHALL 有一份**面向维护者本人**的人话版说明,与命令同名,覆盖:这命令做什么 / 会动目标项目哪些文件 / 产出什么 / 风险边界。该说明 SHALL NOT 随 `install.sh` 分发到目标项目,分发产物 SHALL NOT 指向它(承 distribution-purity)。

#### Scenario: The maintainer understands a command from its walkthrough

- **WHEN** 维护者打开某个命令的人话说明
- **THEN** 无需读命令壳或源码,即可知道该命令做什么、会写哪些目录、产出什么、有哪些诚实边界

#### Scenario: Walkthroughs stay out of the install

- **WHEN** `install.sh` 把工具族装进目标项目
- **THEN** 目标项目里不出现人话说明,命令壳里也不出现指向它的指针——维护者私有文档区的任何内容都不得被分发产物引用

#### Scenario: Walkthrough is plain but pure

- **WHEN** 维护者撰写或修订一份人话说明
- **THEN** 它不含 `R5.x`/`FDn`/`Dn`/变更夹名等悬空引用(人话措辞自然规避,distribution-purity lint 兜底)

### Requirement: Proposal opens with a plain-language preamble

`proposal.md` SHALL 以一段 ~200–300 字的人话序开场,四要素:现象 → 根因 → 改什么 → 怎么验证,先写人话、再展开规格(spec/design/tasks)。

#### Scenario: A maintainer restates a change from the preamble alone

- **WHEN** 维护者只读 proposal 人话序 + tasks.md
- **THEN** 能复述出这个 change 在解决什么问题、改了什么、如何验证(读不懂 = 未就绪,人工闸门)

### Requirement: CI proxy lint enforces the deterministic subset

仓库 SHALL 提供确定性叶脚本 `tools/check_plain_language.py`(标准库,承 R2/R5.3),对可机器判定的子集做代理 lint:proposal 人话序**存在性**检查 SHALL fail-loud(退出码 2);已知术语黑名单(`物化`/`拒识`/`接线`/`承`/`兑现`/`治类`…)与英文原子密度超阈值 SHALL 报 WARN(退出码 0),且仅扫人类面文件。真人类可读性机器测不了,由人工闸门兜底。

#### Scenario: Missing preamble fails the lint

- **WHEN** 某 `proposal.md` 缺人话序,执行 `check_plain_language.py`
- **THEN** 脚本以退出码 2 失败,报该 proposal 缺人话序

#### Scenario: Blacklisted jargon warns but does not block

- **WHEN** 某 man 说明出现黑名单术语「物化」
- **THEN** 脚本以退出码 0 完成,stdout/stderr 报 WARN 指向该文件该行,不阻断合入

#### Scenario: Lint is scoped to human-facing files

- **WHEN** 执行 `check_plain_language.py`
- **THEN** 黑名单 / 密度检查仅覆盖人类面文件(proposal 人话序 / 维护者私有文档区的人话说明与词典 / 终端报告),不扫 agent 操作面(stage 提示词 / 契约 md / JSON schema)
