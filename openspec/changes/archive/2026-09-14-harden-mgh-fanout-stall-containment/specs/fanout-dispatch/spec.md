# fanout-dispatch Delta

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
(宁慢勿杀依据不变);新增 `--stall-timeout-s` 默认 900(字节级失活判定,见失活检测
requirement;healthy 单元分钟级,5× 余量)。**dispatcher SHALL 在 spawn 任何单元前校验**:
调用方传 `--time-budget-ms` 时 MUST 同时显式传 `--call-timeout-s` 且其值 `< time-budget-ms × 0.8`,
且 `--stall-timeout-s < --call-timeout-s`——违反 SHALL 退出码 2 + 可操作 recipe(给出合规
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
  budget×0.8),或 `--stall-timeout-s ≥ --call-timeout-s`
- **THEN** dispatcher 退出码 2,stderr recipe 给出合规取值示例(如
  `--call-timeout-s 540 --stall-timeout-s 300`);零单元被 spawn、零枚举副作用

#### Scenario: 手动直跑(无 budget)默认组合可用

- **WHEN** 人开终端直跑 `fanout_runner.py --tier t1`(不传 `--time-budget-ms`)
- **THEN** 默认 `--stall-timeout-s 900 < --call-timeout-s 7200` 校验通过,正常运行;
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
- **THEN** 默认 7200s / 900s,文案注明四级超时不变式与「宁慢勿杀」依据(被杀单批无 marker
  留 pending,重派浪费一整跑)、失活判定的低误杀余量(healthy 单元分钟级 ×5)

### Requirement: 波次零推进收敛熔断(滚动磁盘进度窗口)

dispatcher SHALL 检测**零磁盘推进循环**:熔断观察点 SHALL 为以下两处——(a) 每新派发
K 个单元(K = `--stall-waves` × `--wave`);(b) 队列耗尽且在飞归零后重派生发现仍有待派
单元时(治「队列只剩坏死单元永远凑不满 K」的尾巴形态)。每个观察点从磁盘重派生一次
done+failed 终态计数(marker 唯一真相源);连续 `--stall-waves`(默认 2)次重派生计数
零增加、且队列仍有待派单元 → 视为收敛失败,**停止派发**,以退出码 2 fail-loud;stdout 摘要 JSON SHALL 报
`stalled:true` + `stalled_pending[]`(每个卡住单元的 id + 其 `.done`/`.failed` marker 在磁盘
上的实际存在性),stderr 给诊断 recipe(停止重派;跑 `resume_state.py --check` 诊断磁盘状态;
对照本摘要逐单元排查 marker 可写性/身份漂移)。单元失活被树杀属于终态事件但**不增加磁盘
计数**——同一单元反复失活(确定性挂死)SHALL 由本熔断截断并在 `stalled_pending[]` 披露。
正常早退(`partial:true`)、正常完成(`partial:false`)路径行为不变。理由〔窗口重锚:槽位
补位下不存在波次边界,判定锚平移为滚动磁盘进度;既治「每轮全量重派、磁盘进度恒零」的身份/
权限漂移,也治「同一单元确定性挂死反复烧」〕。

#### Scenario: 确定性挂死单元被熔断截断

- **WHEN** 某单元每次派发都失活被树杀(无 marker),其后续单元正常推进一波后队列只剩该单元
- **THEN** 连续 2 个滚动窗口磁盘计数零增加且该单元仍待派 → dispatcher 停止派发,退出码 2,
  stdout `stalled:true` + `stalled_pending[]`(该单元 id + marker 均不存在),stderr 含
  resume_state 诊断 recipe

#### Scenario: 失活杀后重派成功不触发熔断

- **WHEN** 某单元一次失活被树杀,重派后正常完成(done 计数增加)
- **THEN** 熔断不触发(计数窗口重置),dispatcher 照常继续

#### Scenario: 正常 partial 早退路径不受影响

- **WHEN** `--time-budget-ms` 软时限触发干净早退,窗口内 `done+failed` 有推进
- **THEN** 行为与熔断引入前逐字一致(退出码 0 + `partial:true`,编排器重派)

## ADDED Requirements

### Requirement: 在飞单元失活检测与外科手术式树杀(运行留痕)

dispatcher SHALL 对每个在飞子进程跟踪其 stdout/stderr 的**字节级最后输出时刻**:静默时长
≥ `--stall-timeout-s`(默认 900;`< 60` 拒识退出码 2)→ 判定该单元失活,**仅杀该单元的整个
进程树**(Windows `taskkill /pid <pid> /T /F`——`.cmd` shim 链下的真实 host-CLI 进程 SHALL
一并终止,NEVER 留孤儿继续烧 token;POSIX 进程组 SIGTERM),无 ack 无 marker → 单元留
pending 重派。`--call-timeout-s` 绝对兜底超时的杀路径 SHALL 使用同一树杀机制(取代仅杀直接
子进程的 `proc.kill()`——Windows 上那是 shim 层,真进程必成孤儿)。失活判定 SHALL 对全部
tier 一致;误杀边界由余量承担(healthy 单元分钟级,默认阈值 ~5×),被误杀单元重派自愈且
run.log 留痕可查。

**每单元运行留痕**:dispatcher SHALL 将每单元子进程的 stdout/stderr 尾部(各自截断上限)落盘
`<checkpoints>/<tier>/<单元 id 文件名安全形>.run.log`(文件名净化规则与 audit 副本同源,
`/ \ :` → `_`);ok 终态亦写(体积小),timeout/stall/crash/failed 终态 MUST 写;失活/超时的
stderr 诊断行 SHALL 附 run.log 绝对路径——事后定位以证据为准,NEVER 依赖事后猜测。

**stdout/心跳披露**:stdout 摘要 SHALL 新增 `stall_killed:[<unit>…]`(本次 run 失活树杀的
单元,既有字段不变);派发循环 SHALL 以默认 60s 周期向 stderr 打在飞披露行(在飞单元 id +
距其子进程上次输出的秒数),人从宿主 TUI 实时区分「正常慢」与「卡死」。

#### Scenario: 失活单元被外科树杀,其余单元不受影响

- **WHEN** 某在飞子进程静默超过 `--stall-timeout-s`,同批其余单元正常推进
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

### Requirement: headless fanout agent 无问询钉扎

opencode fanout agent 克隆(`init-scout-fanout`/`init-induct-fanout`/`init-synthesis-fanout`/
`init-rulewriter-fanout`/`sdr-review-fanout`)的 frontmatter `permission:` SHALL 显式钉扎
opencode 默认权限表中全部 **ask 类**为确定性终局:`external_directory: deny`、
`doom_loop: deny`(既有 `read/glob/grep/list/bash/edit` 钉扎不变)。headless 派发的子会话
SHALL NEVER 进入权限问询等待——问询面在无应答者的 `run` 模式下 = 永久挂(2026-02 前版本),
或有应答者时 = 静默 auto-reject(行为不可控);显式 deny = 工具报错、agent 按纪律适配,与
opencode 版本无关。树内读面不受影响(`read: allow` 钉扎保持,含 `.env` 类分析证据)。
claude 侧 spawn 面不变(`-p` headless + `--allowedTools` 白名单外自动拒绝,无问询挂死面)。

#### Scenario: fanout agent 定义 ask 类全部显式化

- **WHEN** 审阅任一 opencode fanout agent 克隆的 frontmatter `permission:` 块
- **THEN** `external_directory` 与 `doom_loop` 均为显式 `deny`,与既有 `read/glob/grep/
  list/bash/edit` 钉扎并存;无任何权限项依赖 opencode 默认 ask 行为

#### Scenario: 越目录读在 headless 下确定性拒绝

- **WHEN** fanout 子代理尝试读项目目录之外的路径(旧版 opencode 下该触发曾表现为权限问询挂死)
- **THEN** 该工具调用被显式 deny 规则立即拒绝(工具报错),agent 按任务模板纪律留在
  `{{repo}}` 树内继续;子进程不挂死、不等待任何应答者
