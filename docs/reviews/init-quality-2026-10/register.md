# mgh-init 产出质量评审 · 缺陷登记册

> **受众:人类 + agent(双受众)**。本登记册是评审战役的集中台账:每条带问题描述、
> 根因分类(A 模型能力边界 / B 提示词与契约设计 / C 输入切片与信息保真 / D 校验硬度
> 缺口 / E 确定性脚本缺陷)、证据等级([S] 静态推断 / [L] 本机实证 / [E] 企业实证)、
> 状态。评审会话只往里加和核实;修复提案从本册取([L]/[E] 优先)。
> 计划与纪律见
> [评审计划](../../mgh-init-output-quality-review-plan-2026-10-22.md) 与
> [交接文档](../../mgh-init-output-quality-review-handoff-2026-10-22.md)。

| # | 日期 | 阶段 | 问题(自包含描述) | 等级 | 根因类 | 来源锚点 | 状态 | 处置 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-10-21 | T1(pack) | 打包形态的真实会话中,2/11 的 pack 会话违反共享任务模板,额外写了「包级账本 JSON」文件(模板至今无明示禁令;下游把它当垃圾产物) | [E] | B | `openspec/changes/archive/2026-10-21-fix-mgh-init-native-aggregate-dispatch/real-machine-notes.md` §2;模板 `core/prompts/fragments/fanout/t1-task.md` | 未修 | 可提前立项:模板补一条禁令 + 闸门豁免 |
| 2 | 2026-10-21 | T1→T2 闸门 | `validate_t1_records.py` 用 `*.json` 通配收集记录文件,把 #1 的包级账本误读为记录,产生 13 个假违例(退出码 2,误伤外科重派) | [E] | E | 同上;`core/scripts/validate_t1_records.py`(glob 收集处) | 未修 | 可提前立项:收集面排除账本形状或按命名豁免 |
| 3 | 存量 | T3/assemble | 纯净 lint 只覆盖高精度形状(工具内部 token/schema 字段/特征散文);裸通用词、裸层级词、通用脚本名的泄漏非确定性可测,仅提示词护栏 | [S] | D | 根 `AGENTS.md` 诚实边界 | 已披露未修 | C8 评审「终门扩容候选」时一并核 |
| 4 | 存量 | scout-merge | 超字节预算分片时,`evidence_snippet` 等人读字段被确定性截断(锚点不截,`_slimmed` 留痕);摘要可能丢失 competing 成员信息 | [S] | C | 根 `AGENTS.md` 诚实边界;`core/scripts/plan_aggregate.py` 瘦身段 | 已披露未修 | C3 核对留痕如实性与摘要丢失面 |
| 5 | 存量 | scout-merge/T2 | 任一分片失败不 rollup → 候选/控制缺口只在 report.md 披露;终产物消费者(agent)看不到「少了什么」 | [S] | C | 根 `AGENTS.md` 诚实边界 | 已披露未修 | C9「缺口披露链」主题;终门扩容候选(向消费者披露) |
| 6 | 存量 | 消费面 | opencode 面索引块是语义性按需加载:消费 agent 跳过对应 Read 就漏用已有控制(claude 面 `paths:` 是确定性触发,无此问题) | [S] | B | 根 `AGENTS.md` 诚实边界 | 已披露未修 | C9 消费者匹配主题 |
| 7 | 2026-10-13 | T3 | opencode 安装面 agent 权限 `edit: deny` 是否会拦住规则写作孪生的产物落盘,未经 live 验证(若拦,规则根本写不出来) | [S] | D | 2026-10-13 战役交接文档 拍板项 A | 待验证 | C6 动态腿顺带验证(跑一次即知) |

## 增补区(评审会话追加于此线以下)

<!-- 格式同上表;每行一个发现;[S] 项标注「待动态验证」;5why 记录写进对应评审卡文件,这里只落结论。 -->
