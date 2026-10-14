## 1. 红测先行(全部先红)

- [x] 1.1 `tests/test_mgh_sdr_launch.py` 新增 `TestHostErrorEvidence` 组:提取纯函数直测——窗内 ERROR 行捕获、窗外行排除(窗前/窗后各一)、非 ERROR 级排除、无时间戳/不可解析时间戳行跳过、`Z` 尾缀与 naive 时间戳按 UTC 释义、正文逐字保真(含中文/多字节行)、头注两行(source + window)、零捕获仅头注、全局日志缺失返回缺席态(不建文件)
- [x] 1.2 同组集成测(假宿主 `_FakeHostMixin` + monkeypatch 全局日志路径函数):opencode 宿主成功分支同治落盘 + stderr 计数行;假宿主非零退出分支的失败信封与 `FAILED BRANCHES` 汇总携带 `<run-dir>/host_error.log` 指针;零捕获时失败原因附 recipe 句(指认全局日志路径);claude 宿主零提取、无 `host_error.log`;全局日志缺失时退出码语义不变(exit 0 分支仍 ok)且 stderr 出现假定路径 note
- [x] 1.3 跑 `python tests/test_mgh_sdr_launch.py` 确认新测全红(函数/接线未实现),既有测全绿

## 2. launcher 实现(单文件)

- [x] 2.1 `core/scripts/mgh_sdr_launch.py` 新增单点函数 `_opencode_global_log_path()`(`Path.home()/.local/share/opencode/log/opencode.log`,docstring 注明实测形态依据与「未来改路由以 fail-soft note 自暴露」)与纯函数 `_extract_host_errors(log_path, window_start_utc, window_end_utc, out_path) -> int|None`(逐行 `timestamp=`/`level=` regex-over-string 解析、`fromisoformat` 归一 `Z`、窗 `[start, end)` 过滤、逐字正文 + 两行头注写 `host_error.log`、零捕获仅头注、全局日志缺失/不可读返回 None;fail-soft:任何 OSError/ValueError 不上抛)
- [x] 2.2 `_spawn_host` 记 UTC spawn 起点(返回值携带或经可变载体传出,不改其既有返回契约);`_run_one` 真跑路径在宿主退出后接提取:opencode 宿主才提取(claude 跳过),stderr 披露一行计数与路径;`--dry-run` 路径零 spawn 零提取
- [x] 2.3 失败原因拼装接线(D5):有正文 → outcome 追加 `(host error evidence: <绝对路径>)`;仅头注 → 追加 recipe 句(指认全局日志绝对路径);缺席不追加;`FAILED BRANCHES` 汇总复用同一 outcome 零额外拼装;退出码与分支判定一字不动
- [x] 2.4 文档对齐:launcher 头注 BRANCH PRE-CHECK 段后与 `_spawn_host` docstring 的「provider 形失败在 launcher stderr 可定位」失实陈述改述为真实机制(flags = 父进程尽力;扇出子会话错误 = 时间窗提取;诚实边界:同机并发会话窗内行可能混入);`--print-logs` flags 本身保留不删

## 3. 转绿 + 定向回归

- [x] 3.1 `python tests/test_mgh_sdr_launch.py` 全绿(新组转绿 + 既有组不动,含 `test_opencode_carries_log_flags_claude_does_not` 仍绿)
- [x] 3.2 定向回归:`python tests/test_zero_deps.py` + `python tests/test_no_compile_warnings.py`;lint 四件套:`python tools/check_contracts.py`、`python tools/check_distributed_purity.py`、`python tools/check_distributed_prompt_budget.py`、`python tools/check_plain_language.py`(plain_language 既有 exit 2 噪音为准,不新增该 change 相关条目)

## 4. 收尾

- [x] 4.1 `openspec validate fix-mgh-sdr-host-error-capture --strict` 过
- [x] 4.2 VERSION bump + CHANGELOG 条目(单条,含 F1 定位与修法一句话)
- [x] 4.3 实机冒烟(可选,真 provider 错误形态难离线复现):假全局日志 + 真 launcher 单分支干跑,核对 `host_error.log` 三态与 stderr 指针;真机验收(扇出子会话真实断连形态)归下次真仓复测轮
