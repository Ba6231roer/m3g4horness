## Context

动机、实测证据与"哪条判断被证伪"见 `proposal.md`。设计只需知道四条现状:

1. `fanout_runner.py` 的 tier 派发入口在 sdr 分支把 plan 锚点重绑为 `<run-dir>/grouping.json`
   (`checkpoints.parent / "grouping.json"`),即 `plan_path.parent` **就是** sdr 运行目录——
   与 init tier 的 `<init-dir>/run_config.json` 是同一邻居语义。
2. `_codegraph_signal(plan_path, tier_key)` 对 init 读 `plan_path.parent / "run_config.json"`
   的 `no_codegraph`;对 `tier_key == "sdr"` 直接早返回 `"off"`。缺失/不可解析一律落 `off`。
3. sdr 的 codegraph 事实来源已存在且可用:`diff_group.py::_codegraph_available()` 探测
   `<repo>/.codegraph/` 与 PATH 上的 `codegraph`,stdout 回 `codegraph: true|false`。派发器侧
   没有任何对应读取。
4. `resume_state.py` 的运行目录解析为 `--init-dir` > `<target>/<--run-root>`(默认 `.mgh-init`);
   它**没有**接受任意运行目录的形态,故在 sdr 运行目录下不可能成功。

## Goals / Non-Goals

**Goals:**

- 让 sdr 的 `codegraph` 信号从"写入端齐备、读取端恒 off"变成两侧同源:分组用什么事实判断,
  任务消息就填同一个事实。
- 消除命令壳里在 sdr 场景百分之百失败的恢复指引。
- 把 `--stall-timeout-s` 的两个数(硬性拒绝下限 vs 宿主外默认值)写成规格,堵住"改回默认值"
  这条会直接让 sdr 无法启动的错路。

**Non-Goals:**

- 不新建 sdr 的恢复面(无 `resume_state.py` 等价物、无 per-step 状态重派生)——由
  `add-mgh-sdr-resume-surface` 承接,本 change 只做最小消除。
- 不改任何超时**取值**,不动失活判据、自适应宽限、冷却与熔断机制。
- 不改 `diff_group.py` 的分组/预算逻辑,不改 TIERS 表既有行。

## Decisions

### D1 — codegraph 信号:接通,而非删除;载体收敛到 `run_config.json` 单一来源

选"接通"的理由不是"环境变量已经写了"这个沉没成本,而是**两侧判断互相矛盾是可观测缺陷**:
同一次 run 里 `diff_group.py` 可能按调用链把 route 方法与其下游 service/dao 合并成一个单元、
并在 slice 里装入整条链,而任务消息同时告诉复核子代理 `codegraph=off`(语义为"单元可能在接口
边界被切开")——子代理据此放弃跨层判定,恰恰丢掉分组刚刚喂给它的信息。

`MGH_SDR_CODEGRAPH` 环境变量**删除**。它没有任何消费者(仓库全量检索仅命中两个命令壳自身的
说明文字);保留它等于把"死契约"从一个形状换成另一个形状,而本 change 的整个存在理由就是
消除这类死契约。命令壳的自动探测结果改为只经 `run_config.json` 承载。

| 替代案 | 否定理由 |
|---|---|
| 删除 `MGH_SDR_CODEGRAPH` + `run_config.json` 写入 + `--no-codegraph` 声明(整体移除) | 分组已实际消费 codegraph,复核侧却永久失明;等于用删除掩盖两侧不一致,并把"减少扇出"这个既有能力从 sdr 拿掉 |
| 保留环境变量作为传递媒介,派发器读环境变量 | 环境变量在 opencode 宿主上不可靠(守卫域已实测:插件进程不继承 mid-session bash 导出的 env),而 sdr 恰是 opencode 主用场景;文件载体无此边界 |
| 让命令壳把信号拼进任务消息(绕开派发器) | 违反既有的"信号经 run 目录传给 dispatcher,NEVER 拼进 task 消息"约定,并让占位符填充变成两处逻辑 |

### D2 — 落点在 `_codegraph_signal()` 取消早返回,不改 TIERS 表结构

当前 sdr 分支的早返回是唯一障碍,而 sdr 的 `plan_path` 已经指向运行目录内的 `grouping.json`
(Context 第 1、2 条),`plan_path.parent / "run_config.json"` 零路径改动即命中 init 同款语义。
因此改法是**删掉两行早返回**,让 sdr 走与 init 完全相同的代码路径——不新增 tier 字段、不新增
分支、不新增参数。这样"两侧同源"由结构保证,而不是靠两处逻辑保持同步。

签名保留 `tier_key` 形参(既有调用面不动);早返回删除后该参数对 sdr 不再有语义,但保留它可
避免触碰调用方,也留给未来按 tier 分档的余地。

### D3 — 恢复指引换成 `diff_group.py --check <run-dir>`,并诚实披露其语义弱于原意

命令壳"快败风暴三层"第 ① 层用 `resume_state.py --check` 的原意是"确认磁盘上没有异常状态,
故 stalled 是 provider 拥塞而非本地损坏"。sdr 域内唯一具备 `<run-dir>` 形态、且清单已在
`tools/check_contracts.py` 中登记的检查是 `diff_group.py --check <run-dir>`——它校验
`grouping.json` + slices + markers 的完整性,退出码 0/2。

语义差异必须说清:`diff_group --check` 校验的是**分组产物的完整性**,不是**运行进度的自洽性**
(它不认识 run_config、不认识哨兵、不派生"下一步")。它足以支撑该层要回答的问题——"产物没坏,
所以 stalled 更可能是外部拥塞"——但不等于完整的恢复面。完整面延后到 `add-mgh-sdr-resume-surface`。

| 替代案 | 否定理由 |
|---|---|
| 给 `resume_state.py` 加 `--run-dir` 让它认 sdr 目录 | 越界:该脚本的派生逻辑(step/next_action/tiers)整条建立在 init 的产物图上,sdr 没有对应产物;这正是后续 change 的范围,不应在本 change 偷偷开头 |
| 直接删掉第 ① 层的状态判据,只保留"直接同参重派" | 丢掉了"先确认本地没坏再重派"的防线;重派在产物损坏时会变成空转循环 |
| 保持原样,把失败当作可接受的 noise | 该指引在 sdr 场景必然失败,等于把编排器的判据变成噪声,正是本 change 要修的缺陷形状 |

### D4 — 超时:零行为改动,只在规格固化口径

`sdr` 与 `init` 的 `--stall-timeout-s 300` **保持不变**。规格新增的是一条**调用方约束**
(宿主演进调用 MUST 显式传且 `< --call-timeout-s`,NEVER 依赖默认值),不是取值调整。理由已在
`proposal.md` 记录:默认为 900,而宿主演进调用面被强制传 `--call-timeout-s 360/540`,省略该
flag 会让 `stall >= call` 在 spawn 前以退出码 2 拒绝启动。

该约束**不需要改代码**——现行实现已经这样校验;它要防的是**文档/判断层面的改错**,故落点为
`--help` 文案口径与规格条文。

### D5 — 安装副本刷新不整跑 `install.sh`

`install.sh` 会把守卫钩子写入 `.claude/settings.json`(开发仓当前为 `"hooks": {}`,即刻意不接种
自身守卫——本仓的守卫是**给目标项目用的交付物**)。整跑 install 会给开发仓接种一个 CWD 相关的
PreToolUse 拦截,与既有约定冲突。刷新目标只是"让开发仓内的命令副本与 release 版一致",因此
做法是:**只搬运命令/agent/技能副本**,或在整跑后把 `.claude/settings.json` 的 `hooks` 复位为空并
核对 `.opencode/plugins/` 未被改动。

## Risks / Trade-offs

- [开发仓被接种守卫,导致后续会话工具调用被拦截] → D5:按最小搬运刷新,完成后核对
  `.claude/settings.json` 的 `hooks` 仍为空对象、`.opencode/plugins/block_adhoc_scripts.ts`
  未被替换;把这一步写进 tasks 的验收项。
- [接通后复核子代理行为改变(原本恒按 `codegraph=off` 判定,现在可能收到 `on`)] → 这是修复的
  目标而非副作用,但需一次性真机确认:在有 `.codegraph/` 的仓上跑一轮 sdr,断言任务消息占位符
  为 `on` 且 draft 能引用链上下游证据。回退路径 = 恢复早返回两行,零结构性代价。
- [`run_config.json` 的写入端此前从未被验证过内容] → 写入是命令壳的 `printf`(逐字、确定性),
  但"从未被读取过"意味着格式未曾被真实消费验证。缓解:派发器侧对未知字段宽容(只取
  `no_codegraph`)、对坏 JSON 落 `off`(与 legacy 逐字一致),不会因格式偏差硬失败。
- [`diff_group --check` 语义弱于原指引,可能让编排器对"产物坏但分组完好"的形态失去判据] →
  已在 D3 与规格中显式披露;补足由后续 change 提供,本 change 不假装做到。
- [规格新增条文被读成"改了超时行为"] → 在规格里把 `0` / `1..59` / `>= 60` / 默认值四段语义与
  "两个数不可混称下限"写成显式条文,并在 `--help` 文案侧对齐。

## Migration Plan

1. 先改 `fanout_runner.py`(删早返回)——此时 `run_config.json` 若已存在即开始生效,行为切换是
   "从恒 off 到真实信号",无中间破损态。
2. 再改两个命令壳(删环境变量行、改写传播说明、恢复指引换域),使"写入端与读取端同源"在
   同一版本内闭合;命令壳与派发器不同版本混用时的行为 = 读取端落 `off`,与今天等价(安全回退)。
3. 单元测试先行覆盖三态(文件在且真有值 / 文件在且 `no_codegraph` 为真 / 文件缺失)。
4. 分发副本刷新按 D5 执行,完成后跑纯净性 lint 与契约 lint。
5. 回退:恢复 `_codegraph_signal` 的 sdr 早返回两行即可整体退回今天的行为,命令壳侧的文案改动
   是纯说明性的,可独立保留。

## Open Questions

- **生产静默窗口取值 900 vs 300 的口径分歧(承接既有 change 的遗留)**:上一轮
  `fix-mgh-fanout-stall-false-kill` 的设计把默认值 900 标定为"生产取值",其非目标写明"命令壳仍不
  暴露 `--stall-timeout-s`";但 `/mgh-init` 各 tier 与 `/mgh-sdr` 实际**显式传 300**,更早的
  `fanout-dispatch` 规格也把 `300` 写作合规示例。两侧说法至今未对齐。本 change 按"不改超时"
  处理,只固化"宿主演进调用必须显式传"这一层;**900 与 300 谁是期望的生产取值**留给后续 change
  决定(需要一次带 `runtime_*` 分布的真机轮来定标)。该问题不影响本 change 的规格、做法或任务
  拆分——无论未来取值定成多少,"显式传且小于 call-timeout"的约束都成立。
