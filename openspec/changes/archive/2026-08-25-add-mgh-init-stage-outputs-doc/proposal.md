# Proposal: add-mgh-init-stage-outputs-doc

> **人话序**
> **现象**:在真实大仓跑 `/mgh-init` 时,维护者需要读懂 `.mgh-init/` 下各阶段的中间产物
> (如 `clusters.json`、`controls_candidates.json`、`checkpoints/t1/*.json`),才能判断流水线状态
> 健康与否(例如「T1 待跑 830 簇」是不是正常)。但现有文档只讲了**每步跑什么、产出哪个文件**
> (工作流程详解 / man 页),**没有一份按字段讲**的参考:每个文件里有哪些字段、字段值含义、
> `shape: centralized|distributed` 分别代表什么——维护者只能去读脚本源码猜。
> **根因**:文档受众分层(人类面/agent 面)已建立,但「人类读产物字段」这个使用场景一直没人补。
> **改什么**:新增一份人类面的**阶段产物字段参考**(`docs/man/mgh-init-artifacts.md`),按
> `.mgh-init/` 下每个产物文件逐字段解释其作用与取值;并把 `centralized`/`distributed`、
> `cluster_id` 等操作性词补进 `docs/glossary.md`。
> **怎么验证**:文档章节与真实产物一一对应(列全 `.mgh-init/` 下的文件清单),字段解释以
> `core/scripts/` 源码为准;glossary 补条;人类读者(维护者)能只读这份文档就回答「这步产物的
> 这个字段值是什么意思」。

## Why

`/mgh-init` 在真实大仓上的一次完整运行会产生 `discover → scout → T1 → T2 → T3 → assemble →
T4` 多阶段的十几个中间产物文件。维护者要判断运行状态(进度、健康度、能否继续),必须能读懂这些
产物;但目前的文档(man 页讲用法、工作流程详解讲节点)都不覆盖**字段级语义**。例如 `clusters.json`
里 `shape: centralized|distributed` 决定 T1 如何归簇、`cluster_id` 是 `category::anchor::file::sha` 拼接——
这些只有读 `core/scripts/discover_controls.py` / `list_clusters.py` 源码才知道。没有字段参考,维护者
只能靠读脚本或靠猜,真实运行(如这次「T1 830 簇」的判断)时容易误判。

## What Changes

- **新增** `docs/man/mgh-init-artifacts.md`(人类面,受众声明制):`.mgh-init/` 下每个产物文件的
  **逐字段参考**——文件作用、wrapper 结构、字段名 + 取值语义(含枚举),按流水线阶段组织。
  覆盖至少:`run_config.json`、`.active` 哨兵、`controls_candidates.json`、`clusters.json`、
  `skeleton.json`、`i1_enriched.json`(advisory)、`scout_plan.json`、`checkpoints/scout/*.json`、
  `scout_candidates.json`、`checkpoints/t1/*.json`、`controls_inventory.json`、
  `checkpoints/t3/*.<fmt>.json`、`init_manifest.json`、`report.md`、`fanout_progress.<tier>.json`。
  每文件含「字段表 + 枚举取值 + 谁消费它 + 缺失/异常时的影响」。
- **新增** `docs/glossary.md` 词条:`centralized` / `distributed`(簇 shape)、`cluster_id`、
  `checkpoint`(若缺)/ `wrapper 字典`。
- **不改变**任何脚本行为 / 契约 / schema;纯文档增量。
- 既有 `docs/man/mgh-init.md`(用法)与 `docs/mgh-init-工作流程详解.md`(节点讲解)不动,新文档
  与它们互补、互相链到。

## Capabilities

### New Capabilities
- `init-artifacts-reference`: 人类面的 `/mgh-init` 阶段产物**字段级参考**——按产物文件逐一解释
  字段名与取值语义(含 `shape: centralized|distributed` 等枚举),并规定该参考文档的受众、存放路径、
  与既有 man/工作流程文档的边界、以及「字段解释以 `core/scripts/` 源码为准、不得漂移」的维护约定。

### Modified Capabilities
<!-- 无:本变更不改变任何脚本行为 / 契约 / schema,仅新增人类面文档产物 + 词典补条。 -->

## Impact

- **新增文件**:`docs/man/mgh-init-artifacts.md`;`docs/glossary.md` 增补词条。
- **代码**:无(纯文档;不改 `core/scripts/`、不改命令壳、不改 install 分发面)。
- **风险**:低。唯一风险是字段解释与源码漂移——由 spec 的「字段解释以源码为准」约定 + 文档
  按阶段索引缓解;不引入机器校验(纯人类面文档,R3 受众声明制)。
- **非目标**:不给 agent 面加 JSON schema 文档(契约面仍是各脚本 `--help` / `core/contracts/`);
  不改任何脚本输出格式。
