# freeform-security-review Specification

## Purpose

Port-adapter pipeline for the `/mgh-srr` command: a freeform-text security review that does
**not** touch openspec. A deterministic intake adapter (`ingest_requirements.py`) ingests
`.txt` / `.md` / `.csv` / `.json` natively, `.docx` / `.xlsx` via stdlib best-effort extraction,
or `--text` / stdin passthrough, and emits a `change_context.json` of the same shape as
`/mgh-sra`'s `prepare_augment.py`. The sra middle engine (`sra-clarify` / `sra-augment` /
`sra-consistency`, shared fragments, `merge_memory.py`, `business_context.json`) is reused
verbatim with no new stage prompts. A deterministic render adapter (`render_report.py`) emits
a plain `security_review_report.md` + `srr_manifest.json` under an out-dir, never writing
under `openspec/`. Zero runtime dependencies; boundary validation (`--check`) at every step;
honesty boundaries disclosed in the report and manifest.
## Requirements
### Requirement: Freeform-text intake produces sra-compatible context

The `/mgh-srr` input adapter (`ingest_requirements.py`) SHALL accept freeform requirement text from
`.txt` / `.md` / `.csv` / `.json` (read natively), `.docx` / `.xlsx` (extracted best-effort via stdlib
`zipfile` + `xml.etree`), or `--text` / stdin passthrough, and SHALL emit a `change_context.json` of the
**same shape** as `/mgh-sra`'s `prepare_augment.py` (same top-level fields), so the reused sra middle engine
consumes it unmodified. The adapter MUST be the only producer of the fan-out `pending[]` list (R5.3). When the
orchestrator passes `--focus <inline-json|path>`, the adapter SHALL parse + closed-set-validate it via the
shared `focus_scope` module (sibling import, same as sra; see `dimension-focus` capability) and embed the
resolved `focus` (`{dimensions[], facets{}, directive}` or `null`) as a top-level field of
`change_context.json`, identical in shape and semantics to sra — so the reused a2/a3 subagents narrow their
per-dimension scan with **zero new prompts**. When the orchestrator passes `--sensitive-catalog <inline-json|@path|->`,
the adapter SHALL parse + closed-set-validate it via the shared `sensitive_catalog` module (sibling import, same as
sra; see `sensitive-catalog` capability) and embed the resolved `sensitive_catalog` (`{version, source, categories[],
items[], counts{}, directive}` or `null`) as a top-level field of `change_context.json`, identical in shape and
semantics to sra — so the reused a2/a3 subagents check per-item masking gaps with **zero new prompts**. Absent
`--focus` → `focus: null` and absent `--sensitive-catalog` → `sensitive_catalog: null` → behavior identical to before
this change.

#### Scenario: text-native formats ingested verbatim
- **WHEN** intake is given a `.txt`, `.md`, `.csv`, or `.json` requirement file
- **THEN** the adapter reads it natively and the emitted `change_context.json` carries the full text under a single default capability with no `degraded` flag set

#### Scenario: docx/xlsx best-effort extraction flagged degraded
- **WHEN** intake is given a `.docx` or `.xlsx`
- **THEN** the adapter extracts readable text via stdlib (joining all `<w:t>` within each `<w:p>` for `.docx`; resolving `sharedStrings` + raw cell values for `.xlsx`), and the `change_context.json` SHALL set a `degraded` flag noting which fidelity was lost (e.g. dates-as-serial, list-markers, embedded objects)

#### Scenario: text passthrough bypasses extraction
- **WHEN** intake is given `--text` or stdin content
- **THEN** the adapter SHALL use that text verbatim with no file-format extraction and no `degraded` flag

#### Scenario: unsupported format errors with recipe
- **WHEN** intake is given an unsupported format (`.doc`, `.xls`, scanned PDF, password-protected)
- **THEN** the adapter SHALL exit non-zero with a stderr recipe telling the user how to convert/export to a supported format, and SHALL NOT emit a partial `change_context.json`

#### Scenario: focus embedded identically to sra
- **WHEN** `ingest_requirements.py` is run with a valid `--focus`
- **THEN** `change_context.json` carries a `focus` object with the resolved `dimensions`/`facets`/`directive`, same shape as `/mgh-sra`; absent `--focus` → `focus: null`; the reused a2/a3 prompts narrow the scan with no prompt fork

#### Scenario: sensitive-catalog embedded identically to sra
- **WHEN** `ingest_requirements.py` is run with a valid `--sensitive-catalog`
- **THEN** `change_context.json` carries a `sensitive_catalog` object with the resolved `items[]`/`counts`/`directive`, same shape as `/mgh-sra`; absent `--sensitive-catalog` → `sensitive_catalog: null`; the reused a2/a3 prompts check per-item masking gaps with no prompt fork

#### Scenario: invalid focus fails intake before any LLM token
- **WHEN** `ingest_requirements.py` is run with an invalid `--focus` (unknown dimension/facet)
- **THEN** it exits 2 with an actionable stderr message, emits no `change_context.json`, and no LLM subagent is spawned

#### Scenario: invalid sensitive-catalog fails intake before any LLM token
- **WHEN** `ingest_requirements.py` is run with an invalid `--sensitive-catalog` (unknown category / illegal mask / malformed key)
- **THEN** it exits 2 with an actionable stderr message, emits no `change_context.json`, and no LLM subagent is spawned

### Requirement: Intake is non-load-bearing on interface/field extraction

The adapter SHALL treat extracted `endpoints` / `data_fields` / `role_hints` as **optional hints** (they MAY
be empty), because freeform requirement text MAY contain no concrete interface or field information. The review
SHALL still proceed by LLM semantic reading of the full text, with gaps anchored to requirement/section headings.

#### Scenario: doc lacking interfaces/fields still yields reviewable context
- **WHEN** the input text contains no recognizable endpoints or field names
- **THEN** the adapter emits `endpoints` / `data_fields` / `role_hints` as empty arrays and the downstream review still produces gaps anchored to section/requirement headings

### Requirement: Fan-out is script-enumerated, single-unit by default

The intake adapter (`ingest_requirements.py`) SHALL emit exactly one `pending[]` item (the whole document as one
review scope) by default. With `--split`, the adapter SHALL deterministically split by markdown heading levels into
multiple `pending[]` items, each carrying an absolute `draft_path` + `done_marker` + `input_path` + `bytes` +
`oversize` resolved within the project subtree. The orchestrator SHALL iterate only this script-produced list and
MUST NOT self-assemble paths. The adapter SHALL support `--materialize <dir>` (write each unit's full input to
`<dir>/<unit>.input.json`, report `input_path`/`bytes`/`oversize`), `--offset`/`--limit` (paginate `pending[]`),
and `--max-unit-bytes` (oversize unit → flag + recipe; not sharded). When a page's serialized bytes exceed
`--orch-budget-bytes`, the adapter SHALL shrink `--limit`, reporting `effective_limit` + `shrunk:true`. Each
per-unit stage subagent (reused sra engine: `sra-clarify`/`sra-augment`) SHALL read its own `input_path` rather than
receive an inlined record; the orchestrator MUST NOT load the whole sra-shape `change_context.json` into its request
context.

#### Scenario: default single review unit
- **WHEN** `/mgh-srr` runs without `--split`
- **THEN** `change_context.json.pending` contains exactly one item whose `draft_path`/`done_marker`/`input_path` are
  absolute and within the project subtree

#### Scenario: split produces heading-based units
- **WHEN** `/mgh-srr` runs with `--split` on a document with multiple markdown headings
- **THEN** `pending[]` contains one item per top-level section, each with an absolute `draft_path` + `input_path`

#### Scenario: per-unit subagent reads its own bounded input
- **WHEN** `/mgh-srr` fans out a unit into the reused sra engine
- **THEN** the stage subagent input carries an absolute `input_path` → `<out-dir>/inputs/<unit>.input.json` with
  `bytes` ≤ `--max-unit-bytes`; the orchestrator passes `input_path`, never the whole `change_context.json`

#### Scenario: oversize unit is flagged not sharded
- **WHEN** a unit input `bytes` > `--max-unit-bytes`
- **THEN** `ingest_requirements.py` flags `oversize:true` + a recipe (use `--split` / narrow the doc); it does not
  shard the unit

#### Scenario: work-list page shrinks to the orchestrator budget
- **WHEN** a `pending[]` page's serialized bytes > `--orch-budget-bytes`
- **THEN** `ingest_requirements.py` shrinks `--limit`, reporting `effective_limit` + `shrunk:true`; the orchestrator pages

### Requirement: Middle engine reused verbatim, no duplication

`/mgh-srr` SHALL reuse the existing sra stage prompts (`sra-clarify.md`, `sra-augment.md`,
`sra-consistency.md`), fragments (`security-dimensions.md`, `codegraph-hint.md`), `merge_memory.py`, and
the `business_context.json` contract **without copying or forking** them. No new stage prompt or subagent SHALL
be created for the middle engine.

#### Scenario: same prompts consumed by both entry points
- **WHEN** either `/mgh-sra` or `/mgh-srr` drives the middle engine
- **THEN** both resolve the identical `core/prompts/stages/sra-*.md` and `fragments/*.md` files (single source of truth)

### Requirement: Output is a plain report that never touches openspec

The output adapter (`render_report.py`) SHALL read finalized drafts (+ optional memory) and emit a human-readable
`security_review_report.md` (简体中文, brief, by dimension/anchor: gaps + optional reuse suggestions + asked
clarifications + boundaries) plus `srr_manifest.json` (counts + boundaries). All output SHALL land under an
out-dir (default `<project>/.mgh-srr/`, overridable via `--out`) and MUST NOT write anywhere under `openspec/`.

#### Scenario: report and manifest written under out-dir
- **WHEN** the review completes
- **THEN** `security_review_report.md` and `srr_manifest.json` exist under the configured out-dir

#### Scenario: openspec tree untouched
- **WHEN** `/mgh-srr` runs to completion
- **THEN** no file under any `openspec/` directory is created or modified

### Requirement: Shared cross-tool business memory

`/mgh-srr` SHALL persist clarification answers to the **same** `<project>/.mgh-sra/business_context.json` used by
`/mgh-sra` (same schema, same file), so business memory accumulates across both tools and remains consumable by
future `/mgh-blst`. The memory contract SHALL NOT be modified by this change.

#### Scenario: srr and sra accumulate one memory file
- **WHEN** a project runs `/mgh-srr` then `/mgh-sra` (or vice versa)
- **THEN** both read and write the same `business_context.json`, with answers accumulated by `fact_key` without duplication

### Requirement: Per-stage boundary validation

`ingest_requirements.py` and `render_report.py` SHALL each expose a `--check` mode (R5.9). The orchestrator SHALL
run the producer's `--check` after each deterministic stage and, on failure (exit code 2), fall back and rerun
that stage rather than continuing with a broken artifact. `ingest_requirements.py --check` SHALL additionally
validate the `focus` field (when present) is shape-valid (closed-set dimensions, facets matching their
dimension, `null` allowed) and the `sensitive_catalog` field (when present) is shape-valid (items[] each with a
closed-set category, a `full`/`partial` mask, a valid `<category>/<field-type>` key and non-empty label; `null`
allowed).

#### Scenario: malformed intake rejected
- **WHEN** `ingest_requirements.py --check` detects a structurally invalid `change_context.json` (e.g. `pending[]` paths not absolute or outside the subtree)
- **THEN** it exits with code 2 and the orchestrator does not proceed to the LLM stages

#### Scenario: malformed focus field fails intake check
- **WHEN** `ingest_requirements.py --check` sees a `change_context.focus` with an unknown dimension key or a facets/dimension mismatch
- **THEN** it exits with code 2 naming the focus-field violation

#### Scenario: malformed sensitive-catalog field fails intake check
- **WHEN** `ingest_requirements.py --check` sees a `change_context.sensitive_catalog` whose item has an unknown category, a non-`full`/`partial` mask, a malformed key, or a missing label
- **THEN** it exits with code 2 naming the sensitive-catalog field violation

### Requirement: Honest boundaries disclosed

The report and `srr_manifest.json` SHALL carry the SRR-specific boundary — *input extraction is best-effort for
`.docx`/`.xlsx` (dates/formats/lists degraded) and review coverage is bounded by input completeness; a vague
requirement document yields only sparse, anchor-light gaps* — alongside the reused sra boundaries (LLM candidates
need human review; coverage depends on declared + remembered facts; referenced controls assert existence not
effectiveness; memory is user-asserted not code truth; codegraph is optional advisory). When `focus` is non-null
(dimension focus applied), the report header SHALL note the in-scope dimensions and `srr_manifest.json` SHALL
carry a `focus` field (the dimension list) plus a boundary line stating **only the focused dimensions were
scanned; out-of-scope dimensions were not covered**. When `sensitive_catalog` is non-null (company masking policy
applied), the report header SHALL note the catalog coverage (item count + categories) and `srr_manifest.json` SHALL
carry a `sensitive_catalog` field (`counts{items, full, partial, categories}` + `source`) plus a boundary line
stating **masking gaps were checked per the company catalog items; field types outside the catalog were recognized
only via the legacy 6 facets** (so the reader does not mistake the catalog for an exhaustive sensitive-field list).

#### Scenario: SRR-specific boundary present
- **WHEN** the report / manifest is rendered
- **THEN** the boundaries list includes the input-completeness / extraction-degradation boundary in addition to the reused sra boundaries

#### Scenario: Focused run discloses its scope
- **WHEN** `/mgh-srr` runs with `--focus` narrowing to a subset of dimensions
- **THEN** `security_review_report.md` notes the in-scope dimensions and `srr_manifest.json` carries `focus` (dimension list) plus a boundary line disclosing the narrowed coverage; a run without `--focus` carries `focus: null` and no such line

#### Scenario: Catalog-applied run discloses its coverage
- **WHEN** `/mgh-srr` runs with `--sensitive-catalog` (37 items)
- **THEN** `security_review_report.md` notes the catalog coverage (37 items across 10 categories) and `srr_manifest.json` carries `sensitive_catalog` (`counts` + `source`) plus a boundary line disclosing that masking gaps were checked per catalog items and out-of-catalog fields used only the 6 facets; a run without `--sensitive-catalog` carries `sensitive_catalog: null` and no such line

### Requirement: Runtime discipline and zero runtime dependencies

`/mgh-srr` SHALL run under the `MGH_SRR_ACTIVE` run-domain (parallel to `MGH_SRA_ACTIVE`) with the
`block-adhoc-scripts` guard active on both claude (`PreToolUse`) and opencode (`.ts` plugin) ends. The guard's
**activation model + runtime write discipline** SHALL follow the shared contract
[`runtime-hook-enforcement`](../runtime-hook-enforcement/spec.md): activation = `MGH_SRR_ACTIVE=1` env **or**
the `<cwd>/.mgh-srr/.active` disk sentinel (written by the orchestrator at step 0 via `Bash`, removed on
completion/clean-stop — closes the prior opencode "mid-session env not inherited → guard dormant" boundary);
runtime writes of any script extension (`.py`/`.ps1`/`.sh`/`.ts`/…) SHALL fail-loud with **no**
`core/scripts`/`mgh-core/scripts` whitelist exemption (leaf scripts are read-only); out-of-subtree writes SHALL
be blocked (srr retains the out-of-tree check; no positive allowlist). The new scripts SHALL use only the Python
standard library (no `pip` dependency; R2); `.docx`/`.xlsx` handling via `zipfile` + `xml.etree`.

#### Scenario: hook blocks adhoc script in SRR domain
- **WHEN** the orchestrator attempts a `py -c` introspection, a `Write` of an adhoc `.py`/`.ps1`/`.ts` script, or an out-of-subtree write
- **THEN** the `block-adhoc-scripts` guard fails the call (exit code 2) with a stderr recipe; identical behavior on both claude and opencode ends

#### Scenario: opencode activates the srr guard via the disk sentinel
- **WHEN** opencode 下 `MGH_SRR_ACTIVE` env 未设,但 step 0 已写 `<cwd>/.mgh-srr/.active` 哨兵
- **THEN** 守卫经哨兵激活,等效 env 已设;内省/越权脚本写/越树写均 fail-loud

#### Scenario: Shell writes and removes the srr sentinel
- **WHEN** 审阅两份 `mgh-srr.md` 编排流起步与完成态
- **THEN** 两壳均含 `export MGH_SRR_ACTIVE=1` + 写 `<target>/.mgh-srr/.active` 哨兵步骤;完成态移除哨兵

### Requirement: Long-running deterministic Bash calls carry a per-call timeout

`/mgh-srr` 命令壳的编排器 SHALL 给**长跑确定性 Bash 调用**——尤其 `ingest_requirements`(docx/xlsx
尽力抽取,大输入耗时)/`render_report`(及 `--check` 边界校验)——传一个慷慨的 per-call `timeout`
(claude Bash 工具与 opencode shell 工具均接受毫秒级 `timeout` 参数),使其在大输入上不被宿主默认超时
(opencode 实测 60s / 官方 120s;claude 120s)强杀。命令壳 SHALL 在边界/披露段说明:opencode 用户**可**
经环境变量 `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS`(默认 120000)提升全局默认,但该变量**须在
opencode 启动前就绪**(mid-session `export` 不被 opencode 插件进程继承,与 R5.7 `MGH_*_ACTIVE` 可靠性
边界同根因);per-call `timeout` 是跨宿主公共杠杆,可在会话中即时生效。本要求与 `control-discovery` 的
同名横切 recipe 同形(承 `harden-mgh-init-shell-timeout`)。

#### Scenario: Shell recipe tells the orchestrator to pass a per-call timeout
- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-srr.md`
- **THEN** 两壳均显式要求 `ingest_requirements`/`render_report` 等长跑确定性 Bash 调用携带 per-call `timeout`

#### Scenario: opencode env-var boundary disclosed
- **WHEN** 审阅 `mgh-srr.md` 边界段
- **THEN** 其中明示 `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS` 须 opencode 启动前设置、mid-session
  `export` 不生效,并指 per-call `timeout` 为会话内即时生效的替代

