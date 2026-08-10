## ADDED Requirements

### Requirement: Bash command temp-directory I/O detection (defense-in-depth)

When active, the guard SHALL scan the `command` string of each `Bash` tool invocation for patterns
indicating write-redirection to a known temporary directory followed by a read-back of the same file
within the **same** invocation. A match SHALL fail-loud (exit 2) with a stderr recipe pointing to the
orchestrator-discipline fragment's "stdout 直消费" instruction.

Detection scope:
- **Known temp directory patterns**: `$env:TEMP` / `$env:TMP` / `%TEMP%` / `%TMP%` / `/tmp` / `$TMPDIR`
  (case-insensitive for env-var names on Windows)
- **Write pattern**: one of these temp patterns followed by a write redirection (`>` or `>>`) to a file
- **Read-back pattern**: the same file path read via `Get-Content` / `cat` / `type` / `gc` within the
  same `command` string

This is a **defense-in-depth** rule; the primary fix is in the orchestrator-discipline prompt.
The regex detection covers observed failure shapes and SHALL NOT claim exhaustive coverage of all
possible temp-directory I/O patterns.

#### Scenario: PowerShell temp-file write-and-read is blocked

- **WHEN** `mgh-init` 运行域内编排器执行 `Bash` 命令 `py .../list_scout_batches.py ... > $env:TEMP/scout_page0.json; Get-Content $env:TEMP/scout_page0.json -Raw | ConvertFrom-Json ...`
- **THEN** 守卫检测到 `$env:TEMP` + `>` 写重定向 + `Get-Content` 回读同文件 → 退出码 2 + stderr recipe 指向 orchestrator-discipline "stdout 直消费,NEVER temp 中介"

#### Scenario: POSIX temp-file write-and-read is blocked

- **WHEN** `mgh-init` 运行域内编排器执行 `Bash` 命令 `py .../list_scout_batches.py ... > /tmp/scout_page0.json; cat /tmp/scout_page0.json | jq ...`
- **THEN** 守卫检测到 `/tmp` + `>` 写重定向 + `cat` 回读 → 退出码 2

#### Scenario: Legitimate in-tree redirect is NOT blocked

- **WHEN** `mgh-init` 运行域内编排器执行 `py .../discover_controls.py ... > <target>/.mgh-init/discover_stdout.log`(重定向到受信子树)
- **THEN** 守卫不拦(temp 检测未命中;路径不在已知临时目录模式内)

#### Scenario: Temp write without read-back is NOT blocked (conservative)

- **WHEN** `mgh-init` 运行域内编排器执行 `py .../some_script.py > /tmp/debug.log`(写入 temp 但无回读)
- **THEN** 守卫不拦(仅限「同调用内写 + 回读」配对模式;单独写 temp 无回读不计为违例,交由上级纪律治理)

#### Scenario: Inactive session passes all Bash commands

- **WHEN** 既无 env 也无哨兵的非运行域会话
- **THEN** 守卫退出码 0 放行,不做 Bash 命令扫描(零日常噪声)
