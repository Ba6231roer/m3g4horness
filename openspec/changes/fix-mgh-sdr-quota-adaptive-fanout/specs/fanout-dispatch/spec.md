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

**配额准入节流(可选配额模式,调用次数限流网关)**:dispatcher SHALL 接受配额三
flag:`--quota-calls N`(一个窗口内的模型调用上限)、`--quota-window-s W`(窗口秒数)、
`--quota-calls-per-unit K`(每单元调用数估算,默认 10;取保守上界,宁可慢 NEVER 打穿配额)。
配额模式 SHALL 当且仅当 `--quota-calls` 与 `--quota-window-s` **同时**显式传入时激活;
只传其一,或 `--quota-calls-per-unit` 在未配对时单独传入,SHALL 退出码 2 + 可操作 recipe
(零单元 spawn,与超时不变式违例同形的启动校验);取值域 N ≥ 1、W ≥ 1、K ≥ 1,违例同形
fail-loud。配额模式下,dispatcher SHALL 维护**本 run 的单元派发时间戳滑动窗口**,每次准入
判定时以「最近 W 秒内的派发数 × K」估算已耗调用数,余量 < K 时 SHALL NOT 派发新单元
(在飞单元照常运行、照常收割);等待窗口滑动 SHALL 由派发循环以 ≤1s 分片 sleep 承担
(NEVER 忙等自旋),且 SHALL 受剩余时间预算约束——预算耗尽走既有软时限早退(退出码 0 +
`partial:true`,`--resume` 接续)。每段准入等待 SHALL 向 stderr 披露一行(估算口径 +
预计恢复时刻);stdout 摘要与 sidecar SHALL 增配额披露字段(`quota{calls,window_s,
calls_per_unit,admission_waits}`;未配置配额模式时该键缺席,既有字段零增删)。**估算口径
的诚实边界**:每单元真实调用数发生在宿主 CLI 子进程内部,dispatcher 不可观测,准入节流是
估算式闸门——估算偏小仍可能吃 429(由配额窗口复位冷却与限流截断兜底,见相应 requirement);
滑动窗口为**本进程内**口径,`--resume` 起一个新窗口,跨进程不追踪网关侧已耗配额(重启后
首个窗口可能短暂超派,由既有 429 兜底层吸收)。**未配置配额 flag 时,全部 tier 的派发、
冷却、截断、stdout/ sidecar 行为 SHALL 与引入本段前逐字节一致**。

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

#### Scenario: 配额余量不足时暂停新派发,窗口滑动后恢复

- **WHEN** dispatcher 以 `--quota-calls 100 --quota-window-s 600 --quota-calls-per-unit 10
  --wave 1` 运行,本 run 已派发 10 个单元且最早一次派发距今 < 600s,某在飞单元到达终态腾出
  槽位
- **THEN** 第 11 个单元不被派出(估算已耗 100 ≥ 上限,余量 < K);在飞/后续收割照常;
  stderr 披露一段准入等待(含估算口径与预计恢复时刻);最早派发滑出 600s 窗口后,新派发
  自动恢复;stdout 摘要 `quota.admission_waits ≥ 1`

#### Scenario: 配额 flag 未配对 spawn 前 fail-loud

- **WHEN** 调用只传 `--quota-calls 100`(缺 `--quota-window-s`),或单独传
  `--quota-calls-per-unit 8`,或传 `--quota-calls 0`
- **THEN** dispatcher 退出码 2 + 可操作 recipe(配对要求与取值域),零单元 spawn、零枚举
  副作用——与超时不变式违例同形的启动校验

#### Scenario: 配额等待受剩余时间预算约束

- **WHEN** 配额模式下准入等待持续到软时限到达,尚有 pending 与在飞单元
- **THEN** dispatcher 停发新补位、等在飞收敛,以退出码 0 + `partial:true` 干净早退(等待
  NEVER 越过时间预算);编排器同参重派接续,`--resume` 后滑动窗口重新起算

#### Scenario: 未配置配额 flag 时行为逐字节不变

- **WHEN** 同一批单元分别以「不传任何配额 flag」在引入配额模式前后的 dispatcher 上运行
- **THEN** 派发顺序、冷却、截断、stderr 行、stdout 摘要与 sidecar 逐字节一致(stdout 无
  `quota` 键)——配额模式是纯增量,NEVER 触碰未 opt-in 的路径

### Requirement: 快败冷却与熔断前有界退避

`fanout_runner.py` SHALL 维护一个**快败滑动窗口**（120s，实现常量）统计 **requeue 事件**——
单元以 crash/timeout/stall/spawn-error 终态且回到 pending 队尾的事件；显式 `failed:` ack 与
spawn 前锚校验失败 SHALL NOT 计入（两者终态化不回队，无风暴形状，计入会让确定性配置错误
假触发冷却）。窗口内 requeue 事件 ≥ 3（实现常量）时，dispatcher SHALL 暂停派发新单元
`--cooldown-s` 秒（默认 300；`0` = 关闭；取值 SHALL 按「剩余时间预算 − 在飞收敛余量」封顶，
预算不足时冷却退化为立即继续并如实 stderr 披露）；冷却期间在飞单元照常运行、照常收割——
冷却只停**新派发**;冷却生效期间无在飞单元时(含队列空的熔断前退避挂起态),派发循环 SHALL
以分片 sleep 休眠等待冷却到期,**NEVER** 零 sleep 自旋空转。每次冷却 SHALL 向 stderr 打一行披露（触发原因 + 实际冷却秒数），stdout
摘要新增 `cooldowns:<n>`（本 run 冷却次数；既有字段零增删）。

**熔断前有界退避**：零推进熔断准备以退出码 2 收束时，若剩余时间预算允许，dispatcher SHALL
执行**至多一次**「冷却 `--cooldown-s` → 全量重列磁盘终态 → 再观察」——重列有推进（done+failed
计数增加）则撤销熔断、恢复派发；仍零推进才以退出码 2 fail-loud（既有 `stalled` 契约逐字不变）。
NEVER 无限退避（跨配额窗口的收敛 SHALL 仍归编排器 `--resume` 重派循环，不塞进单次调用）。

**配额窗口复位冷却(配额模式增量)**：配额模式激活时,凡触发冷却的快败事件中**存在命中限流
特征集**(`429`/`too many requests`/`rate limit`/`quota`,子串、大小写不敏感)的 requeue,该次
冷却的终点 SHALL 为「最近一次限流特征事件时刻 + `--quota-window-s`」与按 `--cooldown-s`
计算的常规终点取**较大者**——即等满配额窗口复位,而非固定秒数;该终点 SHALL 仍受「剩余时间
预算 − 在飞收敛余量」封顶,预算不足时截断等待并如实 stderr 披露(冷却后如仍吃 429,由配额
截断语义兜底,见「crash 原因分类与限流 crash 风暴截断」requirement)。冷却期间在飞单元照常
运行收割、派发循环分片 sleep 等待的既有语义不变;熔断前有界退避的冷却时长仍按 `--cooldown-s`
口径(零进度未必是配额形态,NEVER 把退避默认放大到窗口级)。非配额模式下,所有限流特征事件的
冷却时长 SHALL 与引入本段前逐字节一致(固定 `--cooldown-s` 口径)。

#### Scenario: 快败风暴触发冷却，新派发暂停而在飞照常

- **WHEN** 配额耗尽，120s 滑动窗口内第 3 个单元 crash 回队
- **THEN** dispatcher 暂停派发 `--cooldown-s` 秒（stderr 披露一行），已 spawn 的在飞单元继续
  运行并正常收割；冷却结束后恢复派发；stdout 摘要 `cooldowns:1`

#### Scenario: failed-ack 与 pre-spawn 失败不触发冷却

- **WHEN** 窗口内 3 个单元全部以显式 `failed:` ack 终态（写 `.failed`，不回队）
- **THEN** 不触发冷却（非 requeue 事件）；failed 终态语义不变

#### Scenario: 冷却受剩余时间预算封顶

- **WHEN** 冷却触发时剩余时间预算 < `--cooldown-s` + 在飞收敛余量
- **THEN** 冷却时长被截到预算允许值；预算耗尽则跳过等待立即继续，stderr 如实披露截断

#### Scenario: 退避挂起空队列期间休眠而非自旋

- **WHEN** 熔断前退避在 drain 点武装（队列空、在飞零）且冷却窗口（默认 300s）未到期
- **THEN** 派发循环以 ≤1s 分片 sleep 休眠等待冷却到期，期间进程处于休眠等待而非忙等自旋
  （NEVER 零 sleep 的 100% CPU 空转）；冷却到期后的退避重列判定行为逐字不变

#### Scenario: 熔断前一次退避自愈

- **WHEN** 零推进熔断条件满足且剩余时间预算允许
- **THEN** 执行一次「冷却 → 全量重列 → 再观察」；重列有推进 → 熔断撤销、继续派发；
  仍零推进 → 退出码 2 + `stalled:true`（契约不变）；本路径在单次调用内至多发生一次

#### Scenario: 配额模式下限流特征冷却等到窗口复位

- **WHEN** dispatcher 以 `--quota-calls 100 --quota-window-s 600` 运行,某单元 crash 回队且其
  输出尾部含 `429`,触发快败冷却时距该特征事件已过 120s
- **THEN** 冷却终点 = 特征事件时刻 + 600s(尚需约 480s),而非固定 `--cooldown-s` 300s;stderr
  披露口径注明「等满配额窗口」;在飞单元照常收割;窗口复位后恢复派发

#### Scenario: 非限流特征事件的冷却时长不因配额模式改变

- **WHEN** 配额模式下,触发快败冷却的 3 个 requeue 事件输出尾部均**不含**任何限流特征串
  (如纯网络瞬断)
- **THEN** 冷却时长仍按固定 `--cooldown-s` 口径计算(窗口复位语义只挂在限流特征事件上);
  熔断前有界退避的冷却时长同样不变

### Requirement: crash 原因分类与限流 crash 风暴截断

`fanout_runner.py` SHALL 在单元以 **crash 终态**(非零退出或无 ack 回执)结束后,对该单元的
输出尾部(stdout/stderr 缓存尾,数据源 = 失活检测/运行留痕机制)做**确定性限流特征分类**:
命中特征集 `429`/`too many requests`/`rate limit`/`quota`(大小写不敏感,子串匹配)→ 该单元记
`crash_cause:"rate-limit"`,否则 `"unknown"`。分类 SHALL 对全部 tier 一致(共享派发循环,一处
生效);ok/failed/timeout/stall 终态 SHALL NOT 参与分类(仅 crash)。

**限流 crash 风暴截断(快路径止损)**:dispatcher SHALL 维护一个**crash 风暴观察窗口**(自上次
磁盘终态推进〔任一单元 ok/failed marker 落盘〕起累计的 crash 事件);当窗口内 crash 计数
≥ `--wave` **且全部** `crash_cause:"rate-limit"` 时,SHALL 立即停止派发剩余单元并**优先于新一轮
冷却**直接截断,以退出码 2 fail-loud:stdout 摘要报 `rate_limited:true` +
`rate_limited_crashes:[<unit>…]`,stderr 给**冷却 recipe**——等满一个配额窗口再 resume(窗口
时长以网关配置为准,如 10 分钟)、wave 校准公式(`wave = floor(8 ÷ 每子每分钟调用数)`,8 =
配额每分钟上限 × 80% 安全余量)、提示失活树杀不属 crash、提及本截断可经
`--no-rate-limit-stop` 禁用。截断 SHALL 先于零推进熔断触发(快路径);零推进熔断(慢路径,含
其熔断前一次退避)行为不变,仍是兜底。`--no-rate-limit-stop` 传入时 SHALL 完全跳过本截断。
**优雅退化**:特征集漂移(新网关措辞)→ 分类全 unknown → 本截断不触发,快败冷却路径照常
自愈兜底——文本签名仅是快停与披露层,NEVER 是唯一防线。非限流 crash(unknown)SHALL NEVER
计入风暴判定。

**配额模式的「等满窗口才截断」语义(增量)**:配额模式激活时,满足「窗口内 crash 计数
≥ `--wave` 且全部 rate-limit」的截断条件 SHALL 追加一项——**至少一次** rate-limit crash 发生
在一次**已完整等到配额窗口复位**的冷却(见「快败冷却与熔断前有界退避」的配额窗口复位段)
之后;即限流特征 crash 先由窗口复位冷却自我恢复,等满一个完整窗口后**仍**出现限流特征才
截断(此时说明配额参数配错或网关比声明更紧,继续等不再收敛)。截断的 stdout 字段、退出码、
stderr recipe SHALL 沿用既有形态,recipe 增补一行「核对 `--quota-calls`/`--quota-window-s`/
`--quota-calls-per-unit` 与网关实际配额是否一致」。未配置配额模式时,截断条件 SHALL 与引入
本段前逐字节一致(计数 ≥ `--wave` 且全 rate-limit 即截断)。

**截断与补位派发的同步语义**:「立即停止派发」SHALL 覆盖补位循环的取单元窗口——截断旗标
生效后,dispatcher SHALL NOT 再向网关提交任何新单元;主线程在**取单元之后、提交 spawn 之前**
SHALL 复查截断状态(或将派发决策与截断旗标置于同一同步域),使补位窗口 SHALL NOT 越过已生效
的截断旗标;已提交的在飞单元不受影响,照常收割记账。

#### Scenario: 限流 crash 风暴被立即截断

- **WHEN** 配额耗尽，一个观察窗口内 `--wave 5` 个单元相继 crash 且输出尾部均含 `429`/
  `Too Many Requests` 特征
- **THEN** 第 5 个 crash 终态判定完成后 dispatcher 停止派发(优先于再等一轮冷却)，退出码 2,
  stdout `rate_limited:true` + `rate_limited_crashes` 含 5 个单元 id,stderr 冷却 recipe 给出
  等窗与 wave 公式;零推进熔断未被等待触发(快路径先停)

#### Scenario: 截断落地前补位窗口不越过旗标

- **WHEN** 截断旗标已生效,主线程补位循环已取出下一单元、尚未提交 spawn
- **THEN** 该单元不被提交(取单元后 spawn 前的复查命中截断状态),网关不再收到新请求;
  该回归场景连跑多次(≥5)结果稳定,NEVER 间歇放行

#### Scenario: 特征漂移时优雅退化到冷却路径

- **WHEN** 网关换用新错误措辞,窗口内 5 个 crash 输出尾部均不含任何特征串
- **THEN** 分类全 unknown → 风暴截断不触发;快败冷却(事件驱动)照常触发自愈,熔断兜底不变

#### Scenario: 单次偶发限流 crash 不触发截断

- **WHEN** 窗口内仅 1 个单元 crash 且带限流特征,其余单元正常终态推进
- **THEN** crash 计数 < `--wave`,不截断;该单元留 pending 照常重派,后续磁盘推进把窗口清零

#### Scenario: 混入非限流 crash 不触发截断

- **WHEN** 窗口内 5 个 crash 中 4 个带限流特征、1 个 `unknown`(如脚本缺陷)
- **THEN** 风暴条件不满足(须全部 rate-limit),不截断;unknown crash 走既有语义(留 pending/
  零推进熔断兜底)

#### Scenario: 禁用 flag 回退

- **WHEN** 调用传 `--no-rate-limit-stop` 且发生限流 crash 风暴
- **THEN** 无快路径截断,冷却与熔断路径行为与未引入本机制逐字一致

#### Scenario: ok/failed/timeout/stall 终态不参与分类

- **WHEN** 某单元 output 尾部含 `429` 字样但以 ok 终态收尾(如子代理在报告文本里引用了 429)
- **THEN** 不产生任何 crash_cause 记录,不进风暴计数;仅 crash 终态参与分类

#### Scenario: 配额模式下等满窗口自我恢复,不截断

- **WHEN** 配额模式激活(`--quota-calls 100 --quota-window-s 600`),窗口内 `--wave` 个单元
  相继 crash 且全部带限流特征,但它们全部发生在**上一次配额窗口复位冷却完成之前**(即尚未
  有「等满窗口之后仍 429」的证据)
- **THEN** 截断不触发;这些 crash 走配额窗口复位冷却自我恢复(在飞照常收割);等满窗口后
  若磁盘推进恢复,run 继续直至完成

#### Scenario: 配额模式下等满窗口后仍限流才截断

- **WHEN** 承上场景:一次配额窗口复位冷却**完整等到终点**之后,观察窗口内再次累计
  `--wave` 个全部带限流特征的 crash
- **THEN** 截断触发(退出码 2 + 既有 stdout 字段),stderr recipe 在既有内容外增补一行
  「核对配额三 flag 与网关实际配额是否一致」;`--no-rate-limit-stop` 照旧可整体禁用

#### Scenario: 未配置配额模式时截断条件零变化

- **WHEN** 不传任何配额 flag,重复「限流 crash 风暴被立即截断」场景
- **THEN** 第 `--wave` 个全 rate-limit crash 即截断(不追加「等满窗口」前提),stdout/stderr/
  退出码与引入配额模式前逐字节一致
