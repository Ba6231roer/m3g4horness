## ADDED Requirements

### Requirement: get_discipline 返回防御性深拷贝(共享纪律表不可被消费方污染)

`core/scripts/discipline_core.py` 的 `get_discipline(step, domain)` SHALL 返回纪律子集的**深拷贝**
(`{gates[], path_recipes[], nevers[]}` 全层复制),SHALL NOT 返回模块级共享表的内部引用(含
`dict(_EMPTY)` 浅拷贝形态——嵌套列表仍是共享引用)。消费方(`resume_state.py` 的
`discipline_reminders`、`list_steps.py` 的 `discipline`)对返回值做任何 append/修改 SHALL NOT
影响后续任何调用、任何域的输出——一次消费方污染(如对 `gates` append 一项)在修复前会**永久**
变更跨域共享表,污染此后所有 run 的 stdout 纪律面。两脚本同 step 输出逐字一致的单源不变量不受
影响(深拷贝保持值相等);调用频次(每 resume/list_steps 调用一次)下的拷贝成本可忽略。

#### Scenario: 消费方修改返回值不污染共享表

- **WHEN** 调用 `get_discipline("t1")` 得到子集,对其 `gates` 执行 `append(...)` 后再次调用
  `get_discipline("t1")`(以及 `get_discipline("t1", domain="sdr")` 等其它域/步)
- **THEN** 后续调用返回的子集与首次调用值相等(共享表未被污染);模块级表常量逐字不变

#### Scenario: 双脚本输出一致性不受深拷贝影响

- **WHEN** 对同一磁盘状态分别调用 `resume_state.py` 与 `list_steps.py --step t1`
- **THEN** `discipline_reminders[]` 与 `discipline` 仍逐字一致(既有单源不变量保持)
