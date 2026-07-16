## ADDED Requirements

### Requirement: Freeform-text intake produces sra-compatible context

The `/mgh-srr` input adapter (`ingest_requirements.py`) SHALL accept freeform requirement text from
`.txt` / `.md` / `.csv` / `.json` (read natively), `.docx` / `.xlsx` (extracted best-effort via stdlib
`zipfile` + `xml.etree`), or `--text` / stdin passthrough, and SHALL emit a `change_context.json` of the
**same shape** as `/mgh-sra`'s `prepare_augment.py` (same top-level fields), so the reused sra middle engine
consumes it unmodified. The adapter MUST be the only producer of the fan-out `pending[]` list (R5.3).

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

### Requirement: Intake is non-load-bearing on interface/field extraction

The adapter SHALL treat extracted `endpoints` / `data_fields` / `role_hints` as **optional hints** (they MAY
be empty), because freeform requirement text MAY contain no concrete interface or field information. The review
SHALL still proceed by LLM semantic reading of the full text, with gaps anchored to requirement/section headings.

#### Scenario: doc lacking interfaces/fields still yields reviewable context
- **WHEN** the input text contains no recognizable endpoints or field names
- **THEN** the adapter emits `endpoints` / `data_fields` / `role_hints` as empty arrays and the downstream review still produces gaps anchored to section/requirement headings

### Requirement: Fan-out is script-enumerated, single-unit by default

The adapter SHALL emit exactly one `pending[]` item (the whole document as one review scope) by default.
With `--split`, the adapter SHALL deterministically split by markdown heading levels into multiple `pending[]`
items, each carrying an absolute `draft_path` + `done_marker` resolved within the project subtree. The
orchestrator SHALL iterate only this script-produced list and MUST NOT self-assemble paths.

#### Scenario: default single review unit
- **WHEN** `/mgh-srr` runs without `--split`
- **THEN** `change_context.json.pending` contains exactly one item whose `draft_path` and `done_marker` are absolute and within the project subtree

#### Scenario: split produces heading-based units
- **WHEN** `/mgh-srr` runs with `--split` on a document with multiple markdown headings
- **THEN** `pending[]` contains one item per top-level section, each with an absolute `draft_path`

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
that stage rather than continuing with a broken artifact.

#### Scenario: malformed intake rejected
- **WHEN** `ingest_requirements.py --check` detects a structurally invalid `change_context.json` (e.g. `pending[]` paths not absolute or outside the subtree)
- **THEN** it exits with code 2 and the orchestrator does not proceed to the LLM stages

### Requirement: Honest boundaries disclosed

The report and `srr_manifest.json` SHALL carry the SRR-specific boundary — *input extraction is best-effort for
`.docx`/`.xlsx` (dates/formats/lists degraded) and review coverage is bounded by input completeness; a vague
requirement document yields only sparse, anchor-light gaps* — alongside the reused sra boundaries (LLM candidates
need human review; coverage depends on declared + remembered facts; referenced controls assert existence not
effectiveness; memory is user-asserted not code truth; codegraph is optional advisory).

#### Scenario: SRR-specific boundary present
- **WHEN** the report / manifest is rendered
- **THEN** the boundaries list includes the input-completeness / extraction-degradation boundary in addition to the reused sra boundaries

### Requirement: Runtime discipline and zero runtime dependencies

`/mgh-srr` SHALL run under the `MGH_SRR_ACTIVE` run-domain (parallel to `MGH_SRA_ACTIVE`) with the
`block-adhoc-scripts` guard active on both claude (`PreToolUse`) and opencode (`.ts` plugin) ends, blocking adhoc
`py -c` introspection, unauthorized `Write *.py`, and out-of-subtree writes. The new scripts SHALL use only the
Python standard library (no `pip` dependency; R2); `.docx`/`.xlsx` handling via `zipfile` + `xml.etree`.

#### Scenario: hook blocks adhoc script in SRR domain
- **WHEN** the orchestrator (with `MGH_SRR_ACTIVE=1`) attempts a `py -c` introspection or an out-of-subtree write
- **THEN** the `block-adhoc-scripts` guard fails the call (exit code 2) with a stderr recipe, identical behavior on both claude and opencode ends
