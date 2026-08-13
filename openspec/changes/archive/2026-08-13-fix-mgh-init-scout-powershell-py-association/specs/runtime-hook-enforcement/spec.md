## ADDED Requirements

### Requirement: Bash file-association script execution is blocked

When active, the guard SHALL block any `Bash` command that **executes a script-extension file** (any extension
in the script set `{.py, .ps1, .sh, .bash, .zsh, .bat, .cmd, .ts, .js, .mjs, .cjs}`) **via the shell's file
association** — i.e. the script path appears as the **command body** (either as the operand of a shell
call-operator such as PowerShell `&`, or as the first command token of the command, optionally quote-wrapped)
**without an explicit interpreter-launcher prefix**. A hit SHALL fail-loud (exit 2) + stderr recipe pointing at
the explicit-launcher form.

Commands SHALL PASS when the script path is reached via an explicit interpreter launcher token — `py`, `python`,
`python3`, `bash`, `sh`, `pwsh -File`, `pwsh -Command`, `powershell -File`, `cmd /c` — preceding the script path
(the canonical `py <abs script>` recipe passes). A script path that appears only as a `--flag <path>`
**argument** to a legitimately-launched command (not as the command body) SHALL NOT be blocked.

This is a **defense-in-depth** rule, a peer of "Bash command temp-directory I/O detection". The primary fix is
the stage-prompt recipe; the regex covers the observed failure shape and SHALL NOT claim exhaustive coverage of
all possible file-association invocation forms. Its host-neutral placement (the guard normalizes the command
string identically for claude and opencode) closes the Windows failure shape where opencode runs every `Bash`
command under PowerShell (`tool/shell.ts`: win32 → `powershell -Command …`) and a degraded
`& "<abs>.py"` resolves the `.py` file association (e.g. Notepad) — opening a GUI editor / "create file?" dialog
that blocks the shell tool, hangs the subagent ack, and deadlocks the parent `task.wait`.

#### Scenario: PowerShell call-operator on a .py is blocked

- **WHEN** `mgh-init` 运行域内(激活)编排器或 subagent 执行 `Bash` 命令
  `& "D:\proj\.opencode\mgh-core\scripts\chunk_sources.py" --out "D:\proj\.mgh-init\slices\scout\scout-003" "d:\proj\…\X.java"`
- **THEN** 守卫以退出码 2 拦截;recipe 指向显式 launcher 形态 `py "<abs script>"`(call-operator `&` 作用在 `.py` 上 =
  文件关联,在 win32 PowerShell 下解析为 Notepad/编辑器 → 弹窗死锁)

#### Scenario: Bare quoted script path as command body is blocked

- **WHEN** `mgh-init` 运行域内执行 `Bash` 命令 `"D:\proj\.opencode\mgh-core\scripts\chunk_sources.py" --in x`
  (无 launcher 前缀,引号包裹的 `.py` 路径作为命令体)
- **THEN** 守卫以退出码 2 拦截;recipe 指向 `py "<abs script>"`

#### Scenario: Canonical py-launcher form passes

- **WHEN** `mgh-init` 运行域内执行 `Bash` 命令
  `py "D:\proj\.opencode\mgh-core\scripts\chunk_sources.py" --in x --out y.json`
- **THEN** 守卫放行(显式 `py` launcher → Python 解释器,无文件关联)

#### Scenario: Other explicit launchers pass

- **WHEN** `mgh-init` 运行域内执行 `python "<abs>.py" …` 或 `bash "<abs>.sh" …` 或 `pwsh -File "<abs>.ps1"`
- **THEN** 守卫放行(显式解释器前缀)

#### Scenario: Script path as a flag argument is NOT blocked

- **WHEN** `mgh-init` 运行域内执行 `Bash` 命令 `py "<abs>discover.py" --in "<other>.py"`(`.py` 路径仅作 `--in` 参数)
- **THEN** 守卫放行(`.py` 不在命令体位置;operand-vs-arg 区分避免误伤)

#### Scenario: Inactive session passes all Bash commands

- **WHEN** 既无 env 也无哨兵的非运行域会话执行 `& "…\.py" …`
- **THEN** 守卫退出码 0 放行,不做 Bash 命令扫描(零日常噪声;install/CI/开发态不受影响)
