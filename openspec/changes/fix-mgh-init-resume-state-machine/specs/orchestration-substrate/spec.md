## MODIFIED Requirements

### Requirement: resume_state.py stdout 携带当前步 stage_flow_files[]

`core/scripts/resume_state.py` 的 stdout(既有 7 字段基座 `{target, format, step, resumable, tiers,
next_action, notes}` + `discipline_reminders[]`)SHALL 增 `stage_flow_files[]` 字段——值 = **当前 step 的
单个** `init-stage/<step>.md` 绝对路径(`Path.resolve()`,Windows 原生),为**增量字段**(不改变既有字段
形状/语义)。当前 step 为 `not-started`(bootstrap 由壳 fresh-run recipe **fixed-path Read**
`<mgh-core>/prompts/fragments/init-stage/bootstrap.md` 加载、非 resume 循环)时 SHALL 为空数组 `[]`;
**`done` 步 SHALL 返回 `init-stage/done.md` 的绝对路径**(收尾纪律:manifest 收尾 + 失败/scout_merged
落账 + 收尾移除哨兵 `.active`——长跑压缩后恢复到收尾态时经既有「Read stage_flow_files[0]」壳配方
可达,不再失联;此前的「done 无后续加载」排除使该纪律仅在 fresh-run 起点可达)。**非
all-remaining**(只给当前步,不给 step 0、不给全部剩余步)。该字段是 **resume 衍生量、非持久态**:
值纯从 `<target>/.mgh-init/` 产物 + `run_config.json` 派生的 step 推断,不写入任何磁盘文件;
`--check`(R5.9)不涉及该字段。路径 `Path.resolve()` 绝对、逐字透传给编排器
(承 R5.3(b) fan-out 路径契约;对 subagent 任意 cwd 安全,含 Windows 盘符相对)。

#### Scenario: resume 输出当前步单文件绝对路径

- **WHEN** 编排器对处于 t1 步的 run 调用 `resume_state.py --target <t>`
- **THEN** stdout 含 `step: "t1"` 且 `stage_flow_files[]` = `["<abs>/prompts/fragments/init-stage/t1.md"]`
  (单个绝对路径,`Path.resolve()` 归一);编排器逐字透传给后续 `Read`

#### Scenario: not-started 返回空数组,done 返回 done.md

- **WHEN** run 未开始(`not-started`)或已到收尾态(`done`,含 manifest 尚未写的 finalize 分支)
- **THEN** `not-started` 时 `stage_flow_files[]` 为空数组 `[]`(bootstrap 由壳 fresh-run recipe
  fixed-path Read 加载);`done` 时 `stage_flow_files[]` = `["<abs>/prompts/fragments/init-stage/done.md"]`;
  stdout 仍恒含该字段(shape 稳定)

#### Scenario: 只含当前步,非 all-remaining

- **WHEN** 当前步 `t1`,审阅 `stage_flow_files[]`
- **THEN** 数组只含 `t1.md` 一个条目,不含 `t2`/`t3`/`assemble`/`t4` 等后续步 fragment(非 all-remaining,
  非 step 0)

#### Scenario: 值派生自磁盘 step 推断,不持久化

- **WHEN** 对同一磁盘状态的 run 连续两次调用 `resume_state.py`
- **THEN** `stage_flow_files[]` 两次逐字一致(同一步 → 同一文件路径);`stage_flow_files[]` 未写入
  `.mgh-init/` 任何文件

## ADDED Requirements

### Requirement: Step→IO 契约表与 list_steps 实现同步

`core/contracts/init/step-manifest.md` 的 Step→IO 表 SHALL 与 `list_steps.py` 的静态 step 表实现
事实保持同步:扇出步(scout/t1/t3)的 `script` SHALL 记 `fanout_runner.py`(dispatcher-first 架构,
枚举器脚本经 runner tier 配置调用,非编排器直调)、`t2` SHALL 记 bash 派发(`fanout_runner.py --tier
t2` 为超预算 map 段的确定性驱动)、scout 步 SHALL 载 `extra_invocations`(scout-merge map 驱动)。
契约漂移 SHALL 有机械化防线:回归测试断言 step-manifest 表中每个 bash 步的 script 名与
`list_steps.py` stdout 同步的 `script` 字段一致(防再次失同步横跨架构演进)。`merge` 行的出口语义
由「--merge 模式确定性出口」的独立决策处理,不因本同步义务先行改写。

#### Scenario: 契约表记派发器为扇出步 script

- **WHEN** 审阅 `step-manifest.md` 的 Step→IO 表 scout/t1/t2/t3 行
- **THEN** 四行的 script 记 `fanout_runner.py`(与 `list_steps.py --step <id>` stdout 的 `script`
  字段一致);scout 行另载 scout-merge 的 extra_invocations

#### Scenario: 契约表与实现失同步被回归测拦截

- **WHEN** `list_steps.py` 的 step 表发生 script/kind 变更而 `step-manifest.md` 未同步(或反之),
  运行契约同步回归测试
- **THEN** 测试失败(逐行比对 bash 步的 script/kind 字段),失同步不能静默滑过
