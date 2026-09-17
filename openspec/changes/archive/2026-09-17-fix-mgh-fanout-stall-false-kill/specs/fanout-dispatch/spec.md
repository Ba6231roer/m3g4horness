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

**T1 scout 闸门透传**:`list_clusters.py` 因 scout 层未完成而退出码 2
(`scout-incomplete-gate`)时,dispatcher SHALL 以退出码 2 fail-loud 并透传其 stderr recipe
(先完成 scout 层),NEVER 将闸门拒识当作单元 crash 进入重派循环。sdr 枚举 gate 形退出码 2
同形透传。

**四级超时关系确定性化 + 启动校验**:自内向外四级 SHALL 满足不变式
`--stall-timeout-s(失活)< --call-timeout-s(绝对兜底)× 收敛余量 < time-budget-ms <
宿主 per-call timeout`,且每级留 ≥20% 余量。`--call-timeout-s` 默认值 SHALL 为 7200
(宁慢勿杀依据不变);`--stall-timeout-s` 默认值 SHALL 由**实测的完成单元运行时分布**标定
(口径:`p99(完成单元运行时)× 2`,向下取整到分钟,且 SHALL NOT 低于 900),标定所用样本与
取整结果 SHALL 记入本 change 的 design Decisions,并在 `--help` 文案中给出该口径。取值域 SHALL
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

### Requirement: 在飞单元失活检测与外科手术式树杀(运行留痕)

dispatcher SHALL 对每个在飞子进程分别跟踪其 stdout 与 stderr 的**字节级最后输出时刻**;
当且仅当**两条流都没有新字节**已经过本轮生效的静默窗口(初值 `--stall-timeout-s`,见下
「本轮生效静默窗口」)才判定该单元失活(等价表述:静默时长取两条流最后输出时刻中的
**较新者**;任一条流有字节即重置,NEVER 以任一条流的陈旧时刻单独判失活——空流的路
MUST NOT 使健康单元被判失活),→ **仅杀该单元的整个进程树**(Windows
`taskkill /pid <pid> /T /F`——`.cmd` shim 链下的真实 host-CLI 进程 SHALL 一并终止,NEVER
留孤儿继续烧 token;POSIX 杀该单元自己的进程组 SIGTERM),无 ack 无 marker → 单元留 pending
重派。**树杀的作用域 SHALL 严格收敛于被杀单元**:杀一个失活单元 NEVER 导致 dispatcher 自身
终止——POSIX 下单元子进程 SHALL 在 spawn 时自成会话/进程组(`start_new_session`),使
`killpg` 只命中该单元自己的树;Windows 分支不受影响。`--call-timeout-s` 绝对兜底超时的杀
路径 SHALL 使用同一树杀机制(取代仅杀直接子进程的 `proc.kill()`——Windows 上那是 shim 层,
真进程必成孤儿)。失活判定 SHALL 对全部 tier 一致;误杀边界由余量承担(healthy 单元分钟级,
默认阈值 ~5×),被误杀单元重派自愈且 run.log 留痕可查,并另有下述自适应宽限以假杀自证收敛。

**判据语义与失效面**:字节静默 SHALL 被解释为「该单元此刻无产出」,**SHALL NOT** 被当作
「该单元卡死」的充分证据——在限流网关上静默的常见成因是调用排在网关队列里等待,与真卡死在
本地信号上不可分。`--help` 文案 SHALL 明写该语义与失效面,并披露该判据的正当用途是**为本 run
的收敛设上界**,而非诊断单元健康度。

**本轮生效静默窗口(假杀自证 + 有界自适应宽限)**:窗口初值 SHALL 为 `--stall-timeout-s`;
同一次 run 内,若某单元曾因静默被判失活(树杀,**无 ack 无 marker**),且其后**在同一次 run 的
重派中成功完成**(`.done` marker 落盘或 ok ack),dispatcher SHALL 将该证据视为「本轮窗口过紧」,
把本轮生效窗口放宽为 `min(当前生效窗口 × 2, --call-timeout-s × 0.8)`,并 SHALL 在 stderr 披露
一次放宽事件(旧值 → 新值 + 触发单元 id)。放宽 SHALL 有界(以 `--call-timeout-s × 0.8` 为上限)
且 SHALL 只影响本 run 后续的静默判定,NEVER 改写 `--stall-timeout-s` 的入参语义、NEVER 跨 run 持久化。
`--stall-timeout-s 0`(关闭态)下本段 SHALL NOT 适用。

**每单元运行留痕**:dispatcher SHALL 将每单元子进程的 stdout/stderr 尾部(各自截断上限)落盘
`<checkpoints>/<tier>/<单元 id 文件名安全形>.run.log`(文件名净化规则与 audit 副本同源,
`/ \ :` → `_`);ok 终态亦写(体积小),timeout/stall/crash/failed 终态 MUST 写;失活/超时的
stderr 诊断行 SHALL 附 run.log 绝对路径——事后定位以证据为准,NEVER 依赖事后猜测。

**stdout/心跳披露**:stdout 摘要 SHALL 新增 `stall_killed:[<unit>…]`(本次 run 失活树杀的
单元,既有字段不变),并 SHALL 新增**代价可视字段**:① 本次 run 已完成单元运行时的
`runtime_p50_s`/`runtime_p95_s`/`runtime_max_s`(秒,整数;无完成单元时省略该三键);
② `stall_killed_slots_s`(本次 run 因失活被杀的单元累计占用槽位秒数)与
`stall_killed_slot_pct`(该秒数 ÷ 本次 run 的槽位总秒数,保留一位小数);③ 若本轮发生自适应
放宽,`stall_window_s` SHALL 报出本轮**生效**窗口终值(未放宽时省略)。派发循环 SHALL 以默认
60s 周期向 stderr 打在飞披露行(在飞单元 id + 距其子进程上次输出的秒数),人从宿主 TUI 实时
区分「正常慢」与「卡死」;该披露的静默秒数 SHALL 与失活判据同源(取两条流最后输出时刻的
较新者),NEVER 把从未产生字节的那条流的 spawn 时刻当成静默起点。进度侧车 SHALL 同步携带
上述代价可视字段。

**进程组隔离的边界披露**:单元子进程自成会话后,交互式终端向 dispatcher 发送的中断信号
(如 Ctrl-C)SHALL NOT 再连带终止在飞单元子进程;这些进程成为孤儿,但 SHALL 由既有 liveness
登记(`<init-dir>/fanout_runner.<tier>.pid` 的 `children[]`)覆盖,并可由既有 `--kill-stale`
检出清理。`--kill-stale` 与失活段的 `--help` 文案 SHALL 明示该边界及补偿路径。

#### Scenario: 失活单元被外科树杀,其余单元不受影响

- **WHEN** 某在飞子进程两条输出流均静默超过本轮生效窗口,同批其余单元正常推进
- **THEN** 仅该单元进程树被终止(含 shim 链真进程),其余单元与后续补位照常;该单元无
  marker 留 pending;stdout 摘要 `stall_killed` 含其 id

#### Scenario: 树杀不留孤儿 shim 链

- **WHEN** 失活(或 call-timeout)树杀一个经 `.cmd` shim spawn 的 opencode 子进程
- **THEN** shim 层与真实 host-CLI 进程一并终止(`taskkill /T /F` 整树),无任何后代进程
  存活烧 token;`--kill-stale` 事后检查无该 run 的存活子进程

#### Scenario: 非 ok 终态运行留痕可诊断

- **WHEN** 某单元以 timeout/stall/crash 终态结束
- **THEN** `<checkpoints>/<tier>/<unit>.run.log` 存在且含该子进程输出尾部;stderr 诊断行
  附该文件绝对路径;事后可从日志尾部读出子进程最后行为(如权限拒绝、流停摆前的输出)

#### Scenario: 周期在飞心跳披露静默时长

- **WHEN** 某在飞单元子进程已静默 5 分钟,其余单元在跑
- **THEN** stderr 每分钟出现该单元的在飞披露行(unit id + 距上次输出秒数),静默秒数单调
  增长直至失活判定;stdout 单行 JSON 契约不变

#### Scenario: 单路静默的健康单元不被判失活

- **WHEN** 某单元子进程持续向 stdout 输出、而 stderr 自 spawn 起从未产生任何字节,时间
  超过本轮生效窗口
- **THEN** 该单元 MUST NOT 被判失活(其静默时长按两条流中较新者计 = 最近一次 stdout 字节的
  时刻);单元正常推进至终态

#### Scenario: 树杀不终止 dispatcher 自身

- **WHEN** POSIX 下 dispatcher 对某失活单元执行树杀,同批其余单元仍在飞
- **THEN** 只有该单元的进程树被终止,dispatcher 进程 MUST 继续存活并照常补位派发;该轮
  运行 SHALL 能继续到软时限或队列耗尽,并打印 stdout 汇总(退出码 0 或按既有语义)

#### Scenario: 双路皆静默仍判失活

- **WHEN** 某在飞子进程的 stdout 与 stderr 均超过本轮生效窗口未产生字节
- **THEN** 仍按本 requirement 判失活并树杀,该单元留 pending 重派——判据放宽 MUST NOT
  变成永不判定

#### Scenario: 被杀单元重派成功即放宽本轮窗口(假杀自证)

- **WHEN** 单元 A 因静默被判失活并树杀(无 ack 无 marker),其后在同一 run 的重派中完成
  (`.done` 落盘),此时本轮生效窗口为 W 且 `2W ≤ --call-timeout-s × 0.8`
- **THEN** stderr 打一条放宽披露行(旧值 W → 新值 2W,触发单元 id = A);此后在飞单元的静默
  判定改用 2W;stdout 摘要 `stall_window_s` 报 `2W`

#### Scenario: 自适应放宽有界,不越过 call-timeout 余量

- **WHEN** 本轮已多次因假杀自证而放宽,`2W > --call-timeout-s × 0.8`
- **THEN** 生效窗口收敛为 `--call-timeout-s × 0.8` 并不再上调;`--call-timeout-s` 仍为绝对
  兜底,任何单元 SHALL NOT 存活超过 `--call-timeout-s`

#### Scenario: 代价可视字段随每次退出落盘

- **WHEN** 一次 run 正常结束(退出码 0,含 `partial:true` 早退)
- **THEN** stdout 摘要含已完成单元的 `runtime_p50_s`/`runtime_p95_s`/`runtime_max_s` 与
  `stall_killed_slots_s`/`stall_killed_slot_pct`;进度侧车同名字段同步;无任何单元完成时三个
  runtime 键省略而非报 0

#### Scenario: 关闭态不再误杀且判据不发散

- **WHEN** 以 `--stall-timeout-s 0` 运行,某单元长时间无输出
- **THEN** 该单元 SHALL 被保留至 `--call-timeout-s` 到达(或被其重派收敛),NEVER 因静默被杀;
  stdout `stall_killed` 为空数组;`runtime_*` 与 `stall_killed_slots_s` 字段照常披露
