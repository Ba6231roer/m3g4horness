## ADDED Requirements

### Requirement: Read-side confinement to the MGH_TARGET tree

When active, the guard SHALL block any `Read`/`Glob`/`Grep` tool call whose resolved target path (or,
for `Glob`/`Grep`, the resolved `path` anchor — defaulting to the guard's cwd when `path` is absent)
falls **outside** the resolved `MGH_TARGET` tree, for all five run-domains (`mgh-init`/`mgh-sast`/
`mgh-sra`/`mgh-srr`/`mgh-ut-init`). A hit SHALL fail-loud (exit 2) + stderr recipe pointing the model
at reading only its batch's `input_path`/`targets[]` and anchoring `Glob`/`Grep` at the repo root.
`MGH_TARGET` resolves with the SAME precedence as the write side — **env `MGH_TARGET` >
sentinel.`target` > degrade (pass)** — so when neither pins a target the read-side check SHALL pass
(never use cwd as a hard block target, to avoid over-blocking; the script-extension write block and
`py -c` introspection block still fire). The read-side check SHALL be a peer of the write-side
out-of-tree check (same `Path.resolve().is_relative_to(target)` semantics), NOT a positive-allowlist
check — any file inside the `MGH_TARGET` tree is readable (the goal is "stay in the working project",
not "stay in a sanctioned subtree"). The `Glob`/`Grep` `pattern` field SHALL NOT be parsed for path
traversal (the `path` anchor is the authoritative scope; regex/glob parsing is conservative to avoid
false positives on legitimate patterns).

#### Scenario: Read of a parent-dir file is blocked (submodule layout)
- **WHEN** an `mgh-init` run-domain is active (env `MGH_INIT_ACTIVE=1` OR `<cwd>/.mgh-init/.active`
  sentinel present) with `MGH_TARGET=D:\parent\sonA`, and a reader subagent issues `Read`
  `file_path=D:\parent\sonB\src\Main.java` (a sibling module under the parent dir, outside `sonA`)
- **THEN** the guard resolves `D:\parent\sonB\src\Main.java` outside the `D:\parent\sonA` tree and
  blocks with exit 2 + a stderr recipe pointing at "Read only this batch's input_path / targets[];
  NEVER read the parent dir or sibling modules" — the read does NOT reach the host permission prompt
  (the soft failure that interrupted runs is replaced by a fail-loud recipe)

#### Scenario: Read of an in-tree file passes
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and a reader issues
  `Read` `file_path=D:\parent\sonA\src\auth\PermGuard.java` (inside the target tree)
- **THEN** the guard passes (exit 0); legitimate batch reads are unaffected

#### Scenario: Glob anchored outside the target tree is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and a reader issues
  `Glob` with `path=D:\parent\sonB` (sibling module) and `pattern=**/*.java`
- **THEN** the guard resolves the `path` anchor outside the target tree and blocks with exit 2 + the
  read-side recipe (anchoring `Glob` at a sibling module is the cross-module leak shape)

#### Scenario: Glob/Grep with no path anchor and cwd outside target is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, the reader's cwd is
  `D:\parent` (the parent dir, outside the target tree), and the reader issues `Grep` with no `path`
  (anchor defaults to cwd) and `pattern=TokenInterceptor`
- **THEN** the guard resolves the implicit cwd anchor outside the target tree and blocks with exit 2
  + a recipe pointing at "anchor Glob/Grep with an explicit path at the repo root; cwd is outside the
  target tree" — the cwd-drift leak shape (submodule cwd = parent) is caught

#### Scenario: Glob/Grep anchored at the repo root passes
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and a reader issues
  `Grep` with `path=D:\parent\sonA` (the repo root = the target tree) and `pattern=TokenInterceptor`
- **THEN** the guard passes (exit 0); legitimate sibling-package confirmation reads inside the
  working project are unaffected

#### Scenario: Active domain with no pinned target degrades the read-side check
- **WHEN** the guard is active (env `MGH_*_ACTIVE=1` or sentinel present) but `MGH_TARGET` env is
  unset AND the sentinel carries no `target`, and a reader issues `Read` of any path
- **THEN** the script-extension write block / `py -c` introspection block / temp-I/O / file-association
  blocks still fire (exit 2); the read-side out-of-tree check **degrades to pass** (NEVER use cwd as a
  hard read block target when no target was pinned, consistent with the write side's degrade rule)

#### Scenario: Read-side confinement fires identically under sentinel activation on opencode
- **WHEN** an opencode session has NO `MGH_*_ACTIVE` env (plugin process does not inherit mid-session
  bash-exported env) but the `<cwd>/.mgh-init/.active` sentinel is present carrying
  `target=D:\parent\sonA`, and a reader issues `Read` `file_path=D:\parent\sonB\x.java`
- **THEN** the guard activates via the sentinel, resolves `MGH_TARGET` from `sentinel.target`, and
  blocks the cross-module read with exit 2 + recipe — the disk sentinel closes the opencode env
  inheritance boundary for the read side exactly as it does for the write side

#### Scenario: Inactive session passes all reads
- **WHEN** neither any `MGH_*_ACTIVE` env nor any `<run-root>/.active` sentinel is present (a
  day-to-day non-run-domain session) and the model issues any `Read`/`Glob`/`Grep`
- **THEN** the guard exits 0 silently (zero day-to-day noise; install/CI/dev unaffected)

### Requirement: opencode shim normalizes read-side tools to the guard

The opencode `.ts` shim SHALL feed the guard for `read`/`glob`/`grep` tool events (in addition to
`bash`/`write`/`edit`), normalizing opencode's camelCase args to the Claude `{tool_name, tool_input}`
stdin shape the guard expects: `read` → `{tool_name:"Read", tool_input:{file_path}}`;
`glob` → `{tool_name:"Glob", tool_input:{pattern, path}}`; `grep` →
`{tool_name:"Grep", tool_input:{pattern, path, glob}}`. The shim SHALL remain glue-only — the
read-side out-of-tree decision logic lives ONLY in the Python guard (single decision source, zero
drift). The shim's `HANDLED` set SHALL include `read`/`glob`/`grep` alongside `bash`/`write`/`edit`.

#### Scenario: opencode read event is normalized and decided by the guard
- **WHEN** an opencode session is inside an `mgh-init` run-domain and the model issues a `read` tool
  call with `filePath=D:\parent\sonB\x.java` (outside `target=D:\parent\sonA`)
- **THEN** the shim normalizes it to `{tool_name:"Read", tool_input:{file_path:"D:\\parent\\sonB\\x.java"}}`,
  feeds it to the guard (single decision source) via `new Blob([stdin])`, the guard exits 2, and the
  shim throws to abort the tool call (the model sees the read-side recipe) — the read-side decision
  does not drift between platforms

#### Scenario: shim remains glue-only for the read side
- **WHEN** the shim source is checked in CI
- **THEN** a parity-test source-form assertion requires the shim to normalize `read`/`glob`/`grep`
  AND forbids it from reimplementing the read-side decision logic (e.g. `_read_out_of_tree` /
  `_out_of_tree_file_search` / `is_relative_to` / target resolution MUST NOT appear in the shim —
  single decision source)

### Requirement: Bash file-search command confinement to the MGH_TARGET tree

When active, the guard SHALL scan each `Bash` command for a leading file-search verb — `rg`/
`ripgrep`/`grep`/`egrep`/`fgrep`/`findstr`/`find`/`fd`/`ag`/`ack` (or the same verb as the first
token of a sub-command after `;`/`|`/`&&`/`||`) — and, on a hit, SHALL block when EITHER (a) any
explicit absolute-path token in the command (Windows drive-letter `[A-Za-z]:[\\/]…`, POSIX `/…`,
or UNC `\\…`) resolves outside the `MGH_TARGET` tree, OR (b) the command carries no explicit
absolute path (its search root defaults to cwd) AND the guard's cwd resolves outside the
`MGH_TARGET` tree. A hit SHALL fail-loud (exit 2) + the read-side recipe. This closes the escape
path where the model, instead of using the native `Grep`/`grep` tool (whose `path` anchor is already
confined by the read-side rule — and whose underlying ripgrep process's scope is therefore bounded),
invokes `rg`/`grep`/… directly in `Bash` (which routes through the `Bash` branch, not the read
branch, and the existing Bash rules do not target out-of-tree search paths). `MGH_TARGET` resolves
with the same precedence as the read/write sides (env > sentinel.`target` > degrade-pass). The
detection is regex-over-observed-shape and SHALL NOT claim exhaustive coverage of every file-search
invocation form (pipes, aliases, env-injected paths are not guaranteed) — consistent with the
temp-I/O and file-association rules.

#### Scenario: Bash rg search in a sibling module is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and a reader issues
  `Bash` `rg "TokenInterceptor" D:\parent\sonB\src` (the native Grep tool's `path` confinement is
  bypassed by invoking rg directly in Bash with an out-of-tree path)
- **THEN** the guard scans the absolute-path token `D:\parent\sonB\src`, resolves it outside the
  target tree, and blocks with exit 2 + the read-side recipe — the cross-module search does not
  reach the host permission prompt

#### Scenario: Bash rg with no path and cwd outside target is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, the reader's cwd is
  `D:\parent` (outside the target tree), and the reader issues `Bash` `rg "TokenInterceptor"` (rg
  recursively searches cwd by default, i.e. the whole parent tree)
- **THEN** the guard finds no explicit absolute path, resolves the implicit cwd anchor outside the
  target tree, and blocks with exit 2 + the read-side recipe

#### Scenario: Bash rg anchored inside the target tree passes
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and a reader issues
  `Bash` `rg "TokenInterceptor" D:\parent\sonA\src` (in-tree path)
- **THEN** the guard passes (exit 0); legitimate in-tree searches via Bash are unaffected

#### Scenario: Bash non-search command is not affected by the file-search rule
- **WHEN** an `mgh-init` run-domain is active and the reader issues `Bash` `py "…discover_controls.py"
  --in "D:\parent\sonA\src\X.java"` (no file-search verb; the `.java`/`.py` paths are arguments, not
  search roots)
- **THEN** the guard does not apply the file-search rule (other Bash rules — script-as-arg — still
  apply as before); a path that is only a `--flag` argument is not a file-search-verb hit

#### Scenario: Inactive session passes Bash rg
- **WHEN** neither any `MGH_*_ACTIVE` env nor any `<run-root>/.active` sentinel is present (a
  day-to-day non-run-domain session) and the model issues `Bash` `rg "x" D:\anywhere`
- **THEN** the guard exits 0 silently (zero day-to-day noise; install/CI/dev unaffected)
