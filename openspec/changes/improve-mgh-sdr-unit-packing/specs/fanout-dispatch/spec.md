# fanout-dispatch Delta

## ADDED Requirements

### Requirement: 派发单元可打包形态的契约不变量

「包」(pack)SHALL 是一种**可被任意 tier 采用的派发单位形态**:枚举脚本把一个或多个成员单元
合并为一个派发条目,dispatcher 把该条目当作**一个普通单元**派发。派发器 SHALL NOT 获得任何
打包感知——它仍只消费 tier 映射表里 `id_field` 指定的标识字段、`path_fields` 指定的路径字段与
该 tier 的固定占位符集。包条目 SHALL 以**复用既有标识字段槽位**的方式表达:包标识载在该标识
字段里,SHALL NOT 新增占位符、SHALL NOT 新增 tier 专属字段映射、SHALL NOT 改 ack 状态机。

包标识 SHALL 由**成员集合内容**确定性派生(成员标识集合排序后的哈希),SHALL NOT 由枚举顺序、
分页位置或任何运行时时序派生——否则上游重排或分页会让包标识漂移、破坏重派同一性(同一批成员
在两次运行里被认成两个不同的派发单元)。

成员级 `.done`/`.failed` marker SHALL 是该包的**恢复粒度与唯一真相来源**;包级 `.done`/
`.failed` 回执仅表示**包级终态**,SHALL NOT 被任何恢复逻辑或步骤派生逻辑当作单元级进度计数。
包级 marker SHALL 落在不与成员 marker 共享枚举面的路径上。

打包关闭时,枚举脚本 stdout SHALL 与无此机制时**逐字节一致**,且 SHALL NOT 出现任何包专属字段。

包级 `.failed` SHALL 为终态、SHALL NOT 触发自动重派;其人工恢复指引 SHALL 随命令面的纪律表
发布(删包级失败回执 → 重新枚举 → 成员级 marker 使已完成成员不重跑)。

#### Scenario: 包标识对枚举顺序不变

- **WHEN** 同一批成员单元以两种不同的枚举顺序各跑一次打包枚举
- **THEN** 两次产出同一组包标识与同一成员归属,逐成员的派发身份一致

#### Scenario: 派发器对包条目零感知

- **WHEN** 枚举脚本产出的 pending 条目中,某条目的标识字段载的是包标识而非成员标识
- **THEN** dispatcher 照常 spawn 一个 subagent、逐字填充该 tier 的既有占位符集、按 ack 状态机
  写包级 marker;该 tier 的字段映射表、占位符集、ack 状态机与其它 tier 零改动

#### Scenario: 关闭打包时枚举输出逐字节不变

- **WHEN** 以打包开关的默认关取值运行枚举脚本,并与本机制引入前的同输入输出对照
- **THEN** stdout 与落盘清单逐字节一致,输出中不出现成员清单与任何包专属计数字段

#### Scenario: 包级终态不污染单元级进度

- **WHEN** 某包级 `.failed` 回执存在,而其成员 marker 只有部分就位
- **THEN** 恢复逻辑与步骤派生按成员 marker 判定进度(该包仍被判为未完成),包级回执仅作为包级
  终态呈现,不被计入单元级 `done`/`failed` 计数

#### Scenario: 包级失败不自动重派

- **WHEN** 某单元的 ack 为 `failed <原因>`,dispatcher 据此写下包级 `.failed`
- **THEN** 该包不再进入重派队列;命令面纪律表给出的恢复指引为「删除包级失败回执 → 重新枚举 →
  仅缺失成员重跑」,已完成成员因成员级 marker 就位而不重跑
