## 1. Orchestrator discipline fragment — temp-file prohibition

- [x] 1.1 `core/prompts/fragments/orchestrator-discipline.md`:在第 2 条硬边界后增「编排器自身 stdout 消费纪律」——显式 `NEVER` 向系统临时目录(`$env:TEMP`/`%TEMP%`/`/tmp`/`TMPDIR`)写中间文件 + 回读;增 positive recipe「取确定性脚本 JSON 输出:经 Bash 跑、从工具返回值取 stdout(最后一行是 JSON)、在推理里解析 `pending[]`」
- [x] 1.2 更新 fragment 分发纯净性:确认新增文本不含 R5.x/FDn/Dn/dev-meta 措辞

## 2. Hook guard — Bash temp-dir I/O detection (defense-in-depth)

- [x] 2.1 `releases/claude-code/hooks/block_adhoc_scripts.py`:增 `_detect_temp_io(command: str) -> str|None` 函数——regex 匹配已知临时目录模式(`$env:TEMP`/`$env:TMP`/`%TEMP%`/`%TMP%`/`/tmp`/`$TMPDIR`)后接 `>`/`>>`(写重定向)+ 同一 command 字符串内该文件被 `Get-Content`/`cat`/`type`/`gc` 回读;命中返回文件名,未命中返回 None
- [x] 2.2 在主流程中调用 `_detect_temp_io`:仅当运行域激活(`_is_active()` True)时扫描;命中 → exit 2 + stderr recipe 指向 orchestrator-discipline "stdout 直消费"
- [x] 2.3 opencode 副本 byte-identical 同步:复制到 `releases/opencode/hooks/block_adhoc_scripts.py`

## 3. Command shells — temp-file 禁令提醒

- [x] 3.1 `releases/claude-code/commands/mgh-init.md`:在 Orchestrator discipline 段或 Deterministic invocation 段增一行提醒——"Bash tool result 已含 stdout;NEVER 重定向到 `$env:TEMP`/`%TEMP%`/`/tmp` 再回读"
- [x] 3.2 `releases/opencode/command/mgh-init.md`:同 3.1(双端对等)
- [x] 3.3 (可选)检查 sast/sra/srr 壳是否有同形风险,若有则同步补禁令

## 4. Tests

- [x] 4.1 `tests/test_block_adhoc_scripts.py`:增 temp-dir I/O 检测用例——`$env:TEMP` 写+回读 → exit 2;`/tmp` 写+回读 → exit 2;受信子树重定向 → 放行;单独写 temp(无回读)→ 放行;非运行域 → 放行
- [x] 4.2 `tests/test_opencode_hook_parity.py`:确认双端 guard byte-identical 一致(自动,若有 parity 测试则补断言)
- [x] 4.3 回归:运行 `py tests/test_block_adhoc_scripts.py` + `py tests/test_deterministic.py` 全绿

## 5. Lint + version bump

- [x] 5.1 `tools/check_contracts.py`:确认 contracts lint 通过(无新增 flag)
- [x] 5.2 `tools/check_distributed_purity.py`:确认 fragment 纯净性 lint 通过
- [x] 5.3 bump 受影响 `.md`/`.py` 版本号:orchestrator-discipline.md、block_adhoc_scripts.py(双端)、mgh-init.md(双端)
- [x] 5.4 `install.sh` 自检:确认自检全绿或 fail-soft warn(承 R5.8)
