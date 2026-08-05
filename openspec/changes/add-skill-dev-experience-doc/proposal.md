## Why

本仓库(m3g4h⊿rness)的本质是**一套「大 skill」**:多角色 subagent + 确定性工具脚本 +
skill 调用编排,串成 `/mgh-init`、`/mgh-sast`、`/mgh-sra`、`/mgh-srr` 等对外命令。开发这类
复杂流程的 skill 踩过的坑、沉淀的规约(AGENTS.md 的 R5.x 铁律、20+ 次 openspec 迭代),
是**可复用的工程经验**,对团队后续做 agent 工具链 / 复杂 skill 有直接学习价值。但目前这些
经验**散落在** `AGENTS.md`(面向本仓维护者、密度极高)、`openspec/changes/archive/`(逐次
迭代记录)、`docs/r5-plain-language.md`(只覆盖 R5 规则)里,**没有一份面向「没参与过本仓的
工程师」、用大白话讲清楚「为什么会有这些迭代、每次解决的是大模型的什么通病」的分享文档**。

## What Changes

- 新增一份**团队内部分享文档** `docs/skill-dev-经验总结.md`(中文、大白话、面向 AI 与人可读):
  - 用**真实迭代案例**讲「**什么原因 → 触发某次迭代 → 解决了什么问题**」,并把每个问题归因到
    **大模型的哪条通用特性**(如:过度热情 codegen、上下文窗口有限且会被摘要、跨会话漂移、
    难守「不要做 X」类禁令、路径/接口幻觉、非确定性、平台差异盲区等)。
  - 覆盖典型主题:编排器即宿主 agent(为何不能物化成 `.py`)、扇出路径漂移、零运行时依赖、
    hook 强制闭环、`--check` 边界校验、长跑可恢复、分发产物纯净性、双端(claude/opencode)对等等。
  - 给出**可迁移的清单**:做新「大 skill」时该前置哪些约束、配哪些兜底机制。
- **顺手优化** `docs/r5-plain-language.md`:该文档现存半英半中、术语堆砌、难懂,做一次可读性 pass
  (保留四要素结构与规则语义,**不改教训**)。
- **不新增任何代码 / 依赖 / 运行时行为**;纯文档。
- 与现有文档**互补不重复**:`docs/r5-plain-language.md` 逐条讲规则本身;本文档讲**规则的来历与
  大模型通病**,跨 R5 全量 + 非规则类迭代(如 opencode hook 误解、cluster_id `::` NTFS 问题等)。
- **新文档不挂反向指针**:不在 README / docs 索引 / AGENTS.md 链接它,定位为一次性分享快照、
  未来可整份删除。

## Capabilities

### New Capabilities
- `skill-dev-lessons`: 仓库维护一份**面向团队分享的「大 skill 开发经验总结」文档**,作为受管
  产物(有 spec 契约,后续迭代可更新)。规定其**受众 / 语气 / 必含内容(真实案例 + 大模型通病
  归因 + 可迁移清单)/ 存放路径 / 与现有文档的边界**。

### Modified Capabilities
<!-- 无:本变更不改变任何产品行为的 spec 级要求,仅新增文档产物。 -->

## Impact

- **新增文件**:`docs/skill-dev-经验总结.md` + 本变更的 spec `specs/skill-dev-lessons/spec.md`。
- **修改文件**:`docs/r5-plain-language.md`(可读性 pass,保留语义与教训;受 `agents-md-discipline`
  spec 约束,属编辑性改进,**无 spec delta**)。
- **受影响代码/依赖**:无(纯文档,不引入 pip 依赖,承 R2)。
- **维护成本**:新文档为**一次性分享快照**,**不挂反向指针、不做维护契约**;`r5-plain-language.md`
  仍按其既有 spec 随 R5 语义变更同步(本变更不改变该约束)。
- **受众**:团队内部工程师;非对外用户文档(对外仍看 `README.md`)。
