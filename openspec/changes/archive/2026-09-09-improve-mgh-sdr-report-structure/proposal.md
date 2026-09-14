# improve-mgh-sdr-report-structure

## Why

> **人话序** 现象:`/mgh-sdr` 报告按 6 维度平铺问题清单,人审时要在几十条按维度穿插的
> 条目里自己拼「哪个接口有什么问题」——想看 `/order/submit` 到底有没有权限/SQL/校验问题,
> 得扫完整个清单;调用链信息只在分组期用过一次,报告里完全没有,人无法从报告判断问题在链
> 上哪一跳。根因:报告数据模型是「维度 → findings」,不是「接口单元 → 维度矩阵」;分组期
> 已经查过 codegraph 调用边并建了链,但链本身没物化进产物,用完即弃。改什么:① 报告改为
> **「章节一简报表(行=评审单元,列=入口/调用链/前端两列/6 维度) + 章节二问题详述(编
> 号跳转)」**,表格内联缩写调用链(仅保留类名,如 `OrderController.submit`——首版「包
> 段首字母 + 类名」形态真仓试用仍过长,已收敛;`·`同类延续、`⤷`分支、`⇢`mapper XML
> 终端、`†`未变更节点),带真实分支的单元在章节三补 mermaid 图(线性链不画);② diff_group
> 分组期把**每单元调用链物化**进 grouping.json(链节点含 FQN 文件名:方法名、线号、变更状
> 态、路由),零新增 codegraph 查询;③ sdr_context 外部仓检索补齐前端两列数据源(路由正则
> 对齐 `@RequestMapping` 族 + 计数入 context.json)。怎么验证:单测覆盖链物化/前端计数/渲
> 染三段;以 springBootTemplate 为示例项目跑只分组+渲染的干跑,人工核对表格与 mermaid 形态
> (格式样例见 `mgh-sdr-report-format-samples.md`,方案 C 已选型)。

- **问题**:报告可读性——按维度平铺的清单让人审时无法按接口归位问题;调用链(安全评审
  判断「问题在链上哪一跳」的关键上下文)在报告里缺席。
- **为何现在**:callchain 分组与 slice 经济性修复刚落地(codegraph 边数据已在分组期获取),
  链物化零新增查询即可兑现;真仓验收(4.4)后报告结构是下一个体验瓶颈。

## What Changes

- **报告结构重构**(`render_sdr_report.py`,**行为变化**:报告面向人的章节组织从「按维
  度分组」改为「单元矩阵 + 问题详述」):章节一 = md 表格简报,行 = 评审单元(排序:inter-
  face 按 route 升序、standalone 殿后按 unit_id),列 = 接口/方法入口、调用链、是否前端接口
  (是/否/未知)、前端使用次数、6 维度各一列(是/否 + 问题编号引用,**纯文本编号**,不产
  任何 md 锚点/HTML anchor 标签——obsidian/Zed 跳转不支持,不再产出);章节二 = 逐问题详
  述(P-NN 编号统一,每条含 severity/维度/route/位置 file:line/风险/建议/control_ref,
  排序 severity 升序、同 severity 按 P-NN);章节三 = 分支调用链图,仅含带真实分支
  (⤷)的单元(每分支单元一张 mermaid `flowchart LR`,线性链不画);诚实边界节保留
  (≥7 条,含排除集披露),头部保留分支/时间/检查面/敏感目录来源/外部仓结论 + 分组概览。
- **调用链物化**(`diff_group.py`):分组期把每单元**完整调用链**写入 grouping.json
  `units[].chain[]`(节点 = `{fqn_short, label, file, line, change: changed|unchanged|
  external, route}`,FQN 短形 = 仅保留类名/文件名:方法名(如 `OrderController.submit`,
  真仓试用后由「包段首字母 + 类名」形态收敛;完整包路径可由 `file` 列还原);链 = 从路由方法(或
  分析可达最上游)沿 callees 边的确定性闭包,接口→实现消解(实现优先,不重复列接口跳),沿
  途变更符号全含、未变更上游路由节点标 `unchanged`,mapper XML 终端节点补全(namespace
  = dao FQN ∧ id = 方法名的确定性 XML 扫描,XML 不在 codegraph 图内)并标 `external`;
  branch/分叉在节点序列上表达(主链线性节点 + `branch_of` 指回宿主节点索引;渲染为 `⤷`
  平铺与章节三 mermaid 边)。零新增 codegraph 查询(复用分组期已返回的原始边;未变更下游
  边是新增消费——`_cg_edges` 已返回,callee 侧此前仅消费变更集内子集)。
- **前端两列数据源补齐**(`sdr_context.py`):外部仓路由出现计数正则从 `@(Get|Post|Put|
  Delete|Patch)Mapping` 扩到 `@RequestMapping` 族(与 diff_group 注解族对齐,含类级 base
  route 拼接);计数结果从「仅 hits.md 文本」**新增物化进 context.json**
  `external_repos[].route_hits[]`(`{route, count}` 列表);无外部仓声明/不可达 → 两列
  「未知/—」。
- **draft schema 扩展**(`sdr-task.md` + sdr-review-fanout agent 定义,双端镜像):
  findings[] 每项新增 `line`(int,问题锚定行号,即现行 `line_hint` 的数值化),render
  的详述行据此写 `file:line`;`line_hint`(hunk 行段)保留,简报表问题列仍按「单元 × 维
  度」聚合。
- **manifest 扩展**:`sdr_manifest.json` 新增 `rows[]`(简报表逐行结构化投影:
  unit_id/entry/chain(渲染用缩写串)/frontend_is/frontend_count/issue_refs[]),供下游工
  具(如未来 /mgh-blst)确定性消费;`counts` 语义不变。
- **不影响**:分组规则本身(排除集/锚定/合并/预算拆分零改动)、fan-out 派发契约、6 维度
  检查面、launcher 流程、`--check` 语义(新增字段并入现有自洽校验)。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `security-design-review`:
  - 「确定性 diff 采集与接口维度分组」——新增调用链物化义务(每单元 `chain[]` 节点 schema、
    接口消解、mapper XML 终端、分支表达、零新增查询约束);
  - 「存量安全设计基线投影与外部仓受控检索」——新增前端计数正则对齐 + `route_hits[]` 物化
    义务;
  - 「统一问题记录汇总与确定性报告渲染」——报告结构需求整体改写(章节一简报表/章节二详
    述/章节三分支图/纯文本编号引用/manifest `rows[]`/draft `line` 字段)。

## Impact

- **代码**:`core/scripts/diff_group.py`(链物化 + `--check` 扩展)、
  `core/scripts/sdr_context.py`(路由正则 + route_hits 物化)、
  `core/scripts/render_sdr_report.py`(渲染重写,行为变化)、
  `core/prompts/fragments/fanout/sdr-task.md`(draft schema 加 `line`)、
  `releases/{claude-code/commands,opencode/command}/mgh-sdr.md`(壳披露更新)、
  `releases/{claude-code/agents,opencode/agent}/sdr-review-fanout.md`(agent 定义镜像)、
  `tools/check_contracts.py`(契约面同步)。
- **测试**:`tests/test_diff_group.py`、`tests/test_render_sdr_report.py`、
  `tests/test_plan_aggregate.py`(如有 sdr 引用)——新增链物化/前端计数/新报告结构用例,
  旧断言更新。
- **依赖**:零新增(全部 stdlib;mermaid 为 md 文本输出,无渲染依赖)。
- **兼容**:grouping.json/context.json/draft JSON 新字段均为**增量字段**(旧消费者忽略即
  可);报告 md 结构变化对人是行为变化(本次变更的目的);draft 缺 `line` 字段时 render
  降级为 `file`(不硬失败,旧 draft 可渲染)。
- **显式不做**:md 表格内跳转锚点(编辑器 obsidian/Zed 实测不支持,编号引用为纯文本);
  树/图导出格式;报告国际化。
