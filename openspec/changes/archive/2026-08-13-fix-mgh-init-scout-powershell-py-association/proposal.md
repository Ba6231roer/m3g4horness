## Why

On Windows + cmd + opencode, the opencode shell tool executes every `Bash` command through PowerShell
(`tool/shell.ts`: win32 → `powershell -NoProfile -NonInteractive -Command …`). During `/mgh-init` scout fan-out
the scout-reader subagent ran `& "…\.opencode\mgh-core\scripts\chunk_sources.py" --out "<slice_dir>" "<src.java>"`
— i.e. it **degraded the canonical `py <abs>` recipe into a PowerShell call-operator invocation of a bare `.py`
path**. On that machine `.py` was associated with Notepad, so PowerShell resolved the file association: it opened
the `.py` source in Notepad and surfaced a "create file?" dialog for the trailing args. The Notepad GUI process
blocked → the shell tool never returned → the subagent never acked → the parent `task.wait` hung → **the whole
run deadlocked**. The current hook (`block_adhoc_scripts`) blocks `Write` of script extensions, `py -c`
introspection, and out-of-tree writes, but has **no rule for executing a script via file-association** — so this
exact command passed the guard unblocked.

## What Changes

- **Add a hook rule** (defense-in-depth, symmetric to the existing "Runtime script writes blocked" and
  "Bash command temp-directory I/O detection" rules): when active, the guard SHALL block any `Bash` command that
  **executes a script-extension file (`{.py,.ps1,…}`) via file association** — i.e. as the command body / first
  operand without an explicit interpreter launcher prefix (`py`/`python`/`python3`/`bash`/`sh`/`pwsh -File`).
  Canonical forms `py <abs script>` / `python <abs script>` pass. A hit fails-loud (exit 2) + stderr recipe
  pointing at the explicit-launcher form.
- **Tighten the scout stage prompt recipe** (`init-scout.md` Sanctioned tools): upgrade the prose recipe to an
  exact verbatim command template and add a minimal `NEVER` counter-example for the file-association form
  (`NEVER & "<abs>.py"` on Windows → Notepad/association dialog deadlock).
- **Add a `chunk_sources.py` input self-check** (defense-in-depth, R5.9): fail-loud (exit 2) with a recipe when
  `--out` resolves to an existing directory (the subagent passed the bare slice **dir**, not
  `<slice_dir>/<safe-stem>.slice.json`).
- **Disclosure** (R3): note the Windows `.py`-association hazard + `py <abs>` remedy in the relevant boundary
  disclosure surface.

No runtime dependencies introduced (R2); the guard stays zero-dep stdlib Python and byte-identical across the
claude `PreToolUse` and opencode `.ts` shim paths.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `runtime-hook-enforcement`: add a new Requirement — Bash file-association script execution is blocked when
  active (the `.py`/`.ps1`/etc. invoked via call-operator / bare path without an explicit interpreter launcher
  prefix). This is the mechanical closure for the failure shape that hung the scout run; it sits alongside the
  existing Bash temp-I/O detection rule as a peer defense-in-depth Bash-command rule.

## Impact

- **Code**: `releases/opencode/hooks/block_adhoc_scripts.py` + `releases/claude-code/hooks/block_adhoc_scripts.py`
  (the dual byte-identical guard) — new Bash-command scan branch; opencode `.ts` shim unchanged (it already
  normalizes the command string before feeding the guard). `core/scripts/chunk_sources.py` — `--out` dir check
  in `main()`.
- **Prompts**: `core/prompts/stages/init-scout.md` Sanctioned-tools recipe; mirror to the claude/opencode
  installed prompt set at install time.
- **Docs / disclosure**: boundary disclosure note (Windows `.py` association → `py <abs>`).
- **Tests**: `tests/test_block_adhoc_scripts*.py` — new cases for the file-association block (positive: `& ".py"`,
  bare `".py"`; negative: `py …`, `python …`, `bash …`); `tests/` — `chunk_sources.py --out <dir>` exits 2.
- **Parity**: claude ↔ opencode guard parity test (`tests/test_opencode_hook_parity.py`) extended to cover the new
  rule. Bump version (R5.8).
