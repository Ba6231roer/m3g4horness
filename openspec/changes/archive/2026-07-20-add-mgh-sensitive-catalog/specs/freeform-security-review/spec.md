## MODIFIED Requirements

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
