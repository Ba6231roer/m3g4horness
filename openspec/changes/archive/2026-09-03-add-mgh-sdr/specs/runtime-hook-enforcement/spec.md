## ADDED Requirements

### Requirement: Sentinel read_roots grants tool-face read-only access to declared external roots

The run-domain sentinel schema SHALL gain an **optional** field `read_roots[]` (a list of absolute
filesystem roots); its absence preserves the existing schema shape byte-for-byte (`{"domain",
"target","out_roots[]","v":1}` remains valid). When `read_roots[]` is present and the guard is
active, the **tool-face read side** (`Read`/`Glob`/`Grep` only) SHALL additionally pass a call whose
resolved target (the same resolution rules as the out-of-tree judgment: `..` folding, identical
resolve semantics) falls inside ANY declared `read_roots[]` root — the declared external roots are
peer **read-only** allowances, and each root is judged with the same `is_relative_to` containment
semantics as `MGH_TARGET`. Every other read-side layer SHALL NOT be relaxed by `read_roots[]`: the
Bash file-search confinement (`rg`/`grep`/`find`/…), the leaf-script-source read block, the write
side (all layers: `Write`/`Edit`/`MultiEdit`/`NotebookEdit`/`ApplyPatch`, Bash write verbs,
redirects, deletes), and the `py -c` / temp-I/O / file-association blocks SHALL keep judging against
`MGH_TARGET` alone — an external root declared via `read_roots[]` NEVER becomes a writable or
Bash-searchable location. `out_roots[]` (write-side allowlist extension for init/ut-init) and
`read_roots[]` (read-side-only extension for any domain) are independent fields with disjoint
effects. The containment check SHALL require the declared root to exist and be a directory at
judgment time; a non-existent declared root grants nothing (fail-closed). This judgment holds
identically on both hosts (claude PreToolUse guard + opencode plugin shim pipe the full sentinel
JSON to the same Python decision core; byte-level parity, same wiring-coverage invariant).

#### Scenario: Declared external root read passes while undeclared is blocked

- **WHEN** an `mgh-sdr` run-domain is active with sentinel `{"domain":"mgh-sdr",
  "target":"D:/work/svc","read_roots":["D:/work/front"],"v":1}`, and a subagent issues
  `Read file_path=D:/work/front/src/api/pay.js` (inside the declared root)
- **THEN** the guard allows the read (exit 0) — the tool-face read side treats the declared root as
  a peer readable tree

#### Scenario: Undeclared sibling path stays blocked

- **WHEN** the same run-domain sentinel declares only `D:/work/front`, and a subagent issues
  `Read file_path=D:/work/other/src/x.js`
- **THEN** the guard blocks with exit 2 + the read-side recipe (declared roots are not a wildcard;
  only `MGH_TARGET` and listed roots are readable)

#### Scenario: Write into a declared read root is still blocked

- **WHEN** the same sentinel, and a subagent issues `Write file_path=D:/work/front/src/api/pay.js`
  (inside the declared read root)
- **THEN** the write side judges against `MGH_TARGET` alone and blocks (exit 2) — `read_roots[]`
  never grants write access

#### Scenario: Bash search verb confined to MGH_TARGET despite read_roots

- **WHEN** the same sentinel, and a subagent runs `Bash: rg pattern D:/work/front/src`
- **THEN** the Bash file-search confinement judges the absolute-path argument against
  `MGH_TARGET` only and blocks (exit 2) — external roots are tool-face-read-only by design

#### Scenario: Sentinel without read_roots is unchanged

- **WHEN** a legacy sentinel `{"domain":"mgh-srr","target":"T","out_roots":[],"v":1}` (no
  `read_roots` field) is active
- **THEN** guard behavior is byte-for-byte identical to before this change (no read relaxation, no
  parse error)

#### Scenario: Non-existent declared root grants nothing

- **WHEN** a sentinel declares `read_roots:["D:/gone/front"]` and the directory does not exist
- **THEN** a `Read` of `D:/gone/front/anything` is blocked (fail-closed containment: root must
  exist and be a directory at judgment time)
