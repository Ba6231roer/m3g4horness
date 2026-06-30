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
