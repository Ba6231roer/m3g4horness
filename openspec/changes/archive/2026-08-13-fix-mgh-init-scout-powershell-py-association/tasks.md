## 1. Guard rule — Bash file-association script execution

- [x] 1.1 In `releases/opencode/hooks/block_adhoc_scripts.py` add a launcher-prefix allowlist constant
  (`py`, `python`, `python3`, `bash`, `sh`, `pwsh -File`, `pwsh -Command`, `powershell -File`, `cmd /c`) and a
  script-extension-as-command-body detector (call-operator `& <ext-path>` OR first-command-token `<ext-path>`,
  quote-tolerant; operand-vs-arg distinction so `--flag <x>.py` args do NOT match).
- [x] 1.2 Implement `_is_file_assoc_script_exec(cmd)` returning True only when a script-extension path is the
  command body AND no launcher-prefix token precedes it in that simple command.
- [x] 1.3 Wire it into `main()`'s `Bash` branch after the aggregate-read check (`_is_whole_aggregate_read`),
  fail-loud exit 2 + stderr recipe pointing at `py "<abs script>"` (host-neutral wording; mention the win32
  PowerShell file-association → editor/dialog deadlock as the reason).
- [x] 1.4 Mirror the identical change in `releases/claude-code/hooks/block_adhoc_scripts.py` (byte-identical
  decision source; the `.ts` shim is unchanged).

## 2. Leaf self-check — chunk_sources.py --out dir guard

- [x] 2.1 In `core/scripts/chunk_sources.py::main()`, after argparse: if `Path(args.out).is_dir()` → exit 2 +
  stderr recipe naming the canonical form `--out <slice_dir>/<safe-stem>.slice.json` (a file path, not a dir).
  Do NOT re-validate `--in` (argparse `required=True` already does) or `--line` (skeleton mode is legit).

## 3. Stage prompt recipe tightening (model-readable)

- [x] 3.1 In `core/prompts/stages/init-scout.md` Sanctioned-tools section: replace the prose recipe with the
  exact verbatim template `py <绝对 chunk_sources> --in <big_file> --big-file-bytes <N> --line <L> --out
  <slice_dir>/<safe-stem>.slice.json` and add the minimal `NEVER` counter-examples: `NEVER & "<abs>.py"`
  (Windows PowerShell file association → Notepad/dialog deadlock) and `NEVER` pass `--out` a directory.
- [x] 3.2 Audit the other stage prompts that invoke script extensions via shell (any scout/resolve/other
  Sanctioned-tools recipes) and align wording where the same Windows degradation is reachable (minimal edit).

## 4. Tests

- [x] 4.1 Extend the guard test suite (the `tests/` file covering `block_adhoc_scripts`) with positive cases:
  `& "<…>.py" …`, bare `"<…>.py" …`, `& "<…>.ps1"`, `./x.sh` → each exit 2; and negative cases: `py "<…>.py" …`,
  `python "<…>.py" …`, `bash "<…>.sh" …`, `pwsh -File "<…>.ps1"`, `py a.py --in "<x>.py"` → each pass (exit 0).
- [x] 4.2 Add a `chunk_sources.py --out <existing dir>` test asserting exit 2 + recipe; assert `--out <file>`
  still writes normally.
- [x] 4.3 Extend `tests/test_opencode_hook_parity.py` with the new rule's positive/negative matrix so the
  claude↔opencode guard stays byte-parity for the file-association rule.
- [x] 4.4 Add the new Bash-command scan to the guard's documented behavior block in the module docstring
  (failure shape (e), peer of (a)–(d)).

## 5. Disclosure + version + purity

- [x] 5.1 Add the Windows `.py`-association hazard + `py <abs>` remedy to the relevant boundary disclosure
  surface (the command shell's "Always disclose" or a docs note), per R3.
- [x] 5.2 Bump version on touched `.md`/scripts (R5.8); run `tools/check_contracts.py` (R5.1) and
  `tools/check_distributed_purity.py` (R5.10) and `tools/measure_prompts.py` to confirm no shell-budget drift
  from the recipe edit.
- [x] 5.3 Run `py tests/test_deterministic.py` (and the guard parity test) — green; confirm zero-dependency AST
  scan still clean (R2).
