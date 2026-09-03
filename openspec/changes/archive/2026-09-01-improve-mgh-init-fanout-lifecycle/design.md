# improve-mgh-init-fanout-lifecycle — Design

## Context

`fanout_runner.py`(core/scripts,stdio 契约见其 `--help`)以波次循环 spawn 宿主 CLI
(`opencode run` / `claude -p`)子进程。编排器侧中断(claude Bash per-call 硬杀、Ctrl-C、
崩溃)只终止 runner 进程本身;Windows 上 `subprocess` 无进程组自动清理,**宿主 CLI 子进程
树存活**并继续烧 token、完成后写 `.done` marker,与 resume 重派的同单元竞态写同一
`checkpoint_path`。现状无任何孤儿检出入口。

可观测侧(本 change 回源码核实,opencode 1.18.18,`C:/DEV/opencode`):

- Bash 工具 spawn 子进程后消费 **stdout+stderr 合并流**的滑动尾部:
  `packages/opencode/src/tool/shell.ts:484-531`(`handle.all = Stream.merge(stdout, stderr)`,
  见 `packages/core/src/cross-spawn-spawner.ts:264`),每 chunk 更新
  `metadata.output = preview(last + chunk)`,尾部 `MAX_METADATA_LENGTH = 30_000` chars
  (`shell.ts:27,220-223,498`)。
- TUI running 态实时渲染 `metadata.output`:`packages/tui/src/routes/session/index.tsx:2054-2110`
  (`Shell` 组件,`isRunning()` → spinner + `output()` 直接 text 渲染,collapse 到 ~10 行)。
- 结论:**Q2 可行**——runner 往 stderr 持续打心跳行,TUI 即实时刷新;无需任何 opencode
  插件/协议改动。现状「停在一行不动」的根因是 runner 每波才打 1-2 行 stderr 且波内 minutes
  级静默(单行 stderr 其实已在刷,只是信息密度=0 且 collapse 只显 10 行尾部)。

计数口径(Q3,回源码核实):

- `resume_state.py:352` `t1_done_count = _count_markers(t1_cp, "*.json.done")` —— **纯
  文件 glob 计数**,不读 body(exclude 仅 scout tier 的 merge/audit)。stdout stderr 行的
  `t1:472/830` 的 472 = `*.json.done` 文件数;830 = `clusters.json::clusters[]` 长度。
- `checkpoints/t1/` 目录 491 个文件 = `.done` 472 + `.failed` F + `<id>.json` 记录体若干
  (每个 done marker 的 sibling 记录体)。**不存在数据丢失**,是两个口径:
  resume_state 口径(marker 文件计数)vs `ls` 眼中的目录条目数。
- `list_clusters.py:164-186` 是第三口径:done = 记录体 `unit` 字段去重集合(shard 感知,
  orphan marker warn+按 stem 兜底)。与 resume_state 口径在无 shard、无 orphan 时相等;
  有 shard 时 list_clusters 按单元数、resume_state 按 marker 文件数,两者自然不一致
  (`fanout_runner` 的 done 摘要取自 list_* stdout,即 list_clusters 口径——这也解释了
  resume_state 与 runner 摘要间可能的小差异)。

## Goals / Non-Goals

**Goals:**

- 孤儿 fanout 确定性检出 + 主动清理:`--kill-stale`,幂等,PID 复用不误杀。
- resume 路径第一跳可见:`resume_state.py` 点名 stale fanout + recipe。
- 长跑 stderr 心跳:opencode TUI / claude Bash 输出实时可见进度,零宿主改动。
- 全 tier 同构(机制只依赖文件名约定,未来 tier 免费获得)。
- Q3 口径文档化,消除「计数不符 = 丢数据」误读。

**Non-Goals:**

- 不做 runner↔编排器双向心跳/租约(单一 liveness 文件 + PID 探测已满足「检出→杀」需求;
  租约引入时钟/竞态复杂度,收益不成比例)。
- 不杀「孤儿宿主 CLI 子进程」本身(单元级孤儿)。杀 runner 树即覆盖主要 token 消耗源;
  单元级残留由既有磁盘 marker 语义兜底(无 marker → pending → 重派;带 `.done` → 终态,
  竞态窗口已收窄到「杀与写 marker 之间」的秒级)。list_* 重派前重扫 marker,双写窗口
  由「marker 幂等 touch + 记录体原子写」承担。
- 不改 stdout JSON shape、退出码、波次循环、超时不变式、marker 语义。
- 不做 opencode 插件/协议级进度(TUI 渲染已由宿主原生提供)。

## Decisions

- **D1 liveness 文件(`<init-dir>/fanout_runner.<tier>.pid`)而非锁文件**:body 记
  `{pid, started_ts, tier, host, cmdline, children[]}`。锁语义(互斥)不需要——同 run 目录
  并发两个 runner 是用户显式动作;liveness 语义(「曾有/有 runner」)才是 resume 要的信号。
  **`children[]` 是关键**:中断的真正受害者是 runner spawn 的宿主 CLI 子进程(烧 token 的
  是它们),而最常见中断形态(用户杀整个 opencode / 宿主 per-call 硬杀)是 runner 与编排器
  连带死亡——只记 runner PID 会在「runner 已死、子进程存活」形态下漏杀。故每波 spawn 经
  `subprocess.Popen`(替代 `subprocess.run`,以取得子 PID)后原子更新 `children[]`
  ({pid, unit, tier}),波次结束清空。启动原子写(tempfile + `os.replace`,承
  `_write_sidecar` 同型),try/finally 删除;硬杀残留 = 合法态,由 PID 探测消歧。
  Alternative:写进 sidecar JSON——否,sidecar 是人读非契约,语义混载。
- **D2 `--kill-stale` 放 fanout_runner 而非独立脚本**:检出与杀的逻辑只对「fanout_runner
  长什么样 + 它 spawn 的宿主 CLI 长什么样」有知识(cmdline 特征、children 记录、文件名
  约定),与 tier 表同住一处(承 D1 单点 tier 映射结构);独立脚本徒增 `check_contracts`
  登记面。子命令形态用 flag(承既有 `--purge-audit` 模式 flag 风格),破坏性守卫沿用
  `--purge-audit`+`--dry-run` 同型(`--kill-stale` 真杀须 `--dry-run` 先行预览,直接真杀
  且检出将杀目标 → 退出码 2 + recipe)。
- **D3 PID 复用防护 = 双条件 cmdline 匹配**:Windows PID 复用常见;仅 PID 探测会误杀无辜
  进程。`psutil` 不可用(零依赖,R2),用标准库:Windows `tasklist /fi "PID eq <pid>" /fo
  csv /nh` 取映像名 + `wmic process where processid=<pid> get commandline` 兜底;POSIX 读
  `/proc/<pid>/cmdline`。runner 按 cmdline 含 `fanout_runner.py`、children 按 cmdline 为
  宿主 CLI(`opencode`/`claude`)匹配;非匹配 = 视为 stale 残留记录,仅删文件不杀。
- **D4 杀树方式 = 平台分叉**:Windows `taskkill /pid <pid> /T /F`(/T = 树,/F = 强制;
  宿主 CLI 是 npm `.cmd` shim 链,`/T` 是唯一可靠全树杀);POSIX `os.killpg`(spawn 时
  `start_new_session=True` 需另行验证——若该改动影响既有行为则回退为仅杀父进程 + 文档
  披露「POSIX 孤儿孙进程由宿主进程组回收」)。taskkill 已在依赖清单外(系统命令,非 pip)。
  形态②(runner 已死)对 children 逐个 taskkill /T——子进程自己的孙子树由 /T 覆盖。
- **D5 心跳 = stderr 单行、节点驱动、无定时器**:节点 = 单元 spawn / 单元终结(ok/failed/
  timeout/crash)/ 波次结束。不加后台心跳线程(ThreadPoolExecutor 波内本就并发,波内静默
  由各单元终结行打破;单波 5 单元并发 spawn 即有 5 行)。行格式
  `[fanout_runner t1] +00:12:34 wave=3 unit=<id> spawn done=45/830`,耗时 = `time.monotonic()`
  相对 t0。opencode TUI collapse 到 ~10 行尾部 → 5 单元并发 × 2-3 行/单元 ≈ 10-15 行
  填满可视窗,持续推进。claude 侧 stderr 进 Bash 结果文本,终态可见(无流式,claude Bash
  不渲染 running 输出——披露此宿主差异,claude 用户收益 = 结果里完整时间线)。
- **D6 resume_state 点名而非自动杀**:resume_state 是只读派生器(除显式 action flag),
  自动杀越权;点名(`stale_fanout[]` + recipe)+ 编排器接线(壳 recipe:tier 派发前先
  `--kill-stale --dry-run` 审、再真杀)保持「破坏性动作永远显式」。`--check` 只 advisory
  (notes[]),不 gate——孤儿 pending 是合法态。
- **D7 计数口径修复 = 文档而非代码统一**:resume_state 纯文件计数(快、无 I/O 放大)与
  list_clusters 去重计数(shard 正确)各有承重场景,统一到任一方都有代价(resume_state
  读 472 份 body 的 I/O;list_clusters 丢 orphan 容错)。修复 = docstring/--help 注明
  三口径 + 等价条件;`--check` 可选披露 done-marker 与去重计数的差异值(仅当读 body 检出
  orphan 时)。

## Risks / Trade-offs

- [PID 探测的 cmdline 查询在部分 Windows 环境受限(wmic 弃用/权限)] → 探测失败降级为
  「PID 存活即杀」前先查映像名(tasklist 几乎总可用);两层都失败 → 视为 stale 残留仅删
  文件 + stderr 警告(漏杀安全侧:重派幂等,双跑窗口仍由 marker 兜底)。
- [runner 被硬杀 → liveness 文件残留 → resume_state 每次都报] → PID 已死即报
  `pid_alive:false` + note「残留文件,--kill-stale 清理」,噪声有界(一次 --kill-stale
  即清);不给 --check 升级为 violation(承 D6)。
- [心跳行 stderr 量大(数百单元 × 3 行)] → 每行 <120 bytes,800 单元 ≈ 300KB stderr,
  opencode 尾部 30K 窗 + 落盘截断机制(`shell.ts:504-521` outputPath)原生兜底;不需要
  节流(行率 = 单元终结率,分钟级/单元)。
- [POSIX 杀树不彻底(start_new_session 未验证)] → D4 回退路径:仅杀父 + 披露;Windows
  (用户实际平台)taskkill /T 全覆盖。
- [--kill-stale 误杀正在跑的合法 runner(用户双终端手动跑两个 runner)] → 这是用户显式
  动作;`--dry-run` 预览 + killed 报告含 started_ts/cmdline 供人工确认;recipe 明示
  「先审 dry-run 输出」。

## Migration Plan

单 commit 落地:fanout_runner(liveness + --kill-stale + 心跳)→ resume_state(stale_fanout
+ 口径文档)→ 双壳接线 + `check_contracts.py` 新 flag 登记 → tests。无 schema/磁盘格式
破坏性变更(liveness 文件是新增产物,旧 run 目录无此文件 = stale_fanout 空 = 零影响)。
回滚 = revert 单 commit。

## Open Questions

(无——Q2 可行性已回源码确认为可行;Q1 机制选型已定;Q3 为口径文档化。)
