> **人话序** 现状:`/mgh-sdr` 把同一接口调用链切成几瓣——controller 方法一个单元、被它调的
> service/dao 归进独立单元,审 controller 的 subagent 看不到 service 的 SQL、审 service 的看不到
> 路由与鉴权上下文,「越权、SQL 注入」这类跨层判定被割裂,分析质量下降。根因:分组只看注解启发式
> + 目录聚类,不懂「谁调用谁」。改什么:分组阶段改由 codegraph 调用图**确定性**驱动——把落在同一
> 条接口调用链上的变更合并进一个 fan-out 单元;判不穿(反射/无 codegraph)的落独立单元、拆多个不
> 硬塞;无 codegraph 退化回注解+目录。怎么验证:`diff_group.py` 分组回归测(同链合并/共享下游拆分/
> 反射回退/无 codegraph 退化),分组数确定性可复现;分组全程在脚本侧,主壳只读 `pending[]` 小清单
> 派发,大 diff 不爆上下文。

> **依赖**:本 change 依赖 `add-mgh-sdr` 先 apply + archive(`security-design-review` 由该 change
> 引入,本 change 对其做 MODIFIED delta,故 `openspec validate` 需在 add-mgh-sdr 归档后通过)。

## Why

`add-mgh-sdr` 的分组是「注解启发式接口单元 + 目录簇 standalone」:按**文件位置**切,不按**调用
关系**切。但 sdr 的 6 个判定维度(垂直越权、横向越权、其他权限、SQL 注入、输入校验、敏感数据)本质
是**跨层**的——判断「接口 `/user/detail` 有没有做横向越权」需要同时看到 controller 的路由鉴权
注解与 service 里的 SQL 查询条件。切散后:controller 单元的 subagent 看不到 service 的 SQL,
service 单元的 subagent 看不到路由与鉴权上下文,两个都不完整;更糟的是,跨层追读会逼 subagent
在单元间越界读(撞守卫、烧 token)。

本 change 把分组从「位置启发式」升级为「调用链感知」:用 codegraph 的确定性调用边
(`callers`/`callees --json`)把落在同一接口调用链上的变更合并成一个 fan-out 单元。codegraph 已
支持 Java 全量 + Spring 框架路由(正是目标域),且提供机器可读 JSON 输出——分组可完全在确定性
脚本 `diff_group.py` 内完成,不进主壳 LLM,主壳上下文不随 diff 大小增长。

## What Changes

- **`diff_group.py` 分组算法升级**(改 `add-mgh-sdr` 已引入的确定性叶脚本,不改其 CLI 契约与
  `pending[]` 字段 shape):
  - **变更符号提取**: `git diff --no-color base..branch` 的变更文件 → 每个 diff hunk 映射到
    「包住它的方法/接口」(注解启发式;codegraph 可用时 `codegraph node --file --symbols-only`
    取符号边界),无法映射的 hunk 归文件级变更;
  - **调用链分组(codegraph 可用时)**:对每个变更符号跑 `codegraph callers --json` /
    `callees --json` 取调用边,在**变更符号集**上建图(仅保留两端均在变更集内的边)、并查集求
    连通分量;含 ≥1 路由注解符号的分量 → `interface` 单元(= 该接口完整下游链,controller + 被调
    变更 service/dao 的 hunk 合并进一个 slice);无路由分量 / 调用边判不穿(反射/DI 残差)→
    `standalone` 单元(按目录 + `--max-standalone-bytes` 拆分,拆多个不硬塞);
  - **共享下游按接口拆**:一个 service 被多个变更接口调,不并成一个分量,该 service hunk 在每个
    引用它的 interface 单元 slice 内字节预算内重复,跨单元重复 finding 交 render 三元组去重;
  - **退化**:无 codegraph → 注解接口单元 + 目录簇 standalone(与 `add-mgh-sdr` 现状逐字等价)。
- **`pending[]` shape 零变化**(`kind` 仍 `interface|standalone`,`route` 仍单串);fan-out 派发、
  波次状态机、模板填充、render 去重**零改动**——分组是 `diff_group.py` 内部升级,下游无感。
- **codegraph 角色升级**:从「subagent 可选减扇出信号」升为「分组阶段确定性输入」;仍是可选宿主
  能力(非 pip 依赖,承 R2),off 时零调用、行为降级等价。

非目标:不做 tree-sitter 调用链后端(mgh-sast 规划);不改 `diff_group.py` 的 CLI flag 面与
`pending[]` 契约 shape;不改 sra/srr 与 mgh-init 任何行为;不把 codegraph 变成硬依赖。

## Capabilities

### Modified Capabilities

- `security-design-review`: 「确定性 diff 采集与接口维度分组」需求改为**调用链感知分组**——
  codegraph 调用边驱动的接口调用链合并、变更符号集并查集、共享下游按接口拆、反射/无 codegraph
  退化 standalone 拆多个;`pending[]` shape 与下游派发/渲染契约不变。

## Impact

- **代码**:`core/scripts/diff_group.py`(分组算法升级:codegraph 子进程 + JSON 解析 + 并查集 +
  变更符号提取;无新增脚本、无第三方 import,`subprocess`/`json`/`pathlib` 均 stdlib);
  `core/prompts/fragments/fanout/sdr-task.md`(占位符 `codegraph` 语义微调,占位符集不增删)。
- **契约**:`core/contracts/sdr/pipeline.md`(补「变更符号提取 + 调用链分组 + 共享下游」小节,
  `pending[]` 字段 shape 不变,stdout 增 `codegraph` bool);无 fanout-dispatch / runtime-hook
  delta。
- **测试**:`tests/test_diff_group.py` 扩展(同链合并 / 共享下游拆分 / 反射回退 / 无 codegraph
  退化 / codegraph JSON 解析 / 变更符号映射)。
- **研发铁律对齐**:R2(不新增 pip 依赖;codegraph 是可选宿主二进制,同 git);R5.3a/b
  (`diff_group.py` 仍是自包含叶脚本,CLI 契约不变,`pending[]` 绝对路径逐字透传);R5.9
  (`--check` 覆盖分组自洽)。
- **诚实边界**:codegraph 调用边是**静态分析**,漏动态分派/反射/DI(Spring 路由覆盖 83.3% 实测
  上限);判不穿的同链变更退入 standalone 拆多个,不漏检但粒度粗;codegraph 存在与否改变分组粒度
  (均确定性、可复现、行为可预期)。
