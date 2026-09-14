# design — harden-mgh-fanout-ratelimit-tolerance

## Context

目标用户环境(本 change 的输入事实):企业内网自部署 LLM 服务,响应慢、并发频率硬限制
(例:每 10 分钟 ≤100 次调用);用户跑 mgh-init 的仓为百万行级、整晚无人值守运行,
**「不中断」优先级高于「快」与「省 token」**(企业部署 token 免费且不可中断成本 = 一晚)。

前置:`harden-mgh-fanout-stall-containment` 已实现槽位补位循环、失活检测、树杀、run.log、
熔断重锚(其 tasks 7.4 实跑验收未完)。它治**挂死**(零输出);本 change 治其镜像形态
**快败风暴**(秒级报错退出)。

风暴机制链路(逐环实证):

| 环节 | 事实 | 锚点 |
| --- | --- | --- |
| 内网配额被健康运行贴顶 | `--wave 5` × 每子代理 1–3 呼叫/min ≈ 5–15 呼叫/min,窗口配额 ≈10 呼叫/min | 用户画像 + 429 常态化 |
| 子代理内建重试无效 | 主会话 `retries: 2`,秒级指数退避,对 10min 窗口无效;耗尽抛错 → 进程退出 | `C:\DEV\opencode` `session/prompt.ts:234`、`session/llm.ts:323`(`maxRetries: input.retries ?? 0`) |
| runner 零延迟重派 | crash/timeout/stall/spawn-error → `queue.append(unit)` 立即回队尾;全文件无 sleep/backoff/cooldown | `core/scripts/fanout_runner.py:1674` + grep 实证 |
| 熔断退出快于窗口恢复 | 单元 fast-fail ≈5–15s,熔断 ≈10 次派发后触发 → 一轮风暴 1–2min ≪ 10min 窗口 | D7(前置 change)窗口参数 |
| 编排器无分支重进风暴 | stalled exit 2 → recipe「resume_state 诊断 → `--resume` 续跑」;磁盘诊断必然「无异常」(crash 不留盘痕)→ 立即重进 | `core/prompts/fragments/init-stage/t1.md:18` |
| failed 终态覆盖洞 | 显式 `failed:` ack(含模型在 provider 报错后礼貌放弃)→ `.failed` 终态 → 枚举器 `pending[]` 排除 → tier 带洞「完成」 | `fanout_runner.py:1658-1662`、`list_clusters.py:53` |
| 枚举器身份基础设施已备 | pending item 已携带 `failed_marker` 绝对路径 + `failed` 计数;forward 谓词共享 | `list_clusters.py:42,64,72,189-195` |

## Goals / Non-Goals

**Goals:**

- 限流风暴的自愈上界内嵌于单次 dispatcher 调用(冷却 + 熔断前一次退避),整晚 run 不因
  「风暴循环快于窗口恢复」而空转或放弃。
- failed 终态拥有确定性、有界的重派口,覆盖洞 MUST 经编排器显式决策(至多一次)才接受。
- 慢响应画像下失活/总长超时的取值有据可依(防误杀循环)。
- 冷却签名与 provider 无关(不给 dispatcher 引入错误文本识别这种脆弱面)。

**Non-Goals:**

- 不做 HTTP 429/错误签名识别(子进程内不可见;跨 provider 文本签名脆弱)。
- 不做配额探测/自适应限速/token-bucket 细粒度 pacing(风暴形态已被冷却覆盖;wave 爆发
  相对 10min 窗口是次要项,归画像指引)。
- 不改 opencode 上游、不改 ack 状态机/marker 语义(除显式 `--retry-failed` 路径)、
  不改枚举缺省行为。
- 不动 claude spawn 面;`--kill-stale`/liveness/sidecar 契约不变。

## Decisions

**D1 冷却信度源 = requeue 事件计数,与 provider 无关。** 滑动窗口(建议 120s)内 requeue
(crash/timeout/stall/spawn-error 回队尾)≥ 3 → 暂停派发 `--cooldown-s`(默认 300,
0=off)。**替代案(识别 run.log/stderr 中 429/限流文本)否**:错误发生在子进程内部,
dispatcher 只能看到退出码与输出尾,文本签名随 provider/版本漂移,且把「慢」与「拒答」
耦合进签名;事件节奏(快速失败再入队)是 provider 无关的高信度形状。**排除项**:`failed:`
ack 与 pre-spawn 锚失败不计数——两者终态化不回队(`:1618`/`:1658`),无风暴形状,计入会
让确定性配置错误假触发冷却。阈值/窗口实现常量(非 flag,控契约面增长);`--cooldown-s`
是唯一新 flag。

**D2 冷却等待受剩余时间预算封顶;熔断前至多一次退避。** 冷却 sleep 按「剩余 budget −
在飞收敛余量」截断,预算不足则冷却退化为立即继续(如实披露)。熔断(零推进、准备 exit 2)
时若预算允许,执行一次「冷却 → 重列磁盘终态 → 再观察」:推进 → 熔断撤销、继续派发;
仍零推进 → exit 2 收束。**替代案(熔断前无限退避循环)否**——把 R5.4 的跨调用重派收敛
塞进单调用会重新制造「占坑不收敛」;一次退避足以跨过一个 10min 窗口的尾段(budget 通常
为宿主级数十分钟)。cooldown 期间在飞单元照常运行、照常收割——冷却只停**新派发**。

**D3 retry-failed 的身份链 = 枚举器 `--include-failed`,NEVER 文件名反推。** 五个枚举器
增 `--include-failed`(failed 单元按 canonical id 重进 `pending[]`,复用既有 forward
failed 谓词与 `failed_marker` 路径字段,`list_clusters.py:189-195` 已有基础设施);
`fanout_runner --retry-failed` 在认领带 `failed_marker` 的单元时删除标记再派发。
**替代案(runner 扫 checkpoints 目录 `*.failed` 反推单元身份)否**——超长 id 截断 stem ≠
canonical id,R5.3b 明文禁反推;枚举器是身份唯一来源。marker 删除而非改名:失败证据在
`*.run.log`(前置 change D4),marker 仅是终态布尔位;删除后重派再失败会写回新 marker,
天然有界(ack 终态不回队)。

**D4 编排器侧的重派界 = 纪律条款(至多一次),非机制强制。** `--retry-failed` 可重复传,
但 fragments/discipline_core path_recipes 钉死:tier 收尾 `failed>0` → 读 run.log 判形态
→ provider 瞬断形态 → 至多一次 `--retry-failed` 重派;再失败 → 接受缺口 + 报告披露。
**替代案(脚本内记 retry 次数状态文件)否**——为一条纪律加磁盘状态违背「状态磁盘化最小
面」;stalled 形态已有熔断兜底,failed 重派的滥用面是「无限烧钱」,一次纪律界 + ack 终态
不回队已封顶。stalled 无磁盘异常 recipe 同处落:「诊断无异常 → provider 拥塞形态 → 直接
重派(runner 已内建退避),NEVER 改写输入/删 marker/微脚本」。

**D5 慢响应画像 = 调用面示例值,非新机制。** 风险:企业慢模型下单元healthy 时长从实测
2.5–3min 拉长,失活表(默认 900s)可能误杀长生成单元 → 重派从头再生成 → 再误杀(每次
浪费一轮长生成 + 配额)。对策是**取值指引**(man + fragments 合规示例):`--stall-timeout-s`
≥ 实测单元 p99 ×3–5、`--call-timeout-s` 相应上移、`--wave` ≤ 配额 ÷ 每单元呼叫率 × 0.8、
`--time-budget-ms` 尽量贴近宿主 per-call 上限 ×0.8(减少重派间隙的配额闲置)。
**替代案(按环境自动探测单元时长分布)否**——观测机制本身复杂且首晚无数据;示例值 +
`--help` 指引零成本可执行。

**D6 delta 纯 ADDED,规避未 sync delta 冲突。** `fanout-dispatch` 能力下 stall-containment
的 MODIFIED delta 尚未 sync 到主 spec;本 change 若 MODIFIED 同名 requirement 会产生双
pending delta 冲突。冷却/退避与 retry-failed 均以**新增 requirement** 表达(行为新增而非
改写既有承诺),与前置 change 的落地顺序在 tasks 显式声明。

## Risks / Trade-offs

- [冷却拖慢健康 run?] → 触发条件 = 窗口内 ≥3 次 requeue,健康 run 的 crash 罕见且分散,
  实际零触发;真触发时说明配额确已打满,等待即吞吐。`--cooldown-s 0` 显式逃生。
- [熔断前退避占用宿主 per-call 预算] → 受剩余预算封顶 + 至多一次;最坏情形 = 少一次
  编排器重派轮次,无正确性影响。
- [--retry-failed 被编排器滥用为无限重派] → 纪律界(至多一次)+ ack 终态不回队 +
  熔断兜底;最坏烧一晚的用户面已被「企业 token 免费」画像吸收,准确性优先。
- [删除 `.failed` marker 丢失败原因?] → run.log(前置 D4)已留每单元输出尾,失败原因
  从日志读;marker 只是终态位。
- [枚举器 `--include-failed` 契约面 +5] → 单一布尔 flag、复用既有谓词与 item 字段,
  `tools/check_contracts.py` 自动断言;缺省行为逐字不变。
- [五 tier 行为分叉] → 冷却与 retry-failed 均落共享循环/共享谓词,t2 map 与 sdr 自动
  继承;单测按 tier 参数化。

## Migration Plan

前置 change 先落地 sync 后再实施本 change(冷却挂在其补位循环上)。纯附加 flag 与缺省
关闭路径(`--retry-failed` 显式、`--cooldown-s` 默认值仅在风暴形态生效),既有调用面零
破坏;回滚 = git revert 单点。运行中 run 不可热升级。

## Open Questions

- 冷却窗口/阈值常量(120s/3 次)取值——先按风暴时间账推导值落地,限流环境实跑数据回来
  再校准(同前置 change `--stall-timeout-s` 的校准路径)。
- t2 map 单元(plan_aggregate 枚举)是否存在 failed ack 形态——实现时核对,若无则
  `--include-failed` 对该枚举器为 no-op 透传(契约仍一致)。
