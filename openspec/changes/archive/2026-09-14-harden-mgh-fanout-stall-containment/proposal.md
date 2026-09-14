> **人话序** mgh-init T1 resume 后连续两波各卡死 1 个子代理（换单元、输入极小），其余 4 个槽位干等，宿主 15/60 分钟 per-call 超时把整棵进程树硬杀，卡死单元无 marker 重派——下一波再挂，每波只推进 4/5。根因三层：① 子进程端——`opencode run` 对 LLM 流**没有任何整体/分块超时**（源码核实 `timeout: false`、`chunkTimeout` 非默认），内网接口流一停子进程就零输出永久挂死；② 派发器端——波次是屏障（一个卡死=全员停工）、无失活检测（只有 7200s 绝对兜底，比宿主超时还大，永远轮不到它）、超时路径 `proc.kill()` 杀不掉 `.cmd` shim 链下的真进程（留孤儿烧 token）、子进程输出不留痕（事后只能靠猜）；③ 配置端——三级超时不变式无启动校验，默认值必然违反，静默错配注定退化为宿主硬杀循环。改什么：`fanout_runner.py` 派发循环从波次屏障改为**槽位补位**（任一单元终态立即补位，卡死只废一个槽）；新增**失活检测**（`--stall-timeout-s`，输出字节级静默超阈 → 只树杀该单元、留痕、留 pending 重派）；每单元运行留痕 `*.run.log`；不变式启动 fail-loud；心跳披露在飞单元静默时长。opencode fanout agent 定义补钉扎 `external_directory`/`doom_loop`（现默认 ask——旧版 opencode 下 ask=永久挂）。怎么验证：单测覆盖补位顺序/失活树杀/留痕/不变式拒识/熔断重锚；契约 lint 断言新 flag；大仓 T1 实跑 resume 推进至 221/221。

## Why

- **实测故障形状**（2026-09-14 会话，T1 resume，176→184/221）：两波各 1 子代理卡死（不同单元、输入 1.6–4.3KB、单元 A 重派后正常完成 → 非内容确定性），波次屏障使 4 槽位陪等，宿主硬杀整树，每波净损失 15/60 分钟预算。
- **子进程挂死面是结构性的、不可避免**（opencode 源码核实，v1.18.16）：
  - `provider/provider.ts:1763` `timeout: false`（无整体请求超时）、`chunkTimeout` 仅显式配置才生效（:1746）——**内网接口 SSE 流中段停摆 = 子进程无限等**，与本次「无输出、无 marker、换单元复现」完全吻合（头超时 300s 仅个别 provider 类型默认启用且只护到响应头）。
  - 权限 ask 面：run 非交互模式 2026-02 起 auto-reject（`run.ts:796-815`，装机 1.18.18 已含），但 fanout agent frontmatter 未钉扎 `external_directory`/`doom_loop`（默认 `ask`，`agent/agent.ts:119-136`）——**旧版 opencode 上 ask=无应答者=永久挂**（本仓 spike 期即观察到子代理读 `/tmp` 触发人工权限确认的同一触发面）。
  - 派发器超时路径 `proc.kill()` 在 Windows 只杀 `.cmd` shim 层，真实 host-CLI 进程成孤儿继续烧 token（`--kill-stale` 只覆盖宿主硬杀形态，覆盖不到 runner 自身超时形态）。
- **两条新守卫 spec（bash-path-allowlist / sdr-read-root-config）与本故障无关**：守卫是确定性拒绝（hook 退出码 2 + recipe，agent 适配后继续），不存在等待应答的路径；仅提醒排除。

## What Changes

- **调度循环：波次屏障 → 槽位补位**（`fanout_runner.py`）。在飞子进程 ≤ `--wave`；任一单元到达终态（ok/failed/timeout/stall/crash）即按 pending 队列补位派发。磁盘 marker 仍是唯一真相源：补位前对下一单元 `stat` 其 `.done`/`.failed` marker（存在即跳过），NEVER 自行反推身份。stdout 既有字段不变；`waves_run` 语义 = 补位轮数（心跳行 `wave=` 同步）。
- **新增 per-unit 失活检测 + 外科手术式树杀**。新 flag `--stall-timeout-s`（默认 900）：子进程 stdout/stderr **字节级静默**超阈 → 仅杀该单元进程树（复用 `_kill_tree`，Windows `taskkill /pid <pid> /T /F`，修复 shim 链孤儿），无 ack 无 marker → 留 pending。`--call-timeout-s` 保留为绝对兜底，超时路径同样改树杀。
- **每单元运行留痕**。子进程 stdout/stderr 尾部（各截断上限）落盘 `<checkpoints>/<tier>/<unit>.run.log`；非 ok 终态（timeout/stall/crash/failed）必写，ok 亦写（体积小）；stdout 摘要新增 `stall_killed:[<unit>…]`；失活/超时的 stderr 诊断行附 run.log 路径——事后定位从猜测变为读证据。
- **三级超时不变式启动校验（fail-loud）**。传 `--time-budget-ms` 时 MUST 同时显式传 `--call-timeout-s` 且 `< time-budget-ms × 0.8`，`--stall-timeout-s < --call-timeout-s`，否则退出码 2 + 可操作 recipe（拦截「默认 7200s > 宿主预算」的静默错配——本次宿主硬杀的直接推手）。不传 budget（宿主外手动直跑）时默认值不变、仅 stderr 提示。
- **opencode fanout agent 定义补 permission 钉扎**（5 个克隆）：frontmatter 增 `external_directory: deny`、`doom_loop: deny`（`read`/`glob`/`grep`/`list`/`bash`/`edit` 既有钉扎不变）——headless 派发任何默认 ask 类全部转为显式终局（deny=工具报错 agent 适配），与 opencode 版本无关地消除 ask→挂面。
- **心跳增强**：派发循环新增周期性（默认 60s）在飞披露行——在飞单元 id + 距该子进程上次输出的秒数；人从宿主 TUI 实时区分「正常慢」与「卡死」，NEVER 再出现 57 分钟零输出。
- **零推进熔断重锚**：判定锚从「波次边界终态计数」改为「滚动窗口内无任何单元终态推进」（`--stall-waves` 语义平移为 `--stall-window-s` + 保留参数名兼容）；`stalled_pending[]` 诊断披露不变。
- **调用面同步**：init-stage fragments（scout/t1/t3）与 sdr 派发段的 dispatcher 调用行、`discipline_core.py` path_recipes、两 man page 增补新 flag 与修正后的超时不变式示例；`tools/check_contracts.py` 自动断言新 flag。
- **非目标（明确不做）**：不改枚举脚本/marker 语义/ack 状态机/`--kill-stale`/liveness 文件契约；不改 claude spawn 面（`claude -p` 无问询挂死面，`--allowedTools` 白名单外自动拒绝）；不上 `--auto`（自动批准会放大越树读授权面）；不做 opencode 上游修复（可在 design 记录建议上游项：默认 chunkTimeout）。

## Capabilities

### New Capabilities

<!-- 无。全部为 fanout-dispatch 既有能力的要求级变更。 -->

### Modified Capabilities

- `fanout-dispatch`: ① 「Dispatcher 脚本消费 pending 清单并零 LLM 驱动波次」——波次屏障改为槽位补位循环（在飞上限不变、终态即补位、补位前 marker 懒校验），三级超时不变式增 `--stall-timeout-s` 层并新增启动 fail-loud 校验；② 「波次零推进收敛熔断」——判定锚重锚为滚动进度窗口，披露契约不变；③ 新增「失活检测与外科手术式单元回收」要求（字节级静默阈值、树杀、run.log 留痕、`stall_killed[]` 披露、周期在飞心跳）；④ 新增「headless fanout agent 无问询钉扎」要求（ask 类默认值全部显式化，版本无关）。

## Impact

- **代码**：`core/scripts/fanout_runner.py`（调度循环重写为槽位补位、失活监控、树杀、run.log、不变式校验、心跳、stdout 扩展）；`releases/opencode/agent/{init-scout,init-induct,init-synthesis,init-rulewriter,sdr-review}-fanout.md` frontmatter +2 行；`core/prompts/fragments/init-stage/{t1,t3,scout}.md` 与 sdr 派发段调用行、`core/prompts/fragments/fanout/*-task.md` 无行为变化（模板不动）；`core/scripts/discipline_core.py` path_recipes；`docs/man/mgh-init.md`、`docs/man/mgh-sdr.md`；`install.sh` 自检清单不变（文件名不变）。
- **测试**：`tests/test_fanout_runner.py`（波次屏障假设的用例重写：补位顺序、marker 懒跳过、不变式拒识、失活树杀〔monkeypatch 时钟与 `_kill_tree`〕、run.log 落盘、熔断重锚）、`tests/test_fanout_stale.py`（children[] 刷新时点）、新增失活检测专项。
- **兼容性**：stdout 既有字段与退出码语义不变（2 增「不变式违例」形态，与既有 CLI 误用同形）；`--pending-file` 测试钩子保留；`--wave`/`--time-budget-ms`/`--call-timeout-s` 既有调用面不变（新增校验只在违例时拦截）。
- **零新依赖**（stdlib 线程/定时即可，R2）；mgh-sdr 与 mgh-init 五 tier 共享同一循环，一改全 tier 受益。
