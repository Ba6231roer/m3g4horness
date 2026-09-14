# design — improve-mgh-sdr-report-structure

## Context

方案选型:三方案样例(`mgh-sdr-report-format-samples.md`)已由维护者拍板**方案 C**——
章节一简报表内联缩写链 + 仅带分支的单元画 mermaid。选型过程中的两个实证结论是本设计
的承重事实:

- **codegraph CLI 原始输出不能直接当报告调用链**:在复杂化后的 springBootTemplate 上
  实测(subagent 复杂化 + codegraph 1.4.1 查询),`callees/callers --json` 是扁平一跳
  邻接表(`{name, kind, filePath, startLine}`),无包路径、无链序、同名符号跨层合并无归
  属、接口/实现并列不消解、mapper XML 不在图中、无 transitive 闭包。任何「直接把 CLI
  输出贴进报告」的方案不成立。
- **但链不需要新查**:diff_group 分组期(`_build_units_callchain` / `_cg_edges`)已对
  每个变更符号跑过 callees/callers,原始边(含未变更端点)本来就在返回值里;当前只把
  「两端均在变更集内」的边用于建图,其余丢弃。链物化 = 复用已返回数据的一次确定性投影,
  零新增 codegraph 查询。

数据源现状(决定各字段从哪来):

| 报告字段 | 来源 | 现状 |
| --- | --- | --- |
| 入口(route) | grouping.json `units[].route` | 已有 |
| 调用链 | codegraph 边 + repo mapper XML 扫描 | 边已有,链与 XML 终端缺 |
| 前端接口/使用次数 | sdr_context 外部仓路由计数 | 计数在 hits.md 文本里,正则漏 `@RequestMapping`,未入 context.json |
| 6 维度问题 | fan-out drafts | 已有(`line_hint` 为 hunk 段,无单行 `line`) |
| 排序/单元形态 | grouping.json `units[]` | 已有(kind/route/unit_id) |

## Goals / Non-Goals

- **Goals**:报告可按接口归位问题(章节一矩阵)+ 问题详情统一编号(章节二)+ 分支链图形
  展开(章节三);链物化零新增查询;前端两列确定性可填;旧 draft/旧 grouping.json 兼容
  (缺字段降级,不硬失败)。
- **Non-Goals**:md 锚点跳转(obsidian/Zed 实测不支持——纯文本 `P-NN` 编号定位);链的
  拓扑导出格式;分组规则本身任何改动(排除集/锚定/合并/预算拆分不动);报告国际化;
  mapper XML 之外的 sink 补全(XML 是安全评审承重终端,其余 yml/properties 不入链)。

## Key Decisions

### D1 — 链物化放 diff_group(分组期),不放 render(渲染期)

链 = 分组期已获 codegraph 边的确定性投影。物化在 diff_group 的好处:① `_cg_edges` 的
edge cache 与 caller/callee 双向留存就地可用,零新增查询;② chain 属于分组产物语义(与
route/kind 同级),render 只做纯投影;③ `--check` 在产出点校验(承 R5.9),坏链不外溢。
standalone 单元 `chain[]` 恒 `[]`(它们无路由锚,链无从谈起;残余归并的文件级变更链骨架
不完整,写进报告反而误导)。

### D2 — 链节点带 repo 相对 file + 声明行 line,不依赖编辑器跳转

节点 schema `{fqn_short, label, file, line, change, route?}`。`file:line` 是给「想看源
码的人」的确定性索引(文件名 + 行号自查),不是 md 跳转。`fqn_short` 缩写规则 = 仅保留
类名/文件名:方法名(`com.linkinstars.springBootTemplate.controller.
OrderController.submit` → `OrderController.submit`);链内同类延续用 `·`(前一
节点宿主类相同)。缩写是**渲染期决策**,grouping.json 存完整值(`fqn_short` 字段名带
short,但存的是「短类名形态」的确定性值——完整包路径可由 file 列还原,不丢信息)。
首版规则是「包段首字母 + 类名」(`c.l.s.c.OrderController.submit`),真仓试用后仍过长
(单链 4 跳即 ~70 chars 且首字母段无信息量),收敛为仅类名;信息无损——`file` 列承载
完整包路径,消歧时读 file。

### D3 — 分叉用 branch_of 下标指回,不用树结构

链的分支(一方法调多下游)在节点序列上以 `branch_of`(指向宿主节点下标)表达。数组保
持「主链线性序 + 分叉指回」,渲染时:表格单元格展开为 `⤷` 平铺;mermaid 展开为真实图边。
不引入嵌套树的理由:grouping.json 是扁平数组消费者多(单测/stdout 分页),树结构让全部
消费者变复杂;下标指回足够表达 `⤷` 语义且 O(1) 可校验(`--check` 断言 branch_of 指向
合法下标)。注意:external mapper 终端节点也以 `branch_of` 挂宿主(dry-run 实证),故
「真实分支」判定(章节三画图门槛)须排除 external 节点,渲染器按
`branch_of 且 change != external` 判。

### D4 — mapper XML 终端 = namespace+id 确定性扫描,标 external

XML 不在 codegraph 图内(实测结论),dao 方法之后的 SQL 终端一跳用确定性规则补:扫 repo
`*.xml`,namespace = dao FQN ∧ statement id = dao 方法名 → 追加 `{fqn_short: <xml 文件
名>, label: <xml 文件名>:<id>, change: "external"}`。多 mapper 命中取文件名字典序第一
个(deterministic);未命中不追加(链止于 dao 方法)。`change: external` 与「未变更」
区分——mapper XML 大概率不在 diff 内,但它是链的承重终端(SQL 检查面锚点)。

### D5 — 前端两列 = route join route_hits,三态语义

sdr_context 已在外部仓做「新增路由出现计数」,三个缺口一次补齐:① 正则扩到
`@RequestMapping` 族(对齐 diff_group 的注解族,含类级 base route 拼接——springBootTemplate
全用 `@RequestMapping`,现行正则会漏计);② 计数物化进 context.json
`external_repos[].route_hits[]`(`{route, count}` 列表);③ render 按 route join。三态
语义:声明 ∧ 命中>0 = `是`+`N 处`;声明 ∧ 0 = `否`+`—`;无声明/不可达 = `未知`+`—`。
多路由合并单元显示主路由(分号分隔串的第一段)计数。

### D6 — 编号引用纯文本 P-NN,NEVER md 锚点

维护者实测 obsidian/Zed 均不支持 md 内嵌锚点跳转(`<a id=`/`{#...}`/`[t](#...)`)。简
报表维度列写 `是 [P-01]`,章节二标题 `### P-01 · ...`,纯文本编号定位。`--check` 断言
报告全文无锚点形态。

### D7 — draft 新增可选 `line` 字段,缺失降级

详述「位置」需要行号,现行 `line_hint` 是 hunk 行段(如 `88-102`)非单行。draft schema
加可选 `line`(int,问题锚定行):sdr-task.md 模板 + agent 定义双端同步;render 对缺
`line` 的旧 draft 降级为 `file`(不硬失败)。`line_hint` 保留(简报层聚合仍可能用)。

### D8 — 报告章节排序:简报 → 详述 → 分支图 → 无问题单元 → 诚实边界

章节顺序 = 使用顺序(先扫表、再看问题、需要时看图、最后放行参考与边界)。头部 + 分组概
览保留;诚实边界 ≥7 条保留(含排除集披露)。「问题清单(按维度)」旧结构整体替换,不保
留双轨。

## Risks / Trade-offs

- **[链忠实度] codegraph 同名符号歧义会入链** — 同名不同文件的同名方法无法消解时保留两
  者并标 `unchanged`,报告读者可从 file 列区分;缓解:链忠实反映分组期数据,不修饰;
  报告诚实边界第 ② 条已声明分组启发式。→ 接受。
- **[token] 大仓多单元时简报表很宽** — 每单元一行 × (入口+链+4 基础列+6 维度列),链列
  是主要 token 占用;缓解:链缩写(真仓试用后收敛为仅类名)+ `·` 同类延续把链列压到最短
  可行形态;暂不做列折
  叠(等真仓 401→数十单元后的实际体量数据)。
- **[兼容] 旧 draft 缺 line / 旧 grouping.json 缺 chain** — 均降级渲染(方法定义短形 /
  file 无行号),不硬失败;`--check` 对缺字段不 violation(增量字段语义)。→ 接受。
- **[行为] 报告结构变化是 breaking-ish 的人面变化** — 按维度的旧清单被替换;这正是本次
  变更目的,proposal 人话序已声明。→ 接受。

## Open Questions

(无——方案 C 已选型,数据源已实证,链物化放分组期与 branch_of 编码方式由设计定。)

## 干跑验收实证(5.2 回填,2026-09-07)

**环境**:springBootTemplate @ 分支 `sdr-dryrun`(16 文件复杂化已提交,5 种链形齐备;
codegraph 1.4.1 索引在)。run 目录 `.mgh-sdr/runs/dry1`(分组+渲染干跑,drafts 手工构造
4 个单元、context.json 手工构造 route_hits,**非真实安全分析**)。

**分组(diff_group)**:6 interface + 2 standalone,`chains_materialized=5`;
`codegraph_stats`:路由锚 4 / 向上锚定 2 / 链合并 1 / 捕获调用边 107 / 变更集内边 46。
两处真实缺陷在干跑中暴露并已修:① Added(A) 文件整文件搁浅(hunk 锚在 package 行,
不在任何方法体内)→ A 文件全部 hunk 归属全部符号;② hunk 首 `+` 行是方法间空行/注释时
锚在符号外 → `_hunk_anchor_candidates` 多候选 + `_owning_hunk_symbol` 首个落在符号内者胜。

**渲染(render_sdr_report)**:报告 `mgh-sdr-sdr-dryrun-*.md` 与方案 C 样例逐项核对:

| 核对项 | 结果 |
| --- | --- |
| 章节一表格形态 | 行=单元(排序/standalone 殿后/failed 不入行)、列=入口/链/前端两列/6 维度 ✓ |
| 链缩写 | `†`(向上锚定 entry,如 delete 链)· `⤷`(22 分支节点)· `⇢`(mapper 终端)· `→`/`·` ✓(干跑时为「包段首字母+类名」形态;其后真仓试用过长,规则已收敛为仅类名,见 5.3 前追加的 1.5) |
| 前端三态 | 是+5 处(/order/detail/{id})· 是+2 处(/order/submit)· 否+—(声明 0 命中:/cache/user/direct、/test)· 未知+—(未声明/无 route)✓ |
| 章节二详述 | P-01..P-05 全局编号、severity 升序、`file:line` 有 line / `file(hint)` 降级、control_ref ✓ |
| 章节三画图门槛 | 见下方偏差 ② |
| 无锚点 | `<a id=` / `{#` / `](#` 零命中 ✓ |

**干跑暴露的规格偏差(两处,已修并回写 spec/design)**:

1. **多路由单元前端 join**:实现初版按「任一分段命中取最大计数」→ `/order/batch(+1)`
   因次路由 `/order/submit` 命中 2 显示 `是`;spec/design(D5)均写**主路由**。已改实现
   为仅主路由(分号串第一段)join,补多路由回归用例;spec scenario 措辞收紧(次路由命中
   不抬升主路由状态)。
2. **「真实分支」画图门槛**:spec 括号写「`chain[]` 存在 `branch_of` 节点」,但 D3 编码下
   external mapper 终端也带 `branch_of` → 直连 dao 短链(cache_user_direct,线性+⇢)被
   误画图。spec 有效措辞是「带真实分支」+「线性链 SHALL NOT 入本节」+ 方案 C 样例(直连
   链在表内、无图)。已改实现为 `branch_of 且 change != external` 判,回归用例固化;
   spec 括号与 design D3 同步改写。

**门禁**:`render_sdr_report --check` + `diff_group --check` 均 ok;test_render 16 OK /
test_diff_group 37 OK(修后复跑)。

**5.3(真仓验收)未执行** —— 需另一环境重装后对真实业务仓跑完整 `/mgh-sdr`,本环境挂起待办。
