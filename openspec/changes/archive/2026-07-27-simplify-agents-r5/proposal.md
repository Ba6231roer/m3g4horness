## Why

`AGENTS.md` 的 **R5 — Agent 工具命令稳定性**(lines 91–187,~97 行 / 10 条子规则 R5.1–R5.10)经多轮迭代堆叠,已**冗长、分散、可读性低**。根因不是内容错误,而是结构性的:

- **同一机制在多处复述**:长跑可恢复机制在 R5.3(c) 与 R5.4 各写一遍(`--time-budget-ms` / `partial:true` / 退出码 0 逐字重复);opencode env 不继承在 R5.4(悬空前向引用 `承 R5.7`)与 R5.7 各写一遍;退出码 `0/1/2` 在 4 处出现。
- **R5.7 塞了 4 个无关关切**:评估方法论 + hook 强制 + opencode `.ts` 定性 + env 不继承边界,挤在一个 bullet 里,是全节最难读处。
- **R5.3(b) 过载**:CLI I/O 契约 + fan-out 枚举 + 绝对输出路径 + `MGH_TARGET` 子树守卫,~8 条规则挤一个子项。
- **R5.5 的 ⑤ 脱离父项**:indent 漂成顶层 bullet,是格式 bug。
- **"理由〔…〕须随规保留/勿软化"样板**重复 4 处。

每条规则的**经验教训都是承重的,不得删除**;本变更只做**结构重组 + 去重 + 补索引**,不做任何弱化或删条。

## What Changes

- **去重长跑可恢复机制**:R5.3(c)(脚本侧契约)与 R5.4(编排器侧纪律)合并为**一处权威表述**,其余位置改为指针。保留全部教训(零全损 / 跨宿主 / 不假设单次跑完 / NEVER wrapper loop / opencode timeout 须启动前就绪)。
- **去重 opencode env 不继承**:单一归宿放 hook 规则;删除 R5.4 的悬空前向引用。
- **拆分 R5.7**:同号下分两段清晰命名 ——「评估方法论」(baseline / A/B / 全新实例首跑 / 漂移回灌)+「hook 强制闭环」(双端 hook / opencode `.ts` 定性 / parity 守卫 / env 不继承 fail-soft)。不新增子号。
- **修 R5.5 的 ⑤ 孤儿**:折回 R5.5 父项下。
- **减载 R5.3(b)**:保留 CLI I/O 契约主体;fan-out 枚举 / 绝对路径 / `MGH_TARGET` 子树守卫给显式子结构或归并到编排器黑盒簇(R5.2),design 定。
- **加 R5 头部「强制面索引表」**:rule → 执行机制(check_contracts lint / install 自检 / `--check` 边界校验 / check_distributed_purity lint / runtime hook),一眼可查。
- **合并样板**:把重复的「理由须随规保留 / 勿软化」收敛为 R5 前言一行注;各规则的 `理由〔…〕` 括号**保留**。
- **修剪纯回声溯源**(`承 R5.x` 无新增信息者删,有溯源价值者留)。
- **新增大白话配套文档**(`docs/r5-plain-language.md`,dev-only、**不分发**),逐条用大白话讲清每条 R5 规则。
- **不改编号** R5.1–R5.10(编号被全仓引用,R5.10 本身就管辖它们)。
- **零规范内容删除**。预估 ~97 → ~70–75 行,可读性显著提升。

## Capabilities

### New Capabilities

- `agents-md-discipline`:把本变更**真正引入的 3 条新规范要求**首次落入 spec 级家 —— R5 头部「强制面索引表」/ 大白话配套文档 / 重构零教训丢失映射。**不编码既有 R5 内容**(那些仍在 AGENTS.md),只固化本变更带来的可维护性增量,使 spec-driven schema 有诚实 delta。

### Modified Capabilities

(无 —— 不改任何既有 spec 的 requirement;既有 R5.1–R5.10 行为语义不变,仅 AGENTS.md 表述重组。)

## Impact

- `AGENTS.md` R5 段(lines 91–187):**原地重组**,无新增/删除规则。
- 新增 `docs/r5-plain-language.md`(dev-only,不进 install 分发集)。
- **零代码 / 零脚本 / 零分发产物 / 零 install 行为变更**。
- **CI 不受影响**:已确认 `tools/check_distributed_purity.py::SCAN_DIRS`(lines 52–62)显式排除根 `AGENTS.md` 与 `docs/`, purity / 契约 / 回归测试均不扫描 R5 内部结构。
- 风险:重组时**误删教训**或**改语义** → 由 design 的「逐条映射表」(current text → new location)+ apply 后人工 diff 核对兜底。
