## MODIFIED Requirements

### Requirement: Sentinel read_roots grants tool-face read-only access to declared external roots

The run-domain sentinel schema carries an **optional** field `read_roots[]` (a list of absolute
filesystem roots); its absence preserves the existing schema shape (`{"domain","target",
"out_roots[]","v":1}` remains valid). When `read_roots[]` is present and the guard is active,
a call or command whose resolved path falls inside ANY declared `read_roots[]` root SHALL pass on
BOTH read faces: the **tool face** (`Read`/`Glob`/`Grep`) and the **Bash face** (any `Bash`
command's path tokens, judged by the Bash path-token allowlist rule). This REVERSES the prior
decision that a declared root NEVER becomes a Bash-searchable location — the unified model is
"what is readable at all is readable through any tool"; it is safe to unify because the Bash face
now judges paths directly (verb-independently) instead of relying on verb enumeration. The write
side is NOT relaxed: every write layer (`Write`/`Edit`/`MultiEdit`/`NotebookEdit`/`ApplyPatch`,
Bash write verbs, redirects, deletes) SHALL keep judging against `MGH_TARGET` alone — a declared
root NEVER becomes a writable location. The leaf-script-source read block and the `py -c` /
temp-I/O / file-association blocks are likewise NOT relaxed. `out_roots[]` (write-side allowlist
extension for init/ut-init) and `read_roots[]` (read-side extension for any domain) remain
independent fields with disjoint effects. The containment check SHALL require the declared root
to exist and be a directory at judgment time; a non-existent declared root grants nothing
(fail-closed). This judgment holds identically on both hosts (claude PreToolUse guard + opencode
plugin shim pipe the full sentinel JSON to the same Python decision core; byte-level parity, same
wiring-coverage invariant).

#### Scenario: Declared external root read passes while undeclared is blocked

- **WHEN** an `mgh-sdr` run-domain is active with sentinel `{"domain":"mgh-sdr",
  "target":"D:/work/svc","read_roots":["D:/work/front"],"v":1}`, and a subagent issues
  `Read file_path=D:/work/front/src/api/pay.js` (inside the declared root)
- **THEN** the guard allows the read (exit 0) — the declared root is a peer readable tree

#### Scenario: Undeclared sibling path stays blocked

- **WHEN** the same run-domain sentinel declares only `D:/work/front`, and a subagent issues
  `Read file_path=D:/work/other/src/x.js`
- **THEN** the guard blocks with exit 2 + the read-side recipe (declared roots are not a wildcard;
  only the target tree and listed roots are readable)

#### Scenario: Write into a declared read root is still blocked

- **WHEN** the same sentinel, and a subagent issues `Write file_path=D:/work/front/src/api/pay.js`
  (inside the declared read root)
- **THEN** the write side judges against `MGH_TARGET` alone and blocks (exit 2) — `read_roots[]`
  never grants write access

#### Scenario: Bash search verb confined to MGH_TARGET despite read_roots

- **WHEN** the same sentinel, and a subagent runs `Bash: rg pay D:/work/front/src`
- **THEN** the guard passes (exit 0) — the Bash face judges the path token against the unified
  read allow-set (target ∪ `read_roots[]`), so a declared root is Bash-readable like it is
  tool-face-readable. **语义反转**: the PRIOR behavior (blocked — "declared roots never become
  Bash-searchable") is replaced by this requirement; the scenario retains its historical name
  for delta traceability

#### Scenario: Bash path outside target and all declared roots is blocked

- **WHEN** the same sentinel, and a subagent runs `Bash: rg pay D:/work/other/src`
- **THEN** the guard blocks with exit 2 + the read-side recipe (the path resolves outside the
  target tree AND every declared root)

#### Scenario: Sentinel without read_roots is unchanged

- **WHEN** a legacy sentinel `{"domain":"mgh-srr","target":"T","out_roots":[],"v":1}` (no
  `read_roots` field) is active
- **THEN** guard behavior is unchanged for the sentinel path (no read relaxation from the
  sentinel; the project config file, if present, still applies per its own requirement)

#### Scenario: Non-existent declared root grants nothing

- **WHEN** a sentinel declares `read_roots:["D:/gone/front"]` and the directory does not exist
- **THEN** a `Read` of `D:/gone/front/anything` is blocked (fail-closed containment: root must
  exist and be a directory at judgment time)

## ADDED Requirements

### Requirement: Bash path-token allowlist judgment (verb-independent fail-closed net)

When active with a pinned target, the guard SHALL judge EVERY path-like token in each `Bash`
command against the unified read allow-set — the resolved `MGH_TARGET` tree ∪ sentinel
`read_roots[]` ∪ project config `read_roots[]` — **regardless of which verb (if any) leads the
command**: any token that resolves outside ALL of them SHALL block (exit 2) with a recipe naming
the allowed read roots. Path-like tokens are: Windows drive-letter absolute (`C:\…`/`C:/…`), UNC
(`\\…`), POSIX absolute (`/…`), `..`-leading relative tokens (resolved against the guard's cwd),
and `~`-leading path tokens (bare `~` alone is not judged); tokens that are part of a URL
(`<word>://…`) SHALL be excluded from judgment. A command carrying no path-like token SHALL pass
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

### Requirement: Project read-roots config file extends the read allow-set in every domain

The guard SHALL consult a per-project read-roots config file at `<MGH_TARGET>/.mgh/read-roots.json`
in EVERY mgh run-domain, merging its `read_roots[]` entries into the unified read allow-set
alongside the sentinel's `read_roots[]` (union; both sources optional; a missing config file
means behavior identical to before this requirement). The schema is
`{"v":1,"read_roots":["<abs root>",…]}`; unknown fields are ignored. A malformed JSON body or a
wrong-typed `read_roots` SHALL grant NOTHING (fail-closed) and SHALL NOT crash the guard or
alter any other judgment. Each entry SHALL be judged with the same fail-closed containment as
the sentinel's `read_roots[]` (the root must exist and be a directory at judgment time; a
non-existent entry grants zero). Config-declared roots are READ-ONLY allowances on the tool face
and the Bash face; they NEVER grant write access (the write side judges `MGH_TARGET` alone),
NEVER relax the leaf-script-source read block, and NEVER relax the `py -c` / temp-I/O /
file-association blocks. The file lives inside the target tree, so writes to it are governed by
the existing write-confinement rules as an ordinary in-tree file. The config is
hand-editable by the user; a deterministic writer (sdr approval flow) is a follow-up change and
is NOT required by this requirement.

#### Scenario: Config root is readable on both faces in every domain

- **WHEN** an `mgh-sast` run-domain is active with config `{"v":1,"read_roots":["D:/shared/specs"]}`,
  and the model issues `Read file_path=D:/shared/specs/auth.md` and `Bash: rg token D:/shared/specs`
- **THEN** both pass (exit 0) — the config extends the read allow-set for the tool face and the
  Bash face alike, in a domain that has no sentinel `read_roots[]`

#### Scenario: Write into a config root is blocked

- **WHEN** the same `mgh-sast` domain and config, and the model issues
  `Write file_path=D:/shared/specs/auth.md`
- **THEN** the write side judges against `MGH_TARGET` alone, finds the path out-of-tree, and
  blocks with exit 2 + the write-side recipe

#### Scenario: Malformed config grants nothing and does not crash

- **WHEN** the config file contains invalid JSON (or `read_roots` is not a list), and the model
  issues `Read file_path=D:/anything/f.txt` (outside the target tree)
- **THEN** the guard blocks the read with exit 2 as if no config existed (fail-closed), exits
  normally on in-tree calls, and never errors out

#### Scenario: Missing config file means unchanged behavior

- **WHEN** no `.mgh/read-roots.json` exists under the target, and the model issues any tool call
- **THEN** guard behavior is identical to before this requirement (no parse, no relaxation, no error)

#### Scenario: Config union with sentinel read_roots

- **WHEN** the sentinel declares `read_roots:["D:/work/front"]` and the config declares
  `read_roots:["D:/shared/specs"]`, and the model reads a file under each root
- **THEN** both reads pass (exit 0) — the two sources are a union, each judged with the same
  fail-closed containment
