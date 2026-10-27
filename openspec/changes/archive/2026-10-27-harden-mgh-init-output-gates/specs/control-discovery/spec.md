## ADDED Requirements

### Requirement: 证据锚点存在性门(T2 边界)

`validate_inventory.py` 在既有形状校验(字段/枚举/evidence 非空)之外,SHALL 对
`controls_inventory.json` 每条控制的每个 evidence token 做存在性校验,任一违规即退出码 2
(NEVER 宽松放行、NEVER 自动改写 token)。token 按 closed 集三形态解析:

- `path:line`(行锚):文件存在且行号在文件行数范围内;
- `path::类.方法` 与 `path:类.方法`(符号锚):文件存在,且类名与方法名(符号段逐段)在
  文件文本中出现。

文件解析 SHALL 按确定性阶梯:仓库根相对精确命中 → 同目录大小写不敏感命中 → **全仓唯一
文件名命中**(命中即算过;路径形态差异不算违规)。解析不到文件记 `file_missing`;行号越界
记 `line_out_of_range`;符号段缺席记 `symbol_absent`。stdout SHALL 输出分类计数
(`anchors_total/ok/file_missing/line_out_of_range/symbol_absent/by_basename`),stderr
SHALL 列每类首 N(默认 5)个违规 token 示例与所属控制名,供编排器回改。锚点解析逻辑
SHALL 单一真源(共享小模块),装配边界的规则文件锚点校验复用同一实现。

#### Scenario: 证据全部可解析

inventory 每条控制的 evidence 分别为 `src/a/Foo.java:12`、`src/a/Foo.java::Foo.bar`、
`src/a/Foo.java:Foo.bar` 且文件、行号、符号均在场 → 退出码 0,stdout 计数
`anchors_total=3 ok=3`,其余分类为 0。

#### Scenario: 文件不存在

某控制 evidence 为 `src/missing/Bar.java:3`,仓库中无此文件且文件名 `Bar.java` 非唯一
命中 → 退出码 2,stdout `file_missing>=1`,stderr 含该 token 与控制名。

#### Scenario: 符号漂移

evidence 为 `src/a/Foo.java::Foo.nope`,文件与类在场、方法 `nope` 不在文件文本中 →
退出码 2,stdout `symbol_absent>=1`。

#### Scenario: 唯一文件名回退不算违规

evidence 写成 `Foo.java:Foo.bar`(无目录前缀),全仓仅 `src/a/Foo.java` 一个同名文件 →
按 `by_basename` 计数并通过;仅当同名文件不唯一或不存在时才记违规。

### Requirement: done 标记必须配套记录文件(marker↔记录对账)

对以"记录文件 + `.done` 标记"为终态单元的 tier(scout 批、t1 簇/成员、t2 分片、t4),
记录文件缺席 SHALL 使该单元**不构成终态**:枚举器(`list_scout_batches.py`/
`list_clusters.py`)SHALL 把"`.done` 在而记录文件缺席"的单元重新列入 `pending[]`(随附
`marker_without_record` 计数字段,原因短码 `no_record`),编排器据此自然重派;
`resume_state.py --check` SHALL 把此类记为不自洽违例(退出码 2 + 计数)。按设计
marker-only 的单元 SHALL 豁免且 NEVER 误报:pack 派发标记(`pack__` 前缀)、t3 规则产物
单元(规则文件即产物,装配 lint 收口)、t2 终结标记(artifact 为 inventory)。重派后
旧 `.done` 标记 SHALL 由枚举器声明为待清理(重派认领时删除,与失败重派同形)。

#### Scenario: scout 批标记在而记录缺

`checkpoints/scout/scout-338.json.done` 存在、`scout-338.json` 缺席 → `list_scout_batches`
stdout `pending[]` 含该批且 `marker_without_record=1`;重派认领时删除旧标记。

#### Scenario: resume 自检报违例

同上状态跑 `resume_state --check` → 退出码 2,输出含 `marker_without_record` 计数与
recipe(重派该单元即可自愈)。

#### Scenario: pack 标记不误报

`checkpoints/t1/pack__input-validation__<sha8>.json.done` 无对应记录文件 → 不计入违例
(pack 派发单元按设计 marker-only)。

#### Scenario: t3 规则单元不在辖域

t3 仅有 `done` 标记而无 checkpoint 记录(规则文件即产物)→ 不计入违例。

### Requirement: tier 任务模板的合法 JSON 校验通道与禁自发账本

五个 tier 任务模板(`scout-task`/`t1-task`/`t2-task`/`scout-merge-task`/`t3-task`)SHALL
各含一条指令:写入 checkpoint 后 MUST 以 `py -m json.tool <checkpoint_path>`(stdout 丢弃)
做只读语法校验;校验失败 SHALL 按该单元失败处理(failed ack / `.failed` 标记),NEVER
摸 `.done`、NEVER 为通过校验改写记录内容。运行域守卫的解释器面 SHALL 放行该只读形态
(`py -m json.tool <子树内路径>`,无 `-c`/无写面);若现状已放行则守卫零改动,apply 期
以守卫单测核实。`t1-task` Form B SHALL 明文:包会话 NEVER 写任何包级账本/清单/manifest
文件——只写任务给定的成员 checkpoint 与标记路径。

#### Scenario: 模板指令在场

五个任务模板各含 `json.tool` 校验指令行与"校验失败即单元失败"的处置句;静态锚测试钉住
(删任一行即红)。

#### Scenario: 只读校验不被守卫拦截

运行域内执行 `py -m json.tool <target>/.mgh-init/checkpoints/t1/<记录>.json` → 守卫放行
(退出码由语法决定);同形态带 `-c` 仍被拦。

#### Scenario: 校验失败按单元失败

子代理写入语法坏 JSON、`json.tool` 退出码非 0 → 该单元产 `.failed`(或 failed ack),
无 `.done`;编排器按既有失败重派路径处理。

#### Scenario: 禁自发账本

t1-task Form B 含"NEVER 写包级账本/清单文件"明文;静态锚测试钉住;真实 run 的
checkpoints 下不再出现设计外记账目录(以回归测试对枚举器"未知文件告警"断言收口)。
