## ADDED Requirements

### Requirement: 快败冷却与熔断前有界退避(限流/拥塞容差)

dispatcher 派发循环 SHALL 对「快速失败再入队」事件具备节流能力:滑动时间窗内 requeue 事件
(crash/timeout/stall/spawn-error 终态、无 ack 无 marker 回队尾的单元;**不含** `failed:` ack
与 pre-spawn 失败——两者不回队、非风暴形状)计数达到阈值时,SHALL 暂停派发新单元
`--cooldown-s`(默认 300;0 = 关闭;实际等待 MUST 受剩余时间预算封顶)后再继续。冷却判定
SHALL 与 provider 无关——NEVER 依赖对子进程输出做错误签名识别(429 等错误发生在子进程内,
dispatcher 不可见,签名跨 provider 脆弱),只以「失败→立即重派→再失败」的事件节奏为信度源。

零推进熔断(滚动磁盘进度窗口)触发、准备以退出码 2 收束时,若时间预算允许,dispatcher
SHALL 先执行**至多一次**「冷却等待 → 重列磁盘终态 → 再观察」的有界退避:等待后出现推进则
继续派发(熔断不触发),仍零推进才以 `stalled:true` 退出码 2 收束——一次 dispatcher 调用
内自带跨限流窗口的自愈尝试, NEVER 无退避地直接熔断。

**披露**:冷却发生时 stderr SHALL 打冷却行(原因计数 + 等待秒数);stdout 摘要 SHALL 新增
`cooldowns:<n>`(本次 run 冷却次数,既有字段不变);熔断前退避的发生与结果 SHALL 在 stderr
披露。`--help` SHALL 声明 `--cooldown-s` 的触发条件与 0 值语义。

#### Scenario: 快败风暴触发冷却

- **WHEN** 短时间窗内连续 ≥ 阈值个单元以 crash 终态快速失败并回队尾(限流拒答形态),
  队列仍有待派单元
- **THEN** dispatcher 暂停派发 `--cooldown-s`(受剩余预算封顶)后继续,期间 stderr 出现
  冷却披露行;窗口内失败密度下降后不再触发;stdout 摘要 `cooldowns` 计数增加

#### Scenario: 熔断前有界退避跨过限流窗口

- **WHEN** 熔断观察点判定零推进、准备退出码 2,但剩余时间预算充足
- **THEN** dispatcher 先等待一次冷却时长并重列磁盘终态;若重派单元此间完成(磁盘推进)
  → 熔断不触发、派发继续;若仍零推进 → `stalled:true` + `stalled_pending[]` 退出码 2,
  本次 run 内退避至多发生一次

#### Scenario: failed ack 与 pre-spawn 失败不触发冷却

- **WHEN** 单元以显式 `failed:` ack 终态(写 `.failed`,不回队)或 pre-spawn 锚校验失败
- **THEN** 该事件不计入快败冷却窗口;正常终态推进的 run 不产生冷却等待

#### Scenario: `--cooldown-s 0` 显式关闭

- **WHEN** 调用方显式传 `--cooldown-s 0`(如宿主预算极紧的场景)
- **THEN** 冷却与熔断前退避均不发生,行为与无此机制时逐字一致;`--help` 文案与行为一致

### Requirement: failed 终态单元的有界重派(--include-failed / --retry-failed)

tier 枚举脚本(`list_scout_batches.py`/`list_clusters.py`/`plan_aggregate.py`/`list_rule_jobs.py`/
`diff_group.py`)SHALL 支持 `--include-failed`:存在 `.failed` 终态标记的单元以 canonical 身份
重新进入 `pending[]`(item 携带既有 `failed_marker` 绝对路径字段),缺省(不传)行为不变
(failed 单元排除于 `pending[]`、只计入 `failed` 计数)。单元身份 MUST 来自枚举器 stdout,
NEVER 由 dispatcher 或编排器从文件名反推(超长 id 截断 stem ≠ canonical id)。

dispatcher SHALL 支持 `--retry-failed`:对认领到的带 `failed_marker` 的 pending 单元,派发前
SHALL 删除该 `.failed` 标记(既有失败证据已由该单元 run.log 留痕,不因 marker 删除而丢失)
并正常派发;stdout 摘要 SHALL 新增 `retried_failed:<n>`(本次 run 重派的 failed 单元数)。
编排器纪律 SHALL 把重派限定为**有界**:同一 tier 收尾 `failed>0` 时,依据 run.log 形态判断
是否 provider 瞬断,至多执行一次 `--retry-failed` 重派;再次失败即接受缺口并在报告中披露,
NEVER 无限重派。

#### Scenario: failed 单元经 --retry-failed 重进队列并清除终态

- **WHEN** 上次 run 留有 3 个 `.failed` 标记的单元,本次以 `--retry-failed` 重派
  (枚举器带 `--include-failed`)
- **THEN** 3 个单元以 canonical 身份出现在 `pending[]`,dispatch 认领时其 `.failed`
  标记被删除;重派成功 → 该单元写 `.done`;stdout `retried_failed:3`

#### Scenario: 缺省路径零行为变化

- **WHEN** 不传 `--include-failed` 与 `--retry-failed`(既有编排器调用面)
- **THEN** 枚举器 `pending[]` 不含 failed 单元、dispatcher 不删除任何 `.failed` 标记,
  stdout 无 `retried_failed` 语义变化;与既有契约逐字一致

#### Scenario: 重派再失败保持有界

- **WHEN** `--retry-failed` 重派的单元再次以 `failed:` ack 终态
- **THEN** 写回 `.failed` 终态标记(不回队尾);编排器纪律判定本 tier 不再重派
  (缺口进报告披露),dispatcher 侧不自行循环重派
