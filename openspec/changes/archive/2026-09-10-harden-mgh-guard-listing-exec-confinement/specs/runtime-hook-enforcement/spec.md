## ADDED Requirements

### Requirement: Bash directory-listing command confinement to the MGH_TARGET tree

When active with a pinned target, the guard SHALL block a `Bash` command whose **directory-listing
verb** (`ls`, `dir`, `Get-ChildItem`, `gci`, and any pwsh alias resolving to `Get-ChildItem` in
the guard's alias table) leads a simple command (as the FIRST token of the command body or of a
sub-command after a `;`/`|`/`&&`/`||` delimiter) with an **out-of-tree scope** — mirroring the
file-search rule's judgment: an explicit absolute-path argument resolving outside the
`MGH_TARGET` tree, or no explicit absolute path with the guard cwd outside the tree. A hit SHALL
fail-loud (exit 2) + the read-side recipe (`ls`/`dir` are read-side enumeration; the sanctioned
alternative is work-list primitives / `describe_artifact.py`). Scope resolution SHALL follow the
same semantics as the file-search rule (fold `..`, same `resolve()` + `is_relative_to(target)`
judgment, `--flag <path>` arguments on a NON-listing leading verb do NOT trip). Detection SHALL
remain regex-over-observed-shape: pipes feeding a listing verb, aliases beyond the guard's table,
and relative-path listings are not guaranteed (same documented stance as the file-search rule).
Target absent => degrade to pass (mirror of the file-search rule).

#### Scenario: ls of an out-of-tree absolute path is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=/adhome/u/gitlab_pab/proj/sub_proj`
  (sentinel or env), and the agent issues `ls /home` or `ls /adhome`
- **THEN** the guard finds the listing verb leading the command with an out-of-tree absolute-path
  scope, and blocks with exit 2 + the read-side recipe (previously passed — listing verbs were not
  in any read-side verb set)

#### Scenario: dir/Get-ChildItem with an out-of-tree scope is blocked
- **WHEN** the guard is active with a pinned target and the command is `Get-ChildItem D:\` or
  `dir ..\..` whose resolution climbs outside the target tree
- **THEN** the guard blocks with exit 2 + the read-side recipe

#### Scenario: in-tree listing passes
- **WHEN** the guard is active with `MGH_TARGET=D:\parent\sonA` and the agent issues
  `ls src/auth` or `Get-ChildItem D:\parent\sonA\docs`
- **THEN** the guard passes (exit 0); legitimate in-tree enumeration is unaffected

#### Scenario: listing verb with no path and cwd inside the tree passes
- **WHEN** the guard is active, the guard cwd is inside the target tree, and the command is a bare
  `ls` or `ls -la`
- **THEN** the guard passes (exit 0) — the implicit cwd scope is in-tree

### Requirement: Bash interpreter script-execution confinement to the MGH_TARGET tree

When active with a pinned target, the guard SHALL block a `Bash` command that invokes an
**interpreter** (`py`, `py3`, `python`, `python3`, `python2`) leading a simple command (FIRST
token or after a delimiter) where the **first script-extension argument** (any `_SCRIPT_EXTS`
member) resolves **outside** the `MGH_TARGET` tree. The script path is judged at the
**positional-argument** face only — `--flag <path>` arguments (e.g. `--checkpoints <in-tree>`)
are NOT the executed script and SHALL NOT trip; a `py -c "<code>"` body is NOT judged here (its
read/write shapes are already governed by the existing introspection/write-relabel rules).
This closes the bypass where `py /home/user/other/repo/script.py` (or any interpreter-run script
outside the project) executes while the no-launcher file-association rule passes it for carrying
an explicit interpreter prefix. A hit SHALL fail-loud (exit 2) + a recipe pointing at the
in-tree installed script path (`py .claude/mgh-core/scripts/<script>.py …`); in-tree interpreter
executions are unaffected. Target absent => degrade to pass.

#### Scenario: interpreter running an out-of-tree script is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=/adhome/u/proj/sub_proj`, and the
  agent issues `py /home/someone/other/run.py` or `python3 ~/tools/scan.py`
- **THEN** the guard resolves the first script-extension argument outside the target tree and
  blocks with exit 2 + the interpreter-exec recipe (previously passed — the explicit launcher
  prefix exempted it from the file-association rule and no other rule judged the script location)

#### Scenario: interpreter running an in-tree script passes
- **WHEN** the guard is active with a pinned target and the command is
  `py .claude/mgh-core/scripts/resume_state.py --target .` (script arg resolves in-tree)
- **THEN** the guard passes (exit 0); all sanctioned deterministic-script invocations are
  unaffected

#### Scenario: --flag path arguments are not judged as the executed script
- **WHEN** the guard is active with a pinned target and the command is
  `py <target>/.mgh-core/scripts/list_clusters.py --clusters <in-tree>.json`
- **THEN** the guard judges the first positional script-extension argument (the script itself,
  in-tree) and passes — a `--flag <in-tree path>` never trips even though it names a path

#### Scenario: py -c bodies are not judged by this rule
- **WHEN** the guard is active with a pinned target and the command is
  `py -c "import json; open('/home/x/f.json').read()"`
- **THEN** this rule does not fire (no script-extension positional argument); the existing
  introspection rule blocks it with its own recipe

### Requirement: mgh-core missing-install detection stops all tasks

When active, the guard SHALL intercept a `Bash` command that references an installed mgh-core
script path (a path segment `mgh-core/scripts/` AND a script extension) whose resolved location
is **absent on disk** or **outside the `MGH_TARGET` tree**, and fail-loud (exit 2) with a
**stop-all recipe**: `mgh-core is not installed in this target — STOP ALL TASKS (do not
continue the run), report to the USER that mgh-init must be installed in the CURRENT project
directory (run install), and NEVER search other directories (parent project, /home, /adhome,
siblings) for scripts or prompts.` This encodes the observed multi-project failure shape: mgh-core
installed only in the root project while the run executes in an independent sub-project — scripts
404, and the model's natural response is cross-directory wandering. The rule SHALL fire on the
first such reference in any Bash command (the missing-install face is terminal for the run; there
is no sanctioned continuation). Non-script or non-mgh-core references are unaffected; the guard
SHALL NOT probe the filesystem beyond the referenced paths themselves.

#### Scenario: mgh-core script referenced but not installed under the target is blocked with stop-all recipe
- **WHEN** mgh-core is installed only in the root project while the run's target is an
  independent sub-project (no `mgh-core/` anywhere under the target), and the agent issues
  `py .claude/mgh-core/scripts/resume_state.py --target .`
- **THEN** the guard resolves the referenced mgh-core script path, finds it absent (or outside the
  target), and blocks with exit 2 + the stop-all recipe (stop all tasks; ask the user to install
  in the current project directory; NEVER search other directories)

#### Scenario: installed mgh-core script reference passes
- **WHEN** mgh-core is installed under the target and the agent issues
  `py .claude/mgh-core/scripts/list_clusters.py …`
- **THEN** the guard passes (exit 0); the normal deterministic-script workflow is unaffected

#### Scenario: non-mgh-core missing paths do not trip this rule
- **WHEN** the guard is active and the command references an in-tree user script that happens not
  to exist (no `mgh-core/scripts` segment), or a project source file
- **THEN** this rule does not fire (existence of arbitrary non-product paths is the caller's
  concern, not the guard's)
