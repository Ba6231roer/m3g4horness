# Changelog

All notable changes to **m3g4h⊿rness** are recorded here.
Format based on [Keep a Changelog](https://keepachangelog.com/), versioning follows
[Semantic Versioning](https://semver.org/).

`m3g4h⊿rness` (SAST tool: `/mgh-sast`) is a zero-runtime-dependency reimplementation of the
[vvaharness](https://github.com/visa/vvaharness) (Visa / Project Glasswing) 9-stage
agentic SAST pipeline. Prompt **content** is ported under Apache-2.0 (see
`core/docs/NOTICE`); no `vvaharness` code is imported or bundled.

The `0.x` line denotes initial development: structurally complete, but live
end-to-end verification is still pending (see *Pending* below).

---

## [0.1.8] — 2026-07-15

### Added
- **`/mgh-srr` — freeform-text security requirements review (no openspec needed).** A new command
  for the common case where requirements arrive as raw text (word/txt/md/excel or pasted) with no
  openspec structure — and possibly no concrete interfaces/fields at all. It is a **port-adapter
  over the `/mgh-sra` middle engine**: a deterministic input adapter (`ingest_requirements.py`)
  extracts the doc into an sra-shape `change_context.json`, the existing sra engine (sra-clarify /
  sra-augment / sra-consistency + 9 dimensions + three-signal control reuse + batched clarification
  + project memory) is **reused verbatim with zero new prompts**, and a deterministic output adapter
  (`render_report.py`) renders a plain, brief Simplified-Chinese `security_review_report.md` +
  `srr_manifest.json` that **never touches openspec/**.
  - **Mixed three-tier input**: `.txt/.md/.csv/.json` read natively (perfect); `.docx`/`.xlsx`
    best-effort via stdlib `zipfile` + `xml.etree` (joining all `<w:t>` within each `<w:p>` so text
    never token-fragments) with **explicit degradation flags** (dates-as-serial / list-markers /
    embedded-objects / merged-cells); a permanent `--text` / stdin **passthrough** escape hatch
    (zero degradation). Unsupported formats (`.doc`/`.xls`/scanned PDF/encrypted) exit 2 with a
    conversion recipe and emit no partial artifact.
  - Interfaces / fields / roles are **optional, non-load-bearing hints** (freeform text may have
    none); the LLM reads the full text and anchors gaps to section headings. Default = one review
    unit; `--split` fans out per markdown `#`/`##` heading (script-enumerated fan-out).
  - **Shares** `<project>/.mgh-sra/business_context.json` with `/mgh-sra` (one accumulating file
    across both tools; same schema, contract unchanged). Optional codegraph enrichment is inherited
    from the reused sra engine (`--no-codegraph` opts out, reproducing pre-codegraph behavior).
  - **Runtime discipline**: a new `MGH_SRR_ACTIVE` run-domain on the **unchanged**
    `block-adhoc-scripts` guard (claude PreToolUse + opencode `.ts` plugin, byte-identical twin),
    covering the review dir + shared project memory under `MGH_TARGET`. Same fail-soft reliability
    boundary on opencode as the other domains.
- Zero new runtime dependencies (R2): `.docx`/`.xlsx` use only the Python standard library. SRR
  reuses all sra stage prompts + fragments + `merge_memory.py` (no duplication — asserted by the
  new `test_mgh_srr_codegraph_parity.py` reuse-not-duplication tests).

### Known limitation (honest boundary)
- `/mgh-srr` input extraction is best-effort for `.docx`/`.xlsx` (dates / formats / list markers
  degraded — flagged in the report); review coverage is bounded by input completeness, so a vague
  requirement document yields only sparse, anchor-light gaps. The `--text`/stdin passthrough has no
  degradation. All other sra boundaries (LLM candidates need human review; controls asserted to
  exist not to be effective; memory is user-asserted; codegraph is optional advisory) apply unchanged.

---

## [0.1.7] — 2026-07-15

### Added
- **Optional codegraph enrichment for `/mgh-init` and `/mgh-sra` (coordinated pair).**
  When the target project has a precomputed codegraph index (`<target>/.codegraph/`)
  **and** the `codegraph` tool on PATH, both commands use it as an optional,
  detection-gated enrichment backend consumed entirely in the **LLM layer** — never
  `import`ed by any `.py`, so zero new runtime dependencies (R2) and zero changes to the
  deterministic script contracts (R5.3). Detection defaults to `auto`; `--no-codegraph`
  opts out and reproduces pre-codegraph behavior exactly (fail-soft).
  - **`/mgh-init`**: a new optional `init-resolve` stage (codegraph-gated, single context)
    resolves the framework-routed / DI / AOP / interface→impl / reflection controls the
    text/AST call graph collects into `unresolved[]`, emitting additive
    `source:"codegraph"` candidates with a real `resolved_path[]`. scout/induct/survey
    stages prefer `codegraph_explore` (MCP) / `codegraph explore` (CLI) for surgical
    context. `init_manifest.json` gains a `codegraph:{available,used,resolved_count,
    unresolved_residual}` block.
  - **`/mgh-sra`**: `sra-augment` (a3) gains an inline **call-path structural-evidence
    confirmation** — for gaps that already matched all three reuse signals, codegraph
    confirms whether the recommended control is actually wired onto the gap endpoint's
    request path, recorded as advisory `recommended_control.call_path:{confirmed,
    path[],source:"codegraph",note}` (plus data-flow / liveness / domain-sibling
    advisory facets). This upgrades signal-2 "business-domain similarity" from a semantic
    guess toward structural evidence, directly targeting SRA's "controls are asserted to
    exist, not to be effective" blind spot. Bounded + fail-soft (top-1 control per gap
    under budget; `confirmed` never fabricated; never overrides code evidence or user
    `business_context.json`). `sra_manifest.json` gains `counts.call_path_confirmed` /
    `call_path_residual` + a 5th honesty boundary; the existing four stay intact.
- **Shared codegraph steering fragment** `core/prompts/fragments/codegraph-hint.md`,
  co-owned by both changes. Prescriptive by intent — "SHALL prefer codegraph, Read only
  as fallback", never the permissive "you may" — to avoid the known trap where a subagent
  keeps self-Reading and codegraph becomes pure overhead.
- **Dual-platform parity (R5.7)**: claude + opencode both reach codegraph via MCP
  (`codegraph_explore`), with CLI (`codegraph explore`) Bash fallback. The existing
  `block-adhoc-scripts` guard is unchanged — codegraph MCP/CLI calls do not hit any of its
  ad-hoc-script surfaces — so **no new hook** is introduced.

### Known limitation (honest boundary)
- codegraph is itself a static analyzer: reflection / DI-container / runtime dispatch
  remain unresolved, so call-path confirmation shrinks but does not zero out mis-wiring.
  `call_path` is LLM+codegraph advisory needing human review; manifests disclose
  `call_path_residual` / `unresolved_residual` and never claim "fully confirmed".
- opencode's plugin process does not inherit env vars exported mid-session, so the
  `codegraph=on` signal activates reliably only when present at opencode launch; the CLI
  Bash fallback + shell bright-lines cover the gap (fail-soft).

## [0.1.6] — 2026-07-10

### Added
- **opencode runtime-discipline hook parity.** opencode now gets the same orchestrator-discipline
  enforcement Claude Code has. `install.sh --opencode` injects a `tool.execute.before` plugin
  (`.opencode/plugins/block_adhoc_scripts.ts`) that normalizes the tool event into Claude's
  PreToolUse stdin shape and pipes it to the **same** platform-neutral Python guard
  (`block_adhoc_scripts.py`, now also mirrored to `.opencode/hooks/`). The guard is unchanged —
  single decision source, byte-parity guarded by `tests/test_opencode_hook_parity.py`. New
  `tools/install_opencode_plugin.py` mirrors `tools/install_hook.py` (idempotent, merge-aware,
  `--remove`). This corrects the prior wrong premise that "opencode has no PreToolUse capability":
  opencode's hook surface is JS/TS plugins (`tool.execute.before`/`tool.execute.after`) — this was
  a porting gap, now closed (not a capability gap).

### Known limitation (honest boundary)
- opencode's plugin process does **not** inherit env vars exported mid-session via `bash` (its shell
  tool builds env from `process.env` and never writes back). So `export MGH_*_ACTIVE=1` inside a run
  may not reach the guard; the runtime gate activates only when the env is present at opencode
  launch (e.g. `MGH_*_ACTIVE=1 opencode run`). The shell bright-lines + per-stage `--check` boundary
  validation remain the real backstop either way (fail-soft). Verified against opencode v1.17.15.

### Fixed
- **`/mgh-init` scout→merge fold-in crashed on two kinds of malformed `scout_candidates.json`**
  (raw traceback, empty stdout, orchestrator unable to decide). (1) A candidate missing its
  `category` field hit a `KeyError` in `merge_scout._normalize`; (2) a broken JSON string value
  (e.g. an `evidence_snippet` with mis-escaped quotes / backslashes) raised `JSONDecodeError` —
  and `merge_scout.py --check` returned exit `1` (not `2`), so the orchestrator gate (which only
  rolls back on exit 2) let it through to `main()`, which had no `try/except`.
- Fix (defense-in-depth, three layers): `--check` now also asserts every candidate carries a
  non-empty `category`, and returns exit `2` for malformed JSON with `lineno`/`colno`/`msg` + a
  nearby byte window; `main()` wraps all `json.loads` (`--candidates` / `--scout` / `--clusters`)
  so a malformed input yields a structured stdout error + exit `1` with NO traceback, and
  `_normalize` now skips + warns on any category-less candidate (count surfaced as `skipped` in
  the success summary) — covering the `audit_found[]` path that bypasses `--check`.
  `discover_controls.form_clusters` is untouched (skipped candidates never reach it).
- The S3 / S4 / audit stage prompts now require a non-empty `category` on every candidate and a
  JSON-safe `evidence_snippet` (single line; `"` → `'`; strip `\`) — structurally incapable of
  breaking the enclosing JSON string. Covered by `tests/test_merge_scout.py`.

---

## [0.1.5] — 2026-07-07

### Fixed
- **`/mgh-init` fan-out checkpoints occasionally landed outside the project tree**
  (observed: a Windows drive root, e.g. `D:\xxx.json`). Root cause: the scout/T1/T3
  output paths were soft — placeholder templates / relative paths assembled twice (once
  by the orchestrator, once by the subagent); a misplaced subagent cwd resolved a
  relative path to the drive root. The enumeration scripts (`list_scout_batches.py` /
  `list_clusters.py` / `list_rule_jobs.py`) did not emit paths at all, so both agents
  had to assemble them.
- Fix: each enumerator now emits a **single authoritative absolute** `checkpoint_path`
  (scout/T1) / `rule_path` (T3) + `done_marker` per pending unit (via `Path.resolve()`).
  The orchestrator passes these **verbatim**; the stage prompts + double-shell agent
  defs treat them as **verbatim input fields** with a `NEVER`-boundary against
  self-assembly / invented filenames / relative paths / out-of-tree writes.
- **Defense-in-depth**: the `block-adhoc-scripts` PreToolUse hook (claude, `MGH_INIT_ACTIVE`
  run-domain) now also blocks `Write`/`Edit` whose resolved target is **outside the
  `MGH_TARGET` tree** (fail-loud, exit 2, recipe points at `list_*` stdout). `MGH_TARGET`
  is sourced from discover's absolute `repo` (via `describe_artifact --field repo`, never
  `py -c`); missing → degrade (pass). `--no-enforce-hook` opt-out unchanged; opencode
  (no PreToolUse) warns + skips.
- **AGENTS.md**: R5.3(b) extended (enumerators MUST emit exact absolute output paths);
  R5.5① gains a fan-out path recipe.
- New contract `core/contracts/init/cluster-enumeration.md` (T1 previously had no
  enumeration contract); `scout-enumeration.md` / `rule-jobs.md` gain the path fields.
- All additive: on-disk artifact schemas unchanged; no new runtime deps; no new CLI flags
  (`check_contracts` 0 violations). 181 tests pass.

### Upgrade
- Re-run `./install.sh --claude <target>` (or `--opencode`) to refresh the hook + shells
  + stage prompts. Existing checkpoints/rules are unaffected (schema unchanged).

---

## [0.1.1] — 2026-06-29

### Fixed
- **opencode agents failed validation on startup** with
  `Configuration is invalid ... invalid input: expected record, receiving string tools`.
  Cause: generated opencode agent frontmatter used `tools: read, glob, grep` (a
  string), but opencode's `tools` field is deprecated and expects a record.
  Fix: `tools` replaced by a `permission:` record (`read/glob/grep/list/bash/edit`
  → `allow|deny` derived from each agent's Claude tool set); the Claude-only
  `model: inherit` was removed (opencode markdown agents omit `model` to use the
  configured default). Verified all 8 agents parse as valid opencode frontmatter.

### Upgrade
- If you installed an earlier `0.1.0` with `--opencode`: re-run
  `bash install.sh --opencode .` (or the `.ps1`) in your project to
  overwrite the broken `.opencode/agent/sast-*.md` files, then restart opencode.

---

## [0.1.0] — 2026-06-29

Initial release.

### Added
- **9-stage SAST pipeline** as a native Claude Code / opencode command `/mgh-sast`
  (survey → threat-model → decompose → deep-dive → prefilter → verify → dedup →
  chain → SARIF). Zero runtime dependency on `vvaharness`.
- **Stage mapping** faithful to the original: LLM reasoning stages (s1/s2/s3/s4/s6/s8)
  run as subagents driven by skill lenses; deterministic stages (s5 prefilter,
  s7 dedup, s9 SARIF/CVSS/CWE) run as Python ≥3.10 stdlib scripts.
- **Verbatim prompt porting** from vvaharness via a stdlib `ast` extractor
  (`tools/extract_prompts.py`): stage system prompts, shared triage fragments,
  specialist lenses, threat baselines. s4 composed SYSTEM = 8,065 chars (matches
  the original). Provenance table in `core/docs/prompt-provenance.md`; Apache-2.0
  headers + `core/docs/NOTICE`.
- **Incremental scan** `--diff <ref>` — git-diff seed + call-chain expansion.
- **Scope scan** `--path <dir>` / `--package <pkg>` — directory/package seed +
  call-chain expansion.
- **Call-chain engine** (`core/scripts/expand_scope.py`): zero-dep text call graph
  (Java/Python/JS-TS/Go + generic), optional tree-sitter fallback, bidirectional
  BFS (default `both`/depth 2), Spring/Feign/AOP/DI framework allowlist.
- **Batch multi-repo** `--repo-file` (+ `--group-by-app`, `--keep-clones`,
  `--workspace`).
- **Dual-platform packaging**: platform-neutral shared `core/` + a Claude Code
  shell + an opencode shell. Installers `install.sh` / `install.ps1` with a
  zero-runtime-dependency self-check.
- **SARIF 2.1.0** output (`core/scripts/emit_sarif.py`) with a CVSS 3.1 base-score
  calculator (official roundup) + CWE mapping; severity always derived from the
  CVSS band and never disagrees with the score.
- **Unit tests** for the deterministic stages (`tests/test_deterministic.py`):
  9 tests covering prefilter gates, dedup merge, CVSS math, severity bands.
- **Distribution guide** (`docs/分发与使用指南.md`) for enterprise intranet rollout
  across Claude Code and opencode users.

### Known limitations
- Findings are **triage candidates, not confirmed vulnerabilities**; runs are
  non-deterministic.
- The call graph is **textual/AST-level**. It misses dynamic dispatch, reflection,
  DI, and framework routing (Spring `@*Mapping`, Feign, AOP, `@Autowired`,
  JPA/Spring Data). Framework-routed files unresolved against the seed are listed
  in `scope_manifest.unresolved[]` and the report for manual follow-up.

### Pending (not in this release)
- Live end-to-end scan against a real target repo.
- opencode live run + Claude↔opencode parity regression.
- Optional differential comparison vs upstream vvaharness output.
- `AGENTS_CN.md` / README pointer update to `/mgh-sast`.

---

## Versioning policy

- `0.x.y` — initial development; structural completeness, live verification in
  progress. Breaking changes may occur between `0.x` releases.
- `1.0.0` — first stable release once the *Pending* live-verification items close.
