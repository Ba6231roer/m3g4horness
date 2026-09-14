# tasks — harden-mgh-fanout-stall-containment

## 1. fanout_runner 槽位补位调度核心(D1)

- [x] 1.1 重写派发循环:波次屏障(`with ThreadPoolExecutor(...) as pool: list(pool.map(...))`)→ 在飞上限 `--wave` 的补位循环(每单元独立 future 提交,`concurrent.futures.wait(FIRST_COMPLETED, timeout=1s)` 轮询收割;终态处理逻辑复用现 `_dispatch` 尾段);内存 pending 队列 + 补位取单元前 `.done`/`.failed` marker `stat` 懒校验(存在即跳过取下一)
- [x] 1.2 终态汇总与退出路径适配:队列耗尽且在飞归零后全量重列一次(`_snapshot()`);`partial`/`done`/`failed`/`pending` 判定沿用现语义;`waves_run` 改为累计派发单元数、心跳 `wave=` 改为单元派发序号(字段名不变);stdout 既有字段零增删(除 2.3 的 `stall_killed`)
- [x] 1.3 `--pending-file` 测试钩子适配:首列消费后重列返回空 pending 的单遍语义保持有效(补位循环下队列排空即收敛,`test` host 不 spawn 路径回归)

## 2. 失活检测 + 外科树杀 + 运行留痕(D2/D3/D4/D8)

- [x] 2.1 `_run_unit` 改造:`Popen` 后按流起读线程(stdout/stderr 各一)滚动更新 `last_byte_ts` + 环形缓存尾部(各 8KB 上限);写线程投递任务消息后关闭 stdin;监控循环 1s 粒度判定「静默 ≥ `--stall-timeout-s`」与「总时长 ≥ `--call-timeout-s`」,触发即调 `_kill_tree(proc.pid)`(替代 `proc.kill()`,修 `.cmd` shim 链孤儿)后收割
- [x] 2.2 新 flag `--stall-timeout-s`(默认 900;`< 60` 退出码 2 拒识)与 `--hb-interval-s`(默认 60)入 argparse + `--help` 文案(四级不变式 + 失活判定依据)
- [x] 2.3 run.log 落盘:每单元终态写 `<checkpoints>/<tier>/<_safe_name(unit)>.run.log`(stdout/stderr 尾部截断;ok 亦写);非 ok 终态 stderr 诊断行附 run.log 绝对路径;stdout 摘要新增 `stall_killed:[<unit>…]`
- [x] 2.4 周期在飞心跳:每 `--hb-interval-s` 向 stderr 打一行在飞披露(`[fanout_runner <tier>] +HH:MM:SS inflight=<k> unit=<id> idle=<s>s done=<d>/<total>`);stdout 单行 JSON 契约不变

## 3. 不变式启动校验 + 熔断重锚(D5/D7)

- [x] 3.1 spawn 前不变式校验:传 `--time-budget-ms` 时要求显式 `--call-timeout-s` 且 `< budget×0.8`、`--stall-timeout-s < --call-timeout-s`,违反退出码 2 + 合规取值 recipe(stderr);未传 budget 时默认组合放行 + 一次性 stderr 提示;`--help` 三/四级不变式文案同步更新
- [x] 3.2 熔断重锚:删除波次边界锚,改为每新派发 K=`--stall-waves × --wave` 个单元全量重列磁盘终态计数;连续 `--stall-waves` 次零增长且队列非空 → 停止派发、退出码 2、`stalled:true` + `stalled_pending[]`(披露 shape 不变)、stderr 诊断 recipe(提及失活杀不增磁盘计数的语义)

## 4. 回归测试(tests/test_fanout_runner.py + test_fanout_stale.py)

- [x] 4.1 补位循环用例:卡死单元(monkeypatch 时钟/读线程)不阻断其余单元终态与补位;`done` 持续增长;补位前 marker 懒跳过(预置 `.done` 后该单元 NEVER spawn)
- [x] 4.2 失活/树杀用例:静默超阈单元被 `_kill_tree`(monkeypatch 断言调用且 pid 正确)而其余不受影响;`stall_killed[]` 正确;run.log 落盘(含截断)且 stderr 附路径;call-timeout 路径同样走 `_kill_tree`
- [x] 4.3 不变式用例:budget 无显式 call-timeout → 退出码 2 + recipe、零 spawn;`stall ≥ call` → 退出码 2;合规组合通过;无 budget 默认组合放行
- [x] 4.4 熔断重锚用例:同一单元反复失活(无 marker)→ 双观察点各测——(a) 每派发 K 个单元的窗口路径、(b) 队列只剩坏死单元的尾巴路径(队列耗尽重列两次零增长 → stalled 退出 2 + `stalled_pending[]`);失活后重派成功 → 窗口重置不触发;partial 早退路径不受影响
- [x] 4.5 既有用例迁移:波次屏障假设的断言(全波 join 次序、wave= 波索引)改为补位语义;`test_fanout_stale.py` children[] 刷新时点用例对齐补位派发(每 spawn 登记、每终态移除)

## 5. opencode fanout agent permission 钉扎(D6)

- [x] 5.1 五个克隆 `releases/opencode/agent/{init-scout,init-induct,init-synthesis,init-rulewriter,sdr-review}-fanout.md` frontmatter `permission:` 增 `external_directory: deny` + `doom_loop: deny`(既有钉扎行不动)
- [ ] 5.2 claude 侧核查:`releases/claude-code/agents/` 对应 fanout 定义与 `--agents` inline JSON 无需变更(`-p` headless 白名单外自动拒绝);design.md D6 结论落到提交说明

## 6. 调用面与文档同步

- [x] 6.1 fragments 调用行:`core/prompts/fragments/init-stage/{scout,t1,t3}.md` 与 sdr 派发段(`core/prompts/fragments/fanout/sdr-task.md` 不动,动两壳 `releases/{claude-code,opencode}/command·commands/mgh-sdr.md` 派发段)的 `fanout_runner.py` 调用示例增 `--stall-timeout-s`、超时不变式注释改四级(含「传 budget MUST 显式 call-timeout」)
- [x] 6.2 `core/scripts/discipline_core.py` 各 fan-out 步 `path_recipes`:软时限重派纪律文案同步四级不变式与失活重派语义
- [x] 6.3 man pages:`docs/man/mgh-init.md`、`docs/man/mgh-sdr.md` dispatcher 段增新 flag/不变式/`stall_killed`/run.log 诊断路径(R3 人类面:现象→原因→改法,简练索引化)
- [x] 6.4 `core/contracts/hooks/runtime-enforcement.md` 无涉不修改;`docs/glossary.md` 补「失活检测/槽位补位」条目(若缺)

## 7. 全量校验与收尾

- [x] 7.1 `py tests/test_fanout_runner.py`、`py tests/test_fanout_stale.py` 全绿;五 tier(`--tier scout/t1/t2/t3/sdr`)`--pending-file` 冒烟 + `--dry-run` 全流程通过
- [x] 7.2 `py tools/check_contracts.py`(新 flag 经 `--help` 断言)、`py tools/check_distributed_purity.py`、`py tools/measure_prompts.py`(fragments 增量在预算内)无新违例
- [x] 7.3 install 冒烟:`install.sh --claude .` + `--opencode .` 镜像后自检无 warn(fanout agent 克隆 frontmatter 变更随镜像落地)
- [ ] 7.4 CHANGELOG.md / VERSION bump(R5.8);大仓 T1 实跑验收:resume 自当前磁盘状态推进至 `partial:false`,期间至少经历一次失活树杀 + 重派成功,run.log 可读、宿主 TUI 心跳可判读
