## Why

> **人话序** 现象:真仓首跑 /mgh-sdr 产生 **401 个评审单元**,按实测吞吐(~24–32 单元/百分钟)还要 9–10 小时才跑完;日志里 `AaaBbbController__xxx.slice.md`、`AaaBbbService.slice.md`、`AaaBbbServiceImpl.slice.md`、`AaaBbbServiceTest.slice.md`、各 Dto 全部各自成单元散落。根因(已对 `core/scripts/diff_group.py` 源码确认,三个叠加):① **没有排除集**——测试代码、构建产物、静态资源全部进入评审,其中 callchain 模式下 java 残余(含 `src/test/java`)**每个文件一个 standalone 单元**(`_build_units_callchain` 第 5 步),这是散落的直接来源;② **向上锚定缺失**——「controller 没动、只改 Service」是业务 diff 最常见形态,此时没有任何路由锚点,整条调用链散落;而 codegraph 其实已返回未变更 caller 边,只是被 `if e in adjacency` 直接丢弃;③ **接口粒度 per-route**——同 controller 改 10 个端点 = 10 个 subagent。改什么:diff 采集后加确定性排除过滤器(报告披露 + `--include-excluded` 兜底)、用已有调用边向上锚定 ≤2 跳找路由方法、同 controller 共享链合并、java 残余回归目录聚簇、stdout 增加分组统计(`codegraph_stats`)让「codegraph 是否生效」可观测。怎么验证:单测覆盖各排除/锚定/合并形态 + 真仓重跑单元数对比(401 → 预期数十量级)。

- **问题**:slice 经济性 = 单元数爆炸,直接乘在「每个单元一个 subagent × 6 维度 × 慢 LLM」上;且 `codegraph:true` 只报模式开关,真仓无法诊断调用链分组实际捕获率。
- **为何现在**:callchain 分组(`2026-09-03-improve-mgh-sdr-callchain-grouping`)刚落地并在真仓首跑,实测暴露上述结构性缺口,趁用户评审窗口修复。

## What Changes

- **diff 排除过滤器**(新增,确定性、分组前置):`diff_group.py` 在分组前排除闭集文件——`src/test|test|**/test/**` 测试树、`*Test.java`/`*Tests.java`/`*IT.java` 命名、`target/`/`build/`/`out/`/`dist/` 构建产物、`generated/`/`**/generated-sources/**`、静态资源扩展(`.png/.jpg/.gif/.ico/.woff/.woff2/.ttf/.eot/.svg/.min.js/.min.css/.map` 等)、锁文件与构建脚本(`package-lock.json/yarn.lock/pom.xml/build.gradle*/settings.gradle*/mvnw*`)。**保留**:SQL/`*Mapper.xml`/`application*.yml` 等配置(六维度检查面,且本就目录聚簇、便宜)。排除不静默:stdout `excluded{count, by_reason}` + 报告诚实边界披露排除清单与计数;`--include-excluded` 兜底开关恢复旧全量行为。
- **向上锚定(unchanged-route anchoring)**:对未被任何变更路由覆盖的变更符号,复用**已返回但被丢弃的** callers 边向上走 ≤2 跳,找到(含未变更的)controller 路由方法 → 整条链并入该路由的 interface 单元;slice 附路由方法源码片段(有界)作上下文。codegraph 查询次数零新增。
- **共享链合并**:同一 controller 文件内、下游变更符号可达集相同的多个变更 route 合并为一个 interface 单元(route 字段承载全部路由串),下游不同的保持拆分。
- **java 残余回归目录聚簇**:callchain 模式下锚定/闭包后仍未归属的 java 残余文件,从「每文件一单元」改为与非 java 残余相同的目录聚簇 + `--max-standalone-bytes` 预算(有实测依据的回退,覆盖 callchain change 的「拆多个不硬塞」粒度决策)。
- **接口单元字节预算**:interface 单元 slice 新增上限(默认 256KB,`--max-interface-bytes`),超限确定性拆为 route 续单元(`(part N)` 后缀),防止合并后单 slice 撑爆 subagent 上下文。
- **分组可观测**:`diff_group.py` stdout/grouping.json 新增 `codegraph_stats{symbols_queried, edges_captured, edges_in_changed_set, anchors_changed, anchors_upstream, units_interface, units_standalone, excluded_files}` + stderr 摘要行;`render_sdr_report.py` 把单元数/排除计数/codegraph 捕获率写进报告诚实边界。

## Capabilities

### New Capabilities

(无——全部为既有 `security-design-review` capability 的需求级行为变化)

### Modified Capabilities

- `security-design-review`:「确定性 diff 采集与接口维度分组」需求新增——排除过滤器闭集 + 披露/兜底、向上锚定、共享链合并、java 残余聚簇、接口单元预算、`codegraph_stats` 可观测字段;「统一问题记录汇总与确定性报告渲染」需求新增——报告诚实边界披露排除清单/计数与分组统计。

## Impact

- **代码**:`core/scripts/diff_group.py`(排除/锚定/合并/聚簇/预算/统计,CLI 新增 `--include-excluded`/`--max-interface-bytes`)、`core/scripts/render_sdr_report.py`(诚实边界 + manifest 计数)、`core/scripts/mgh_sdr_launch.py`(透传新 flag,可选)、双壳 `releases/{claude-code/commands,opencode/command}/mgh-sdr.md`(flag 表 + 纪律段)、`core/prompts/fragments/fanout/sdr-task.md`(上游锚定 slice 的上下文段说明)。
- **契约**:`pending[]` 字段 shape 不变(route 可含多路由串);stdout 新增字段为纯增量;`--check` 同步校验新字段。
- **测试**:`tests/test_diff_group.py` 新增排除/锚定/合并/聚簇/预算/统计形态用例;R5.1 `tools/check_contracts.py` 同步新 flag。
- **风险**:排除集误伤(闭集 + 报告披露 + `--include-excluded` 兜底);向上锚定把大链并进单 slice(接口预算 + 续单元拆分兜住)。
- **非目标**:不改 fan-out 派发/波次状态机/render 去重;不引入 tree-sitter;codegraph 仍为可选输入(缺省退化行为不变)。
