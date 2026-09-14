## 1. diff_group 链物化

- [x] 1.1 `core/scripts/diff_group.py`:`_build_units_callchain` 新增链物化——分组期保留每变更符号的原始 callees 边(现仅消费变更集内子集;未变更下游边此前被 `if e in adjacency` 丢弃),对每个 interface 单元沿路由方法确定性投影 `chain[]` 节点序列(`{fqn_short, label, file, line, change, route?}`;fqn_short = 包段首字母 + 完整类名:方法名;接口→实现消解;branch_of 下标指回表达分叉;路由节点含 route 串、向上锚定入口标 `change:"unchanged"`);grouping.json `units[]` 项写入 `chain[]`,standalone 恒 `[]`;codegraph off 时全单元 `chain[] == []`(结构恒在)
- [x] 1.2 mapper XML 终端补全:确定性扫描 repo `*.xml`(namespace = dao FQN ∧ statement id = dao 方法名),命中追加 `{fqn_short: <xml 文件名>, label: <文件名>:<id>, change:"external"}` 节点(branch_of 指回 dao 节点);多命中取文件名字典序第一;未命中不追加
- [x] 1.3 `--check` 扩展:`chain[]` 结构校验(节点必填字段、`branch_of` 指向合法下标);缺 `chain` 字段的旧 grouping.json 不 violation(增量字段)
- [x] 1.4 `tests/test_diff_group.py` 新增用例:线性深链 4 节点 + mapper 终端、fqn_short 缩写形态、接口/实现消解(实现优先)、branch_of 分叉形态、向上锚定入口 unchanged 节点、mapper 无命中不追加、codegraph off 时 chain 全空、旧 grouping.json 无 chain 字段 `--check` 通过
- [x] 1.5 fqn_short 规则收敛为仅类名(真仓试用反馈:`c.l.s.c.OrderController.submit` 形态仍过长):`diff_group.py::_fqn_short` 去掉包段首字母段(仅保留类名/文件名:方法名;`label` 语义不变),同步更新 1.4 用例断言与 `tests/test_render_sdr_report.py` fixture 中 `c.l.s.c.*` 形态值;`--check`/消解/mapper 终端逻辑零改动

## 2. sdr_context 前端计数物化

- [x] 2.1 `core/scripts/sdr_context.py`:`_new_routes` 正则从 `@(Get|Post|Put|Delete|Patch)Mapping` 扩到 `@RequestMapping` 族(与 diff_group 路由注解族对齐),含类级 base route 平凡拼接(与 diff_group `_base_route` 同规则)
- [x] 2.2 `_external_retrieve` 新增:逐路由计数物化进 context.json `external_repos[].route_hits[]`(`{route, count}` 列表;hits.md 文本保留);stdout `external_repos[]` 项同步携带
- [x] 2.3 `--check` 扩展:context.json `route_hits[]` 存在时校验 `{route, count}` 列表形态
- [x] 2.4 `tests/test_sdr_context.py`(新建或并入现有):`@RequestMapping` 族路由计数、类级 base route 拼接、route_hits 形态、无外部仓时 external_repos 空

## 3. render_sdr_report 报告结构重写(D8)

- [x] 3.1 `core/scripts/render_sdr_report.py`:章节一「简报表」——行 = 单元(grouping.json `units[]` 排序:interface 按 route 升序、standalone 殿后按 unit_id),列 = 入口/调用链/是否前端接口/前端使用次数/6 维度;链渲染(chain[] → 缩写链文本:`·` 同类延续、`⤷` branch_of、`⇢` mapper 终端、`†` unchanged);前端两列按 route join `route_hits[]`(三态:是+N 处/否+—/未知+—);维度列 `否` 或 `是 [P-NN]` 纯文本
- [x] 3.2 章节二「问题详述」——P-NN 全局编号,`### P-NN · <维度标签> · <route> · <severity>`,正文 位置(file:line 或降级 file)/风险/建议/control_ref;排序 severity 升序、同 severity 按 P-NN
- [x] 3.3 章节三「分支调用链图」——仅 branch_of 单元,每单元一张 mermaid `flowchart LR`(入口→逐节点→mapper 虚线边);线性单元不画
- [x] 3.4 头部 + 分组概览 + 无问题单元 + 诚实边界(≥7 条)保留;「按维度问题清单」旧结构删除,不双轨
- [x] 3.5 manifest 新增 `rows[]`(简报表逐行投影:`{unit_id, entry, chain, frontend_is, frontend_count, issue_refs[]}`);`--check` 断言 rows 长度 = 表格行数、无锚点形态(全文无 `<a id=`/`{#`/`](#`)
- [x] 3.6 `tests/test_render_sdr_report.py`:新报告结构端到端(造 grouping.json 带 chain + context.json 带 route_hits + drafts 带 line)——表格行列/排序/前端三态/P-NN 编号与去重共享/mermaid 仅分支单元/draft 缺 line 降级/rows 投影一致性/无锚点断言;旧用例(去重合并/failed 单元/排除披露)更新到新结构

## 4. 契约与壳同步

- [x] 4.1 `core/prompts/fragments/fanout/sdr-task.md`:draft schema 加可选 `line`(int,问题锚定行号)+ `line_hint` 保留说明;`releases/{claude-code/agents,opencode/agent}/sdr-review-fanout.md` 镜像同步
- [x] 4.2 双壳 `releases/{claude-code/commands,opencode/command}/mgh-sdr.md`:报告结构描述(简报表/详述/分支图)与前端两列数据源各 1–2 行更新(R5.6 预算内)
- [x] 4.3 `tools/check_contracts.py`:RENDER_SDR/DIFF_GROUP 契约面复核(无新 CLI flag 则仅确认无漂移);`py tools/check_contracts.py` + `py tools/check_distributed_purity.py` 通过
- [x] 4.4 版本号 bump + `CHANGELOG.md` 条目(承 R5.8)

## 5. 验收

- [x] 5.1 全量回归:`py tests/test_diff_group.py` + `py tests/test_render_sdr_report.py` + `py tests/test_sdr_context.py` + `py tests/test_deterministic.py` + 契约/purity lint 全过;旧断言非回归(1.5 收敛后再复跑一轮)
- [x] 5.2 springBootTemplate 干跑验收(格式样例兑现):对已复杂化的 springBootTemplate(5 种链形齐备:4 跳深链/双分支 fork/无路由独立链/直连 dao 短链/3 分支大方法;codegraph 索引在)做只分组+渲染的干跑(手工构造 drafts,不跑安全分析),产示例报告核对——章节一表格形态与已选型样例(方案 C)一致、链缩写/⤷/⇢/† 正确、前端三态正确(构造外部仓 route_hits)、章节三仅分支单元有图;结果回填本 change 报告节
- [ ] 5.3 真仓验收(另一环境):重装后对真实业务仓跑完整 `/mgh-sdr`,核对简报表行数 = 单元数、链忠实度抽查(抽 2 条链对源码核实节点/顺序/分支)、前端两列与 sdr_context 计数一致、报告 token 体量可接受;结果回填本 change 报告节
