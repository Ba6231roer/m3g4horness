# fanout-dispatch Delta

## ADDED Requirements

### Requirement: 快败冷却与熔断前有界退避

`fanout_runner.py` SHALL 维护一个**快败滑动窗口**（120s，实现常量）统计 **requeue 事件**——
单元以 crash/timeout/stall/spawn-error 终态且回到 pending 队尾的事件；显式 `failed:` ack 与
spawn 前锚校验失败 SHALL NOT 计入（两者终态化不回队，无风暴形状，计入会让确定性配置错误
假触发冷却）。窗口内 requeue 事件 ≥ 3（实现常量）时，dispatcher SHALL 暂停派发新单元
`--cooldown-s` 秒（默认 300；`0` = 关闭；取值 SHALL 按「剩余时间预算 − 在飞收敛余量」封顶，
预算不足时冷却退化为立即继续并如实 stderr 披露）；冷却期间在飞单元照常运行、照常收割——
冷却只停**新派发**。每次冷却 SHALL 向 stderr 打一行披露（触发原因 + 实际冷却秒数），stdout
摘要新增 `cooldowns:<n>`（本 run 冷却次数；既有字段零增删）。

**熔断前有界退避**：零推进熔断准备以退出码 2 收束时，若剩余时间预算允许，dispatcher SHALL
执行**至多一次**「冷却 `--cooldown-s` → 全量重列磁盘终态 → 再观察」——重列有推进（done+failed
计数增加）则撤销熔断、恢复派发；仍零推进才以退出码 2 fail-loud（既有 `stalled` 契约逐字不变）。
NEVER 无限退避（跨配额窗口的收敛 SHALL 仍归编排器 `--resume` 重派循环，不塞进单次调用）。

#### Scenario: 快败风暴触发冷却，新派发暂停而在飞照常

- **WHEN** 配额耗尽，120s 滑动窗口内第 3 个单元 crash 回队
- **THEN** dispatcher 暂停派发 `--cooldown-s` 秒（stderr 披露一行），已 spawn 的在飞单元继续
  运行并正常收割；冷却结束后恢复派发；stdout 摘要 `cooldowns:1`

#### Scenario: failed-ack 与 pre-spawn 失败不触发冷却

- **WHEN** 窗口内 3 个单元全部以显式 `failed:` ack 终态（写 `.failed`，不回队）
- **THEN** 不触发冷却（非 requeue 事件）；failed 终态语义不变

#### Scenario: 冷却受剩余时间预算封顶

- **WHEN** 冷却触发时剩余时间预算 < `--cooldown-s` + 在飞收敛余量
- **THEN** 冷却时长被截到预算允许值；预算耗尽则跳过等待立即继续，stderr 如实披露截断

#### Scenario: 熔断前一次退避自愈

- **WHEN** 零推进熔断条件满足且剩余时间预算允许
- **THEN** 执行一次「冷却 → 全量重列 → 再观察」；重列有推进 → 熔断撤销、继续派发；
  仍零推进 → 退出码 2 + `stalled:true`（契约不变）；本路径在单次调用内至多发生一次

### Requirement: crash 原因分类与限流 crash 风暴截断

`fanout_runner.py` SHALL 在单元以 **crash 终态**(非零退出或无 ack 回执)结束后,对该单元的
输出尾部(stdout/stderr 缓存尾,数据源 = 失活检测/运行留痕机制)做**确定性限流特征分类**:
命中特征集 `429`/`too many requests`/`rate limit`/`quota`(大小写不敏感,子串匹配)→ 该单元记
`crash_cause:"rate-limit"`,否则 `"unknown"`。分类 SHALL 对全部 tier 一致(共享派发循环,一处
生效);ok/failed/timeout/stall 终态 SHALL NOT 参与分类(仅 crash)。

**限流 crash 风暴截断(快路径止损)**:dispatcher SHALL 维护一个**crash 风暴观察窗口**(自上次
磁盘终态推进〔任一单元 ok/failed marker 落盘〕起累计的 crash 事件);当窗口内 crash 计数
≥ `--wave` **且全部** `crash_cause:"rate-limit"` 时,SHALL 立即停止派发剩余单元并**优先于新一轮
冷却**直接截断,以退出码 2 fail-loud:stdout 摘要报 `rate_limited:true` +
`rate_limited_crashes:[<unit>…]`,stderr 给**冷却 recipe**——等满一个配额窗口再 resume(窗口
时长以网关配置为准,如 10 分钟)、wave 校准公式(`wave = floor(8 ÷ 每子每分钟调用数)`,8 =
配额每分钟上限 × 80% 安全余量)、提示失活树杀不属 crash、提及本截断可经
`--no-rate-limit-stop` 禁用。截断 SHALL 先于零推进熔断触发(快路径);零推进熔断(慢路径,含
其熔断前一次退避)行为不变,仍是兜底。`--no-rate-limit-stop` 传入时 SHALL 完全跳过本截断。
**优雅退化**:特征集漂移(新网关措辞)→ 分类全 unknown → 本截断不触发,快败冷却路径照常
自愈兜底——文本签名仅是快停与披露层,NEVER 是唯一防线。非限流 crash(unknown)SHALL NEVER
计入风暴判定。

#### Scenario: 限流 crash 风暴被立即截断

- **WHEN** 配额耗尽,一个观察窗口内 `--wave 5` 个单元相继 crash 且输出尾部均含 `429`/
  `Too Many Requests` 特征
- **THEN** 第 5 个 crash 终态判定完成后 dispatcher 停止派发(优先于再等一轮冷却),退出码 2,
  stdout `rate_limited:true` + `rate_limited_crashes` 含 5 个单元 id,stderr 冷却 recipe 给出
  等窗与 wave 公式;零推进熔断未被等待触发(快路径先停)

#### Scenario: 特征漂移时优雅退化到冷却路径

- **WHEN** 网关换用新错误措辞,窗口内 5 个 crash 输出尾部均不含任何特征串
- **THEN** 分类全 unknown → 风暴截断不触发;快败冷却(事件驱动)照常触发自愈,熔断兜底不变

#### Scenario: 单次偶发限流 crash 不触发截断

- **WHEN** 窗口内仅 1 个单元 crash 且带限流特征,其余单元正常终态推进
- **THEN** crash 计数 < `--wave`,不截断;该单元留 pending 照常重派,后续磁盘推进把窗口清零

#### Scenario: 混入非限流 crash 不触发截断

- **WHEN** 窗口内 5 个 crash 中 4 个带限流特征、1 个 `unknown`(如脚本缺陷)
- **THEN** 风暴条件不满足(须全部 rate-limit),不截断;unknown crash 走既有语义(留 pending/
  零推进熔断兜底)

#### Scenario: 禁用 flag 回退

- **WHEN** 调用传 `--no-rate-limit-stop` 且发生限流 crash 风暴
- **THEN** 无快路径截断,冷却与熔断路径行为与未引入本机制逐字一致

#### Scenario: ok/failed/timeout/stall 终态不参与分类

- **WHEN** 某单元 output 尾部含 `429` 字样但以 ok 终态收尾(如子代理在报告文本里引用了 429)
- **THEN** 不产生任何 crash_cause 记录,不进风暴计数;仅 crash 终态参与分类

### Requirement: failed 终态单元的有界重派

五个 tier 枚举器(`list_scout_batches.py`/`list_clusters.py`/`plan_aggregate.py`/
`list_rule_jobs.py`/`diff_group.py`)SHALL 各增 `--include-failed` 布尔 flag(缺省关闭):开启时,
failed 单元 SHALL 以 **canonical 身份**重进 `pending[]`——身份与 `failed_marker` 绝对路径均来
自枚举器自身的 forward 谓词与既有 item 字段,NEVER 经文件名 stem 反推;缺省(不传 flag)stdout
逐字节不变。`fanout_runner.py` SHALL 增 `--retry-failed`:认领携带 `failed_marker` 的单元时
SHALL 先删除该 `.failed` marker(失败证据已留存在该单元的 `*.run.log`)再正常派发;stdout 摘要
新增 `retried_failed:<n>`。重派后再失败 SHALL 写回新 marker(天然有界:ack 终态不回队,无
重派循环)。编排器纪律(调用面文案,非机制强制):tier 收尾 `failed>0` 且 run.log 呈 provider
瞬断形态 → **至多一次** `--retry-failed` 重派;再失败 → 接受缺口并在报告披露。

#### Scenario: include-failed 重列 failed 单元

- **WHEN** 某单元有 `.failed` marker,枚举器以 `--include-failed` 运行
- **THEN** 该单元以 canonical id 出现在 `pending[]` 且携带 `failed_marker` 绝对路径;
  不传 flag 时它仍被排除,stdout 其余字段逐字节不变

#### Scenario: retry-failed 认领时删除 marker

- **WHEN** dispatcher 以 `--retry-failed` 认领一枚举出的 failed 单元
- **THEN** 该单元 `.failed` marker 先被删除再 spawn;成功 → 写 `.done`,失败 → 写回新
  `.failed`(无自动循环);stdout `retried_failed` 计数 +1

#### Scenario: 身份永远来自枚举器

- **WHEN** 某 failed 单元的 id 超长(文件名 stem 被截断)
- **THEN** `--include-failed` 重进 `pending[]` 的身份仍是完整 canonical id(与既有 forward
  谓词同源);NEVER 出现「按截断 stem 反查身份」的路径
