## MODIFIED Requirements

### Requirement: 在飞单元失活检测与外科手术式树杀(运行留痕)

dispatcher SHALL 对每个在飞子进程分别跟踪其 stdout 与 stderr 的**字节级最后输出时刻**;
当且仅当**两条流都没有新字节**已经过 `--stall-timeout-s`(默认 900;`< 60` 拒识退出码 2)
才判定该单元失活(等价表述:静默时长取两条流最后输出时刻中的**较新者**;任一条流有字节即
重置,NEVER 以任一条流的陈旧时刻单独判失活——空流的路 MUST NOT 使健康单元被判失活),
→ **仅杀该单元的整个进程树**(Windows `taskkill /pid <pid> /T /F`——`.cmd` shim 链下的真实
host-CLI 进程 SHALL 一并终止,NEVER 留孤儿继续烧 token;POSIX 杀该单元自己的进程组 SIGTERM),
无 ack 无 marker → 单元留 pending 重派。**树杀的作用域 SHALL 严格收敛于被杀单元**:杀一个
失活单元 NEVER 导致 dispatcher 自身终止——POSIX 下单元子进程 SHALL 在 spawn 时自成会话/
进程组(`start_new_session`),使 `killpg` 只命中该单元自己的树;Windows 分支不受影响。
`--call-timeout-s` 绝对兜底超时的杀路径 SHALL 使用同一树杀机制(取代仅杀直接子进程的
`proc.kill()`——Windows 上那是 shim 层,真进程必成孤儿)。失活判定 SHALL 对全部 tier 一致;
误杀边界由余量承担(healthy 单元分钟级,默认阈值 ~5×),被误杀单元重派自愈且 run.log
留痕可查。

**每单元运行留痕**:dispatcher SHALL 将每单元子进程的 stdout/stderr 尾部(各自截断上限)落盘
`<checkpoints>/<tier>/<单元 id 文件名安全形>.run.log`(文件名净化规则与 audit 副本同源,
`/ \ :` → `_`);ok 终态亦写(体积小),timeout/stall/crash/failed 终态 MUST 写;失活/超时的
stderr 诊断行 SHALL 附 run.log 绝对路径——事后定位以证据为准,NEVER 依赖事后猜测。

**stdout/心跳披露**:stdout 摘要 SHALL 新增 `stall_killed:[<unit>…]`(本次 run 失活树杀的
单元,既有字段不变);派发循环 SHALL 以默认 60s 周期向 stderr 打在飞披露行(在飞单元 id +
距其子进程上次输出的秒数),人从宿主 TUI 实时区分「正常慢」与「卡死」;该披露的静默秒数
SHALL 与失活判据同源(取两条流最后输出时刻的较新者),NEVER 把从未产生字节的那条流的
spawn 时刻当成静默起点。

**进程组隔离的边界披露**:单元子进程自成会话后,交互式终端向 dispatcher 发送的中断信号
(如 Ctrl-C)SHALL NOT 再连带终止在飞单元子进程;这些进程成为孤儿,但 SHALL 由既有 liveness
登记(`<init-dir>/fanout_runner.<tier>.pid` 的 `children[]`)覆盖,并可由既有 `--kill-stale`
检出清理。`--kill-stale` 与失活段的 `--help` 文案 SHALL 明示该边界及补偿路径。

#### Scenario: 失活单元被外科树杀,其余单元不受影响

- **WHEN** 某在飞子进程两条输出流均静默超过 `--stall-timeout-s`,同批其余单元正常推进
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
  超过 `--stall-timeout-s`
- **THEN** 该单元 MUST NOT 被判失活(其静默时长按两条流中较新者计 = 最近一次 stdout 字节的
  时刻);单元正常推进至终态

#### Scenario: 树杀不终止 dispatcher 自身

- **WHEN** POSIX 下 dispatcher 对某失活单元执行树杀,同批其余单元仍在飞
- **THEN** 只有该单元的进程树被终止,dispatcher 进程 MUST 继续存活并照常补位派发;该轮
  运行 SHALL 能继续到软时限或队列耗尽,并打印 stdout 汇总(退出码 0 或按既有语义)

#### Scenario: 双路皆静默仍判失活

- **WHEN** 某在飞子进程的 stdout 与 stderr 均超过 `--stall-timeout-s` 未产生字节
- **THEN** 仍按本 requirement 判失活并树杀,该单元留 pending 重派——判据放宽 MUST NOT
  变成永不判定
