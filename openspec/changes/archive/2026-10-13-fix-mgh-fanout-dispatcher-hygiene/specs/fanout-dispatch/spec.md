# fix-mgh-fanout-dispatcher-hygiene — fanout-dispatch delta

## MODIFIED Requirements

### Requirement: 宿主 CLI 探测与 headless spawn 映射

dispatcher SHALL 探测可用宿主 CLI(`claude` / `opencode` / `dsh`,PATH 查找)并映射为各自的
headless subagent 调用,agent 名按 tier 参数化:scout → `init-scout-fanout`、t1 →
`init-induct-fanout`、t3 → `init-rulewriter-fanout`(opencode 侧均为 `mode: primary` 的
fanout agent 克隆,install 落位 `.opencode/agent/`;claude 侧经 `--agents` inline JSON 按同名
单元装载,工具面白名单等价于交互路径;dsh 侧经 `dsh --profile <mgh profile> --patch
<tier 装载文件> -` 装载,装载物由 install 从 `releases/dsh/agents/` 编译生成)。自动探测次序
SHALL 保持既有 claude/opencode 相对次序不变、`dsh` 仅追加在链末(已装双端的老机器默认行为
零变化);显式 `--host` 恒优先于探测。spawn 的 dsh 子进程 SHALL 使用 plain 输出模式(推理/
进度持续产生 stderr/stdout 字节流)供双 reader 静默检测消费,**NEVER** 用按步提交事件的机器
可读输出做活性信号(事件稀疏会喂大误杀窗口)。任务消息的正文 SHALL NOT 出现在 argv 里
(npm `.cmd` shim 实测在首个换行处截断多行 argv,对 dsh 同样成立):claude/opencode 经 stdin
管道传递;dsh headless 无 stdin 任务通道(实测),经**进程环境注入**投递——dispatcher 把任务
全文放入子进程 env 的 `MGH_TASK_TEXT`,tier 装载文件的固定模板行以该 env 覆盖任务来源,
argv 仅携带无内容占位符 `-`。子进程 cwd SHALL 为 `repo`(目标项目根);子进程 env SHALL
剥离 `PWD`(全部 host 形一致,dsh 形继续附加 `MGH_TASK_TEXT`)——opencode 按
`PWD ?? cwd` 解析项目归属,继承的 `PWD`(宿主外从其它目录的 shell 拉起 runner 时指向别处)
会使子会话把非 repo 目录认成项目;剥离后归属回落到显式 cwd = `repo`(claude/dsh 不读
`PWD`,剥离无副作用)。任一宿主 CLI 均不可用
→ 退出码 2 fail-loud,stderr 给出 recipe(回退 = 编排器现状波次式手派,行为不变)。spawn 的
子进程 SHALL 继承运行域守卫激活(经磁盘哨兵 `<target>/.mgh-init/.active`,env 不跨进程亦不
失效)。

#### Scenario: opencode 可用时走 opencode run

- **WHEN** `opencode` 在 PATH,dispatcher 以 `--tier t1` 派发一个 cluster 单元
- **THEN** 子进程命令形如 `opencode run --agent init-induct-fanout`(消息经 stdin),cwd =
  `repo`;完成后该单元 `.done` marker 出现

#### Scenario: 双 CLI 均缺失 fail-loud

- **WHEN** `claude`、`opencode`、`dsh` 三者在 PATH 全缺失
- **THEN** dispatcher 退出码 2,stderr 说明回退 recipe(编排器按现状波次式手派);无部分 spawn

#### Scenario: 仅装 dsh 的机器可完成扇出

- **WHEN** 机器只有 `dsh` 在 PATH,`--tier scout` 派发
- **THEN** 子进程命令形如 `dsh --profile <mgh> --patch <tiers/scout 装载文件> -`(任务全文
  经子进程 env `MGH_TASK_TEXT` 投递、argv 仅占位符),stall 检测吃其 plain 模式字节流;
  单元按既有 marker/ack 合同收口

#### Scenario: 双端既有次序不受 dsh 加入影响

- **WHEN** 机器同时装有 opencode 与 dsh
- **THEN** 自动探测仍选 opencode(dsh 在链末);`--host dsh` 显式指定才切 dsh

#### Scenario: 宿主外手动运行时子进程项目归属正确

- **WHEN** 维护者从非 repo 目录的 shell(其 `PWD` 指向别处)手动拉起
  `fanout_runner.py --tier t1`,host 探测为 opencode
- **THEN** spawn 的 opencode 子进程 env 不含 `PWD`,项目归属按 cwd = `repo` 解析(NEVER 把
  继承的 `PWD` 目录认成项目);dsh 形子进程 env 同样不含 `PWD` 且仍携带 `MGH_TASK_TEXT`

### Requirement: ack 状态机与 marker 真相源语义承接

dispatcher SHALL 承接既有 fan-out 状态语义:`ok`/`oversize` ack 或磁盘 `.done` marker → 单元
完成;`failed` ack → dispatcher 写该单元 `.failed` marker(body `{unit,reason,tier}`,`tier`
取当前 `--tier` 值;终态、不重试、不阻断当前波次);crash 无 ack 且无 marker → 单元仍
pending → `--resume` 重派(crash ≠ 确认失败)。stdout 摘要 JSON SHALL 报
`{repo, tier, total, done, failed, pending, wave, partial}`,退出码 `0/1/2`(成功含
partial/通用错/误用),stderr 进度与 stdout JSON 严格分流。dispatcher SHALL 幂等:重派已
`.done` 单元 NEVER 再 spawn(以磁盘 marker 为唯一真相源)。**marker 真相源的读取 SHALL
与其写入同源**:dispatcher 每波重派生 pending 时消费的枚举脚本 stdout,其 done/failed
判定 SHALL 由正向 marker 路径计算产生(见 `request-context-budget` 能力同名 requirement);
dispatcher SHALL NEVER 自行从记录体字段或文件名 stem 反推单元身份。

**marker 写入的 repo 锚定守卫**:dispatcher 的 `.failed` marker 写入(显式 `failed:` ack 与
spawn 前路径越树拦截两入口)SHALL 在任何 mkdir/写盘动作前校验目标 marker 路径 resolve 后
落在枚举 stdout `repo` 锚树内:树内 → 照旧写;树外 → NEVER 创建目录、NEVER 写文件,
stderr fail-loud 披露该路径与处置 recipe,该单元留磁盘 pending(无 marker)——有界性由既有
零推进熔断承担(`stalled_pending[]` 披露)。理由〔路径越树拦截的存在意义是防投毒输入;
响应动作若物化被检出的越树路径(mkdir + 写 marker),等于检测到投毒后反而执行投毒路径〕。

#### Scenario: failed ack 终态且不阻断

- **WHEN** 某单元 subagent 回 `failed <原因>` ack
- **THEN** dispatcher 写 `.failed` marker(body `{unit,reason,tier}`),该单元从后续波次移除,
  其余单元照常推进;stdout 摘要 `failed` 计数 +1

#### Scenario: 子进程 crash 后 resume 重派

- **WHEN** 某子进程异常退出且无任何 marker
- **THEN** 该单元无 `.failed`(crash ≠ 确认失败),`--resume` 重派时再次 spawn

#### Scenario: 已完成单元在重派生 pending 时消失

- **WHEN** 上一波某单元已写 `.json` 记录 + touch `.done` marker(含超长 id 截断编码文件名),
  dispatcher 进入下一波重派生 pending
- **THEN** 该单元不在新 `pending[]` 中(正向 marker 路径判定 done),NEVER 再次 spawn

#### Scenario: 越树 marker 路径不被物化

- **WHEN** 投毒/损坏的 pending 清单里某单元的 `failed_marker` resolve 后落在 repo 锚树外,
  dispatcher 对其判定路径越树(path-drift)
- **THEN** dispatcher NEVER 在该越树路径创建目录或写文件,stderr fail-loud 披露路径与处置
  recipe;该单元无 marker 留磁盘 pending,由零推进熔断以 `stalled_pending[]` 有界披露

#### Scenario: 树内 marker 照旧写入

- **WHEN** 某单元仅非 marker 路径字段(如 input_path)越树,其 `failed_marker` 本身 resolve
  在 repo 锚树内
- **THEN** 该单元标 failed(reason=path-drift)且 NEVER spawn 的既有语义不变,`.failed`
  marker 照旧写在树内路径

### Requirement: `--kill-stale` 检出并清理孤儿 runner 进程树(含 runner 已死的存活子进程)

`fanout_runner.py --kill-stale --tier <t> [--checkpoints <dir>] [--inputs-dir <dir>]`(其余 tier
artifact flag 同派发模式;`--checkpoints`/`--inputs-dir` 在 kill-stale 恢复模式 SHALL 可省略——
该模式下二者仅是扫描提示,省略时本功能照常工作,既有含参调用形不受影响)SHALL 处理 liveness
文件的两种残留形态:
① runner PID 仍存活且 cmdline 含 `fanout_runner.py` → 杀整个进程树(Windows
`taskkill /pid <pid> /T /F`,POSIX 进程组 SIGTERM)——覆盖「runner 还在跑」形态;
② runner PID 已死(或 cmdline 不匹配)但其 `children[]` 记录的宿主 CLI 子进程 PID 仍存活
且 cmdline 是宿主 CLI(`opencode`/`claude`/`dsh`)→ 逐个连树杀——覆盖「runner 与编排器被连带
硬杀(如用户杀掉整个 opencode 进程)、子进程 LLM 调用仍在烧 token」形态。两形态处理后均
删除 liveness 文件。stdout JSON 报 `{"kill_stale": {"killed": [{"pid","tier","kind":
"runner"|"child"}], "removed": [pid-file], "none": bool}}`;无任何 stale → `killed:[]`
退出码 0(幂等,可安全重复调用;存在被删除的 pid 文件时 `none` SHALL 为 false)。
破坏性守卫(R5.3b):真实杀进程 SHALL 先经 `--dry-run`(列出将杀 PID,不杀);缺
`--dry-run` 且检出将杀目标 → 退出码 2 + recipe。`--kill-stale` SHALL 对全部 tier 同构适用
(含未来新增 tier——机制只依赖 liveness 文件名约定,不含 tier 分支)。

**宿主 CLI 身份匹配锚定可执行 token**:② 形态的「cmdline 是宿主 CLI」判定 SHALL 锚定在
cmdline **首个空白分隔 token(可执行路径)的基名**:大小写不敏感比较,基名剥
`.exe`/`.cmd`/`.bat` 扩展后 ∈ {`opencode`, `claude`, `dsh`} 才判为宿主 CLI(spawn 侧经
`shutil.which` 解析,Windows 上 npm CLI 是 `.cmd`/`.exe` 绝对路径形)。匹配 SHALL NOT 使用
全命令行子串包含——命令行任意位置含宿主名的无关进程(编辑器打开 `claude-notes.txt`、
脚本路径恰含 `dsh` 字样等)会被整树强杀;不匹配的存活子进程按既有「PID 复用防护」路径处理
(不杀、清 liveness 文件)——漏杀是安全方向,误杀不可接受。

**cmdline 探测的跨版本可用性(Windows)**:进程命令行探测 SHALL 不依赖单一平台工具——
SHALL 先试经典探测途径,失败(工具缺失/不可执行)时 SHALL 回退到 Windows CIM 探测
(PowerShell `Get-CimInstance Win32_Process`,PowerShell 为 Windows 核心组件,零附加依赖);
回退探测 SHALL 有单次超时与确定性输出解析。当 PID 确认存活但两种探测均不可用、cmdline 无法
判定时,SHALL fail-loud:stderr 披露探测不可用与后果,SHALL NOT 删除任何 liveness 文件,
SHALL NOT 以退出码 0 报告成功——孤儿归属无法判定时证据 SHALL 保留(孤儿进程 SHALL NOT 在
「静默零杀 + 销毁证据 + 假成功」路径上流失)。

**扫描根锚定**:kill-stale 的 liveness 扫描根 SHALL 与派发侧写入根使用**同一锚定逻辑**——
SHALL 锚定到 liveness 文件实际所在的 run 目录(经既有 plan-path 再锚定),SHALL NOT 按
「tier 参数形态的朴素父目录推断」扫描(该推断对目录形参数/仓根形参数会扫到无关目录而漏检)。

#### Scenario: 孤儿 runner 被检出并杀死

- **WHEN** 上次运行被宿主硬杀,runner 进程仍在跑,liveness 文件残留且 PID 活跃
- **THEN** `--kill-stale --dry-run` 列出该 PID(kind=runner);去掉 `--dry-run` 后进程树
  终止、liveness 文件删除、stdout `killed` 非空、退出码 0

#### Scenario: runner 已死但记录的子进程仍存活(宿主连带被杀形态)

- **WHEN** 用户杀掉整个 opencode 进程(runner 是其 Bash 子进程,连带死亡),但 runner 记录
  在 `children[]` 里的宿主 CLI 子进程(opencode run 单元)仍存活烧 token,liveness 文件残留
- **THEN** `--kill-stale` 检出 runner PID 已死、`children[]` 中 PID 存活且 cmdline 为宿主
  CLI,逐个连树杀(kind=child);被杀单元无 `.done`/`.failed` marker → 留 pending,本轮
  resume 重派(重派前先经本命令清理,无双跑)

#### Scenario: 无孤儿时幂等空转

- **WHEN** 无残留 liveness 文件(或文件残留但记录的所有 PID 均已死/被复用为非 fanout 进程)
- **THEN** `--kill-stale` 退出码 0、`killed:[]`,残留文件被清理,不杀任何无辜进程

#### Scenario: PID 复用误杀防护

- **WHEN** liveness 文件残留但其中某 PID 已被操作系统复用为一个非 fanout/宿主 CLI 进程
- **THEN** `--kill-stale` 不杀该进程,仅删除残留 liveness 文件(runner 按 cmdline 含
  `fanout_runner.py`、子进程按 cmdline 为宿主 CLI 双条件才杀)

#### Scenario: 命令行含宿主名的无关进程不被误杀

- **WHEN** liveness 文件残留的 `children[]` 中某 PID 已被复用,其 cmdline 为
  `notepad C:\notes\claude-meeting.txt`(可执行 token 基名是 `notepad`,宿主名只出现在
  参数里)
- **THEN** 可执行 token 锚定匹配不命中,该进程 NEVER 被杀;其记录按 PID 复用防护路径处理
  (不杀、liveness 文件照常清理);真宿主 CLI 子进程(`opencode run --agent …`、
  `C:\…\opencode.cmd run …`、`dsh --profile mgh …`)仍被正确分类连树杀

#### Scenario: 经典探测工具缺失时 CIM 回退检出目标

- **WHEN** Windows 上经典 cmdline 探测工具不存在(新版 Windows 已移除),孤儿 runner 与
  宿主 CLI 子进程真实存活,liveness 文件残留
- **THEN** 探测经 CIM 回退取得两者 cmdline,按双条件正确分类出 runner 与 child 目标;
  `--dry-run` 列出目标、真实执行连树杀并删除 liveness 文件(NEVER「零 targets + 删证据 +
  假成功」)

#### Scenario: 探测完全不可用时保全证据并 fail-loud

- **WHEN** PID 存活但两种 cmdline 探测途径均不可用(如受控环境禁用两者)
- **THEN** `--kill-stale` stderr 披露探测不可用,不删除任何 liveness 文件,退出码非 0;
  恢复决策留给调用方(NEVER 静默零杀且销毁证据后报成功)

#### Scenario: sdr 形态调用的扫描根命中真实 run 目录

- **WHEN** sdr tier 的规范恢复调用形执行(kill-stale + sdr 参数形态),liveness 文件位于
  run 目录
- **THEN** 扫描根锚定到该 run 目录,liveness 被检出并按形态处理(NEVER 扫到仓库父目录/
  仓根而报 `none:true`)

#### Scenario: 恢复配方省略 artifact 参数可运行

- **WHEN** 调用方按仓内恢复配方原样执行 kill-stale(仅 `--kill-stale --tier <t>`,省略
  `--checkpoints/--inputs-dir`)
- **THEN** 命令进入 kill-stale 分支正常执行(NEVER 因参数必填校验在 argparse 层退出)

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

**树杀失败的检测与升级**:树杀调用 SHALL 检查其成败:POSIX 侧 SIGTERM 后 SHALL 在短宽限内
复查该进程组存活性,仍存活 SHALL 升级 `SIGKILL`;Windows 侧 `taskkill` 失败 SHALL 重试一次。
升级后仍确认杀失败时,dispatcher SHALL:① 该单元本 run 内 NEVER 再重派(不回队、不进 drain
re-list 再队——幸存进程拥有该单元,其终态 marker 由幸存者落盘或由后续 `--resume` 重派收口);
② 该子进程 PID SHALL 保留在 liveness `children[]`(供 `--kill-stale` 检出清理,NEVER 摘除成
不可追踪孤儿);③ stderr fail-loud 披露 + stdout 摘要新增 `kill_failed:[unit…]`(仅确认杀
失败时出现,无则省略)。杀成功路径的重派与 liveness 摘除语义逐字不变。

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
`<checkpoints>/<tier>/<单元 id 文件名安全形>.run.log`(文件名编码与枚举器 marker 路径、audit
副本**同源单一函数**:替代 `/ \ :` 为 `_` 且超长 stem 按 200 上限截断保判别尾——
`init_tier.safe_unit_filename` 的别名;超长 id 的留痕/审计文件 NEVER 超 NTFS 255 上限写失败);
ok 终态亦写(体积小),timeout/stall/crash/failed 终态 MUST 写;失活/超时的
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

#### Scenario: POSIX SIGTERM 后短宽限内升级 SIGKILL

- **WHEN** POSIX 下某失活单元的进程组对 SIGTERM 无响应(宽限窗口内仍存活)
- **THEN** 树杀升级为对同进程组的 SIGKILL;升级仍失败才走「杀失败」处置(不重派 + PID
  保留 + `kill_failed` 披露)

#### Scenario: 杀失败时单元不重派且 PID 保留可追踪

- **WHEN** 某单元失活树杀,但 SIGKILL 升级后仍确认失败(幸存进程继续运行)
- **THEN** 该单元本 run 内不再被重派(不回队、drain re-list 不再收),stdout 摘要
  `kill_failed` 含其 id;其 PID 留在 liveness `children[]`,`--kill-stale --dry-run` 可
  检出;幸存进程若自行完成,marker 照常落盘,后续 resume 按 marker 判定

#### Scenario: 超长 id 的 run.log 与 audit 副本可写

- **WHEN** 某单元 canonical id 超过 200 字符(stem 上限)
- **THEN** 其 `.task.md`/`.run.log` 文件名经共享安全编码(截断保判别尾)落盘成功,路径总长
  ≤ NTFS 255 上限;短 id 的文件名与既有形态逐字节一致

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
