> **人话序** mgh-init 的目标用户环境是企业内网部署的大模型服务:响应慢、且有硬性调用频率限制(如每 10 分钟 100 次)。在这个环境下 fanout 的失败形状不是已复盘过的「挂死」,而是**限流风暴**:单元撞上配额 → opencode 内建重试仅 2 次且是秒级退避(`session/prompt.ts:234`),耗尽即进程报错退出 → runner 记 crash、无 marker → **立即回队尾重派**(`fanout_runner.py:1674`,全文件无任何 sleep/退避)→ 再撞配额。风暴一轮(崩→重派→熔断 exit 2→编排器诊断→`--resume`→再风暴)只要 1–2 分钟,远快于 10 分钟窗口恢复,整晚可能耗在反复熔断上;弱编排器也可能在无指引的反复 stalled 中放弃 → 中途失败,隔天晚上重来。另外模型在 provider 报错后礼貌回 `failed:` ack 会写 `.failed` **终态**标记,枚举器把该单元排除出 pending → tier「完成」但带覆盖洞。改什么:① runner 派发循环加快败冷却(连续快速失败 → 暂停派发一段时间)+ 熔断退出前一次有界退避重试;② 枚举器增 `--include-failed` + runner 增 `--retry-failed`,给 failed 终态一个有界的确定性重派口;③ 慢响应画像的失活/总长超时校准指引(防误杀→重派→再误杀);④ 编排器 stalled 无磁盘异常时的 recipe 补分支。怎么验证:单测(冷却触发/披露/退避重试/retry-failed 重派)+ 契约 lint + 限流环境大仓实跑。

## Why

- **环境事实(新)**:目标用户跑 mgh-init 的 LLM 是企业内网自部署服务——响应慢、并发频率硬限制(例:每 10 分钟 ≤100 次调用)。`--wave 5` × 每子代理 1–3 次呼叫/分钟 ≈ 5–15 次/分钟,**健康运行就已贴着或超过 10 次/分钟窗口配额**;429 形态不是异常而是常态。
- **opencode 源码证据**:主会话 LLM 调用 `retries: 2`(`packages/opencode/src/session/prompt.ts:234`)→ `maxRetries: input.retries ?? 0`(`session/llm.ts:323`)。AI SDK 重试为秒级指数退避,对 10 分钟量级的限流窗口无效;重试耗尽 → 抛错 → `opencode run` 进程退出 → runner 归为 crash(无 ack 无 marker)。
- **runner 现状无退避**:`core/scripts/fanout_runner.py` 全文件无 sleep/backoff/cooldown(grep 实证);crash/timeout/stall/spawn-error → `queue.append(unit)` **零延迟回队尾**(`:1674`)。D7 熔断(连续 2 窗口 ×5 槽零磁盘推进 → exit 2)之后,编排器 recipe(t1 fragment)`resume_state 诊断 + --resume 续跑`——诊断(磁盘)必然「无异常」(崩溃不留痕),编排器立即重进风暴。**全链路没有任何一处等待窗口恢复**。
- **风暴时间账**:单单元 fast-fail ≈5–15s;熔断触发 ≈ 10 次派发后 → 一轮风暴 1–2 min ≪ 10 min 窗口 → 编排器重派时配额未恢复 → 永动空转,整晚预算耗在反复熔断;或弱编排器在无指引的反复 stalled 中提前放弃(R5.4 磁盘续跑能救回进度,但那一晚已废)。
- **failed 终态覆盖缺口**:子代理显式 `failed:` ack(含模型在 provider 报错后礼貌放弃的形态)→ `.failed` 终态标记 → 枚举器 `pending[]` 排除 → tier 以「完成」收尾但带覆盖洞,直接损失 mgh-init 的准确性;当前无任何确定性重派口(只能手工删 marker)。
- **与 stall-containment 的关系**:该 change(槽位补位/失活检测/树杀/run.log/熔断重锚)治「挂死」;本 change 治「**快败风暴**」——两者失败签名相反(零输出 vs 秒级报错退出),机制正交、都需要。本 change 挂在槽位补位循环上,**以 stall-containment 先落地为前提**。

## What Changes

- **快败冷却 + 有界退避**(`fanout_runner.py` 派发循环)。滑动窗口内 requeue 事件(crash/timeout/stall/spawn-error;**不含** failed-ack 与 pre-spawn failed——两者不回队、非风暴形状)≥ 阈值 → 暂停派发 `--cooldown-s`(默认 300,0=off,受剩余时间预算封顶)。熔断 exit 2 之前,若时间预算允许,做**一次**「冷却 → 重列 → 再观察」的有界退避重试(跨过限流窗口的自愈尝试)。stderr 冷却行 + stdout 摘要新增 `cooldowns:<n>`。签名**与 provider 无关**:不识别 429 文本(子进程内不可见、跨 provider 脆弱),只数「快速失败再入队」事件本身。
- **failed 终态的有界重派口**。五个 tier 枚举器(`list_scout_batches` / `list_clusters` / `plan_aggregate` / `list_rule_jobs` / `diff_group`)增 `--include-failed`:failed 单元以 canonical 身份重进 `pending[]`(携带既有 `failed_marker` 绝对路径字段,NEVER 文件名反推);`fanout_runner.py --retry-failed` 在认领此类单元时删除其 `.failed` 标记(run.log 已留证据)并正常派发;stdout 摘要新增 `retried_failed:<n>`。编排器纪律:tier 收尾 `failed>0` 且 run.log 形态像 provider 瞬断 → **至多一次** `--retry-failed` 重派。
- **慢响应画像校准指引**(调用面/doc,非代码行为)。man pages + fragments 的合规示例值增「慢/限流画像」:`--stall-timeout-s`/`--call-timeout-s` 按实测单元时长 p99 ×3–5 取值(防慢生成被失活误杀 → 重派 → 再误杀的空转循环)、`--wave` 按「配额 ÷ 每单元呼叫率 × 0.8」收缩。
- **编排器 stalled recipe 补分支**。scout/t1/t3 fragments 派发段、sdr 两壳派发段、`discipline_core.py` path_recipes 增一行:`stalled:true` 且 `resume_state --check` 无磁盘异常 → 判定 provider 拥塞/限流形态 → 直接重派(runner 内冷却已退避);NEVER 改写任务输入、NEVER 删 `.done`/`.failed` marker、NEVER 微脚本内省。
- **非目标**:不做 HTTP 429 签名识别;不做配额探测/自适应限速;不改 opencode 上游;不改 marker 语义(除显式 `--retry-failed` 路径);不做细粒度 token-bucket 派发节奏(冷却已覆盖风暴形态,wave 爆发相对 10min 窗口是次要项,归入画像指引)。

## Capabilities

### New Capabilities

<!-- 无。全部为 fanout-dispatch 既有能力的新增要求(纯 ADDED)。 -->

### Modified Capabilities

- `fanout-dispatch`: 新增两条 requirement(**纯 ADDED,不改动既有 requirement 文本**——该能力下 `harden-mgh-fanout-stall-containment` 的 MODIFIED delta 尚未 sync,本 change 避免与其冲突):① 「快败冷却与熔断前有界退避」——派发循环对快速失败再入队事件具备节流与跨窗口自愈,披露契约明确;② 「failed 终态单元的有界重派」——枚举器 `--include-failed` 与 dispatcher `--retry-failed` 的组合契约(身份来自枚举器、marker 删除、计数披露)。

## Impact

- **代码**:`core/scripts/fanout_runner.py`(冷却窗口/熔断前退避/`--retry-failed` 认领时删 marker/stdout 扩展);`core/scripts/list_scout_batches.py`、`list_clusters.py`、`plan_aggregate.py`、`list_rule_jobs.py`、`diff_group.py`(各增 `--include-failed`,复用既有 forward failed 谓词);`core/prompts/fragments/init-stage/{scout,t1,t3}.md` 派发段、`releases/{claude-code,opencode}` sdr 两壳派发段、`core/scripts/discipline_core.py` path_recipes(recipe 分支 + 画像示例值);`docs/man/{mgh-init,mgh-sdr}.md`、`docs/opencode-fanout-runner-guide.md` §6 增限流画像经验。
- **测试**:`tests/test_fanout_runner.py`(冷却触发/披露/熔断前一次退避/retry-failed 重派与 marker 删除/failed-ack 不触发冷却)、各枚举器 `--include-failed` 用例。
- **前提**:`harden-mgh-fanout-stall-containment` 先落地并 sync(冷却挂在槽位补位循环 + 熔断重锚之上)。
- **零新依赖**(stdlib,承 R2);五 tier 共享同一循环与枚举器谓词,一改全 tier 受益。
