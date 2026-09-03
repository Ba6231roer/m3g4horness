# Design: add-mgh-init-stage-outputs-doc

## Context

纯文档交付物:新增人类面 `docs/man/mgh-init-artifacts.md`(字段级参考)+ 补 `docs/glossary.md` 词条。
动机见 `proposal.md`;行为要求见 `specs/init-artifacts-reference/spec.md`。现有三份人类面文档分工明确
(`docs/man/mgh-init.md` 讲用法、`docs/mgh-init-工作流程详解.md` 讲节点流程、`docs/glossary.md` 管用词),
本设计只决定「新文档怎么组织、字段以哪为唯一依据」,不涉及任何脚本/契约/schema 变更。

## Goals / Non-Goals

**Goals:**
- 一份按 `.mgh-init/` 产物文件组织、逐字段解释的人类面参考,维护者不读源码即可判断运行状态。
- 字段解释**以 `core/scripts/` 对应产出者的源码 / `--help` 契约为唯一依据**,杜绝凭记忆撰写。
- glossary 补齐本文档用到的操作性词条。

**Non-Goals:**
- 不给 agent 面加 JSON schema 文档(契约面仍是各脚本 `--help` / `core/contracts/`)。
- 不引入机器校验(纯人类面文档,R3 受众声明制;字段同步靠 spec 明文约定)。
- 不重排既有三份文档结构。

## Decisions

### D1 — 文档按「产物文件」而非「流水线步骤」组织

按 `.mgh-init/` 下的文件逐章组织(每文件一章),而非按 discover→scout→T1… 的步骤讲。
**理由**:维护者读产物时的查询入口是「我看到某个文件,它是干嘛的、字段什么意思」;按文件组织
对得上这个使用场景。与工作流程详解(按节点讲「谁跑、产出什么」)互为互补:那篇回答「这步怎么来」,
这篇回答「这个文件里是什么」。
**备选**:按步骤组织——维护者不知道产物在哪个步骤产出,入口不对;弃。

### D2 — 字段表 + 枚举 + 消费方 + 缺失影响,四列式

每个文件章节统一四块:① 文件作用与 wrapper 结构;② 字段表(字段名 / 取值语义);③ 枚举取值说明
(如 `shape: centralized|distributed`、`source: regex|scout|codegraph`);④ 谁消费它 + 缺失/异常影响。
**理由**:字段参考的价值在「取值语义」与「异常时怎么办」(例如空 `checkpoints/t1` = T1 未开始的正常
前置态,而非损坏);四块齐备才支撑维护者做状态判断。统一格式降低维护成本。
**备选**:只列字段名不解释语义——不足以支撑状态判断;弃。

### D3 — 字段事实来源固定为对应产出者脚本

`clusters.json` → `discover_controls.py`(form_clusters / stdout)、`controls_candidates.json` →
`discover_controls.py` / `merge_scout.py`、T1 记录 → `validate_t1_records.py`(契约面)+
`init-induct.md`、inventory → `validate_inventory.py` 等。撰写时**逐字段对读源码**,不凭记忆。
**理由**:字段语义的唯一真相源是产出者;凭记忆会漂移(本仓已有多起 agent 虚构 before/after 的记录)。
**备选**:依赖工作流程详解的叙述——那篇不含字段级细节;弃。

## Risks / Trade-offs

- [文档字段与源码漂移(未来脚本加字段不改文档)] → spec `init-artifacts-reference` 明文约定
  「字段解释以源码为唯一依据,脚本字段变更时文档 SHALL 同步」;文档按阶段索引便于定位。
- [文档与既有三份重复] → D1 边界:只讲字段,不展开步骤;链到既有文档不复述。
- [篇幅膨胀] → 人类面允许同义复述但忌长;字段表用表格(R3),不保留长代码块,只给 3–5 行内联
  结构片段。

## Migration Plan

纯文档增量,无迁移;发布后维护者直接引用新文档,既有文档不变。

## Open Questions

无。
