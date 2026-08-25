# Tasks: improve-mgh-init-fanout-longrun-timeout-visibility

> 归档序依赖:本 change 的 apply/archive MUST 排在 `add-mgh-init-scout-fanout-runner` 归档之后
> (design D4;`fanout-dispatch` baseline 由该 change 建立)。

## 1. dispatcher 超时标定(方案 A,`core/scripts/fanout_runner.py`)

- [x] 1.1 `--call-timeout-s` 默认值 1800→7200(`DEFAULT_CALL_TIMEOUT_S`),`--help` 与模块
  docstring 文案同步:注明三级超时不变式(`call-timeout-s × 收敛余量 < time-budget-ms < 宿主
  per-call timeout`,每级 ≥20% 余量)+ 内网慢接口标定依据(~4× 余量 + 宁慢勿杀:被杀单批无
  marker 留 pending,重派浪费一整跑)
- [x] 1.2 `--time-budget-ms` 的 `--help` 文案补推荐值(宿主 per-call timeout × 0.8,如宿主
  900s → 720000;claude 侧宿主上限 600s → 480000)

## 2. 进度 sidecar(方案 B,`core/scripts/fanout_runner.py`)

- [x] 2.1 sidecar 写盘函数:目标 `<init-dir>/fanout_progress.json`(init-dir = scout_plan.json
  所在目录),字段 `{ts, host, total, done, failed, pending, wave, waves_run, wave_done_avg_s,
  eta_batches, state}`,state ∈ {running, exited-partial, exited-clean};stdlib
  tempfile 同目录 + `os.replace` 原子替换;`ts` = `datetime.now().isoformat()`(带本地
  offset);写失败仅 stderr warn 不影响主流程
- [x] 2.2 写点接线:每波 `pool` 收敛 + `_snapshot()` 重派生后写 `state:"running"`(计数取
  snapshot 派生值,与 stdout 摘要同源);软时限 break 后写 `exited-partial`、全部跑完写
  `exited-clean`(终态计数与 stdout 摘要一致)
- [x] 2.3 `--help`/docstring 补 sidecar 说明:人面运行态披露件(第二终端 `Get-Content -Wait`
  查看)、agent NEVER 读、非契约产物(resume/init_manifest 不读不校验)

## 3. 接线面(方案 A 引导 + 方案 C 文档化)

- [x] 3.1 `core/prompts/fragments/init-stage/scout.md` dispatcher 调用行:补 `--time-budget-ms`
  显式示例(注明按宿主 per-call timeout × 0.8 取值)+ 「MUST < 宿主 per-call timeout(留 ≥20%
  收敛余量)」提示;段尾补手动直跑一句(大仓长跑可宿主外直跑同一命令,stderr 逐波直读,跑完
  回会话 `--resume` 接续);token 复测(scout fragment ≤ 上限)
- [x] 3.2 `core/scripts/discipline_core.py` `scout-fanout-dispatcher` path_recipe:补「重派传
  per-call `timeout` > `--time-budget-ms`(软时限先于宿主硬杀)」半句
- [x] 3.3 `docs/man/mgh-init.md` 风险与边界段:补「大仓长跑可见性」说明——第二终端看
  `.mgh-init/fanout_progress.json` 进度、内网慢接口下总时长以小时计是正常、可自己开终端直跑
  dispatcher 命令(跑完回会话 `/mgh-init --resume` 接续);术语首现按 R3 给一句解释

## 4. 回归与冒烟

- [x] 4.1 `tests/test_fanout_runner.py` 增:① `--call-timeout-s` 默认值 = 7200 断言(`--help`
  文案含不变式);② sidecar 单测(`--pending-file` 测试钩子跑完后 sidecar 存在、state 终态、
  计数与 stdout 摘要一致;原子写不破坏既有 JSON);③ 超时关系文档断言(fragment 调用行示例
  的 `--time-budget-ms` < 对应宿主 timeout 示例值)
- [x] 4.2 既有回归全绿(test_fanout_runner + test_deterministic + test_init_ack_contract +
  test_list_steps + test_resume_state + test_list_scout_batches + test_init_runtime +
  test_zero_deps + test_distributed_md_purity)+ `tools/check_contracts.py`(flag 面)+
  双壳 token lint + 分发纯净性 lint
- [ ] 4.3 真机复跑事故场景(同一大仓 resume,900 批级):断言软时限先于宿主硬杀触发
  (dispatcher 退出码 0 + `partial:true`,无 `<shell_metadata>…timeout</shell_metadata>`)、
  sidecar 进度推进可见(第二终端)、重派轮轮干净早退(杀-重派循环消失);CHANGELOG/VERSION
  bump(改动的一切 `.md`/脚本)
