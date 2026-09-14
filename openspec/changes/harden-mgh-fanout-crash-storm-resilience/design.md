# design — harden-mgh-fanout-crash-storm-resilience

## Context

配额限流(实测背景:每 10 分钟 100 次)下的故障链已源码核实:opencode LLM 调用
`retries: 2`(`session/prompt.ts:234` → `session/llm.ts:323`),429 由 AI SDK 秒级指数退避重试
2 次后本轮失败 → 子进程非零退出 → crash、无 marker。形状 = **快败风暴**(秒级报错退出),
与 stall-containment 所治的「挂死」(零输出)互为镜像,机制正交。

风暴机制链路(逐环实证):

| 环节 | 事实 | 锚点 |
| --- | --- | --- |
| 内网配额被健康运行贴顶 | `--wave 5` × 每子 1–3 呼叫/min ≈ 5–15 呼叫/min,窗口配额 ≈10 呼叫/min | 用户画像,429 常态化 |
| 子代理内建重试无效 | `retries: 2` 秒级退避,对 10min 窗口无效;耗尽抛错 → 进程退出 | opencode `session/prompt.ts:234`、`session/llm.ts:323` |
| runner 零延迟重派 | crash/timeout/stall/spawn-error → `queue.append(unit)` 立即回队尾;全文件无 sleep/backoff | `core/scripts/fanout_runner.py:1674` |
| 熔断退出快于窗口恢复 | fast-fail ≈5–15s → 一轮风暴 1–2min ≪ 10min 窗口 → resume 立即重进 | 前置 change 熔断参数 |
| failed 终态覆盖洞 | 显式 `failed:` ack(含 provider 报错后礼貌放弃)→ `.failed` 终态 → 枚举排除 → tier 带洞「完成」 | `fanout_runner.py:1658-1662`、`list_clusters.py:53` |
| 枚举器身份基础设施已备 | item 已携 `failed_marker` 绝对路径 + forward failed 谓词共享 | `list_clusters.py:42,64,72,189-195` |

**前提依赖**:`harden-mgh-fanout-stall-containment` 先落地(输出尾部缓存/run.log 为分类数据源;
槽位补位循环为冷却挂载点)。本 change 吸收先前一次同域尝试(`…ratelimit-tolerance`,已弃用)
的可取部分(冷却/退避/retry-failed/画像指引),并修正其一处已被前提改变的裁定(见 D1)。

## Goals / Non-Goals

**Goals:**

- 限流风暴的自愈上界内嵌于单次 dispatcher 调用(冷却 + 熔断前一次退避),整晚 run 不因
  「风暴循环快于窗口恢复」而空转。
- 确认配额耗尽时快速止损(风暴截断),披露精确到单元;特征漂移时优雅退化到事件路径。
- failed 终态拥有确定性、有界的重派口;覆盖洞 MUST 经编排器显式决策(至多一次)才接受。
- 慢响应画像下失活/总长超时取值有据可依(防误杀循环)。

**Non-Goals:**

- 不做配额探测/自适应限速/token-bucket 细粒度 pacing(冷却已覆盖风暴形态;wave 爆发归画像
  指引)。
- 不改 opencode 上游 `retries`/退避策略;不改 ack 状态机/marker 语义(除显式 `--retry-failed`
  路径);不改枚举缺省行为;不动 claude spawn 面;`--kill-stale`/liveness/sidecar 契约不变。

## Decisions

**D1 双层防线:事件驱动冷却(自愈层) + 文本特征截断(止损层),推翻「纯事件、拒绝文本」的
旧裁定。** 冷却触发 = requeue 事件节奏(120s 窗 ≥3),provider 无关、零漂移风险;风暴截断 =
crash 输出尾部限流特征全符。旧尝试以「错误文本在子进程内不可见、随 provider 漂移」否决文本
识别——其**可见性前提已被 stall-containment 改变**(读线程尾部/run.log 落盘现成);漂移风险
由双层结构吸收:特征失配 → 截断静默不触发、冷却照常兜底,文本层只承担「更快止损 + 精确
披露」,NEVER 是唯一防线。

**D2 冷却信度源 = requeue 事件计数。** crash/timeout/stall/spawn-error 回队才计数;`failed:`
ack 与 pre-spawn 锚失败终态化不回队,计入会让确定性配置错误假触发冷却。阈值/窗口为实现
常量(120s/3 次,控契约面增长);`--cooldown-s` 唯一新旗标。

**D3 冷却受剩余时间预算封顶;熔断前至多一次退避。** 冷却 sleep 按「剩余 budget − 在飞收敛
余量」截断,不足则退化立即继续并披露。熔断 exit 2 前一次「冷却 → 重列磁盘终态 → 再观察」:
推进 → 撤销熔断;仍零推进 → 收束。**替代案(无限退避循环)否**——把跨调用重派收敛塞进单
调用会重造「占坑不收敛」;一次退避足以跨过 10min 窗口尾段。冷却期在飞单元照常收割。

**D4 风暴判定 = crash 事件窗口(自上次磁盘终态推进)内 crash ≥ `--wave` 且全部 rate-limit;
满足时优先于新一轮冷却直接截断。** 窗口锚磁盘推进事件而非时间(与既有熔断重锚同理由);
「全部 rate-limit」把单元真缺陷排除——**替代案(任意 crash 计数)否**:真实缺陷风暴会被误
标成限流误导排障。截断与冷却的关系:截断 = 确认配额耗尽、止损退出(等满窗口交给宿主
resume 节奏);冷却 = 瞬态拥塞的调用内自愈;两者窗口/计数器互不共享。

**D5 retry-failed 的身份链 = 枚举器 `--include-failed`,NEVER 文件名反推。** 五枚举器复用既有
forward failed 谓词与 `failed_marker` 路径字段;runner 认领时删 marker 再派发。**替代案
(runner 扫 checkpoints 目录反推身份)否**——超长 id 截断 stem ≠ canonical id,枚举器是身份
唯一来源。删除而非改名:失败证据在 `*.run.log`,marker 只是终态布尔位;重派再失败写回新
marker,天然有界。

**D6 编排器侧重派界 = 纪律条款(至多一次),非机制强制。** `--retry-failed` 可重复传,但
fragments/discipline path_recipes 钉死:tier 收尾 `failed>0` → 读 run.log 判形态 → provider
瞬断形态 → 至多一次;再失败接受缺口 + 报告披露。**替代案(脚本内 retry 计数状态文件)否**——
为一条纪律加磁盘状态违背「状态磁盘化最小面」;ack 终态不回队已封顶滥用面。stalled 无磁盘
异常 recipe 同处落:「诊断无异常 → provider 拥塞形态 → 直接重派(runner 已内建退避),NEVER
改写输入/删 marker/微脚本」。

**D7 慢响应画像 = 调用面示例值,非新机制。** 慢模型下 healthy 单元时长拉长,失活表可能误杀
长生成单元 → 重派从头再生成 → 再误杀。对策是取值指引(man + fragments):`--stall-timeout-s`
≥ 实测单元 p99 ×3–5、`--call-timeout-s` 相应上移、`--wave` ≤ 配额 ÷ 每单元呼叫率 × 0.8、
`--time-budget-ms` 贴近宿主 per-call × 0.8。**替代案(自动探测单元时长分布)否**——观测机制
复杂且首晚无数据;示例值零成本可执行。

**D8 delta 纯 ADDED,规避未 sync delta 冲突。** `fanout-dispatch` 下 stall-containment 的
MODIFIED delta 尚未 sync 主 spec;本 change 全部以**新增 requirement** 表达(行为新增而非改写
既有承诺),不触同名 requirement。

## Risks / Trade-offs

- [冷却拖慢健康 run?] → 触发条件 = 120s 窗内 ≥3 requeue,健康 run 的 crash 罕见且分散,
  实际零触发;真触发时说明配额确已打满,等待即吞吐。`--cooldown-s 0` 显式逃生。
- [熔断前退避占用宿主 per-call 预算] → 受剩余预算封顶 + 至多一次;最坏 = 少一次编排器
  重派轮次,无正确性影响。
- [误截断:网关瞬时抖动导致整波真 429] → 损失 = 剩余单元晚一个窗口派发;resume 即续、
  marker 无损;`--no-rate-limit-stop` 逃生。
- [特征集过时:新网关措辞 → 全 unknown] → 优雅退化(D1):冷却照常兜底;补特征表即恢复
  (run.log 留证使新措辞可被发现)。
- [--retry-failed 被编排器滥用为无限重派] → 纪律界(至多一次)+ ack 终态不回队 + 熔断
  兜底。
- [删除 `.failed` marker 丢失败原因?] → run.log 已留每单元输出尾,失败原因从日志读;marker
  只是终态位。
- [枚举器契约面 +5] → 单一布尔 flag、复用既有谓词,item 字段零新增;缺省行为逐字不变;
  `tools/check_contracts.py` 自动断言。

## Migration Plan

前置 change(stall-containment)先落地 sync 后再实施本 change(冷却挂其补位循环,分类读其
尾部缓存)。纯附加 flag 与缺省安全路径(冷却仅风暴形态生效、截断可禁用、include-failed/
retry-failed 显式 opt-in),既有调用面零破坏;回滚 = git revert 单点。运行中 run 不可热升级。

## Open Questions

- 冷却窗口/阈值常量(120s/3 次)与 `--cooldown-s` 默认 300——先按风暴时间账推导值落地,
  限流环境实跑数据回来再校准(同前置 `--stall-timeout-s` 校准路径)。
- 特征集是否需按网关/端点差异化——先统一闭集,真机 run.log 数据回来再校准。
- t2 map 单元(plan_aggregate 枚举)是否存在 failed ack 形态——实现时核对,若无则
  `--include-failed` 对该枚举器为 no-op 透传(契约仍一致)。
- opencode 上游:LLM `retries`/退避是否值得暴露为 provider 配置(429 长退避可部分自愈配额
  窗口)——另立上游 issue。
