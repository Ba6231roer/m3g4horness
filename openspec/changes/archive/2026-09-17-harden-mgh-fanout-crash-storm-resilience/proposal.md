> **人话序** 现象：企业内网网关按调用数限流（如实测背景：每 10 分钟 100 次）时，opencode 对
> 429 只快速重试 2 次（源码核实 `retries: 2`、秒级退避），仍失败就报错退出——超配额的形状是
> 「**快败风暴**」：单元秒级 crash、零延迟回队重派、再撞配额，一轮风暴 1–2 分钟远快于 10 分钟
> 窗口恢复，整晚耗在「风暴→熔断→resume→再风暴」空转里；更糟的是模型在 provider 报错后**礼貌
> 回 `failed:` ack** 会写 `.failed` 终态标记——枚举器把它排除出 pending，tier 以「完成」收尾但
> 带覆盖洞，直接损失 mgh-init 准确性。根因：派发器对快败无冷却、无退避、无自愈，failed 终态
> 无确定性重派口。改什么（三层 + 一个重派口）：① **快败冷却**——滑动窗口内快速失败再入队
> 事件超阈 → 暂停派发 `--cooldown-s`（受剩余时间预算封顶），零推进熔断前至多一次「冷却 →
> 重列 → 再观察」的有界退避；② **限流特征分类 + 风暴快路径截断**——crash 单元输出尾部命中
> 限流特征（`429`/`rate limit`/`quota`）且一窗内 crash ≥ `--wave` 全为限流 → 立即 exit 2 +
> `rate_limited:true` + 冷却 recipe（特征漂移时优雅退化到 ①）；③ **failed 终态有界重派口**——
> 五个枚举器增 `--include-failed`、runner 增 `--retry-failed`（认领时删 marker，身份永远来自
> 枚举器），编排器纪律至多一次；④ 调用面 recipe/man 增慢响应画像校准与 stalled 无磁盘异常
> 分支。前提：`harden-mgh-fanout-stall-containment` 已落地（输出尾部/run.log 是分类数据源）。
> 怎么验证：单测（冷却触发/预算封顶/一次退避/特征命中与漂移退化/风暴阈值/retry-failed 身份
> 链与 marker 删除）+ 契约 lint + 配额环境真机专项。

## Why

- **快败风暴的时间账**（逐环实证）：单单元 fast-fail ≈5–15s（429 → 2 次秒级重试 → 退出），
  熔断 ≈10 次派发后触发 → 一轮风暴 1–2 min ≪ 10 min 配额窗口 → 编排器 resume 时窗口未恢复
  → 立即重进风暴。全链路（runner 零延迟回队 + 熔断 recipe 直接 resume）没有任何一处等待
  窗口恢复；每轮重派把单元已花的 8–12 次调用全损重付。
- **failed 终态覆盖洞**：显式 `failed:` ack（含模型在 provider 报错后礼貌放弃的形态）→
  `.failed` 终态 → 枚举器 `pending[]` 排除 → tier「完成」但缺单元记录，直接损失下游 T2/T3
  的输入完整性；当前唯一出路是手工删 marker。限流环境下 provider 瞬断高发，洞不再是小概率。
- **分类与冷却互补而非互斥**：事件节奏（快速失败再入队）是 provider 无关的高信度自愈触发；
  输出尾部文本（stall-containment 落地后可见）是确认「配额耗尽」的高特异证据——前者管自愈，
  后者管快速止损与精确披露；文本漂移时退化到纯事件路径，不失去兜底。

## What Changes

- **快败冷却（provider 无关自愈层）**（`fanout_runner.py`）：滑动窗口（120s 常量）内 requeue
  事件（crash/timeout/stall/spawn-error 回队尾；**不含** failed-ack 与 pre-spawn failed——两者
  终态化不回队，非风暴形状）≥ 3 → 暂停派发 `--cooldown-s`（默认 300，`0`=off，按「剩余时间
  预算 − 在飞收敛余量」封顶，不足则退化立即继续并如实披露）；冷却只停新派发，在飞单元照常
  收割。stderr 冷却行 + stdout 摘要新增 `cooldowns:<n>`。
- **熔断前有界退避**：零推进熔断准备 exit 2 时，若时间预算允许，执行**至多一次**「冷却 →
  重列磁盘终态 → 再观察」——有推进则撤销熔断继续派发，仍零推进才 exit 2。NEVER 无限退避
  （跨窗口收敛仍归编排器 `--resume` 重派循环）。
- **crash 限流特征分类 + 风暴快路径截断（确认配额耗尽时的止损层）**：crash 终态后扫描单元
  输出尾部（数据源 = stall-containment 的读线程尾部/run.log），命中特征集（`429`/`too many
  requests`/`rate limit`/`quota`，大小写不敏感）→ `crash_cause:"rate-limit"`；风暴窗口（自上次
  磁盘终态推进起）内 crash ≥ `--wave` 且全部 rate-limit → 立即停止派发，exit 2 + stdout
  `rate_limited:true` + `rate_limited_crashes:[…]` + stderr 冷却 recipe（等满一个配额窗口再
  resume；wave 校准公式 `floor(8 ÷ 每子每分钟调用数)`）。风暴条件满足时优先于新一轮冷却直接
  截断。特征漂移 → 分类全 unknown → 截断不触发、冷却路径照常兜底（优雅退化）。新 flag
  `--no-rate-limit-stop` 禁用截断层。
- **failed 终态的有界重派口**：五个 tier 枚举器（`list_scout_batches`/`list_clusters`/
  `plan_aggregate`/`list_rule_jobs`/`diff_group`）增 `--include-failed`——failed 单元以 canonical
  身份重进 `pending[]`（携带既有 `failed_marker` 绝对路径字段，NEVER 文件名反推），缺省关闭
  逐字节不变；`fanout_runner.py --retry-failed` 认领此类单元时删除其 `.failed` marker（失败
  证据已在 `*.run.log`）再正常派发，stdout 新增 `retried_failed:<n>`；重派再失败写回新 marker，
  天然有界（ack 终态不回队）。
- **调用面 recipe 与画像校准**：`discipline_core.py` path_recipes 与各派发段增两分支——
  `stalled:true` 且 `resume_state --check` 无磁盘异常 → provider 拥塞形态 → 直接重派（runner
  内已自愈），NEVER 改写输入/删 marker/微脚本；tier 收尾 `failed>0` 且 run.log 呈 provider
  瞬断形态 → **至多一次** `--retry-failed` 重派，再失败接受缺口 + 报告披露。man pages 增
  慢/限流画像取值：`--stall-timeout-s`/`--call-timeout-s` ≥ 实测单元 p99 ×3–5（防误杀→重派
  →再误杀）、`--wave` ≤ 配额 ÷ 每单元呼叫率 × 0.8、`--time-budget-ms` 贴近宿主 × 0.8。
- **非目标（明确不做）**：不做配额探测/自适应限速/token-bucket 细粒度派发节奏（冷却已覆盖
  风暴形态，wave 爆发归画像指引）；不改 opencode 上游 `retries`/退避；不改 ack 状态机与
  marker 语义（除显式 `--retry-failed` 路径）；不改枚举缺省行为；T2 分块已存在
  （`plan_aggregate.py --node t2`）不涉。

## Capabilities

### New Capabilities

<!-- 无。全部为 fanout-dispatch 既有能力的新增要求（纯 ADDED，规避与未 sync 的前置 delta 冲突）。 -->

### Modified Capabilities

- `fanout-dispatch`: 新增三条 requirement——① 「快败冷却与熔断前有界退避」（requeue 事件
  窗口、预算封顶冷却、熔断前至多一次退避、`cooldowns` 披露）；② 「crash 原因分类与限流
  crash 风暴截断」（特征分类、风暴阈值、快路径止损与 `rate_limited` 披露、漂移退化）；③
  「failed 终态单元的有界重派」（枚举器 `--include-failed` 与 dispatcher `--retry-failed` 的
  组合契约：身份来自枚举器、认领删 marker、计数披露、缺省不变）。ack 状态机/超时不变式/
  补位调度零改动。

## Impact

- **代码**：`core/scripts/fanout_runner.py`（冷却窗口/预算封顶/熔断前退避/特征分类/风暴截断/
  `--retry-failed` 认领删 marker/stdout 扩展：`cooldowns`/`rate_limited`/`rate_limited_crashes`/
  `retried_failed`）；`core/scripts/list_scout_batches.py`、`list_clusters.py`、`plan_aggregate.py`、
  `list_rule_jobs.py`、`diff_group.py`（各增 `--include-failed`，复用既有 forward failed 谓词与
  `failed_marker` 路径字段）。**前提依赖**：`harden-mgh-fanout-stall-containment` 先落地
  （分类数据源 + run.log 留证 + 槽位补位循环挂载点）。
- **测试**：`tests/test_fanout_runner.py`（冷却触发/在飞不受影响/预算封顶退化/一次退避两分支/
  特征命中与漂移退化/风暴阈值边界/`--no-rate-limit-stop` 回退/retry-failed 认领删 marker 与
  披露/failed-ack 不触发冷却）；`tests/test_list_clusters.py` 等枚举测试（`--include-failed`
  缺省不变 + 重进 pending 身份正确）。
- **调用面与文档**：`core/scripts/discipline_core.py` path_recipes、`core/prompts/fragments/
  init-stage/{scout,t1,t3}.md` 与 sdr 派发段（stalled 分支 + retry-failed 纪律）、维护者私有
  文档区里的命令人话说明（配额/慢画像配置段）、fan-out 运行手册、术语词典。
- **兼容性**：stdout 既有字段零增删（四个新键）；新 flag 均有安全缺省（冷却 300s 仅风暴形态
  生效、截断可禁用、`--include-failed`/`--retry-failed` 显式 opt-in）；退出码 2 新增「风暴截断」
  形态（与既有熔断同族 fail-loud）；零新依赖。
