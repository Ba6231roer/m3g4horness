## Context

`block_adhoc_scripts.py` is the dual (claude `PreToolUse` + opencode `.ts` shim) byte-identical guard. Its
`main()` Bash branch currently runs four scans, in order: (1) `_is_introspect_py_c` (`py -c` + introspection
tokens), (2) `_detect_temp_io` (temp-dir write+read-back), (3) `_is_whole_aggregate_read` (shell-read of a
multi-unit aggregate). The Write/Edit branch handles script-extension writes + write confinement. None of these
cover the failure shape observed on Windows: a subagent executing a `.py` (or any script-extension) file **via
the shell's file association** — PowerShell `& "<abs>.py"` — which on a machine where `.py` resolves to Notepad
opens the source in Notepad and deadlocks the run.

The opencode shell tool runs every `Bash` command under PowerShell on win32
(`tool/shell.ts`: `powershell -NoProfile -NonInteractive -Command …`). The canonical recipe in every mgh-*
command shell and stage prompt is `py <abs script>` (explicit `py` launcher → Python interpreter, no file
association). The hazard is purely the **degraded** form. The guard already normalizes the command string the
same way for both claude and opencode (the `.ts` shim feeds `tool_input.command` to the same Python guard), so a
single new predicate covers both hosts and all five domains.

This is a defense-in-depth Bash-command rule, a direct peer of the existing temp-I/O and aggregate-read rules —
same placement, same fail-loud (exit 2) + stderr recipe contract, same "model-readable recipe is primary; hook
is the mechanical closure" framing already used for temp-I/O.

## Goals / Non-Goals

**Goals:**
- Mechanically block script-extension files executed via file association (no explicit interpreter launcher
  prefix) inside any active mgh run-domain, before the command reaches the shell — preventing the
  Notepad/dialog deadlock deterministically, host-neutral.
- Keep the guard zero-dep stdlib (R2) and byte-identical across claude/opencode (R5.7 parity).
- Tighten the scout stage prompt recipe so the weak-model degradation path is less likely in the first place.
- Add a single-script self-check in `chunk_sources.py` so an `--out <dir>` misuse fails loud at the leaf rather
  than silently emitting into a mis-shaped path.

**Non-Goals:**
- Not changing the opencode shell tool's PowerShell-on-win32 behavior (out of scope; it is the host's contract).
- Not building a general Bash-command parser; the detection is a bounded regex over observed failure shapes
  (same conservatism as the temp-I/O rule — it SHALL NOT claim exhaustive coverage).
- Not validating the full `chunk_sources.py` flag contract in the hook (R5.1 contract lint governs the
  command-shell↔script flag surface; the leaf self-check is the narrow `--out <dir>` guard only).
- Not touching scout orchestration, fan-out mechanics, or resume state — the scout tier ran correctly; only the
  leaf invocation form was wrong.

## Decisions

### D1 — New guard rule: block Bash file-association script execution
Add a predicate `_is_file_assoc_script_exec(cmd)` invoked in the `Bash` branch of `main()` (after the
aggregate-read check). It returns True when the command **executes a script-extension path as the command body
without an explicit interpreter-launcher prefix**.

- **Launcher prefixes that PASS** (explicit interpreter → no file association): `py`, `python`, `python3`,
  `bash`, `sh`, `pwsh -File`, `pwsh -Command`, `powershell -File`, `cmd /c`. The canonical `py <abs script>`
  recipe passes.
- **Forms that BLOCK**: PowerShell call-operator `& "<…>.py"` / `& "…\.ps1"`; a bare quoted path
  `"…\.opencode\…\chunk_sources.py"` / `"./x.sh"` used as the leading command token; an unquoted `./x.py`.
  Concretely the observed shape `& "D:\…\chunk_sources.py" --out …` is blocked.
- **Why not whitelist exact script names**: the sanctioned primitive set differs per domain and the failure
  shape is the *invocation mechanism*, not the script identity. Blocking the mechanism (`& <ext>` / bare
  `<ext>`-path as command body) is host-neutral and covers all five domains + every leaf script, not just
  `chunk_sources.py`.
- **Regex shape (illustrative, not normative — see spec for behavior)**: a script-extension path
  (`[…]\.(py|ps1|sh|bash|zsh|bat|cmd|ts|js|mjs|cjs)`) appearing either (a) immediately after a leading `&` /
  call-operator token, or (b) as the first command token of the command (optionally quote-wrapped), AND not
  preceded (within the same simple command) by a launcher-prefix token. Anchoring on "first command token /
  call-operator operand" avoids false positives on a script path that is merely a `--flag <path>` **argument**
  to a legitimately-launched command (e.g. `py … --in <something>.py` would be unusual, but the operand-vs-arg
  distinction is what keeps `py foo.py` PASSing and `& foo.py` BLOCKing).

**Alternative considered — block ALL bare `.py` token mentions**: rejected; would false-positive on
`--flag <x>.py` args and on documentation/grep-style references. Operates on command-body position, not
substring.

**Alternative considered — fix only `chunk_sources.py` recipe in the prompt**: rejected as sole fix; it leaves
every other leaf script and every other domain exposed to the same Windows degradation, and relies on model
compliance where a hook can close it mechanically (R5.7: "能用 hook 做确定性闭环的,不写进 MD 靠 agent 自觉").

### D2 — Self-check in `chunk_sources.py --out` (defense-in-depth, R5.9)
In `main()`, after argparse: if `args.out` resolves to an **existing directory**, exit 2 with a stderr recipe
naming the canonical form `--out <slice_dir>/<safe-stem>.slice.json` (a file, not a dir). This catches the
observed `--out "<slice_dir>/scout-003"` misuse at the leaf even if the hook somehow did not fire. It does NOT
re-validate `--in`/`--line` (argparse `required=True` already handles `--in`; `--line` absence is a legitimate
skeleton-mode request, not a misuse).

### D3 — Recipe tightening in `init-scout.md` (model-readable, R5.5①⑤)
Upgrade the Sanctioned-tools prose to an exact verbatim template and add the minimal `NEVER` counter-example:
`NEVER & "<abs>.py"` (Windows PowerShell file association → Notepad/dialog deadlock); `NEVER` pass `--out` a
directory. R5.5⑤: the counter-example is given only because the agent could not otherwise guess the
file-association boundary (the deadlock is a host-specific failure the prompt alone can't make observable).

## Risks / Trade-offs

- **[False positive: a legitimately-launched command whose first arg is a script path]** → mitigated by the
  operand-vs-arg distinction (D1): `py foo.py` and `python "…\.py"` pass; only the *command-body* position is
  matched. CI parity test covers the positive/negative matrix.
- **[False negative: novel file-association forms]** → the regex covers observed shapes (`& <ext>`, bare
  `<ext>`-path command body); it SHALL NOT claim exhaustive coverage, same as the temp-I/O rule. The leaf
  self-check (D2) and recipe (D3) are the defense-in-depth backstops.
- **[claude↔opencode parity drift]** → the `.ts` shim is unchanged (already normalizes `command`); the new
  predicate lives in the single Python decision source. `tests/test_opencode_hook_parity.py` extended with the
  new rule's cases.
- **[Over-block during install/dev]** → the guard returns 0 before any Bash scan when inactive (no env, no
  sentinel); install/CI/dev are unaffected (same as every existing rule).
