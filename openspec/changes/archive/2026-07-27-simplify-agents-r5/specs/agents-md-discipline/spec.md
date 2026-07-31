## ADDED Requirements

### Requirement: R5 enforcement-surface index

`AGENTS.md` 的 R5 段头部 SHALL 提供一张索引表,把每条子规则(R5.1–R5.10)映射到其**强制机制**与**入口**(脚本 / hook / CI),使维护者无需通读正文即可定位某条规则如何被机器执行。

#### Scenario: 维护者定位某规则的强制机制

- **WHEN** 维护者需要知道 R5.9(边界校验)如何被强制
- **THEN** R5 头部索引表列出机制(`--check` fail-loud / 退出码 2)与入口(各产出者 `--check`),无需扫读正文。

#### Scenario: 索引表覆盖全部强制规则

- **WHEN** R5 头部索引表存在
- **THEN** R5.1 / R5.2 / R5.3 / R5.4 / R5.7 / R5.8 / R5.9 / R5.10 每条至少有一行「规则 → 机制 → 入口」对应。

### Requirement: R5 plain-language companion

仓库 SHALL 维护一份**不分发**的大白话配套文档 `docs/r5-plain-language.md`,逐条用大白话解释 R5.1–R5.10:这条说什么、为什么有、违反会怎样、哪个工具/hook 兜底。该文档是 AGENTS.md(面向 AI、简练)的人类/新人桥梁,亦是教训的第二副本,防重组去重后单点灭失。

#### Scenario: 新人读懂某条规则

- **WHEN** 新贡献者读 AGENTS.md 某条 R5 规则后需要大白话背景
- **THEN** `docs/r5-plain-language.md` 提供该规则的「说什么/为什么/违反后果/兜底机制」四要素解释,无需读源码。

#### Scenario: 配套文档不进分发集

- **WHEN** `install.sh` 镜像产物到目标项目
- **THEN** `docs/r5-plain-language.md` **不**被分发(开发态 only;`tools/check_distributed_purity.py::SCAN_DIRS` 排除 `docs/`)。

#### Scenario: 配套文档随规则同步

- **WHEN** AGENTS.md 的 R5 任一子规则发生语义性变更
- **THEN** `docs/r5-plain-language.md` 对应条目同步更新(纯表述重组可不触发,但教训灭失/弱化必触发)。

### Requirement: R5 refactor safety (no lesson loss)

任何对 R5 的**结构性变更**(合并 / 拆分 / 改写 / 迁移位置)SHALL 保全每一条既有**规范教训**,由变更 design 中的「current → new 映射表」逐条证明;**R5.1–R5.10 编号 SHALL 保持稳定**(全仓引用 + R5.10 管辖编号)。变更不得删除或弱化既有教训,只允许重组表述。

#### Scenario: 重组保留全部教训

- **WHEN** R5 被重组(去重 / 拆段 / 改写)
- **THEN** 变更 design 含「current → new 映射表」,逐条旧教训均有显式新归宿;reviewer 可 `git diff AGENTS.md` 确认无教训被删或被软化。

#### Scenario: 编号不被重排

- **WHEN** R5 被重组
- **THEN** R5.1–R5.10 的编号与语义对应关系不变(可同号内拆段、可改表述,但**不重排号、不删号**)。

#### Scenario: 去重后防单点灭失

- **WHEN** 某教训经去重后只剩单一权威位置
- **THEN** 大白话配套文档(`docs/r5-plain-language.md`)提供该教训的人类可读第二副本,降低未来误删即灭失的风险。
