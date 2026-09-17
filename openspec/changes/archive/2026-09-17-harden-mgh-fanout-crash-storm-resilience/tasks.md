# tasks — harden-mgh-fanout-crash-storm-resilience

> 前提:`harden-mgh-fanout-stall-containment` 已落地并 sync(冷却挂其槽位补位循环;分类读其
> 输出尾部缓存/run.log;本 change delta 纯 ADDED,不触其 MODIFIED requirement)。

## 1. fanout_runner 快败冷却与熔断前退避

- [x] 1.1 requeue 事件窗口:滑动 120s 窗(实现常量)统计 crash/timeout/stall/spawn-error 回队
  事件;`failed:` ack 与 pre-spawn 锚失败不计数;窗口计数与既有熔断窗口、风暴窗口互不共享
- [x] 1.2 冷却触发:窗内 ≥3 次 requeue → 暂停派发 `--cooldown-s` 秒(默认 300,`0`=off);冷却
  时长按「剩余时间预算 − 在飞收敛余量」封顶,不足则退化立即继续 + stderr 披露;冷却只停
  新派发,在飞照常收割;stderr 冷却行 + stdout `cooldowns:<n>`
- [x] 1.3 熔断前有界退避:零推进熔断 exit 2 前,预算允许时至多一次「冷却 → 全量重列磁盘
  终态 → 再观察」;有推进撤销熔断继续派发,仍零推进才 exit 2(`stalled` 契约逐字不变)
- [x] 1.4 argparse 新增 `--cooldown-s`;`--help` 文案写明触发条件、预算封顶、一次退避语义

## 2. fanout_runner crash 分类与风暴截断

- [x] 2.1 crash 终态钩子:扫描单元输出尾部缓存(数据源 = stall-containment 读线程尾部/run.log),
  闭集特征(`429`/`too many requests`/`rate limit`/`quota`,大小写不敏感子串)记
  `crash_cause:"rate-limit"|"unknown"`;仅 crash 终态参与(ok/failed/timeout/stall 不扫)
- [x] 2.2 风暴窗口计数器:自上次磁盘终态推进起累计 crash 事件;与冷却窗口、熔断窗口计数器
  互不共享;磁盘推进即清零
- [x] 2.3 风暴截断:窗内 crash ≥ `--wave` 且全部 rate-limit → 优先于新一轮冷却直接停派,
  exit 2;stdout `rate_limited:true` + `rate_limited_crashes:[…]`;stderr 冷却 recipe(等满一个
  配额窗口再 resume、wave 公式 `floor(8 ÷ 每子每分钟调用数)`、失活杀不属 crash、
  `--no-rate-limit-stop` 可禁用)
- [x] 2.4 argparse 新增 `--no-rate-limit-stop`(store_false,默认启用);`--help` 写明分类特征、
  阈值、与冷却/熔断的快慢三层关系
- [x] 2.5 终态汇总适配:`partial`/`stalled` 判定与 `stalled_pending[]` 契约逐字不变;`waves_run`
  语义不变

## 3. failed 终态有界重派口

- [x] 3.1 五枚举器 `--include-failed`(缺省关闭逐字节不变):failed 单元以 canonical 身份重进
  `pending[]`,复用既有 forward failed 谓词与 `failed_marker` 路径字段,NEVER 文件名反推;
  涉及 `list_scout_batches.py`/`list_clusters.py`/`plan_aggregate.py`/`list_rule_jobs.py`/
  `diff_group.py`(plan_aggregate 若无 failed ack 形态则 no-op 透传,契约一致)
- [x] 3.2 `fanout_runner.py --retry-failed`:认领携 `failed_marker` 单元时先删 marker 再 spawn;
  stdout `retried_failed:<n>`;重派再失败写回新 marker(无自动循环)
- [x] 3.3 调用面纪律:`discipline_core.py` path_recipes 与 `init-stage/{scout,t1,t3}.md`、sdr
  两壳派发段增两分支——`stalled:true` 且 `resume_state --check` 无磁盘异常 → provider 拥塞
  → 直接重派(NEVER 改写输入/删 marker/微脚本);tier 收尾 `failed>0` 且 run.log 呈 provider
  瞬断 → 至多一次 `--retry-failed`,再失败接受缺口 + 报告披露

## 4. 回归测试

- [x] 4.1 冷却用例:第 3 次 requeue 触发/在飞不受影响/`--cooldown-s 0` 关闭/预算封顶退化 +
  披露/failed-ack 与 pre-spawn 失败不触发/熔断前一次退避两分支(推进撤销、零推进出束)/
  单调用至多一次退避
- [x] 4.2 分类与风暴用例:特征命中(大小写混杂/各特征串)、ok 终态含 `429` 不分类、特征漂移
  全 unknown → 不截断且冷却照常、wave 个全限流 → 截断 exit 2 + 披露 + recipe、wave-1 不
  触发、混入 unknown 不触发、磁盘推进清零、`--no-rate-limit-stop` 回退路径与引入前逐字一致
- [x] 4.3 retry-failed 用例:五枚举器 `--include-failed` 缺省不变 + 开启重进(含超长 id canonical
  身份)、认领删 marker、失败写回、`retried_failed` 计数
- [x] 4.4 stdout 契约断言增四新键(`cooldowns`/`rate_limited`/`rate_limited_crashes`/
  `retried_failed`);既有字段零增删断言

## 5. 调用面与文档同步

- [x] 5.1 涉及命令的人话说明(维护者私有文档区):配额/慢画像配置段(wave 校准公式、
  `--stall-timeout-s`/`--call-timeout-s` ≥ 实测单元 p99 ×3–5、`--time-budget-ms` 贴近宿主 ×
  0.8、`--stall-timeout-s` ≥ 600 不下调、冷却/截断/`--retry-failed` 三机制与 flag 表)
- [x] 5.2 fan-out 运行手册补经验 8(配额限流:快败形状、冷却/截断/
  retry-failed 三层、wave 公式);术语词典补「快败风暴/冷却/retry-failed」条目(若缺)
- [x] 5.3 `tools/check_contracts.py` 断言新 flag(`--cooldown-s`/`--no-rate-limit-stop`/
  `--retry-failed`/五枚举器 `--include-failed`)

## 6. 全量校验与收尾

- [x] 6.1 `py tools/check_contracts.py`、`py tests/test_fanout_runner.py`、`py
  tests/test_fanout_stale.py`、`py tests/test_list_clusters.py` 全绿;五 tier 冒烟
- [x] 6.2 install 冒烟:两宿主镜像后自检无 warn
- [ ] 6.3 真机验收(配额环境):人为压满配额 → 观察冷却触发与(若特征命中)风暴截断 exit 2;
  冷却后 resume 推进;制造一个礼貌 `failed:` ack → `--include-failed`/`--retry-failed` 重派
  成功;CHANGELOG.md / VERSION bump(注明前提依赖 stall-containment 已落地)
