## ADDED Requirements

### Requirement: Bash write-verb confinement to the MGH_TARGET tree

When active, the guard SHALL scan each `Bash` command for a leading **write verb** — `New-Item`/`ni`,
`Set-Content`/`sc`, `Add-Content`/`ac`, `Out-File`, `tee`, `mkdir`/`md`, `Copy-Item`/`cpi`/`cp`/`copy`/`xcopy`,
`Move-Item`/`mi`/`mv`/`rename`/`Rename-Item` (or the same verb as the first token of a sub-command after
`;`/`|`/`&&`/`||`) — and, on a hit, SHALL block when EITHER (a) the write **destination** resolves outside the
`MGH_TARGET` tree (for single-path verbs any out-of-tree absolute-path token; for `Copy-Item`/`Move-Item`/`xcopy` the
LAST absolute-path token = the destination), OR (b) the command carries no explicit absolute path (destination
defaults to cwd) AND the guard's cwd resolves outside the `MGH_TARGET` tree. A hit SHALL fail-loud (exit 2) + the
write-side recipe. `MGH_TARGET` resolves with the same precedence as the read/write sides (env > sentinel.`target` >
degrade-pass). This closes the bypass where the model, instead of using the native `Write`/`Edit` tool (whose target
is already confined by the existing write-confinement rule), invokes a file-write verb directly in `Bash` (which routes
through the `Bash` branch, and the existing Bash rules — `py -c` introspection / temp-I/O / aggregate-read / file-assoc /
file-search — do not target out-of-tree write paths). The detection is regex-over-observed-shape and SHALL NOT claim
exhaustive coverage of every write form (pipes, aliases, env-injected paths, PowerShell `.NET` static methods like
`[System.IO.File]::WriteAllText`, `robocopy`/`fsutil` are not guaranteed) — consistent with the temp-I/O,
file-association, and read-side Bash file-search rules.

#### Scenario: Bash Set-Content to an out-of-tree path is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `Set-Content D:\out\f.json "x"` (the Write/Edit tool's confinement is bypassed by invoking a write verb directly
  in Bash with an out-of-tree path)
- **THEN** the guard scans the absolute-path token `D:\out\f.json`, resolves it outside the target tree, and blocks
  with exit 2 + the write-side recipe — the out-of-tree write does not silently execute

#### Scenario: Bash New-Item creating an out-of-tree file/dir is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `New-Item -ItemType File -Path D:\out\f.json -Force` (or `-ItemType Directory -Path D:\out\d`)
- **THEN** the guard resolves the `-Path` token outside the target tree and blocks with exit 2 + the write-side recipe

#### Scenario: Bash mkdir of an out-of-tree directory is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `mkdir D:\out\d`
- **THEN** the guard blocks with exit 2 + the write-side recipe

#### Scenario: Bash Copy-Item destination outside the target tree is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `Copy-Item x.java D:\out\` (the LAST absolute-path token = destination, outside the target tree)
- **THEN** the guard resolves the destination token outside the target tree and blocks with exit 2 + the write-side
  recipe; the in-tree source token does not exempt the out-of-tree destination

#### Scenario: Bash write verb with no path and cwd outside target is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, the model's cwd is `D:\parent`
  (outside the target tree), and the model issues `Bash` `Set-Content evil.txt "x"` (relative path resolves under
  cwd, i.e. the parent tree)
- **THEN** the guard finds no explicit absolute path, resolves the implicit cwd anchor outside the target tree, and
  blocks with exit 2 + the write-side recipe — the cwd-drift write leak is caught

#### Scenario: Bash write verb anchored inside the target tree passes
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `Set-Content D:\parent\sonA\.mgh-init\report\out.json "x"` (inside a sanctioned init subtree)
- **THEN** the guard passes (exit 0); legitimate in-tree writes via Bash (inside sanctioned subtrees for init/ut-init)
  are unaffected

#### Scenario: Bash non-write command is not affected by the write-verb rule
- **WHEN** an `mgh-init` run-domain is active and the model issues `Bash` `py "…list_clusters.py" --out
  "D:\parent\sonA\.mgh-init\clusters.json"` (no write verb; the `.json` path is a `--flag` argument to a
  producer, which writes inside the sanctioned subtree itself)
- **THEN** the guard does not apply the write-verb rule (other Bash rules — script-as-arg — still apply as before);
  a path that is only a `--flag` argument to a non-write-verb command is not a write-verb hit

#### Scenario: Active domain with no pinned target degrades the write-verb check
- **WHEN** the guard is active but `MGH_TARGET` env is unset AND the sentinel carries no `target`, and the model
  issues `Bash` `Set-Content D:\out\f.json "x"`
- **THEN** the script-extension write block / `py -c` introspection block / temp-I/O / file-association /
  aggregate-read blocks still fire (exit 2) where applicable; the write-verb out-of-tree check **degrades to pass**
  (NEVER use cwd as a hard block target when no target was pinned, consistent with the read/write sides' degrade rule)

#### Scenario: Inactive session passes Bash write verbs
- **WHEN** neither any `MGH_*_ACTIVE` env nor any `<run-root>/.active` sentinel is present and the model issues
  `Bash` `Set-Content D:\anywhere\f.json "x"`
- **THEN** the guard exits 0 silently (zero day-to-day noise; install/CI/dev unaffected)

### Requirement: Bash destructive-delete confinement to the MGH_TARGET tree

When active, the guard SHALL scan each `Bash` command for a leading **delete verb** — `Remove-Item`/`ri`, `del`,
`erase`, `rm`, `rmdir`/`rd` (or the same verb as the first token of a sub-command after `;`/`|`/`&&`/`||`) — and,
on a hit, SHALL block when EITHER (a) any explicit absolute-path token in the command resolves outside the
`MGH_TARGET` tree, OR (b) the command carries no explicit absolute path AND the guard's cwd resolves outside the
`MGH_TARGET` tree. A hit SHALL fail-loud (exit 2) + a **delete-side recipe** that calls out that deletion is
irreversible. Deletion is structurally worse than write (no artifact is produced; the action cannot be rolled back),
so the recipe SHALL explicitly forbid removing anything outside the target tree, including sibling modules. This
closes the bypass where the model invokes `Remove-Item`/`rm`/… directly in `Bash` (the existing Bash rules do not
target out-of-tree delete paths). `MGH_TARGET` resolves with the same precedence as the other sides
(env > sentinel.`target` > degrade-pass); the detection is regex-over-observed-shape (pipes/aliases/env-injected
paths, `shutil.rmtree` via `py -c`, `.NET` `::Delete` are covered by the `py -c` write-token relabel and the
absolute-path scan where a path literal is present, but not guaranteed for every form).

#### Scenario: Bash Remove-Item of a sibling module is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `Remove-Item D:\parent\sonB -Recurse -Force` (deletes a sibling module outside the target tree — irreversible)
- **THEN** the guard resolves `D:\parent\sonB` outside the target tree and blocks with exit 2 + the delete-side
  recipe ("deletion is irreversible; NEVER Remove-Item / del / rm outside the target tree, including sibling modules")

#### Scenario: Bash rm -rf of an out-of-tree path is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `rm -rf D:\out`
- **THEN** the guard resolves `D:\out` outside the target tree and blocks with exit 2 + the delete-side recipe

#### Scenario: Bash py -c shutil.rmtree of an out-of-tree path is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `py -c "import shutil; shutil.rmtree('D:/out')"` (interpreter-indirect delete; no introspection token, so the
  prior `py -c` rule did not catch it)
- **THEN** the guard's `py -c` write-token relabel recognizes the write/delete shape, scans the absolute-path literal
  `D:/out`, resolves it outside the target tree, and blocks with exit 2 + the delete-side recipe

#### Scenario: Inactive session passes Bash delete verbs
- **WHEN** neither any `MGH_*_ACTIVE` env nor any `<run-root>/.active` sentinel is present and the model issues
  `Bash` `Remove-Item D:\anywhere -Recurse -Force`
- **THEN** the guard exits 0 silently (zero day-to-day noise)

### Requirement: Bash redirect confinement to the MGH_TARGET tree

When active, the guard SHALL detect a `>`/`>>` redirect in a `Bash` command whose target resolves OUTSIDE the
`MGH_TARGET` tree (generalizing the prior temp-only redirect rule, which matched only known temp-dir prefixes) and
SHALL block it (exit 2) + the write-side recipe. For `mgh-init` AND `mgh-ut-init the redirect target SHALL
additionally land inside a sanctioned subtree (positive allowlist), mirroring the Write/Edit tool-layer rule — so a
redirect that pollutes the target root (`echo x > D:\parent\sonA\evil.txt`) fails loud too. The prior temp-dir
write + read-back defense (`_detect_temp_io`) is retained as an independent defense; this rule adds the out-of-tree /
non-sanctioned-subtree axis. `MGH_TARGET` resolves with the same precedence (env > sentinel.`target` > degrade-pass).

#### Scenario: Bash redirect to an out-of-tree non-temp path is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `echo x > D:\out\f.json` (a non-temp out-of-tree redirect the prior temp-only rule did not match)
- **THEN** the guard resolves the redirect target `D:\out\f.json` outside the target tree and blocks with exit 2 +
  the write-side recipe

#### Scenario: Bash append redirect to an out-of-tree path is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `echo x >> D:\out\f.json`
- **THEN** the guard blocks with exit 2 + the write-side recipe

#### Scenario: Bash redirect polluting the target root is blocked (init allowlist)
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `echo x > D:\parent\sonA\evil.txt` (in-tree but at the target root, outside the sanctioned init subtrees)
- **THEN** the guard applies the init positive allowlist to the redirect target, finds it outside the sanctioned
  subtrees, and blocks with exit 2 + the write-side recipe — Bash-side root pollution is caught like the Write-tool
  allowlist catches it

#### Scenario: Bash redirect to a sanctioned in-tree path passes
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `echo x > D:\parent\sonA\.mgh-init\report\out.json` (inside a sanctioned init subtree)
- **THEN** the guard passes (exit 0); legitimate in-tree redirects are unaffected

#### Scenario: Bash temp write + read-back still blocked by the retained temp-I/O rule
- **WHEN** an `mgh-init` run-domain is active and the model issues `Bash` `echo x > $env:TEMP\t.json; Get-Content
  $env:TEMP\t.json`
- **THEN** the retained `_detect_temp_io` defense still fires (exit 2 + the temp-I/O recipe), independent of the
  generalized redirect rule

### Requirement: In-tree Bash write confined to sanctioned subtrees for init and ut-init

When active in an `mgh-init` OR `mgh-ut-init` run-domain, the guard SHALL apply the existing positive-allowlist check
(the same `_ALLOWLIST_SUBTREES` used for the `Write`/`Edit` tool layer) to the destination of a Bash write verb
(`Set-Content`/`Add-Content`/`Out-Content`/`Out-File`/`New-Item`/`tee`/`>` redirect) even when that destination is
INSIDE the `MGH_TARGET` tree. This closes the bypass where a Bash write verb pollutes the target root
(`Set-Content D:\parent\sonA\evil.txt`) — the Write/Edit tool-layer allowlist governs only the tool abstraction, not
Bash. sast/sra/srr retain the out-of-tree check without the allowlist (mirroring their Write/Edit tool-layer stance).
The sanctioned subtrees for init are `<target>/.mgh-init`, `<target>/.claude/rules`, `<target>/docs/security-controls`,
plus `<target>/AGENTS.md` and sentinel `out_roots[]`; for ut-init `<target>/.mgh-ut-init`, `<target>/.claude/rules`,
`<target>/docs/test-conventions`, plus `<target>/AGENTS.md` and `out_roots[]`.

#### Scenario: Bash Set-Content polluting the init target root is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `Set-Content D:\parent\sonA\evil.txt "x"` (in-tree but at the target root, outside the sanctioned init subtrees)
- **THEN** the guard applies the init allowlist to the Bash write destination, finds it outside the sanctioned
  subtrees, and blocks with exit 2 + the write-side recipe — the Bash root-pollution bypass of the Write-tool
  allowlist is closed

#### Scenario: Bash Set-Content inside a sanctioned init subtree passes
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `Set-Content D:\parent\sonA\.mgh-init\report\out.json "x"`
- **THEN** the guard passes (exit 0)

#### Scenario: sast domain Bash write inside target tree passes (no allowlist)
- **WHEN** an `mgh-sast` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `Set-Content D:\parent\sonA\src\notes.txt "x"` (in-tree; sast has no positive allowlist, only the out-of-tree check)
- **THEN** the guard passes (exit 0); sast/sra/srr retain the out-of-tree check without the allowlist

### Requirement: claude MultiEdit and NotebookEdit confined like Write/Edit

The guard SHALL treat claude's `MultiEdit` and `NotebookEdit` tools identically to `Write`/`Edit` for confinement:
both SHALL enter the write-confinement branch. `MultiEdit` carries its target under `file_path`; `NotebookEdit`
carries its target under `notebook_path` — the path extraction SHALL read `tool_input.file_path` falling back to
`tool_input.notebook_path` then `tool_input.path`. The same script-extension block, out-of-tree check, and init/ut-init
positive allowlist SHALL apply. `.ipynb` SHALL NOT be added to the script-extension set (notebooks are artifacts, not
runtime scripts; `NotebookEdit` is confined only by tree location, not by extension). This closes the bypass where an
out-of-tree batch edit (`MultiEdit file_path=D:\out\f.json`) or out-of-tree notebook edit
(`NotebookEdit notebook_path=D:\out\nb.ipynb`) fell through to `return 0` because the write-confinement branch
matched only `Write`/`Edit`.

#### Scenario: claude MultiEdit outside the target tree is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `MultiEdit`
  `file_path=D:\out\f.json` `edits=[…]`
- **THEN** the guard resolves `D:\out\f.json` outside the target tree and blocks with exit 2 + the write-side recipe

#### Scenario: claude NotebookEdit outside the target tree is blocked
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `NotebookEdit`
  `notebook_path=D:\out\nb.ipynb`
- **THEN** the guard resolves `D:\out\nb.ipynb` outside the target tree (reading `notebook_path`) and blocks with
  exit 2 + the write-side recipe

#### Scenario: claude MultiEdit inside a sanctioned init subtree passes
- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `MultiEdit`
  `file_path=D:\parent\sonA\.claude\rules\auth.md` (inside a sanctioned init subtree)
- **THEN** the guard passes (exit 0)

### Requirement: opencode apply_patch confined to the MGH_TARGET tree

The opencode `.ts` shim SHALL feed the guard for `apply_patch` tool events (opencode's multi-file mutating tool —
add/update/delete/move, whose file paths live inside a `patchText` blob as `*** Add File: <path>` /
`*** Update File: <path>` / `*** Delete File: <path>` / `*** Move to: <path>` marker lines). The shim SHALL normalize
`apply_patch` by extracting every marker path into a `paths[]` list (glue-only field extraction; NO confinement
decision logic in the shim — single decision source, zero drift) and pass `{tool_name:"ApplyPatch",
tool_input:{paths:[…]}}` to the guard. The guard SHALL, for an `ApplyPatch` tool event, run the existing
script-extension block, out-of-tree check, and init/ut-init positive allowlist against EACH path in `paths[]`, and
SHALL block (exit 2 + write-side recipe, delete-side wording for delete operations) if ANY path is out-of-tree / a
blocked script extension / outside the sanctioned subtrees. The shim's `HANDLED` set SHALL include `apply_patch`
alongside `bash`/`write`/`edit`/`read`/`glob`/`grep`.

#### Scenario: opencode apply_patch adding an out-of-tree file is blocked
- **WHEN** an opencode session is inside an `mgh-init` run-domain (sentinel `target=D:\parent\sonA`) and the model
  issues `apply_patch` with `patchText` containing `*** Add File: D:\out\evil.ps1`
- **THEN** the shim extracts `D:\out\evil.ps1` into `paths[]`, the guard resolves it outside the target tree (and as
  a `.ps1` script extension), and blocks with exit 2 + the write-side recipe; the shim throws to abort the tool call
  (the model sees the recipe)

#### Scenario: opencode apply_patch deleting an out-of-tree file is blocked with delete wording
- **WHEN** an opencode session is inside an `mgh-init` run-domain and the model issues `apply_patch` with `patchText`
  containing `*** Delete File: D:\parent\sonB\x.java` (a sibling module, outside the target tree)
- **THEN** the shim extracts the path, the guard blocks with exit 2 + the delete-side recipe ("deletion is
  irreversible; NEVER delete outside the target tree, including sibling modules")

#### Scenario: opencode apply_patch entirely inside sanctioned subtrees passes
- **WHEN** an opencode session is inside an `mgh-init` run-domain and the model issues `apply_patch` whose every
  marker path is inside `<target>/.mgh-init` or `<target>/.claude/rules`
- **THEN** the guard passes (exit 0); legitimate in-tree patches are unaffected

#### Scenario: shim remains glue-only for apply_patch
- **WHEN** the shim source is checked in CI
- **THEN** a parity-test source-form assertion requires the shim to extract `apply_patch` marker paths AND forbids it
  from reimplementing the confinement decision logic (e.g. `_out_of_tree_mutation` / `_WRITE_VERBS` / `_DELETE_VERBS`
  / `is_relative_to` / target resolution / `ApplyPatch` guard-side branching MUST NOT appear in the shim — single
  decision source)

### Requirement: opencode shim arg-name defense-in-depth for write/edit/read

The opencode `.ts` shim's `normalize` SHALL read the file path for `edit`/`write`/`read` from a fallback chain
`args.filePath ?? args.file_path ?? args.path` (the opencode tool schema field is `path`; relying solely on `filePath`
— which the LLM emits in camelCase — would silently yield an empty path if opencode ever passes schema-validated
args). This is a defense-in-depth with zero behavior change for the current camelCase-emitting LLM; it closes a
latent parity gap where a schema-validated `path` arg would bypass confinement (empty `file_path` → guard degrades to
pass). The `grep` source field SHALL be read as `args.include ?? args.glob` (the opencode schema field is `include`).

#### Scenario: opencode write with schema-validated path arg is still confined
- **WHEN** an opencode session is inside an `mgh-init` run-domain and the model issues a `write` tool call whose args
  carry the path under the schema field `path` (not `filePath`), targeting `D:\out\f.json`
- **THEN** the shim's fallback chain resolves the path from `args.path`, the guard blocks the out-of-tree write with
  exit 2 + the write-side recipe (rather than silently passing on an empty `filePath`)
