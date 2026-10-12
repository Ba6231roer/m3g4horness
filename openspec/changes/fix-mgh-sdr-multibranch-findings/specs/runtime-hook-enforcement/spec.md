## MODIFIED Requirements

### Requirement: Bash path-token allowlist judgment (verb-independent fail-closed net)

When active with a pinned target, the guard SHALL judge EVERY path-like token in each `Bash`
command against the unified read allow-set — the resolved `MGH_TARGET` tree ∪ sentinel
`read_roots[]` ∪ project config `read_roots[]` — **regardless of which verb (if any) leads the
command**: any token that resolves outside ALL of them SHALL block (exit 2) with a recipe naming
the allowed read roots. Path-like tokens are: Windows drive-letter absolute (`C:\…`/`C:/…`), UNC
(`\\…`), POSIX absolute (`/…`), `..`-leading relative tokens (resolved against the guard's cwd),
and `~`-leading path tokens (bare `~` alone is not judged); tokens that are part of a URL
(`<word>://…`) SHALL be excluded from judgment. **Glob-form tokens**: a path-like token
containing glob metacharacters (`*`/`?`) SHALL be judged by its **glob-free prefix** (everything
before the first metacharacter); a glob segment that **directly abuts a quote-closed absolute
path** (`"C:\t"/*.html` or `"C:\t"\*.log`) SHALL be joined with that path into one logical token
before extraction (without the join, the closing quote ends the token and the glob fragment is
misread as a bare `/…` absolute path that resolves to the drive root — a false out-of-tree hit);
a glob whose prefix resolves outside the allow-set (`D:\other\*.log`) remains a block. This
glob-form semantics SHALL apply to EVERY Bash absolute-path-token judgment in the guard
(file-search, directory-listing, write/delete/redirect, and this net), so all rules judge the
same normalized token stream. A command carrying no path-like token SHALL pass
this rule (all other rules still apply to it). This judgment SHALL run AFTER the mutation rules
(write/delete verbs, redirects, `py -c` write-shape relabel) so mutation-shaped hits surface
their specific write/delete recipes, and alongside/after the existing verb-triggered read rules
(file-search, listing, interpreter-exec, mgh-core missing-install), which REMAIN IN FORCE as
refinements — this rule is the structural fail-closed net under them, closing the
"verb not in the enumeration table" escape class (`robocopy`, `curl -o`, `.NET` static write
methods, `Get-Content <out-of-tree file>`, `Expand-Archive`, …). Target unpinned => this rule
degrades to pass (mirror of every other path rule; never a hard block when no target was pinned).

#### Scenario: Unknown mutation verb with an out-of-tree destination is blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model
  issues `Bash: robocopy D:\parent\sonA\docs D:\backup` (the write verb `robocopy` is in NO
  enumeration table)
- **THEN** the guard judges the path tokens, finds `D:\backup` outside the target tree, and
  blocks with exit 2 + a recipe naming the allowed roots (previously passed — no enumerated verb
  matched)

#### Scenario: Direct read of an out-of-tree file is blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model
  issues `Bash: Get-Content D:\parent\sonB\notes.json` (a plain read verb, not a search/listing
  verb; previously passed every rule)
- **THEN** the guard resolves the path token outside the target tree and blocks with exit 2 +
  the recipe

#### Scenario: In-tree command passes untouched

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model
  issues `Bash: py .claude/mgh-core/scripts/list_clusters.py --out D:\parent\sonA\.mgh-init\c.json`
- **THEN** the guard passes (exit 0) — every path token resolves inside the target tree; the
  sanctioned deterministic-script workflow is unaffected

#### Scenario: `..`-climbing relative token is blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA` (guard cwd inside
  the tree), and the model issues `Bash: type ..\..\secret.txt` (cwd-relative resolution climbs
  out of the tree)
- **THEN** the guard resolves the `..`-leading token against the cwd, finds it outside the tree,
  and blocks with exit 2 + the recipe

#### Scenario: URL token does not false-trip

- **WHEN** an `mgh-init` run-domain is active with a pinned target, and the model issues
  `Bash: py .claude/mgh-core/scripts/tool.py --doc https://example.com/a/b`
- **THEN** the guard passes (exit 0) — the `s://…` fragment of the URL is excluded from
  path-token judgment (URL-scheme exclusion), so no false block

#### Scenario: Write-shaped hit into a declared read root surfaces the write recipe, not the read net

- **WHEN** an `mgh-sdr` run-domain is active with sentinel `read_roots:["D:/work/front"]`, and
  the model issues `Bash: Set-Content D:/work/front/x.js "v"` (a known write verb targeting a
  declared read-only root)
- **THEN** the mutation rules run FIRST, judge the destination against `MGH_TARGET` alone, and
  block with exit 2 + the write-side recipe (the read-net's allow-set never relaxes a write)

#### Scenario: Unpinned target degrades the token judgment to pass

- **WHEN** the guard is active but neither env nor sentinel pins a target, and the model issues
  `Bash: cat D:\anywhere\f.txt`
- **THEN** the token judgment degrades to pass (exit 0); the script-extension write block,
  `py -c` introspection block, temp-I/O, file-association, and mgh-core missing-install rules
  still fire where applicable

#### Scenario: Quoted in-tree path abutting a glob fragment passes

- **WHEN** an `mgh-sdr` run-domain is active with `MGH_TARGET=C:\DEV\springBootTemplate`, and
  the model issues the repo-root report-discovery command
  `ls -la "C:\DEV\springBootTemplate" | grep -i "mgh-sdr" ; ls "C:\DEV\springBootTemplate"/*.html`
- **THEN** the guard passes (exit 0): the glob segment `/*.html` abuts the quote-closed in-tree
  path and is joined with it before judgment (joined prefix in-tree), and the pipe/sub-command
  tokens all resolve inside the target tree — previously this exact form was a false
  out-of-tree block that burned host retry rounds

#### Scenario: Out-of-tree glob prefix is still blocked

- **WHEN** an `mgh-sdr` run-domain is active with `MGH_TARGET=C:\DEV\springBootTemplate`, and
  the model issues `Bash: ls "D:\other\repo"/*.html` (glob abutting an out-of-tree quoted path)
- **THEN** the guard joins the glob with its quoted prefix, resolves the prefix outside the
  target tree, and blocks with exit 2 + the recipe (the join is a false-positive fix, NEVER a
  read-side relaxation)

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
temp-I/O and file-association rules. Absolute-path token judgment in condition (a) SHALL apply the
glob-form semantics of the path-token allowlist net: a token containing glob metacharacters
(`*`/`?`) is judged by its glob-free prefix, and a glob segment directly abutting a quote-closed
absolute path is joined with that path before judgment (in-tree join => pass; out-of-tree prefix =>
block).

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

#### Scenario: In-tree quoted path abutting a glob passes the search-verb rule

- **WHEN** an `mgh-sdr` run-domain is active with `MGH_TARGET=C:\DEV\springBootTemplate`, and the
  model issues `Bash` `ls "C:\DEV\springBootTemplate"/*.html | grep -i "mgh-sdr"` (search verb
  after the pipe; the glob token abuts a quote-closed in-tree path)
- **THEN** the guard joins the glob with its in-tree quoted prefix, resolves it inside the target
  tree, and passes (exit 0) — the report-discovery form the sdr orchestration legitimately uses is
  no longer a false block

#### Scenario: Out-of-tree glob search root is still blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model
  issues `Bash` `rg "x" "D:\parent\sonB"/*.java` (glob abutting an out-of-tree quoted path)
- **THEN** the guard joins the glob with its out-of-tree quoted prefix, resolves the prefix
  outside the target tree, and blocks with exit 2 + the read-side recipe

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
judgment, `--flag <path>` arguments on a NON-listing leading verb do NOT trip), including the
glob-form semantics of the path-token allowlist net: a token containing glob metacharacters
(`*`/`?`) is judged by its glob-free prefix, and a glob segment directly abutting a quote-closed
absolute path is joined with that path before judgment (in-tree join => pass; out-of-tree prefix
=> block). Detection SHALL
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

#### Scenario: in-tree quoted path abutting a glob passes the listing rule

- **WHEN** an `mgh-sdr` run-domain is active with `MGH_TARGET=C:\DEV\springBootTemplate`, and the
  agent issues `ls "C:\DEV\springBootTemplate"/*.html` (the evidence false-positive shape: the
  closing quote ends the path token and the glob fragment used to be misread as a bare `/…`
  absolute path resolving to the drive root)
- **THEN** the guard joins the glob with its quoted in-tree prefix and passes (exit 0)
