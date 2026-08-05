# spec.md — skill-dev-lessons (ADDED)

> 本 capability 约束一份**受管的团队分享文档**:把 m3g4h⊿rness 开发「大 skill」过程中沉淀的
> 经验,以大白话中文 + 真实迭代案例 + 大模型通病归因的形式固化下来,供团队复用。

## ADDED Requirements

### Requirement: 文档存在与定位

仓库 SHALL 在 `docs/skill-dev-经验总结.md` 维护**一份**面向团队内部分享的经验总结文档。
文档 SHALL 以**中文大白话**为主(仅当中文表达不准的术语保留英文,如 hook、subagent、AST、
`tool.execute.before`、fail-loud / fail-soft 等,首次出现处给中文释义)。文档面向**未参与过本仓的
工程师**,目标是可迁移到下一个「大 skill / agent 工具链」项目。

#### Scenario: 团队成员想获取经验

- **WHEN** 一名未参与本仓的工程师想了解「做复杂 skill 踩过的坑与兜底机制」
- **THEN** 读取 `docs/skill-dev-经验总结.md` 即可得到一份中文大白话、自洽可读的经验总结,无需先读完 `AGENTS.md` 全文或逐个翻阅 `openspec/changes/archive/`

#### Scenario: 语言基调

- **WHEN** 读者通读该文档
- **THEN** 正文以中文大白话叙述;技术术语首次出现处给出中文释义,而非整段英文或中英混杂的技术描述

### Requirement: 以「大模型通病」为组织主线并 cite 真实来源

文档 SHALL 以**大模型通病(可复现的 LLM 行为特性)**为章节主线,**非**时间线、**非**逐条规则序。
每个通病章节 SHALL 包含四要素:**(a) 通病描述 → (b) 真实迭代案例 → (c) 沉淀出的机制/规约 →
(d) 可迁移到新 skill 的清单**。每个案例 SHALL cite 至少一个真实来源:归档变更夹名(如
`harden-mgh-init-orchestration-discipline`)或 `AGENTS.md` 规则号(如 R5.2)或 `文件:行号`。
通病归因 SHALL 显式标注为「团队回溯性解读」,不冒充上游原始结论。

#### Scenario: 工程师复用到新 skill

- **WHEN** 工程师在新项目里设计一个多 agent + 工具脚本的复杂 skill
- **THEN** 文档针对每条通病给出「案例 + 沉淀机制 + 可迁移清单」,使其能前置对应约束与兜底,而非重新踩坑

#### Scenario: 案例可追溯

- **WHEN** 读者想核实某个案例的真实性
- **THEN** 该案例在文中 cite 了真实变更夹名 / 规则号 / `文件:行号`,可据此回溯到 `openspec/changes/archive/` 或源码

### Requirement: 覆盖规则类与非规则类教训,并单列「前提出错」

文档 SHALL 同时覆盖:**(1) 规则类教训**(R5.1–R5.10 各机制,如黑盒纪律、扇出路径 recipe、
`--check` 边界校验、长跑可恢复、分发纯净性、双端 hook 闭环等);**(2) 非规则类认知纠正**。
文档 SHALL 设**独立一章「前提出错」**,列出至少这些「此前误判、后经查证纠正」的案例:opencode
无 hook(实为 `tool.execute.before` 插件)、`opencode.json instructions` 省 token(实为 eager 全装载)、
`::` 是 NTFS ADS 分隔符(写盘 errno 22)、opencode 插件进程不继承 mid-session env。

#### Scenario: 识别「动手前先验证平台事实」

- **WHEN** 读者面临一个看似成立的平台 / 工具能力前提(如「某宿主是否支持某 hook 事件」)
- **THEN** 文档「前提出错」章提供的案例促使其先查证官方文档 / 实测,而非直接采信既有记忆

### Requirement: 与现有文档边界清晰且不重复

文档 SHALL 在开头显式声明与下列文档的**互补边界**,不复述其正文:`README.md`(对外用户)、
`docs/r5-plain-language.md`(R5 规则逐条大白话)、`docs/mgh-*-工作流程详解.md`(各命令工作流)。
本文档讲「**规则的来历 + 大模型通病**」,不重抄规则条文。

#### Scenario: 读者区分本文与 R5 大白话文档

- **WHEN** 读者同时持有本文档与 `docs/r5-plain-language.md`
- **THEN** 两份文档职责清晰不重叠:前者讲「为什么会有这条规则、撞的是什么通病」,后者讲「这条规则本身怎么说」

### Requirement: 非分发产物,可引用开发态标识

文档 SHALL 定位为**研发态内部文档**,不随 `install.sh` 分发到目标项目。因不分发,文档 MAY 自由
引用 R5.x / FDn / 变更夹名 / `task.*.md` 等开发态标识。R5.10(分发产物纯净性)的 purity lint
SHALL NOT 把本文档纳入分发扫描集(与根 `AGENTS.md`、`docs/` 同属研发态豁免)。

#### Scenario: purity lint 不误伤本文档

- **WHEN** `tools/check_distributed_purity.py` 运行
- **THEN** `docs/skill-dev-经验总结.md` 因含 `R5.x` / 变更夹名等开发态标识而**不被判为违例**(它不在分发扫描集内)

### Requirement: 一次性分享快照,不挂反向指针

文档 SHALL 定位为**一次性团队分享快照**,而非永久维护契约;文档 MAY 在未来被整份删除。
文档 SHALL NOT 在 `README.md` / docs 索引 / `AGENTS.md` 等任何处建立指向本文档的反向指针,以保证
未来可整份删除而不留断链。文档**不需要**随 R5 迭代回灌(不写维护契约)。

#### Scenario: 未来删除文档不留断链

- **WHEN** 维护者未来删除 `docs/skill-dev-经验总结.md`
- **THEN** 仓库内不存在指向该文件的残留指针 / 链接(因从未挂过反向指针),不产生断链

#### Scenario: 无反向指针关联

- **WHEN** 检索 `README.md` / docs 索引 / `AGENTS.md`
- **THEN** 不存在指向 `docs/skill-dev-经验总结.md` 的链接
