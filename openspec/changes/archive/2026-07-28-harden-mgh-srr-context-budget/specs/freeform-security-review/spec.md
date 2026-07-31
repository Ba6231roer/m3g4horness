# freeform-security-review Delta

承 `harden-mgh-init-context-budget`(泛化):`/mgh-srr` 复用 sra 中间引擎(见「Middle engine reused verbatim」),
故 sra a3 per-capability 的 per-unit 物化 + 预算**透传生效**;其 intake 适配器 `ingest_requirements.py` 亦采纳
`request-context-budget`——per-unit **输入物化** + slim 分页 `pending[]` + 字节预算;编排器 **NEVER** 整份读
sra-shape `change_context.json`;`render_report.py` 的聚合输入(全部定稿)有界或披露。机制统辖见
`request-context-budget`。

## MODIFIED Requirements

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
