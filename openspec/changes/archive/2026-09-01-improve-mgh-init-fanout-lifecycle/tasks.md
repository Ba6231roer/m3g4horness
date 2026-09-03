# improve-mgh-init-fanout-lifecycle — Tasks

## 1. fanout_runner liveness + --kill-stale

- [x] 1.1 `core/scripts/fanout_runner.py`:liveness 登记——`_write_liveness(init_dir, tier, host)` 原子写 `<init-dir>/fanout_runner.<tier>.pid`(body `{pid, started_ts, tier, host, cmdline, children[]}`,tempfile+`os.replace` 同 `_write_sidecar` 型);每波 spawn 后原子更新 `children[]`({pid, unit, tier});main 派发模式 try/finally 删除;`--help`/docstring 更新(liveness 语义 + 非 lock 声明)
- [x] 1.2 spawn 改 `subprocess.Popen`(替代 `subprocess.run`,取得子 PID 以记入 `children[]`;保留超时/捕获语义——`Popen.communicate(input, timeout=)` 等价替换);波结束清空 children
- [x] 1.3 `--kill-stale` flag + `_kill_stale(args)`:两形态——① runner PID 活 ∧ cmdline 含 `fanout_runner.py` → 杀树(kind=runner);② runner PID 死/不匹配 ∧ `children[]` PID 活 ∧ cmdline 为宿主 CLI → 逐个杀树(kind=child);`--dry-run` 预览(列出将杀 PID + kind,不杀);真杀须 `--dry-run` 先行否则退出码 2 + recipe(承 `--purge-audit` 守卫同型);stdout `{"kill_stale": {"killed":[{pid,tier,kind}], "removed":[...], "none":bool}}`;无 stale 幂等退出码 0
- [x] 1.4 PID 探测 + 双条件误杀防护:`_pid_alive(pid)`(Windows `tasklist /fi` 映像名,POSIX `/proc/<pid>`)+ `_pid_cmdline_matches(pid)`;runner 匹配 `fanout_runner.py` 子串、child 匹配宿主 CLI;不匹配 → 仅删残留文件不杀(探测双层失败降级 = 仅删文件 + stderr 警告)
- [x] 1.5 杀树平台分叉:Windows `taskkill /pid <pid> /T /F`(形态②对 children 逐个 /T);POSIX `os.killpg`(若 `start_new_session` 影响既有 spawn 行为则回退仅杀父 + docstring 披露);`--kill-stale` 与 tier 无关(全 tier 同构)
- [x] 1.6 stderr 心跳:单元 spawn/终结(ok|failed|timeout|crash)/波结束三节点打 `[fanout_runner <tier>] +HH:MM:SS wave=<k> unit=<id> <event> done=<d>/<total>`;`time.monotonic()` 相对 t0;stdout JSON 契约零变化

## 2. resume_state stale_fanout + 口径文档

- [x] 2.1 `core/scripts/resume_state.py`:`_stale_fanout(init_dir)` 扫 `fanout_runner.*.pid` → stdout 增 `stale_fanout[]`(`{tier, pid_file, pid_alive, note}`,任一 alive → note 附 `--kill-stale --dry-run` recipe;无文件 → `[]` 字段恒存在)
- [x] 2.2 `--check` advisory 披露:alive 残留 → `notes[]` 追加 stale-fanout 条目(非 violation,不 gate)
- [x] 2.3 计数口径文档:docstring/--help 注明三口径(resume_state 纯 `*.json.done` glob 计数 / list_clusters 记录体 `unit` 字段去重 shard 感知 / 目录条目 = done+failed+记录体)+ 等价条件(无 shard、无 orphan 时相等);472≠491 非丢数据

## 3. 编排器接线 + 契约登记

- [x] 3.1 `releases/{claude-code/commands,opencode/command}/mgh-init.md`:tier fanout 派发 recipe 前置 `--kill-stale --dry-run`(审)→ 真杀(仅当 killed 非空);resume recipe 首步读 `resume_state` stdout `stale_fanout` 壳行
- [x] 3.2 `tools/check_contracts.py`:`FANOUT_RUNNER_REQUIRED_FLAGS` 增 `--kill-stale`;`RESUME_REQUIRED_FLAGS` 无变化(无新 flag)——确认 lint 过
- [x] 3.3 `docs/opencode-context-mechanics.md`:补记 Bash stderr→TUI 实时尾部机制(`shell.ts:484-531` merge 流 + `session/index.tsx:2054-2110` Shell 组件渲染 + 30K 尾窗),标注核实版本 1.18.18

## 4. 测试 + 版本

- [x] 4.1 `tests/test_fanout_stale.py`:liveness 写/删(正常退出删、硬杀残留可检出、children[] 波次更新)、`--kill-stale` 两形态(runner 活杀树 / runner 死 children 活逐个杀)、幂等(两次调用第二波 `killed:[]`)、PID 复用误杀防护(cmdline 不匹配不杀)、dry-run 守卫(无 dry-run 真杀 → 退出码 2)、心跳行格式断言(stderr 逐行 parse)、stdout 契约不变(stdout 仅末行 JSON)
- [x] 4.2 `tests/test_resume_state.py` 增补:`stale_fanout` 字段恒存在/空形态、alive 残留 → recipe + notes advisory、`--check` 非 gate
- [x] 4.3 全量回归:`py tests/test_deterministic.py` + 相关 tests + `py tools/check_contracts.py`;bump `VERSION`
