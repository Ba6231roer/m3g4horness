# design — harden-mgh-init-output-gates

> 三个闸门共用一个前提:所有校验都是**零大模型调用的确定性检查**,部署在既有 R5.9 边界
> 上,失败形态走既有"编排器回退重跑"路径,不新增流程步骤。

## D1 闸门落位(为什么是这三处)

| 闸门 | 落位 | 理由 |
| --- | --- | --- |
| 证据存在性 | `validate_inventory.py`(T2 边界) | 该脚本已是 inventory 的 R5.9 边界;锚点在 T2 汇聚成唯一权威清单,在此校验一次即覆盖 T1 全部上游 |
| 覆盖对账 | `assemble_rules.py --check`(装配边界) | 装配是"规则文件 ←→ inventory"两个输入都在手的唯一节点;且已有 lint 违例 → 回 T3 的既有回退路径可复用,零新增编排逻辑 |
| marker↔记录 | 枚举器 + `resume_state --check` | 枚举器是 pending 的单一真相源:判回 pending 即自然重派,无需新机制;resume --check 提供自检面 |

不选的落位:T1 闸门(`validate_t1_records`)不加存在性——T1 记录的 evidence 会汇聚进
inventory,在 T2 边界校验一次等价且少一处实现;不在 T3 提示词里加对账要求——对账是
确定性工作,下沉脚本(根因类 D,不是 B)。

## D2 锚点解析共享小模块(单一真源)

新增 `core/scripts/anchor_resolve.py`(纯标准库、自包含、兄弟导入):token 三形态解析
(`path:line` / `path::sym` / `path:sym`)、解析阶梯(exact → case → 唯一 basename)、
行数与符号子串校验、归一化文本匹配(供覆盖对账用)。`validate_inventory` 与
`assemble_rules` 导入同一实现,NEVER 各写一份(防语义漂移)。basename 索引按需惰性构建
(首次 miss 才全仓 walk 一次),大仓成本可接受(实测 ~1.7 万文件量级秒级)。

选择"唯一文件名命中算过"的边界:真实仓实测证据路径存在"无目录前缀/前缀形态不一致"
的写法,直接判 fail 会把形态问题误报成造假;唯一命中算过 + `by_basename` 计数,既不
误伤又让形态占比可见(部署首跑自动回答"1065 个解析失败里形态 vs 造假各占多少")。

## D3 覆盖对账的严格性与逃生门

默认 fail-loud(不写盘、退出码 2、按 category 计数 + 首 N 名单),编排器走既有 lint 违例
回 T3 的路径(同形复用,壳零改动)。但弱模型一次重修 646 条缺口不现实,故提供
`--accept-coverage-gaps` 显式放宽:对账照跑、披露行照写、缺口落台账——**放宽的是写盘,
不是可见性**。编排器 fragment(t3/done)补一句指引:首轮对账失败 → T3 受影响类别重派
一轮;仍失败 → assemble 带 flag 收口(缺口如实披露)。这条"至多一轮修 + 显式接受"
与既有失败重派纪律同形。

匹配语义定为"证据路径整串或文件名出现在类别文件文本中"(归一化大小写与斜杠),不要求
控制名出现——控制名是模型起的,文件路径/锚点才是可机械对账的硬键。

## D4 marker↔记录的豁免闭集(防误报)

豁免恰为实测确认的三类 marker-only 设计单元:`pack__` 前缀(pack 派发标记,`init_tier`
既有孤儿审计同款豁免)、t3(规则文件即产物,装配 lint 收口)、t2 终结标记(artifact 是
inventory)。其余"记录 + .done"单元(scout 批、t1 簇/成员、t2 分片、t4)全部纳入。
重派认领时删旧 `.done` 与失败重派删 `.failed` 同形(标记真相源不变量不变——枚举器删除,
非编排器手删)。枚举器顺带对 checkpoint 目录里的**未知文件**(非记录/非标记/非豁免形态)
输出告警计数(不失败)——自发账本类残留(如设计外的 pack_manifests 目录)从此可见。

## D5 合法 JSON 校验通道(给守卫的一个白名单口,不是开口子)

任务模板指令:写入 checkpoint 后 `py -m json.tool <路径>`(只读、stdout 丢弃)。守卫面
预期**零改动**:`py <脚本> <参数>` 形态本就放行,`-m json.tool` 是模块形态,apply 期先以
`test_block_adhoc_scripts` 加一用例核实;若现行动词表确实拦 `-m`,则仅在解释器规则加
"模块白名单 = `json.tool` 且参数为子树内单一路径"的窄口(判定仍在守卫单一真源)。
不放开 `-c`、不放开其它模块、无写面——与"微脚本内省禁令"不冲突:禁令防的是**内省/重
派生**,`json.tool` 是**只读语法校验**,正是该禁令想要的替代品。

## D6 模板改动与预算

五个 task 模板各 +2–3 行(校验指令 + 失败处置),t1-task Form B +1 行禁账本。预算影响
微小(单模板 <80 token),`check_distributed_prompt_budget` 复核;措辞走 recipe 形态
("写入后 MUST 校验,失败即单元失败"),不用 prohibition 堆叠。静态锚进
`test_init_native_dispatch` 既有锚面(删行即红),与"共享任务模板零改动"的既有断言冲突
处按本 change 语义更新断言。

## D7 披露行形态(opencode 受管块)

`<!-- security-controls:begin -->` 块尾追加一行:`- 覆盖:45/691 控制已入规则(未入规则
清单见 .mgh-init/report.md)`——消费 agent 一眼看到覆盖与缺口去向;幂等重写(整行替换,
不重复追加);claude 面不涉及(无索引块),缺口仅落报告。报告/台账新增
`coverage` 小节:按 category 的 covered/missing 计数与(放宽时)接受标记。

## D8 明确不做(与登记册待办的对齐)

守卫 heredoc 误伤修复(维护者另立任务);evidence_snippet 引文一致性(当前 inventory
证据为纯字符串无片段,无数据可查);checkpoint 带 schema 工具提交(真实管线 ~1800 个
JSON 零坏,恐惧未兑现,降级);扫描面扩声明式配置(比例未量化,条件项)。
