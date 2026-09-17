# init-artifacts-reference Specification

## Purpose

人类面的 `/mgh-init` 阶段产物**字段级参考文档**:按 `.mgh-init/` 下的每个产物文件逐一解释字段名
与取值语义(含 `shape: centralized|distributed` 等枚举),让维护者不读脚本源码就能判断运行状态与
产物健康度。纯文档交付物,不改变任何脚本行为 / 契约 / schema;文档住在维护者私有文档区,
不随包分发,其路径不出现在任何分发产物或 SDD 产物里(承 R5.11)。

## Requirements

### Requirement: 阶段产物字段参考文档的受众与边界

系统 SHALL 在维护者私有文档区维护一份人类面文档,受众 = **人类**(维护者 / 首次读产物的人)。
它 SHALL 与 `/mgh-init` 同名系列,按流水线阶段组织 `.mgh-init/` 下每个产物文件的字段参考,并 SHALL
与同族的两份文档划清边界:命令用法说明讲「怎么跑」、节点流程详解讲「每步做什么」,本文档只讲
**产物文件的字段与取值**。三份 SHALL 互相链到,不复述其内容。

#### Scenario: 文档入口可定位且受众声明
- **WHEN** 人类维护者需要查 `clusters.json` 的字段含义
- **THEN** 能在该字段参考文档里找到按阶段组织的产物字段章节,且文件开头声明受众 = 人类

#### Scenario: 与既有文档边界清晰
- **WHEN** 维护者想查「这步怎么跑」而非「这步产物字段」
- **THEN** 字段参考只做字段参考,不展开步骤细节,并链到节点流程详解 / 命令用法说明

### Requirement: 产物覆盖清单与逐字段解释

该字段参考文档 SHALL 覆盖 `.mgh-init/` 下这些产物文件(每文件一个章节):控制侧
`run_config.json`、`.active` 哨兵、`controls_candidates.json`、`clusters.json`、`skeleton.json`、
`i1_enriched.json`(advisory)、`scout_plan.json`、`checkpoints/scout/*.json`、`scout_candidates.json`、
`checkpoints/t1/*.json`、`controls_inventory.json`、`checkpoints/t3/*.<fmt>.json`、
`init_manifest.json`、`report.md`、`fanout_progress.<tier>.json`。每个章节 SHALL 给出:文件作用、
wrapper 结构、**字段表**(字段名 + 取值语义)、枚举取值说明、谁消费它、缺失/异常时的影响。

#### Scenario: 字段解释与真实产物结构一致
- **WHEN** 维护者把文档里的字段表与某次真实运行产出的 `clusters.json` 对照
- **THEN** 文档中的字段名与取值与该产物逐一对得上(字段解释以 `core/scripts/` 源码为唯一依据,
  不得凭记忆撰写)

#### Scenario: 枚举取值有明确语义
- **WHEN** 维护者查 `clusters.json::clusters[].shape` 的取值
- **THEN** 文档给出 `centralized`(按锚点 `category::anchor::file` 归簇,控制只在一处)与
  `distributed`(按 token `category::pattern` 归簇,注解散落多文件)的区分与典型例子

#### Scenario: 缺失/异常影响有披露
- **WHEN** 维护者看到 `checkpoints/t1` 为空而 `clusters.json` 有 830 簇
- **THEN** 文档能解释:空 `checkpoints/t1` 是 T1 尚未开始的正常前置状态,且 T1 受 scout 层完成闸门
  (`scout-incomplete-gate`)约束——字段参考与状态机语义一致,不造成误判

### Requirement: 操作性词补进术语词典

系统 SHALL 在维护者私有的术语词典中增补本文档用到的操作性词条,至少含:`centralized` / `distributed`
(簇 shape 含义)、`cluster_id`(组成形态与用途)。词典自由增补,不设准入审批(承 R3)。

#### Scenario: 人类面用词前词典有据
- **WHEN** 字段参考文档使用 `centralized`、`distributed`、`cluster_id` 等词
- **THEN** 这些词在术语词典中均有条目,释义与文档正文一致

### Requirement: 字段解释以源码为准的维护约定

本 spec SHALL 规定:字段参考文档的字段解释以 `core/scripts/` 下对应产出者的源码 / `--help` 契约为
唯一依据;脚本字段变更时文档 SHALL 同步更新,不得漂移。文档不引入机器校验(纯人类面,受众声明制),
维护约定靠 spec 明文约束。

#### Scenario: 字段语义变更时文档同步
- **WHEN** `list_clusters.py` 的 stdout 字段(如 pending[] 增加字段)在后续 change 中变化
- **THEN** 该字段参考文档对应章节 SHALL 同步更新,维持与源码一致
