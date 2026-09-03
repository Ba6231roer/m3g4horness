# improve-mgh-init-fanout-lifecycle

> **人话序** 现象:`fanout_runner.py` 一跑就是几十分钟到几小时(opencode `run` 波次循环)。
> 中途会话被 Ctrl-C / 宿主超时 / 崩溃打断后,**已 spawn 的宿主 CLI 子进程树并不随之死亡**——
> 它们仍在后台烧 token,而 resume 一跑又派发同样的 pending 单元,同一单元两份 LLM 跑同时进行,
> checkpoint 互相覆盖。另外整个 fanout 期间 opencode 界面只有一行「正在执行 Bash」,毫无进度反馈。
> 根因:① runner 无「自己是否已被遗弃」的检测,也无对旧实例的清理入口;② runner 心跳进度只写
> stdout 末尾摘要 + 人读 sidecar 文件,opencode TUI 只渲染 Bash 工具的**流式 stderr**
> (`shell.ts:487` `handle.all = merge(stdout, stderr)` → `metadata.output` → TUI 实时刷新,
> 已回源码核实),而 runner 的进度全走 stderr 但每波才打一行、且派发中长时间静默。改什么:
> runner 获得 pid/心跳登记(liveness 文件)→ `--resume` 前 `resume_state`/编排器可确定性检出
> 「还有活着的旧 fanout」→ `fanout_runner --kill-stale` 先杀再继续;派发循环每单元 spawn/完成
> 向 stderr 打带时间戳的心跳行,TUI 实时可见。怎么验证:`--kill-stale` 幂等单测 + 孤儿树被杀
> 断言;心跳行 stderr 格式断言;472/491 计数口径文档化(见下)。

## Why

所有 fanout_runner 消费方(scout/t1/t3,含未来 ut-init 等 tier)共享同一失败形状:编排器侧
中断(claude Bash per-call 硬杀、宿主崩溃、用户 Ctrl-C、终端关闭)只杀 runner 进程本身,
**不杀它 spawn 的宿主 CLI 子进程树**(Windows 上 subprocess 树不随父进程退出而终止)。孤儿
单元继续消耗 LLM token,并在完成后写 `.done` marker——与 resume 重派的同单元产生竞态:两份
写同一 `checkpoint_path`,后写者覆盖先写者,T2 消费的记录可能是两个不同模型运行的杂交产物。

同时,长跑期间零可观测:opencode TUI 对 running 状态的 Bash 工具渲染
`metadata.output`(`packages/tui/src/routes/session/index.tsx:2059`),其内容 = 子进程
stdout+stderr 合并流的**滑动尾部**(`shell.ts:487-529`,尾 30K chars,`MAX_METADATA_LENGTH`,
`shell.ts:27`)。fanout_runner 派发循环 minutes 级静默 → 用户在 TUI 只看到转圈,无法区分
「正常慢」与「卡死」。

## What Changes

- **fanout_runner 登记 liveness**(新):runner 启动时原子写 `<init-dir>/fanout_runner.<tier>.pid`
  (body `{pid, started_ts, tier, host, cmdline, children[]}`;`children[]` = 每波 spawn 的
  宿主 CLI 子进程 PID,每波更新),退出(含 partial 早退)时删除。spawn 改用
  `subprocess.Popen` 以取得子 PID。
- **`--kill-stale` 模式**(新):检查 liveness 文件 → ① runner PID 仍存活且 cmdline 匹配
  fanout_runner → 杀整个进程树(Windows `taskkill /pid <pid> /T /F`;POSIX 进程组);
  ② runner PID 已死但它记录的子进程 PID 仍存活且 cmdline 是宿主 CLI(`opencode`/`claude`)
  → 逐个连树杀(覆盖「runner 被连带硬杀、子进程存活」形态)→ 删除 liveness 文件
  → stdout 报 `{killed:[...]}`;无 stale → `{killed:[]}` 退出码 0(幂等)。dry-run 先行
  (R5.3b 破坏性操作守卫)。
- **编排器接线**(mgh-init 双壳):fanout tier 派发前一律先 `--kill-stale`(或 resume recipe
  明示该步),杀干净再派发;stdout `killed` 非空时在 stderr 提示被杀单元留 pending、由本轮重派。
- **stderr 心跳**(新):派发循环在关键节点(spawn 各单元 / 单元 ack / 波次结束)向 stderr 打
  `[fanout_runner t1] +HH:MM wave=3/59 unit=<id> done=45/472` 形状的单行心跳;opencode TUI
  实时渲染(Bash 工具 running 态显示合并流尾部),claude 侧 BASH stderr 亦可见。**不改 stdout
  JSON 契约**(stdout 仍只有末尾一行摘要)。
- **计数口径文档**(Q3):472 = `resume_state.py` 对 `checkpoints/t1/*.json.done` 的**文件计数**
  (`_count_markers`,resume_state.py:352,不读 marker body);491 = 用户 `ls` 看到的同名目录
  文件数——差异来源:**`.failed` marker 不计入 done**(resume_state 分开计 failed)、目录里还
  有 `<id>.json` 记录体本身(非 marker)、以及 t1 的 done 计数对 orphan marker(无记录体)不
  去重。`list_clusters.py` 的 done 计数是**另一口径**(读记录体 `unit` 字段去重,shard 感知,
  list_clusters.py:164-186);resume_state 的口径是纯文件 glob 计数。两者在无 shard、无孤儿时
  才相等。本 change 在 `resume_state.py --help`/docstring 注明口径差异,消除「472≠491 = 数据
  丢失」的误读(实际无丢失;差异 = 计数语义不同)。

## Capabilities

### New Capabilities

(无——全部为既有 fanout-dispatch / resume-step-discipline 能力的需求扩展)

### Modified Capabilities

- `fanout-dispatch`:新增 requirement——liveness 登记 + `--kill-stale` 孤儿树清理 + stderr
  心跳可观测;既有波次循环/超时不变式/闸门透传 requirement 不变。
- `resume-step-discipline`:新增 requirement——resume 入口暴露 stale-fanout 检出
  (`resume_state.py` stdout 增 `stale_fanout` 字段,liveness 文件存在即报,附
  `--kill-stale` recipe);`--check` 增 stale-fanout 披露(非 gate,advisory)。

## Impact

- `core/scripts/fanout_runner.py`:liveness 登记/清理、`--kill-stale`、stderr 心跳
  (新 flag 进 `tools/check_contracts.py` `FANOUT_RUNNER_REQUIRED_FLAGS`)。
- `core/scripts/resume_state.py`:stdout 增 `stale_fanout` 派生字段(liveness 文件探测 +
  PID 存活粗检),`--check` 增 advisory 披露;docstring 计数口径说明。
- `releases/{claude-code/commands,opencode/command}/mgh-init.md`:tier 派发前 `--kill-stale`
  接线 + resume recipe 更新。
- `tests/`:`test_fanout_stale.py`(liveness 写/删、`--kill-stale` 幂等、PID 复用误杀防护——
  cmdline 不匹配不杀)、心跳格式断言、resume_state `stale_fanout` 字段。
- opencode 机制文档 `docs/opencode-context-mechanics.md`:补记「Bash stderr → TUI 实时尾部」
  机制(本 change 核实,`shell.ts:487`/`session/index.tsx:2059`)。
- 不变:stdout JSON 摘要 shape、退出码 0/1/2、波次循环语义、三级超时不变式、`.done`/`.failed`
  marker 语义、磁盘 schema。
