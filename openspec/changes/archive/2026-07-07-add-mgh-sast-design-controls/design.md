# Design — add-mgh-sast-design-controls

> 承 `proposal.md`。给关键决策的**选择 / 理由 / 备选(否决)**,可证伪。R3 简练:不贴长
> 代码,用 `文件:行号` 索引。

## Context

`/mgh-sast` 的 9 阶段提示词是从 vvaharness 逐字移植的(`core/prompts/stages/s*.md`,
头部带 `Source: vvaharness/...` 溯源注释,R1 保留)。vvah 经 `injectors/design_controls.py`
把 `design_controls` 注入 prompt 上下文,供 s2(降 likelihood)/ s3(chunk 排序)/ s4(上游
保护排除)/ s6(中和型 FP)/ s8(chain 阻断)消费。本仓移植时**保留了这些消费措辞**(实证:
`s2-threat-model.md:37-40,56`、`s3-decompose.md:19`、`s4-system.md:18-26,88-98`、
`s6-verify.md:24-31,39`、`s8-chain.md:14-18,24-25,50`),却**未移植注入器**——故威胁的
`controls` 字段恒为 `"none"`、chain 的 `blocked_by_controls` 恒空。

`/mgh-init` 现产出 `controls_inventory.json`(`core/contracts/init/inventory.md`):顶层
`controls[]`,每条 `Control` 带 `name/kind(6 枚举)/category/description/usage/evidence[]/
entry_points[]/protects[](fnmatch)/notes/gaps/cluster_id/role/confidence`,`kind`/`protects`/
`notes` 与 vvah `design_controls` 后向兼容。

约束:R1(移植提示词正文非必要不改)、R2(零依赖)、R5.3(确定性阶段经脚本 + CLI I/O 契约)、
R5.9(intake 边界 `--check`)、R5.10(分发产物纯净性)。

## Goals / Non-Goals

**Goals:**
- `/mgh-sast` 经 `--controls` 消费 `/mgh-init` 的 `controls_inventory.json`,按 scope 投影后
  注入 s2/s3/s4/s6/s8,使既有提示词的控制消费措辞真正生效。
- 控制走**确定性 intake 脚本 + 任务消息注入**;不改动移植提示词正文(R1);不诱导 subagent
  手挖 inventory(R5.2)。
- intake 边界有 `--check` 校验(R5.9);全程零新增运行时依赖;双壳镜像;回归测 + CLI lint。

**Non-Goals:**
- 不改 s1/s5/s7/s9(s1 纯结构;s5/s7/s9 确定性,不消费控制语义)。
- 不改 `/mgh-init` 的 inventory schema 或 `validate_inventory.py`(消费侧独立实现 intake 校验,
  避免 sast 反向依赖 init 内部)。
- 不引入 tree-sitter / 数据流分析;「控制是否在该数据流上游」由 subagent 据 evidence 锚点判定
  (LLM 判断),本变更只供应**结构化、scope 投影过**的控制摘要。
- 不做控制有效性验证(存在≠有效,承 mgh-init CVE-2025-41248 边界)。

## Decisions

### D1 — 控制走任务消息注入,不改移植提示词正文(R1)
**选择**:编排器 spawn s2/s3/s4/s6/s8 subagent 时,把投影后的 `controls_bundle` 放进**任务消息**;
SYSTEM 提示词(`core/prompts/stages/*.md`)正文一字不改。新增 fragment
`core/prompts/fragments/controls-context.md`(rewrite-original)由编排器 inline 进任务消息,
规定消费语义 + 诚实边界。
**理由**:vvah 的 `design_controls` 本就靠注入器 prepend 进上下文、不靠改 prompt;移植提示词正文
已预留消费位(见 Context 实证行号)。改正文违 R1(手改提示词),且无必要。
**备选(否决)**:编辑移植提示词加控制段——违 R1,且重抽(`tools/extract_prompts.py`)会冲掉手改。

### D2 — 确定性 intake + scope 投影脚本 `load_controls.py`
**选择**:`core/scripts/load_controls.py` 三职责:① **intake 校验**(well-formed wrapper、每条
`name/kind(6 枚举)/protects/evidence`、`kind` 别名归一);② **scope 投影**(每条标
`in_scope: bool`,= 该控制 `protects` globs 或 `entry_points` 与扫描 `in_scope[]` 求交非空;
`--diff` 增量时 `in_scope[]` 来自 `diff_seed.py` 产出);③ **emit** `controls_bundle`(含
`in_scope[]` 控制摘要 + `out_of_scope_count` + 计数)。stdout JSON、stderr 诊断、退出码 `0/1/2`、
自定位 `sys.path`、utf-8、零依赖、任意 cwd(承 R5.3a)。
**理由**:「哪些控制与本次扫描相关」是确定性 fnmatch 问题,应走脚本(R5.3 确定性阶段经脚本),
而非让 subagent 手挖整份 inventory(违 R5.2)。
**备选(否决)**:直接把整份 inventory 喂 subagent——大、含 out-of-scope 噪声、且诱导 `py -c`
挖 JSON(违 R5.2)。

### D3 — intake 边界 `--check`(R5.9),与 init `validate_inventory.py` 职责分离
**选择**:`load_controls.py --check <inventory>` 在扫描消费前校验 inventory well-formed +
vvah `design_controls` 兼容字段 + 每条 evidence 锚点 + `kind` 枚举/归一;失败退出码 2 → 编排器
回退(warn + 以「无控制」继续,advisory)。独立实现,**不 import** `validate_inventory.py`。
**理由**:intake 是 sast 的**消费侧**边界校验;`validate_inventory.py` 是 init 的**产出侧**(T2)
边界校验。耦合会让 sast 反向依赖 init 内部、违解耦。
**备选(否决)**:复用 `validate_inventory.py`——跨命令耦合、且其校验项(T2 语义)与 sast intake
不完全一致。

### D4 — 注入 s2/s3/s4/s6/s8,不注入 s1/s5/s7/s9
**选择**:对齐 vvah 消费点 + 现有提示词预留位:s2(降 likelihood)、s3(chunk 排序考虑控制)、
s4(上游保护排除)、s6(中和型 FP)、s8(chain 阻断 + `blocked_by_controls`)。
**理由**:这些阶段的提示词已显式提 design controls;漏注会让措辞落空。s1/s5/s7/s9 不消费控制语义。
**备选(否决)**:只注 s2/s6/s8——s3/s4 提示词已显式提控制,会落空。

### D5 — scope 投影是 relevance hint,防 under-filter 漏判
**选择**:`controls_bundle` 同时含 `in_scope[]`(优先喂)与 `out_of_scope_count`;subagent 拿
`in_scope[]` 为主,**保留**对全量控制 name/kind 的可见(经 `out_of_scope_summary`)。投影只标
`in_scope` flag、不删控制。
**理由**:fnmatch 投影可能 under-filter(误判 out-of-scope),漏掉相关控制 → 漏报。保留全量 +
flag 让 subagent 在 in_scope 不命中时仍可参考,把投影降级为 hint。
**备选(否决)**:硬切只传 in_scope——under-filter 直接变漏报,不可接受。

### D6 — 诚实边界:存在≠有效(承 mgh-init CVE-2025-41248)
**选择**:fragment 强制 subagent 把控制视为「**声称的保护**」而非「已验证的中和」:仅当控制
`evidence` 锚点确认位于该 finding 数据流**上游**时才判 FP/阻断 chain;否则只降权不中和。
`run_manifest.json` 记 `controls.{source, in_scope_count, out_of_scope_count, inventory_path}`;
`report.md` 披露控制来源 + 「存在≠有效」边界;无 controls 运行声明「未注入控制」。
**理由**:inventory 是 LLM-induced 候选、断言存在不断言有效;误把存在当有效会**漏报真漏洞**
(CVE-2025-41248:参数化类型上 `@PreAuthorize` 可绕过)。
**备选(否决)**:控制即视为有效中和——直接漏报,违诚实边界。

## Risks / Trade-offs

- **控制误判 → 漏报**(把真漏洞当中和型 FP)→ D6:evidence-grounded 中和判定 + 报告披露被控制
  影响的 finding;fragment MUST 要求 subagent 列出「被控制下架」的 finding 供人工复核。
- **scope 投影 under-filter** → D5:保留全量 + in_scope flag,投影为 hint。
- **inventory schema 漂移**(与 init 不一致)→ D3:`load_controls.py --check` 是 intake 闸门;
  契约 `core/contracts/sast/controls-intake.md` 锁 shape,字段对齐 `core/contracts/init/inventory.md`
  的 `Control` 元素 schema。
- **R1 误改移植提示词** → D1:只加 fragment + 任务消息,不动 `stages/*.md` 正文;tasks 显式标注。
- **分发纯净性(R5.10)** → fragment/契约是操作性内容,不含研发铁律编号/失败 ID;install 分发前
  经 `tools/check_distributed_purity.py`(承 R5.7)校验。

## Migration Plan

- **无 schema/数据迁移**:不传 `--controls` 时行为字节级不变;全部 additive。
- **版本号**:任一 `.md`/脚本改动 bump(承 R5.8)。
- **回滚**:移除 `--controls` flag / `load_controls.py` / fragment / 契约 / 测试,无下游依赖。

## Open Questions

- `--controls` 是否接受目录(自动找 `controls_inventory.json`)?倾向**只接受显式文件路径**
  (closed-set,R5.3b),避免歧义。
- 是否需 `--controls-mode strict|advisory`?倾向**默认 advisory**(无则正常跑、仅声明未注入),
  保持向后兼容;strict 留后续。
