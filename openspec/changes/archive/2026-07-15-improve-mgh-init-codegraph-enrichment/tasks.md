## 1. Shared codegraph-hint fragment + stage prompt wiring

- [x] 1.1 Create `core/prompts/fragments/codegraph-hint.md`: prescriptive (`codegraph=on` → SHALL prefer MCP `codegraph_explore` / CLI `codegraph explore` fallback → Read only for uncovered items: non-indexed lang / >`--big-file-bytes` / index-missing / `⚠️ pending sync` banner files). 主谓非「you may」。Apache/rewrite provenance header per repo convention.
- [x] 1.2 `core/prompts/stages/init-scout.md`: add a `codegraph=on` stanza that references the fragment (Sanctioned-tools allowlist gains `codegraph_explore`/`codegraph explore` when signaled). Keep `codegraph=off` behavior byte-identical.
- [x] 1.3 `core/prompts/stages/init-induct.md`: same fragment reference + note blast-radius as advisory evidence for existence≠effectiveness (CVE-2025-41248).
- [x] 1.4 `core/prompts/stages/init-survey.md`: same fragment reference (advisory layer).

## 2. init-resolve stage (prompt + dual-shell subagent defs)

- [x] 2.1 Create `core/prompts/stages/init-resolve.md`: input = `unresolved[]` list (verbatim from orchestrator) + repo root + `checkpoint_path`/`done_marker` (absolute, verbatim); task = resolve via `codegraph_explore`/`callers` + framework routes, emit Candidate-subset anchors `source:"codegraph"` with resolved call path; hard rules (ground every anchor in codegraph-returned real `file:line`; unresolvable stays unresolved; precision over recall); Sanctioned-tools allowlist (codegraph MCP/CLI + Read fallback; NEVER `Write .py` / `py -c`); output = `resolved.json` at the given absolute path + touch `done_marker`.
- [x] 2.2 Create claude subagent def `releases/claude-code/agents/init-resolve.md` mirroring the stage prompt's Hard constraints (NEVER `Write .py`/`py -c`; checkpoint_path verbatim).
- [x] 2.3 Create opencode subagent def `releases/opencode/agent/init-resolve.md` (byte-parity with claude, opencode YAML frontmatter).
- [x] 2.4 Define `resolved.json` contract at `core/contracts/init/resolved.md` (fields: `repo`, `resolved[]{file,line,category,kind,anchor,shape,evidence_snippet,confidence,source:"codegraph",resolved_path[]}`, `unresolved_residual[]`).

## 3. Command shells (both claude + opencode) — detection, flow, flag, map, disclosure

- [x] 3.1 Add detection stanza to step 0 of both `mgh-init.md`: `test -d <target>/.codegraph && command -v codegraph` → `codegraph=on|off` signal; set BEFORE spending tokens; pass verbatim into subagent tasks.
- [x] 3.2 Add `--no-codegraph` to the Parse-arguments flag table of both shells (default `auto`; opt-out aligns with `--no-scout`). Document in `--help`/no-arg flag table print.
- [x] 3.3 Insert `init-resolve` stage into the Orchestration flow of both shells between scout-merge (step 3b) and T1 (step 4); mark optional + codegraph-gated + non-fatal + bounded (large unresolved → skip + disclose). Show the rigid triple `[controls_candidates.json::unresolved[]] → describe_artifact.py --field → init-resolve subagent → [resolved.json]`.
- [x] 3.4 Add `init-resolve` row to the Stage → component map of both shells (subagent `init-resolve` + `core/prompts/stages/init-resolve.md`).
- [x] 3.5 Add MGH_TARGET note: `init-resolve` writes `resolved.json` under `<target>/.mgh-init/` (covered by existing subtree guard; checkpoint path is absolute verbatim from orchestrator, never interpolated).

## 4. Contracts, manifest, report disclosure

- [x] 4.1 `core/contracts/init/candidates.md`: extend `source` enum doc to `regex | scout | codegraph`; note `codegraph` candidates are additive (from `init-resolve`), same purity rules.
- [x] 4.2 `init_manifest.json` schema/producer (i4 step): add `codegraph: {available, used, resolved_count, unresolved_residual}` block.
- [x] 4.3 `report.md` + `init_manifest.json::boundaries[]`: add codegraph disclosure (assisted? resolved N / residual M; codegraph static-analysis ceiling shrinks-not-zeros `unresolved[]`; resolved = LLM+codegraph candidates, human review). Keep existing 3 honesty boundaries intact.

## 5. Tests (deterministic regression — R5.8)

- [x] 5.1 Extend `tests/test_distributed_md_purity.py` to cover new shipped MD (`codegraph-hint.md`, `init-resolve.md`, both `init-resolve` agent defs, edited scout/induct/survey prompts, both shell stanzas): assert no dev-meta (R5.x/FDn/Dn/change-folder names/`承/兑现`/`范式锚点`/`本仓`) leaks; `codegraph` as operational external-tool reference is permitted.
- [x] 5.2 Add/extend a claude↔opencode parity test (`tests/test_mgh_init_codegraph_parity.py`): both shells declare `--no-codegraph`, both reference the codegraph-hint fragment, both declare `init-resolve` optional/codegraph-gated/non-fatal, both list `init-resolve` in the Stage→component map.
- [x] 5.3 `tests/test_zero_deps.py`: confirm no new `.py` added (this change adds zero `.py`); AST scan still clean; `codegraph` never imported.
- [x] 5.4 `tests/test_stage_check.py`: if it enumerates stage prompts, add `init-resolve.md` to the set; confirm its Sanctioned-tools + checkpoint_path-verbatim sections parse.

## 6. Evaluation (R5.7 TDD-for-docs — prompt change baseline)

- [ ] 6.1 Baseline: on a codegraph-indexed target repo (e.g. a Spring/Flask sample with known AOP/route-only controls), run `/mgh-init` ≥3× with `--no-codegraph`; capture scout token/round-trip counts + `unresolved[]` size (variance is the metric).
- [ ] 6.2 Blind A/B: same repo, `codegraph=on` vs `--no-codegraph`; assert (a) scout subagents actually issue `codegraph_explore` (not bypass to Read), (b) `resolved_count > 0` for framework-route/AOP controls, (c) token/round-trip delta on the large sample. Record pass-rate/tokens; new failure modes (e.g. subagent bypass) flow back into fragment wording (D4).
- [ ] 6.3 opencode parity check (resolves O1): confirm opencode subagent context can invoke `codegraph_explore` MCP; if not, confirm CLI `codegraph explore` Bash fallback works.

## 7. Version bumps, install self-check, validate

- [x] 7.1 Bump version markers in both `mgh-init.md` shells + any affected `core/prompts/**` headers (per R5.8).
- [x] 7.2 `install.sh` self-check: confirm new MD (fragment, resolve prompt, agent defs) mirrors into `.claude/mgh-core/` + `.opencode/`; fail-soft on missing files, CI must fail (R5.8).
- [x] 7.3 `openspec validate improve-mgh-init-codegraph-enrichment --strict` passes; `openspec status` shows all `applyRequires` artifacts done.
