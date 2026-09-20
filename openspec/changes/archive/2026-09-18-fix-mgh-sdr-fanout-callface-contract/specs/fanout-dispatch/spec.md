## MODIFIED Requirements

### Requirement: sdr tier dispatches diff-review units through the shared wave machine

`fanout_runner.py` 的 `--tier` 闭集 SHALL 扩为 `scout|t1|t3|sdr`,新增 `sdr` 条目挂入既有 TIERS
单点映射表:枚举脚本 = `diff_group.py`(`--repo/--base/--branch/--checkpoints/--materialize` 转发)、
任务模板 = `core/prompts/fragments/fanout/sdr-task.md`、fanout agent = `sdr-review-fanout`、
占位符集 = 路径字段(`input_path`/`draft_path`/`done_marker`/`failed_marker`)+ `unit_id`/
`kind`/`route`/`repo`/`codegraph`。波次循环、ack 状态机、三级超时不变式、liveness 登记、
`--kill-stale`、零推进熔断、进度 sidecar(`<init-dir>/fanout_progress.sdr.json`)SHALL 对 sdr
tier 零改动复用(tier 无关代码路径不变);`diff_group.py` 的 gate 形退出码 2(如 base ref 不存在)
SHALL 与 t1 scout-incomplete-gate 同形透传(fail-loud + stderr recipe,NEVER 进入重派循环)。
`install.sh` 自检清单与 fanout agent 自检 SHALL 覆盖 `diff_group` 脚本、`sdr-task.md` 模板与
`sdr-review-fanout` agent 克隆;`tools/check_contracts.py` 覆盖引用 `diff_group.py` /
`render_sdr_report.py` / `sdr_context.py` 的壳调用 flag。既有 scout/t1/t3 三 tier 的调用面、模板、
agent、行为 SHALL 逐字不变。

**`codegraph` 占位符 MUST 有确定性消费者**:dispatcher SHALL 从 sdr run 目录的
`run_config.json` 读取 `no_codegraph` 字段派生 `codegraph=on|off`(sdr 的 plan 锚点为
`<run-dir>/grouping.json`,其父目录即运行目录,与 init tier 同形),并据此填充每个单元任务消息的
`{{codegraph}}` 占位符。该占位符 SHALL NOT 对 sdr tier 恒为 `off`:分组阶段
(`diff_group.py`)与任务填充阶段 SHALL 使用同一事实来源,两侧信号 MUST 一致。`run_config.json`
缺失或不可解析 SHALL 落 `off`(legacy 语义);`no_codegraph` 为真值 SHALL 落 `off`。

**信号载体唯一**:sdr 的 codegraph 信号 SHALL 只经 `run_config.json` 承载;命令壳 SHALL NOT
另设专用环境变量中转,亦 SHALL NOT 由编排器手执行写入配方——**写入端**由确定性脚本
`sdr_context.py` 以副作用 co-write(取 `--no-codegraph` flag),**读取端**即本节 dispatcher 的
`_codegraph_signal()`(两侧同源,sdr 与 init tier 走逐字相同的读取路径)。写入端契约见
`security-design-review` 的「sdr 运行目录无起始态文件;codegraph 信号由脚本确定性写出」条目;
本条只约束读取端,SHALL NOT 复述写入端(无消费者的中转载体等于死契约,而重复的载体声明同样
会让两侧漂移)。

#### Scenario: sdr tier 经共享状态机波次消化

- **WHEN** `diff_group.py --materialize` 产出 12 个 pending 单元,编排器一次调用
  `fanout_runner.py --tier sdr --repo <abs> --base master --branch X --checkpoints <dir> --inputs-dir <dir>`
- **THEN** dispatcher 以 `--wave` 并发度内部消化全部波次,每单元 spawn 一个 `sdr-review-fanout`
  subagent(任务消息 = `sdr-task.md` 模板逐字填充),stdout 摘要含 `tier:"sdr"`;软时限早退 /
  resume / 熔断行为与既有 tier 一致

#### Scenario: sdr 单元越树路径 spawn 前拦截

- **WHEN** 某 pending 项的 `draft_path` 解析后落在 `repo` 锚树外
- **THEN** dispatcher 不 spawn,直接写 `.failed` marker(reason=path-drift),后续波次不受影响
  (与既有 tier 同一 `_anchor_check` 代码路径)

#### Scenario: sdr 的 codegraph 占位符随运行目录配置变化

- **WHEN** sdr run 目录的 `run_config.json` 不含 `no_codegraph`(或该键为假值),编排器以
  `--tier sdr` 派发
- **THEN** 每个单元任务消息的 `codegraph=` 占位符填为 `on`;同一次 run 中
  `diff_group.py --materialize` 的 stdout `codegraph` 字段同为真值,两侧信号一致

#### Scenario: 关闭信号与缺失配置均落 off

- **WHEN** run 目录的 `run_config.json` 含 `no_codegraph: true`(用户传 `--no-codegraph`),或该
  文件缺失/不可解析
- **THEN** 占位符填为 `off`,复核子代理按"单元可能在接口边界被切开"的语义判定;缺失文件的
  降级行为与既有 legacy 语义逐字一致

#### Scenario: 强制关信号不改变分组(开关语义如实披露)

- **WHEN** 用户在**已索引**的仓上显式传 `--no-codegraph`(或 launcher 同名 flag)
- **THEN** 写入的 `no_codegraph` 为真、任务书占位符为 `off`,而 `diff_group.py --materialize`
  的 stdout `codegraph` 仍为真(分组阶段恒自行探测,该 flag 对其不可见)——两侧在此**刻意**
  不一致,方向保守:子评审被要求按"可能被切开"判定,而已合好的链仍在切片里。该语义 SHALL 在
  命令壳的参数表、`--help` 与 launcher 文案中如实写明(「只改信号、不改分组」);同族断言
  SHALL NOT 被读成"传该 flag 即零 codegraph 调用"(现行为不成立)

#### Scenario: 既有 tier 行为零漂移

- **WHEN** 对 scout/t1/t3 各自的枚举产物运行既有调用面并比对本次变更前后的 stdout 摘要与模板
  填充结果
- **THEN** 三 tier 的枚举脚本、模板、agent、占位符集、波次行为逐字一致(TIERS 表增行不触既有行)

## ADDED Requirements

### Requirement: 宿主驱动调用的 `--stall-timeout-s` 取值口径

`fanout_runner.py` 的 `--stall-timeout-s` 取值域 SHALL 为三段互斥语义,且三段的分工 SHALL 在
`--help` 文案中给出:**`0`** = 显式关闭失活判据(该 run 内不再因字节静默树杀,收敛有界由
`--call-timeout-s` 单独承担);**`1..59`** = 非法,退出码 2 + 可操作 recipe;**`>= 60`** = 生效的
静默窗口。`STALL_TIMEOUT_FLOOR_S`(=60)SHALL 表述为**硬性拒绝下限**,
`DEFAULT_STALL_TIMEOUT_S`(=900)SHALL 表述为**仅适用于宿主外手动直跑的默认值**,二者 SHALL NOT
在规格或文案中被混称为"下限"。

**宿主演进调用面**(经编排器 Bash 调用、传 `--time-budget-ms` 的路径)SHALL 显式传
`--stall-timeout-s` 且其值 `< --call-timeout-s`,NEVER 省略该 flag 依赖默认值。理由:宿主演进
调用 MUST 同时显式传 `--call-timeout-s < time-budget-ms × 0.8`(见四级超时不变式),而该值远小于
默认的 900——省略 `--stall-timeout-s` 会取到 900,直接触发 `stall >= call` 的 spawn 前校验并以
退出码 2 拒绝启动,使该 tier 完全不可用。生产取值 SHALL 由调用方按宿主预算显式给出(现行
`/mgh-init` 各 tier 与 `/mgh-sdr` 均取 300,规格合规示例为 `720000/540/300` 与
`480000/360/300`)。

#### Scenario: 宿主演进调用显式传 stall 且小于 call

- **WHEN** 编排器以 `--time-budget-ms 480000 --call-timeout-s 360 --stall-timeout-s 300` 调用
  任一 tier
- **THEN** spawn 前校验通过,派发正常进行;`300` 是规格许可的显式取值,SHALL NOT 被任何校验
  以"低于下限"为由拒绝

#### Scenario: 宿主演进调用省略 stall 时 fail-loud

- **WHEN** 编排器传 `--time-budget-ms 480000 --call-timeout-s 360` 但省略 `--stall-timeout-s`
  (取默认 900)
- **THEN** dispatcher 在 spawn 任何单元前以退出码 2 拒绝,stderr recipe 说明"失活窗口必须小于
  单次超时"并给出合规取值示例(如 `--call-timeout-s 360 --stall-timeout-s 300`)与关闭态
  `--stall-timeout-s 0` 两条出路;零单元被 spawn

#### Scenario: 宿主外手动直跑取默认值可用

- **WHEN** 人开终端直跑 `fanout_runner.py --tier t1`(不传 `--time-budget-ms`,也不传
  `--stall-timeout-s`)
- **THEN** 默认 `900 < --call-timeout-s 7200` 校验通过,正常运行,stderr 一次性提示"宿主外直跑
  无宿主超时钳制";该默认值 SHALL NOT 被解读为宿主演进调用面的推荐取值
