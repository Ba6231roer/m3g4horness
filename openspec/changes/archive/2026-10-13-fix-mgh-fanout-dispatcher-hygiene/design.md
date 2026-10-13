# fix-mgh-fanout-dispatcher-hygiene — Design

> 范围:`core/scripts/fanout_runner.py` 单文件六处异常分支收口。全部改动位于 tier 无关的
> 共享分支,六域(scout/t1/t2/t3/sdr 及其宿主三态)共用面零分叉新增。评审行号已因
> a092e65 重写失效,本文按内容锚定(HEAD = 4b35700)。

## D1 — 冷却等待 gate 条件简化(治忙等)

现状:主循环的冷却 gate 为
`if (monotonic() < cooldown_until and (queue or inflight) and not inflight): sleep; continue`
——`(queue or inflight) and not inflight` 化简后即「队列非空」。熔断前退避恰在 **drain 点**
(队列空、在飞零)武装 `backoff_pending` + `cooldown_until = now + --cooldown-s`,此后循环
顶部退避判定因冷却未到期不动作、gate 因队列空不 sleep、`if backoff_pending: continue` 无
等待回顶 → 零 sleep 自旋,默认烧满一个核 300s。

修法:gate 条件改为 `monotonic() < cooldown_until and not inflight`——冷却生效中且无在飞
即休眠(≤1s 分片),不再要求队列非空。论证:冷却期间 `_fill` 本就不派发新单元(有
`cooldown_until` 前置检查),队列非空时唯一正确动作也是等;在飞非零时走收割循环(1s poll
粒度)不受影响。**被否的替代**:在 `if backoff_pending: continue` 前插 sleep——治标(其他
两态皆空的冷却来源仍可构造),且把「冷却等待」语义拆到两处。gate 单点收敛是正确层。

## D2 — 树杀失败检测、升级与「幸存者拥有单元」处置

现状:stall/timeout 两调用点 `_kill_tree(proc.pid)` 不查返回值;`_kill_tree` POSIX 侧只发
SIGTERM(killpg 失败回退 os.kill SIGTERM),无升级。杀失败时单元照常 `queue.append(unit)`
重入队 → 重新 spawn 与幸存进程并发双跑、竞写 checkpoint;`_terminal_children_rm(child_pid)`
把 pid 从 liveness `children[]` 摘除 → 幸存进程成不可追踪孤儿。

修法三层:

1. **升级**:`_kill_tree` POSIX 侧 SIGTERM 后短宽限(实现常量 ~1.5s,分片复查 `os.killpg`
   的 ProcessLookupError)内进程组仍存活 → 升级 SIGKILL(组杀 + 直接 kill 兜底);Windows 侧
   `taskkill` 非零退出码重试一次。返回 True = 确认进程组消失或 SIGKILL 已送达;False = 升级
   后仍无法杀(权限拒绝等)。
2. **调用点检查**:stall/timeout 路径 `if not _kill_tree(...)` → 置 kill-failed 标志随
   `_run_unit` 返回;杀成功路径语义逐字不变。
3. **处置 = 幸存者拥有单元**:确认杀失败时 ① 该 uid 记入本 run 的 `kill_failed` 集合,
   **不**重入队、drain re-list 的 `queue.extend` 排除该集合(理由:幸存进程仍在执行该单元
   的任务,它自行完成时 marker 照常落盘;再派发必然双跑。幸存者若死透,单元留磁盘 pending,
   由编排器 `--resume` 或 `--kill-stale` 收口)② **跳过** `_terminal_children_rm`,pid 留在
   liveness 供 `--kill-stale` 检出 ③ stderr fail-loud(recipe 指向 `--kill-stale --dry-run`)
   + stdout 摘要新增 `kill_failed:[unit…]`(可选键,同 `runtime_p50_s` 惯例:无则省略)。

**被否的替代**:杀失败仍重入队 + 仅披露——双跑竞写 checkpoint 是数据完整性问题,披露不消除
竞态;杀失败即整体退出码 2——过度反应(其余单元可正常推进,单点失败不应废掉整 run,与
「挂死只占一槽」的既有设计相悖)。

## D3 — marker 写入的 repo 锚定守卫(治「检测到投毒后执行投毒路径」)

现状:`_write_failed_marker` 直接物化 unit 记录的 `failed_marker` 路径(`p.parent.mkdir`
+ `write_text`)。`failed_marker` 本身是 `tier["path_fields"]` 之一——`_anchor_check` 检出
marker 越树的单元,响应动作恰是向那个越树路径 mkdir + 写文件。

修法:守卫放 `_write_failed_marker` **单点**(显式 `failed:` ack 与 path-drift 两入口同判,
防御纵深):写盘前 resolve 校验目标在 repo 锚树内。树内 → 照旧(各 tier 既有场景语义不变);
树外 → NEVER mkdir/写盘、stderr fail-loud(recipe:检查 `--checkpoints` 根是否被指到锚外 /
pending 清单是否被篡改)、该单元不进 `failed_written`(不虚增摘要 failed 计数——marker 是
唯一真相源,计数无盘面凭据即造假)、留磁盘 pending。

**有界性论证**:单元无 marker → 枚举器重派生仍列它 → 派发 → 再次拦截(不写)→ 磁盘终态
计数零推进 → 既有零推进熔断(窗口 → 一次退避 → `stalled:true` 退出码 2 + `stalled_pending[]`
+ resume_state recipe)天然收口,无需新增任何循环控制。这与「显式失败上浮、由用户处置」的
既有毒输入哲学一致。

## D4 — kill-stale 身份匹配锚定可执行 token(治子串误杀)

现状:`_classify_targets` 子进程判定含析取项 `cl.find(h) >= 0`(全命令行小写子串包含)——
`notepad C:\notes\claude-meeting.txt` 这类进程被整树强杀。spawn 侧 `_host_exe` 经
`shutil.which` 解析,children 记录的 cmdline argv[0] 是绝对路径形(`C:\…\opencode.cmd`)或
裸名;子串析取项大概率是为兼容 `.cmd`/绝对路径形而加的过度补丁。

修法:匹配改为「cmdline 首个空白分隔 token → 路径基名(统一分隔符、小写)→ 剥
`.exe`/`.cmd`/`.bat` 扩展 → ∈ {opencode, claude, dsh}」;删除子串析取项。**误杀方向归零,
漏杀方向退回既有 PID 复用防护路径**(不杀、清 liveness 文件)——PID 复用守卫的设计取向本就
是宁漏勿错(漏杀的孤儿下次 `--kill-stale` 或人工处置,误杀的无关进程无法挽回)。runner 侧
`_RUNNER_MARK in cl` 维持不变:表面窄(`fanout_runner` 组合词,且 runner 的 cmdline 形态
多样——py/python/绝对路径/直接执行),_argv token 锚定反而会把 `py fanout_runner.py` 形
误判为非 runner( argv[0]=py);收益不抵回归风险,本批不动(留观察)。

## D5 — spawn env 剥离 PWD(镜像姊妹修复)

现状:`_run_unit` 的 env:opencode/claude 形 `env=None`(全量继承,含 `PWD`);dsh 形
`dict(os.environ)` + `MGH_TASK_TEXT`。opencode 按 `PWD ?? cwd` 解析项目归属;Git Bash 总是
导出 `PWD`,宿主外从其它目录手动拉起 runner 时,显式 `cwd=repo` 被 `PWD` 压制 → 子会话把
错误目录认成项目。姊妹脚本 `mgh_sdr_launch.py`(sdr 批次 P3 修复)已修同形并实机验证
(2026-10-13 真仓回归 run2 行为级通过)。

修法:镜像其形态——全部 host 统一构造 `env = {k: v for k, v in os.environ.items() if k != "PWD"}`,
dsh 形继续附加 `MGH_TASK_TEXT`;`env=None`(opencode/claude)改为传显式 dict(claude/dsh
不读 `PWD`,剥离无副作用)。主路径(编排器 Bash cwd=repo)行为零变化——`PWD` 与 `cwd`
同值时剥离不改变归属解析结果。

## D6 — `_safe_name` 归一 `init_tier.safe_unit_filename`(镜像枚举器别名形态)

现状:`fanout_runner._safe_name` 只做 `/ \ :` → `_`,自称 mirrors list_scout_batches,但
后者早已是 `init_tier.safe_unit_filename` 的别名(含 200 stem 截断保判别尾);私有拷贝漂移
的后果:超长 id 的 `.task.md`/`.run.log` 超 NTFS 255 上限写失败仅 warn(audit 写有 try/
except;marker 路径来自枚举器、已用截断编码,不受影响)。

修法:镜像 `list_scout_batches` 的别名形态——`from init_tier import safe_unit_filename`,
`_safe_name = safe_unit_filename`(兄弟导入纪律已在位:`sys.path.insert(0, dir-of-file)`)。
短 id(≤200)输出逐字节不变;超长 id 获得与 marker 同源的截断编码,audit/run.log 文件名与
枚举器物化路径**同名一致**(一致性净提升,两个 id 中段碰撞的判别尾机制同源继承)。

## D7 — stdout 契约增量最小化

唯一新增键 `kill_failed:[unit…]`,「无则省略」(镜像 `runtime_p50_s`/`stall_window_s` 既有
惯例);其余字段零增删。消费者影响:编排器按需读键、缺键即无杀失败——无需改任何壳/契约
消费面。

## D8 — 测试策略(先红后绿;harness 纪律)

- **忙等(F1)**:不以墙钟/CPU 占用断言(慢且脆)——monkeypatch `time.sleep` 计数:构造
  drain 点退避武装 + 冷却生效态,断言等待期内 `sleep` 被调用(现状零调用 → 红)。
- **杀失败(F2)**:mock 层双轨——`_kill_tree` 返回 False 的 stall 路径断言(kill_failed
  披露/不重队/liveness 保留);POSIX 升级逻辑在 Windows 开发机上以 monkeypatch
  `os.killpg`/`os.kill`/`os.name` 验证信号序列(SIGTERM → 复查存活 → SIGKILL)。真子进程
  面(既有 `TestRunUnitTreeKill`)不扩杀失败形态(构造「杀不死」的真进程不安全)。
- **越树 marker(F3)**:pending 清单注入 `failed_marker` 指向 repo 外临时目录 → 断言该
  目录不存在、无 marker 文件、stderr 含 recipe;树内 marker 的既有用例不变。
- **PWD(F5)**:monkeypatch `subprocess.Popen` 捕获 env → 三 host 形断言无 `PWD`、dsh 形
  仍有 `MGH_TASK_TEXT`。
- **kill-stale 锚定(F4)**:沿用既有 mock `_pid_cmdline` 的测试形态,喂「宿主名仅在参数」
  与「绝对路径 .cmd 形」两组 cmdline。
- **_safe_name(F6)**:>200 stem 的 id 断言 `.task.md`/`.run.log` 落盘成功且路径 ≤255;
  与 `init_tier.safe_unit_filename` 样本集 parity。
- **harness 纪律**:in-process 调 `fanout_runner.main()` 一律显式 `--cooldown-s 0`
  (R5.8:漏传 = 单测静默挂 5 分钟);忙等红测试本身需冷却生效,用极小值(如 `--cooldown-s 1`)
  + monkeypatch sleep,勿用默认 300。

## D9 — 六域共用面与批次边界

- 全部改动在共享分支,无 tier 分叉;定向面跑完 MUST 确认 `test_fanout_runner` 内 sdr tier
  用例零回归。
- **已修项不重修**(评审同域,更早 sdr 批次顺带落):kill-stale 的 wmic→CIM 回退、退出摘要
  failed 双计。
- **批次边界**:run_config `budgets.max_unit_bytes` 无消费者(runner 不透传 `--max-unit-bytes`)
  属批次 5(枚举/聚合/切片口径),本批不碰——尽管同文件,锁步注记见战役交接文档三.3。
- 守卫三镜像(`block_adhoc_scripts.py`)零涉及;壳/agent/契约文档零涉及(唯一 stdout 增量
  是可选键,无契约文档记载 failed/kill 类计数的全量清单需要更新——核对过
  `core/contracts/fanout/*` 无 kill_failed 同名先行键)。
