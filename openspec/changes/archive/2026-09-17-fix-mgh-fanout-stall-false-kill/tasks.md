# tasks — fix-mgh-fanout-stall-false-kill

> 契约与措辞以 `specs/fanout-dispatch/spec.md` 的两条 MODIFIED requirement 为准;
> 技术选型与替代案见 `design.md` D1–D5(含一处 apply 前需代入的实测值,见第 4 组)。

## 1. 取值域与关闭态(D2)

- [x] 1.1 `core/scripts/fanout_runner.py` 的 `--stall-timeout-s` 校验:取值域由 `>= 60` 改为
  `0 或 >= 60`;`1..59` 仍退出码 2,错误文案与 recipe 同时给出「合规最小值 60」与「关闭取值 0」
  两条出路
- [x] 1.2 四级不变式校验:仅当 `--stall-timeout-s > 0` 时校验 `stall < call`;
  关闭态下只校验 `call < time-budget-ms × 0.8`,默认值兜底与手动直跑提示行为逐字不变
- [x] 1.3 关闭态下 `_run_unit` 的静默分支不发生(`stall_timeout_s == 0` 即跳过该判据),
  `--call-timeout-s` 路径与树杀机制零改动
- [x] 1.4 关闭态下自适应宽限与本轮生效窗口逻辑整体短路(见 2.x),避免出现「窗口为 0 时的
  整除/放大」退化

## 2. 假杀自证 + 有界自适应宽限(D3)

- [x] 2.1 `_run_unit` / 派发循环引入**本轮生效窗口**可变状态(初值 = `--stall-timeout-s`,
  随 run 结束即弃,NEVER 跨 run 持久化);监控循环与心跳披露行都改读该生效值
- [x] 2.2 假杀自证:某单元曾以 `stall` 终态被树杀(无 ack 无 marker),其后在同一 run 的重派中
  以 ok/.done 收敛 → 触发一次放宽 `W ← min(2W, call_timeout_s × 0.8)`
  (复用既有 `stall_killed` 记录与终态登记,零新状态源)
- [x] 2.3 放宽事件在 stderr 披露一行(旧值 → 新值 + 触发单元 id);放宽到上限后不再上调
- [x] 2.4 边界:同一单元多次被杀-成功只计一次放宽;`2W` 溢出上限时直接落到上限值而非跳过

## 3. 代价可视(D4)

- [x] 3.1 stdout 摘要新增 `runtime_p50_s` / `runtime_p95_s` / `runtime_max_s`(由既有
  `unit_durations` 派生;本次 run 无完成单元时**省略三键**,不报 0)
- [x] 3.2 stdout 摘要新增 `stall_killed_slots_s`(被杀单元累计占用槽位秒)与
  `stall_killed_slot_pct`(÷ 本次 run 槽位总秒,保留一位小数);既有字段一个不改
- [x] 3.3 本轮发生过放宽时输出 `stall_window_s`(生效窗口终值);未放宽时省略该键
- [x] 3.4 进度侧车 `fanout_progress.<tier>.json` 同步携带 3.1–3.3 的同名字段

## 4. 默认值标定(D5)

> 标定已代入完成:`p99 × 2 = 650s` → 取整 600s → 下限 → **900s,默认值不改**。
> 样本(n=84, p50=134 / p95=229 / p99=325 / max=325)与偏差说明记于 `design.md` D5。

- [x] 4.1 确认 `DEFAULT_STALL_TIMEOUT_S` 保持 900,代码不改该常量
- [x] 4.2 `--help` 与模块 docstring 写明标定口径(`p99(完成单元运行时) × 2`,向下取整到分钟,
  不低于 900)与本次代入的样本摘要,使日后重标定有据可依
- [ ] 4.3 (承 D4)`runtime_*` 字段落地后,下一次真机轮用其复核标定值;样本显著漂移则重标定

## 5. 帮助与文档

- [x] 5.1 `--stall-timeout-s` 的 `--help` 文案重写:判据语义为「该单元此刻无产出」,
  **SHALL NOT** 表述为卡死证据;披露失效面(静默不区分「等网关排队」与「真卡死」)、正当用途
  (为 run 收敛设上界)、关闭取值 `0`、默认值标定口径(`p99 × 2`,不低于 900)、自适应宽限规则
- [x] 5.2 模块顶部 docstring 的失活检测段落同步(与 `--help` 逐字一致的口径)
- [x] 5.3 维护者私有文档区里的 `/mgh-init`、`/mgh-sdr` 命令人话说明:失活段补同一披露
  (按现有文档结构就近放置,不改行为)
- [x] 5.4 术语词典如需补「假杀自证 / 生效静默窗口」条目则补,否则不动
- [x] 5.5 `CHANGELOG.md` 记录默认静默窗口变化与新增字段;`VERSION` bump

## 6. 回归测试

- [x] 6.1 增用例:注入「先静默被杀、其后重派成功」的假单元 → 断言生效窗口翻倍、stderr 出现
  放宽披露行、stdout `stall_window_s` 为新值
- [x] 6.2 增用例:连续放宽至 `call × 0.8` 后不再上调(有界性),且 `--call-timeout-s` 仍是
  绝对兜底(单元绝不会存活超过它)
- [x] 6.3 增用例:`--stall-timeout-s 0` 下长时间静默的单元**不**被杀,`stall_killed` 为空数组,
  且校验不因 `stall >= call` 而退出码 2
- [x] 6.4 增用例:`--stall-timeout-s 1..59` 仍退出码 2 且 recipe 同时给出 60 与 0 两条出路
- [x] 6.5 增用例:代价可视字段存在性 + 无完成单元时 `runtime_*` 三键**省略**(非 0)
- [x] 6.6 断言既有 `TestRunUnitTreeKill` 各用例在默认(未放宽)路径下语义不变

## 7. 全量校验与真机验收

- [x] 7.1 `py tests/test_fanout_runner.py`、`py tests/test_fanout_stale.py` 全绿
- [x] 7.2 `py tools/check_contracts.py`、`py tools/check_distributed_purity.py`
- [x] 7.3 `py tests/test_deterministic.py` + 零依赖 AST 扫描(承 R2/R5.8,确认未引入 import)
- [x] 7.4 install 冒烟:双宿主镜像后自检无 warn
- [ ] 7.5 真机 45 分钟轮:对照 `stall_killed` 数量与完成增量,核对 `runtime_*` /
  `stall_killed_slot_pct` / `stall_window_s` 与日志自洽;记录本轮是否触发自适应放宽
- [ ] 7.6 真机复跑一轮 `--stall-timeout-s 0`:确认零静默杀、`partial:true` 干净早退、
  收敛有界由 `--call-timeout-s` 承担

> 4.3 / 7.5 / 7.6 留空:三者的动作都发生在**一次限流网关下的真机轮**里(45 分钟对照 +
> 关闭态复跑 + 用退出摘要的 `runtime_*` 复核标定),不是本仓可跑出来的结果。代码/文档/回归
> 测已就绪,勾选它们需要维护者在真机上跑完那一轮。
