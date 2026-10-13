# fix-mgh-init-enumeration-caliber — fanout-dispatch delta

## MODIFIED Requirements

### Requirement: Dispatcher 脚本消费 pending 清单并零 LLM 驱动槽位补位循环

`fanout_runner.py`(stdlib 确定性叶脚本)SHALL 以 `--tier scout|t1|t2|t3|sdr` 参数化消费各自枚举
脚本的 stdout JSON(`--pending-file` 或内部调用枚举 CLI,接受其 `pending[]`/`repo`/预算字段
原样形态):scout → `list_scout_batches.py`、t1 → `list_clusters.py --materialize`、t2 →
`plan_aggregate.py --node t2`、t3 → `list_rule_jobs.py --materialize`、sdr → `diff_group.py`。
派发 SHALL 为**槽位补位循环**而非波次屏障:在飞子进程数 SHALL ≤ `--wave N`(默认 5);
任一单元到达终态(ok/failed/timeout/stall/crash)SHALL 立即从 pending 队列取下一单元补位
spawn,NEVER 等待同批全部收敛。补位取下一单元前 SHALL 对其 `.done`/`.failed` marker 做
存在性懒校验(marker 已存在 → 跳过不 spawn,取再下一单元);队列耗尽且在飞归零后 SHALL 按
磁盘 marker 重派生终态汇总。单元终态判定与 marker 真相源语义不变(见 ack 状态机 requirement);
一个在飞单元挂死 SHALL 只占用其槽位,NEVER 阻断其余槽位的派发与推进。循环全程 SHALL 零
LLM 请求;`--wave` 为在飞并发上限;心跳行 `wave=` 字段 SHALL 为该单元在本 run 内的派发序号,
sidecar `waves_run` SHALL 为累计派发单元数(字段名不变,语义重定义)。

**枚举 stdout `repo` 锚**:枚举脚本 stdout SHALL 均携带 `repo`(目标仓绝对根)锚字段,
dispatcher 以之为锚树校验与子进程 cwd 的依据。

**单元预算透传(run_config 消费闭环)**:scout/t1/t3 三个单元枚举 tier,dispatcher 在内部
调用枚举 CLI 前 SHALL 读取 init 目录(既有 plan-artifact 锚定)的 `run_config.json`,其
`budgets.max_unit_bytes` 存在且为正整数时 SHALL 以 `--max-unit-bytes <值>` 透传给枚举器;
缺 run_config 或字段缺失时 SHALL 不附加该 flag(枚举器用自身默认,行为与既有 run 一致)。
理由〔用户在 step 0 传入的自定义单元预算此前只被记录、无消费方——切分仍按枚举器默认 192KB,
预算静默失效;透传使「记录的预算」与「物化切分用的预算」恒同值,且与 resume 侧 t1 复算的
同 change 锁步(见 `resume-step-discipline` 能力「T1 终态闸门」requirement)——漏任一侧会
造成派发物化与状态机复算口径分叉,复活分片簇卡死形态〕。

**T1 scout 闸门透传**:`list_clusters.py` 因 scout 层未完成而退出码 2
(`scout-incomplete-gate`)时,dispatcher SHALL 以退出码 2 fail-loud 并透传其 stderr recipe
(先完成 scout 层),NEVER 将闸门拒识当作单元 crash 进入重派循环。sdr 枚举 gate 形退出码 2
同形透传。

**四级超时关系确定性化 + 启动校验**:自内向外四级 SHALL 满足不变式
`--stall-timeout-s(失活)< --call-timeout-s(绝对兜底)× 收敛余量 < time-budget-ms <
宿主 per-call timeout`,且每级留 ≥20% 余量。`--call-timeout-s` 默认值 SHALL 为 7200
(宁慢勿杀依据不变);`--stall-timeout-s` 默认值 SHALL 由**实测的完成单元运行时分布**标定
(口径:`p99(完成单元运行时)× 2`,向下取整到分钟,且 SHALL NOT 低于 900),该口径 SHALL 在
`--help` 文案中给出。取值域 SHALL
为 `0` 或 `≥ 60`:**`0` = 显式关闭失活判据**,此时排序不变式中的 `--stall-timeout-s <
--call-timeout-s` 一级 SHALL NOT 适用(仅剩 `--call-timeout-s < time-budget-ms × 0.8`),
`--call-timeout-s` 单独承担收敛有界;`1..59` SHALL 退出码 2 + 可操作 recipe。**dispatcher
SHALL 在 spawn 任何单元前校验**:调用方传 `--time-budget-ms` 时 MUST 同时显式传
`--call-timeout-s` 且其值 `< time-budget-ms × 0.8`,且(仅当 `--stall-timeout-s > 0`)
`--stall-timeout-s < --call-timeout-s`——违反 SHALL 退出码 2 + 可操作 recipe(给出合规
取值示例),NEVER 带违例不变式进入派发(默认 `--call-timeout-s 7200` 大于任何小时级宿主
预算,静默错配必然退化为宿主硬杀循环);未传 `--time-budget-ms`(宿主外手动直跑)时
默认值组合 SHALL 可用,stderr 打一次性提示。当调用方传 `--time-budget-ms` 时,dispatcher
SHALL 保证在宿主硬超时之前软时限触发(停发新补位、等在飞收敛——失活检测保证收敛有界——
退出码 0 + `partial:true`)。该超时契约 SHALL 对全部 tier 一致适用。

#### Scenario: 大量 pending 由槽位补位循环消化,编排器一次调用

- **WHEN** 任一 tier 有数百个 pending 单元,编排器一次 `Bash` 调用
  `fanout_runner.py --tier <tier>`(带 per-call `timeout`)
- **THEN** 脚本以 ≤ `--wave` 在飞补位循环内部消化全部单元,stdout 摘要报 `partial:false`、
  `done` 接近 total;编排器在整个 tier 无逐单元 LLM 决策回合

#### Scenario: 单个在飞挂死只废一槽,其余槽位继续推进

- **WHEN** 某在飞单元的子进程挂死无输出,同批其余单元陆续到达终态
- **THEN** dispatcher 在其余单元终态时立即补位派发后续单元,done 计数持续增长;挂死单元占
  槽至失活判定(或 call-timeout)被树杀后留 pending;全 run 推进 NEVER 停摆

#### Scenario: 补位前 marker 懒校验跳过已完成单元

- **WHEN** 补位取到的下一单元其 `.done`(或 `.failed`)marker 已在磁盘
- **THEN** dispatcher 不 spawn 该单元,直接取后续单元;磁盘 marker 仍是唯一真相源,已终态
  单元 NEVER 再次 spawn

#### Scenario: run_config 单元预算被透传给枚举器

- **WHEN** 某 run 的 `run_config.json` 记录 `budgets.max_unit_bytes: 65536`,dispatcher 以
  `--tier scout`/`--tier t1`/`--tier t3` 内部调用枚举 CLI
- **THEN** 枚举命令携带 `--max-unit-bytes 65536`,超 64KB 的簇按该值切分/标 oversize(NEVER
  按枚举器默认 192KB);同 run 的 resume 侧 t1 复算使用同一 run_config 值,两侧口径恒一致

#### Scenario: 缺 run_config 时枚举命令形态不变

- **WHEN** init 目录无 `run_config.json`(或 `budgets.max_unit_bytes` 缺失/非正整数),
  dispatcher 调用枚举 CLI
- **THEN** 枚举命令不附加 `--max-unit-bytes`,枚举器按自身默认切分——与既有 run 行为一致
  (透传是增量,不改变无 run_config 场景)

#### Scenario: 时间预算耗尽干净早退

- **WHEN** dispatcher 带 `--time-budget-ms` 运行,软时限到达时尚有 pending
- **THEN** 脚本停止发起新补位、等在飞单元收敛(失活检测保证收敛有界),以退出码 0 +
  stdout `partial:true` 干净早退;编排器重派同一命令直至 `partial:false`

#### Scenario: 超时不变式违例 spawn 前 fail-loud

- **WHEN** 调用传 `--time-budget-ms 720000` 但未显式传 `--call-timeout-s`(默认 7200 ≥
  budget×0.8),或 `--stall-timeout-s ≥ --call-timeout-s`(两者皆 > 0),或
  `--stall-timeout-s` 取 1..59
- **THEN** dispatcher 退出码 2,stderr recipe 给出合规取值示例(如
  `--call-timeout-s 540 --stall-timeout-s 300`,或关闭态 `--stall-timeout-s 0`);零单元被
  spawn、零枚举副作用

#### Scenario: `--stall-timeout-s 0` 显式关闭失活判据且不触发排序违例

- **WHEN** 调用传 `--stall-timeout-s 0 --call-timeout-s 2000 --time-budget-ms 2700000`
- **THEN** 校验通过(不再要求 `stall < call`),无单元因静默被判失活;收敛有界由
  `--call-timeout-s` 单独承担;stdout 摘要 `stall_killed` 为空数组,`--help` 文案列出关闭态语义

#### Scenario: 手动直跑(无 budget)默认组合可用

- **WHEN** 人开终端直跑 `fanout_runner.py --tier t1`(不传 `--time-budget-ms`)
- **THEN** 默认 `--stall-timeout-s < --call-timeout-s 7200` 校验通过,正常运行;
  stderr 一次性提示(宿主外直跑无宿主超时钳制)

#### Scenario: T1 在 scout 未完成时闸门 fail-loud

- **WHEN** `run_config.json` 启用 scout 而 scout 层未完成,编排器以 `--tier t1` 调用 dispatcher
- **THEN** dispatcher 退出码 2,stderr 透传 `list_clusters.py` 的 scout-incomplete-gate recipe
  (先完成 scout 层);无单元被 spawn、无 crash 重派循环发生

#### Scenario: 软时限先于宿主硬超时触发

- **WHEN** 宿主 per-call timeout = 900000ms,dispatcher 以 `--time-budget-ms 720000
  --call-timeout-s 540 --stall-timeout-s 300` 运行
- **THEN** dispatcher 在 ~720s 停发新补位并等在飞收敛,以退出码 0 + `partial:true` 退出;
  宿主硬超时(900s)NEVER 触发;重派循环的每一轮都是干净早退而非硬杀

#### Scenario: call-timeout 与 stall-timeout 默认值按内网慢接口标定

- **WHEN** 审阅 `py fanout_runner.py --help` 的 `--call-timeout-s`/`--stall-timeout-s`
  默认值与文案
- **THEN** `--call-timeout-s` 默认 7200s;`--stall-timeout-s` 默认值 SHALL 等于实测标定结果
  (`p99(完成单元运行时)× 2`,向下取整到分钟,不低于 900);文案 SHALL 注明四级超时不变式与
  「宁慢勿杀」依据(被杀单批无 marker 留 pending,重派浪费一整跑)、该判据的**失效面**
  (字节静默不区分「等网关排队」与「真卡死」)、关闭取值(`0`)与标定口径
