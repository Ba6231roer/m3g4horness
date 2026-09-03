## ADDED Requirements

### Requirement: Dispatcher liveness 登记(启动写、退出删、波次记子进程)

`fanout_runner.py` 派发模式(非 `--kill-stale`/`--purge-audit`)启动时 SHALL 原子写 liveness
文件 `<init-dir>/fanout_runner.<tier>.pid`(body `{pid, started_ts, tier, host, cmdline,
children[]}`;`pid` = 当前进程 PID,`cmdline` = `sys.argv` 原样列表;`children[]` = 当前
在飞宿主 CLI 子进程的 `{pid, unit, tier}` 列表,每波 spawn 后原子更新——子进程经
`subprocess.Popen` spawn 以取得 PID),任一退出路径(正常完成、partial 早退、异常退出)
SHALL 删除之(try/finally 兜底;进程被硬杀时文件残留——残留文件由 `--kill-stale` 的 PID
存活检测消歧,非错误)。该文件是**人机两用孤儿信号**:编排器/后续 resume 据此检出「还有
(或曾有)fanout 在跑」,不作为进度真相源(进度真相源仍是磁盘 marker)。

#### Scenario: 派发运行期间 liveness 文件存在且含在飞子进程

- **WHEN** runner 以派发模式运行(tier 任一)且已进入波次循环
- **THEN** `<init-dir>/fanout_runner.<tier>.pid` 存在,body 携带当前进程 PID、`tier`/`host`
  与 `children[]`(在飞子进程 PID + 单元 id)

#### Scenario: 干净退出删除 liveness 文件

- **WHEN** runner 完成(含 `partial:true` 早退)退出
- **THEN** liveness 文件不存在;再次以同参运行不会把旧文件误判为活跃实例

### Requirement: `--kill-stale` 检出并清理孤儿 runner 进程树(含 runner 已死的存活子进程)

`fanout_runner.py --kill-stale --tier <t> --checkpoints <dir> --inputs-dir <dir>`(其余 tier
artifact flag 同派发模式)SHALL 处理 liveness 文件的两种残留形态:
① runner PID 仍存活且 cmdline 含 `fanout_runner.py` → 杀整个进程树(Windows
`taskkill /pid <pid> /T /F`,POSIX 进程组 SIGTERM)——覆盖「runner 还在跑」形态;
② runner PID 已死(或 cmdline 不匹配)但其 `children[]` 记录的宿主 CLI 子进程 PID 仍存活
且 cmdline 是宿主 CLI(`opencode`/`claude`)→ 逐个连树杀——覆盖「runner 与编排器被连带
硬杀(如用户杀掉整个 opencode 进程)、子进程 LLM 调用仍在烧 token」形态。两形态处理后均
删除 liveness 文件。stdout JSON 报 `{"kill_stale": {"killed": [{"pid","tier","kind":
"runner"|"child"}], "removed": [pid-file], "none": bool}}`;无任何 stale → `killed:[]`
退出码 0(幂等,可安全重复调用)。破坏性守卫(R5.3b):真实杀进程 SHALL 先经
`--dry-run`(列出将杀 PID,不杀);缺 `--dry-run` 且检出将杀目标 → 退出码 2 + recipe。
`--kill-stale` SHALL 对全部 tier 同构适用(含未来新增 tier——机制只依赖 liveness 文件名
约定,不含 tier 分支)。

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

### Requirement: 派发循环 stderr 心跳(宿主 TUI 实时可见)

`fanout_runner.py` 派发循环 SHALL 在每个关键节点向 **stderr**(诊断流,R5.3b 分流不变)打
单行心跳:`[fanout_runner <tier>] wave=<k> unit=<id> <event> done=<d>/<total>`(event ∈
spawn|ok|failed|timeout|crash|wave-end;至少覆盖:每单元 spawn、每单元终结状态、每波结束)。
心跳 SHALL 携带自首次 spawn 起的相对耗时(`+HH:MM:SS`)。stdout 契约 SHALL 零变化(stdout
仍只含末尾一行 JSON 摘要)。宿主 TUI(opencode)对 running 态 Bash 工具实时渲染
stdout+stderr 合并流的滑动尾部(源码核实:`shell.ts` `handle.all = merge(stdout, stderr)` →
`metadata.output` → TUI 刷新),故心跳行 = 实时进度可见;claude 侧 stderr 亦入 Bash 结果。

#### Scenario: opencode TUI 实时显示 fanout 进度

- **WHEN** runner 在 opencode 会话内经 Bash 工具长跑,单元陆续完成
- **THEN** TUI 该 Bash 工具的输出区持续刷新心跳行(wave/unit/done 计数随推进变化),
  用户无需第二终端即可区分「正常慢」与「卡死」

#### Scenario: stdout JSON 契约不变

- **WHEN** 审阅 runner stdout 全部输出
- **THEN** stdout 仍只在结束时输出一行结构化 JSON 摘要(shape 与既有字段不变);心跳只出现在
  stderr
