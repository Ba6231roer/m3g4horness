## ADDED Requirements

### Requirement: Closed-set focus-scope registry as single source of truth

`core/scripts/focus_scope.py` SHALL embed the canonical **closed-set** registry of the 9 security dimensions
and their optional per-dimension facets, and SHALL be the single source of truth those keys validate against.
The 9 dimension keys SHALL be exactly: `sensitive-data`, `injection`, `horizontal-authz`, `vertical-authz`,
`authentication`, `integrity`, `audit`, `rate-limiting`, `secrets` (mirroring
`core/prompts/fragments/security-dimensions.md`). Per-dimension facets SHALL be defined only for dimensions
whose catalog enumerates discrete sub-categories: `sensitive-data` facets = `id-card` / `bank-card` / `phone` /
`email` / `password` / `token`; `injection` facets = `sqli` / `xss` / `command-injection` / `path-traversal` /
`ssrf` / `deserialization` / `xxe`. The other 7 dimensions have **no** facets (whole-dimension focus only). The
registry SHALL carry a human-readable label (简体中文) per dimension and per facet so a rendered directive is
readable. The registry keys MUST stay in lockstep with the dimension catalog (`security-dimensions.md`); adding
a dimension or facet is a registry + catalog co-change (closed-set, never free-text).

#### Scenario: list enumerates the 9 dimensions and their facets
- **WHEN** `focus_scope.py --list` is run
- **THEN** stdout is JSON listing all 9 dimension keys with labels, and `sensitive-data`/`injection` carry their facet keys with labels, while the other 7 dimensions carry an empty facet set

#### Scenario: registry keys match the dimension catalog
- **WHEN** the 9 dimension keys in the registry are compared to `security-dimensions.md`
- **THEN** they are identical (the catalog's 维度键 column and the registry's keys are the same closed set)

### Requirement: Parse and validate --focus against the closed set

`focus_scope.py` SHALL accept a focus spec as inline JSON **or** a path to a JSON file, with this shape:
`{"dimensions": [<key>, ...], "facets": {"<dim>": [<facet>, ...]}}`. The argument is interpreted as inline JSON
when it begins with `{`; otherwise it is treated as a path to a UTF-8 JSON file (a leading `@` is optional and
stripped before this check; a missing/unreadable file exits 1). `dimensions` is a closed-set list of the 9
keys (or the literal `"*"` / omitted = all 9). `facets` is an optional per-dimension whitelist; a dimension
listed under `facets` MUST also be present in `dimensions`; facet keys MUST be valid for that dimension (a
dimension with no facets rejects any `facets` entry). Validation SHALL reject, with **exit code 2** and an
actionable stderr message naming the offending key and the allowed set: any unknown dimension key, any unknown
facet key, any facet entry for a dimension that has no facets, any `facets` entry for a dimension not in
`dimensions`, and an empty/all-excluded `dimensions` list (which would review nothing). A syntactically valid
spec with a known subset SHALL resolve to exit 0. `--check <spec>` SHALL perform validation only (no rendering,
no side effects).

#### Scenario: valid subset focus accepted
- **WHEN** `--focus` is `{"dimensions":["sensitive-data","horizontal-authz"],"facets":{"sensitive-data":["id-card","bank-card"]}}`
- **THEN** `focus_scope.py` parses + validates it (exit 0) and the resolved focus carries exactly those two dimensions and the two facets

#### Scenario: star means all nine
- **WHEN** `--focus` is `{"dimensions":"*"}` or `--focus` is omitted
- **THEN** the resolved `dimensions` is all 9 keys (equivalent to the default, no narrowing)

#### Scenario: unknown dimension rejected with exit 2
- **WHEN** `--focus` is `{"dimensions":["authz-broken"]}`
- **THEN** `focus_scope.py` exits 2 with a stderr message naming `authz-broken` and listing the 9 allowed dimension keys

#### Scenario: unknown facet for a dimension rejected with exit 2
- **WHEN** `--focus` is `{"dimensions":["sensitive-data"],"facets":{"sensitive-data":["ssn-number"]}}`
- **THEN** `focus_scope.py` exits 2 naming `ssn-number` and listing the allowed `sensitive-data` facets (`id-card`/`bank-card`/...)

#### Scenario: facet on a facet-less dimension rejected
- **WHEN** `--focus` is `{"dimensions":["horizontal-authz"],"facets":{"horizontal-authz":["idor"]}}`
- **THEN** `focus_scope.py` exits 2 noting `horizontal-authz` has no facets

#### Scenario: empty dimension list rejected
- **WHEN** `--focus` is `{"dimensions":[]}`
- **THEN** `focus_scope.py` exits 2 with a message that an empty focus would review nothing

#### Scenario: file-path form reads a JSON file
- **WHEN** `--focus path/to/focus.json` (or `--focus @path/to/focus.json`) is given and the file contains a valid focus object
- **THEN** `focus_scope.py` reads + validates it identically to the inline form

#### Scenario: inline-vs-path detection is unambiguous
- **WHEN** the `--focus` value begins with `{`
- **THEN** it is parsed as inline JSON; any other value is treated as a file path (a leading `@` is tolerated and stripped); a non-`{` value that is not a readable file exits 1

### Requirement: Render a deterministic focus directive

`focus_scope.py --parse` (and `--render`) SHALL, for a valid focus, emit a resolved focus object on stdout:
`{"dimensions":[<key>,...], "facets":{<dim>:[<facet>,...]}, "directive":"<简体中文>"}`. The `directive` SHALL be a
deterministic简体中文 sentence listing the in-scope dimensions (by label) and, for any dimension with a facet
whitelist, the in-scope facets (by label) in parentheses, ending with the rule that out-of-scope dimensions
produce no gaps and no clarification questions. The directive string is the only thing the orchestrator passes
verbatim into the LLM subagents; it MUST be stable for a given focus (same input → byte-identical directive) so
runs are reproducible. When focus is all-9 (default), the resolved object SHALL be `null` and no directive is
rendered (signal to the orchestrator: do not inject any narrowing).

#### Scenario: directive names dimensions and facets in 简体中文
- **WHEN** the focus is `{"dimensions":["sensitive-data","horizontal-authz"],"facets":{"sensitive-data":["id-card","bank-card"]}}`
- **THEN** the `directive` mentions 敏感数据 with 身份证号 + 银行卡号 in parentheses and 横向越权·IDOR, and states other dimensions are out of scope

#### Scenario: directive is deterministic
- **WHEN** `--parse` is run twice on the same focus spec
- **THEN** the two `directive` strings are byte-identical (ordering of dimensions/facets follows registry order, not input order)

#### Scenario: all-nine focus resolves to null
- **WHEN** `--focus` is omitted or `{"dimensions":"*"}`
- **THEN** the resolved focus is `null` and no directive string is produced

### Requirement: focus field in change_context.json

The intake stages SHALL accept `--focus <inline-json|@path>` (`prepare_augment.py` for `/mgh-sra`, `ingest_requirements.py` for `/mgh-srr`), parse + validate it via the shared `focus_scope` module (sibling
import, R5.3a) **before any LLM subagent runs** (it is the deterministic a1/r1 stage), and embed the resolved
`focus` as a new top-level field of `change_context.json`. The field value SHALL be the resolved focus object
(`{dimensions[], facets{}, directive}`) or `null` when `--focus` is absent (default = all 9, behavior unchanged).
The orchestrator SHALL read `change_context.focus.directive` from the stage stdout and pass it verbatim into the
a2/a3 subagent task input; it MUST NOT re-parse or re-assemble the focus. Validation failure (exit 2 from
`focus_scope`) SHALL fail the intake stage loud (exit 2) before any token is spent, consistent with the
zero-token guard. Backward compatibility: a run without `--focus` SHALL produce a `change_context.json`
byte-equivalent in behavior to today (`focus: null`, no directive injected).

#### Scenario: focus embedded when flag given
- **WHEN** `prepare_augment.py` / `ingest_requirements.py` is run with a valid `--focus`
- **THEN** `change_context.json` carries a `focus` object with the resolved `dimensions`/`facets`/`directive`

#### Scenario: focus is null when flag absent
- **WHEN** either script is run without `--focus`
- **THEN** `change_context.json` carries `focus: null` and downstream behavior is identical to before this change

#### Scenario: invalid focus fails intake before any LLM token
- **WHEN** either script is run with an invalid `--focus` (unknown key)
- **THEN** the script exits 2 with an actionable stderr message and emits no `change_context.json`, and no LLM subagent is spawned

### Requirement: Focus directive narrows sra-clarify and sra-augment per-dimension scan

When the orchestrator passes a non-null `focus.directive` into the `sra-clarify` (a2) and `sra-augment` (a3) subagent task input, both subagents SHALL restrict their per-dimension pass to the dimensions listed in the directive (and, within a dimension that has facets, to the listed facets only). They SHALL emit **no** gaps and
**no** clarification questions for dimensions/facets outside the focus. All other behavior — anchoring each gap
to a concrete requirement/endpoint/field, dropping ungrounded boilerplate, three-signal control matching,
codegraph advisory, memory priority, output purity — SHALL remain unchanged for in-scope gaps. When no directive
is passed (`focus: null`), both subagents SHALL behave byte-identically to before this change (all 9 dimensions).
This narrowing is realized as a small additive overlay section in `core/prompts/stages/sra-clarify.md` and
`sra-augment.md` (the only prompt edits); `/mgh-srr` reuses these prompts verbatim and so obtains the behavior
with zero new prompts. The `sra-consistency` (a4), `merge_augment` (a5), and codegraph stages operate on the
already-produced in-scope gaps and require no change.

#### Scenario: augment only emits in-scope gaps
- **WHEN** `sra-augment` is given a directive narrowing to `horizontal-authz` + `vertical-authz` only
- **THEN** its draft `gaps[]` carry only those dimensions (no `sensitive-data`/`injection`/... gaps), while in-scope gaps still anchor to concrete requirements and may still match controls

#### Scenario: augment facet filter drops out-of-facet sensitive-data gaps
- **WHEN** `sra-augment` is given a directive narrowing `sensitive-data` to facets `[id-card, bank-card]`
- **THEN** it emits sensitive-data gaps only for 身份证号 / 银行卡号 fields; sensitive-data gaps anchored to phone/email/password/token fields are NOT emitted

#### Scenario: clarify only asks about in-scope dimensions
- **WHEN** `sra-clarify` is given a directive narrowing to `authentication` only
- **THEN** its `clarifications[]` carry only `dimension: authentication`; no clarification is emitted for other dimensions

#### Scenario: no directive is fully backward-compatible
- **WHEN** no focus directive is passed (`focus: null`)
- **THEN** `sra-clarify` and `sra-augment` iterate all 9 dimensions exactly as before this change

### Requirement: focus_scope.py runtime and CLI contract

`focus_scope.py` SHALL use only the Python ≥3.10 standard library (R2; no `pip` dependency), be self-locating
(`sys.path.insert(0, dir-of-__file__)`) so the sibling import from `prepare_augment.py` /
`ingest_requirements.py` resolves under any cwd, and read any focus file with `encoding="utf-8"`. Its CLI
surface SHALL be: `--list` (enumerate registry), `--parse <inline-json|path>` (validate + render resolved focus),
`--render <inline-json|path>` (alias of the render portion), `--check <inline-json|path>` (validate only), and
`--help`. For all value-taking flags, an argument beginning with `{` is inline JSON; otherwise it is a file path
(leading `@` optional, stripped).
`--help` is the contract surface (R5.1): the four sra/srr command shells SHALL mirror these flags exactly, and
`tools/check_contracts.py` SHALL assert every `--flag` the shells invoke is declared here. stdout SHALL carry
structured JSON (the resolved focus or the `--list` registry or the `--check` verdict); stderr SHALL carry
diagnostics/progress only; exit codes SHALL be `0` ok · `1` file missing / JSON malformed · `2` misuse
(argparse) or closed-set validation violation (R5.3b). The script SHALL be idempotent and side-effect-free
(`--parse`/`--check`/`--list`/`--render` write nothing to disk).

#### Scenario: zero runtime dependencies
- **WHEN** an AST scan is run over `focus_scope.py`
- **THEN** no third-party import exists (stdlib only)

#### Scenario: contract lint sees declared flags
- **WHEN** `tools/check_contracts.py` lints the four sra/srr shells
- **THEN** every `--focus` / `--list` / `--parse` / `--check` invocation in the shell bash blocks is declared in `focus_scope.py --help`

#### Scenario: stdout/stderr separation
- **WHEN** `focus_scope.py --parse` succeeds
- **THEN** stdout is a single JSON object (the resolved focus) and stderr carries only a progress line

#### Scenario: malformed JSON exits 1
- **WHEN** `--focus` inline JSON is syntactically broken
- **THEN** `focus_scope.py` exits 1 with a stderr message (not 2; this is a read/parse failure, not a closed-set violation)
