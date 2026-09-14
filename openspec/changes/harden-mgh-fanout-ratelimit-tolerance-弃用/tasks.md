# tasks — harden-mgh-fanout-ratelimit-tolerance

> 前提:`harden-mgh-fanout-stall-containment` 已落地(本 change 冷却/退避挂在其槽位补位循环
> 与熔断重锚之上)。实施顺序:先 1(冷却)→ 2(retry-failed)→ 3(调用面)→ 4(测试)→ 5(收尾)。

## 1. 快败冷却 + 熔断前有界退避(design D1/D2)

- [ ] 1.1 `core/scripts/fanout_runner.py` 派发循环加快败窗口:滑动窗口(常量 120s)统计
      requeue 事件(crash/timeout/stall/spawn-error 回队尾;`failed:` ack 与 pre-spawn 失败
      不计),≥ 3 → 暂停新派发 `--cooldown-s`(默认 300,0=off);冷却期间在飞单元照常运行
      与收割,仅停新派发
- [ ] 1.2 冷却等待受剩余时间预算封顶(`--time-budget-ms` 传了则按剩余截断,无预算按全额);
      stderr 冷却披露行(触发计数 + 等待秒数)
- [ ] 1.3 熔断触发点前置有界退避:零推进判定成立、准备 exit 2 且预算允许 → 至多一次
      「冷却等待 → 全量重列磁盘终态 → 再观察」;推进 → 撤销熔断继续派发;仍零推进 →
      `stalled:true` 退出码 2;退避发生与否 stderr 披露
- [ ] 1.4 stdout 摘要新增 `cooldowns:<n>`(既有字段不变);`--help` 增 `--cooldown-s`
      (触发条件、0 值语义、与四级超时不变式的关系)

## 2. failed 终态有界重派口(design D3)

- [ ] 2.1 五枚举器增 `--include-failed`(缺省行为逐字不变):`list_scout_batches.py`、
      `list_clusters.py`、`plan_aggregate.py`(t2 map 节点)、`list_rule_jobs.py`、
      `diff_group.py`——failed 单元以 canonical 身份重进 `pending[]`,item 复用既有
      `failed_marker` 绝对路径字段(failed 谓词沿用各自既有 forward 判定,NEVER 文件名反推)
- [ ] 2.2 `fanout_runner.py --retry-failed`:认领带 `failed_marker` 的 pending 单元时删除
      该 marker(失败证据留 `*.run.log`)并正常派发;stdout 摘要新增 `retried_failed:<n>`;
      重派再 `failed:` ack → 写回 `.failed` 终态(既有 ack 状态机,零新增逻辑)
- [ ] 2.3 fragments 任务模板(`core/prompts/fragments/fanout/{scout,t1,t3}-task.md` 等)
      核对:任务消息模板不含 failed 语义假设,`--retry-failed` 单元收到与首次相同的消息
      (模板逐字替换机制天然保证,若有 id/序号类字段需核对幂等)

## 3. 调用面与编排器纪律同步(design D4/D5)

- [ ] 3.1 编排器 recipe 分支(三处):`core/prompts/fragments/init-stage/{scout,t1,t3}.md`
      派发段 + sdr 两壳(`releases/claude-code/commands/mgh-sdr.md`、
      `releases/opencode/command/mgh-sdr.md`)派发段 + `core/scripts/discipline_core.py`
      path_recipes——① `stalled:true` 且 `resume_state --check` 无磁盘异常 → provider
      拥塞/限流形态 → 直接重派(runner 内建退避),NEVER 改写任务输入、NEVER 删
      `.done`/`.failed` marker、NEVER 微脚本内省;② tier 收尾 `failed>0` → 读该单元
      `*.run.log` 判形态 → provider 瞬断 → **至多一次**带 `--include-failed` + `--retry-failed`
      重派;再失败 → 接受缺口、报告披露
- [ ] 3.2 慢/限流画像示例值(R3 人类面简练):`docs/man/mgh-init.md`、`docs/man/mgh-sdr.md`
      dispatcher 段增画像表——`--stall-timeout-s` ≥ 实测单元 p99 ×3–5、`--call-timeout-s`
      相应上移、`--wave` ≤ 窗口配额 ÷ 每单元呼叫率 × 0.8、`--time-budget-ms` 贴近宿主
      per-call × 0.8;fragments 合规示例组同步一条慢画像组合
- [ ] 3.3 `docs/opencode-fanout-runner-guide.md` §6 增「经验 8 — 限流风暴要冷却,不要熔断
      循环」(现象→原因→改法,与既有经验同格式)
- [ ] 3.4 `docs/glossary.md` 补条目(若缺):限流风暴、快败冷却、有界重派

## 4. 回归测试

- [ ] 4.1 `tests/test_fanout_runner.py` 冷却用例(test host + monkeypatch 时钟注入):窗口内
      ≥3 次 requeue → 触发冷却与 stderr 披露;`cooldowns` 计数正确;`failed:` ack/pre-spawn
      失败不计数;`--cooldown-s 0` 零行为变化;预算封顶截断
- [ ] 4.2 熔断前退避用例:零推进 + 预算充足 → 一次退避后磁盘推进 → 熔断撤销;退避后仍零
      推进 → `stalled:true` exit 2 且本次 run 不再退避;无预算 → 直接熔断
- [ ] 4.3 retry-failed 用例:预置 `.failed` marker → 枚举器 `--include-failed` 后 pending
      含该单元且 `failed_marker` 路径正确;`--retry-failed` 认领时 marker 被删除、重派
      成功写 `.done`、`retried_failed` 计数;缺省(两 flag 均不传)零行为变化(既有用例
      全绿即证);重派再 failed → `.failed` 写回、不回队
- [ ] 4.4 五枚举器 `--include-failed` 参数化用例(各枚举器测文件内):flag 缺省不动既有
      stdout shape;开启后 failed 单元身份与 `failed_marker` 路径正确
- [ ] 4.5 `py tools/check_contracts.py`(新 flag 经 `--help` 断言)、
      `py tools/check_distributed_purity.py`、`py tools/measure_prompts.py`(fragments
      增量在预算内)无新违例

## 5. 全量校验与收尾

- [ ] 5.1 `py tests/test_fanout_runner.py`、`py tests/test_fanout_stale.py` 及各枚举器测试
      全绿;五 tier `--pending-file` 冒烟 + `--dry-run` 全流程通过
- [ ] 5.2 CHANGELOG.md / VERSION bump(R5.8)
- [ ] 5.3 大仓限流环境实跑验收:人为压低配额(或记录真实 429 时段)跑 T1/scout tier,
      验证——冷却触发与自愈(熔断不再每 1–2min 空转)、run.log 可判读 provider 报错形态、
      一次 `--retry-failed` 后 failed 清零或缺口披露;宿主 TUI 心跳/冷却行可判读
