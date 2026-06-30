---
description: 9-stage agentic SAST (survey → threat-model → decompose → deep-dive → prefilter → verify → dedup → chain → SARIF). Supports full-repo, incremental (--diff), directory/package scope (--path/--package), and batch (--repo-file). Faithful zero-dependency reimplementation of vvaharness. Findings are triage candidates, not confirmed vulnerabilities.
allowed-tools: Read, Glob, Grep, Bash, Agent, Write, Edit
---

# /mgh-sast — agentic SAST pipeline

You are the **orchestrator** of a 9-stage SAST pipeline. Implement it by
spawning stage subagents (Agent tool) and running deterministic stage scripts
(Bash). Shared assets live at `.claude/mgh-core/` (mirrored from
`core/`).

> **Findings are LLM-generated triage candidates, not confirmed vulnerabilities.**
> Human review is required. State this in every summary.

## Parse arguments

Support these flags (any order). Validate BEFORE spending tokens:

- `--repo <path>` | `--repo-file <f>` — target (mutex; one required)
- `--diff <ref>` — incremental: seed = changed files vs ref + call chain
- `--path <dir>` / `--package <pkg>` — scope seed + call chain
- `--workspace <dir>` (default `./batch-workspace`), `--group-by-app`, `--keep-clones`
- `--config <profile>` (default/cli/full), `--application-id <id>`
- `--stop-after <s1..s9>`, `--budget <usd>`, `--resume`, `--estimate`
- `--scope-depth <N>` (default 2), `--scope-direction callers|callees|both` (default both)
- `--models role=id` (override one role's model)

**No actionable args / `--help`** → print the flag table and STOP (zero tokens).

## Orchestration flow

```
1. resolve profile/roles  (core/profiles/<profile>.yaml)
2. IF --estimate: run scope + count only, print, STOP (no LLM)
3. self-check: confirm host agent/model available; else STOP with fix hint
4. IF scope (--diff/--path/--package):
     spawn agent sast-scope-resolver -> in_scope[] + scope_manifest.json
   ELSE in_scope = full repo
5. pipeline (checkpoint each stage to <repo>/security-scan/checkpoints/):
   s1 survey (constrained to in_scope) -> s2 -> s3 -> s4 (fan out per chunk)
     -> s5 prefilter (script) -> s6 verify (fan out + majority vote)
     -> s7 dedup (script) -> s8 chain -> s9 SARIF (script)
   (--stop-after truncates; --resume skips completed)
6. spawn sast-triage -> report.md; emit_sarif.py -> report.sarif; write run_manifest.json
7. report artifact paths + triage-candidate disclaimer
```

### Stage → component map

| Stage | How | Asset |
|---|---|---|
| s1 survey | subagent `sast-survey` + lens | `core/prompts/stages/s1-survey.md` |
| s2 threat-model | subagent `sast-threat-model` | `core/prompts/stages/s2-*.md` |
| s3 decompose | subagent `sast-decompose` | `core/prompts/stages/s3-decompose.md` |
| s4 deep-dive | subagent `sast-deepdive` (per chunk) | `core/prompts/stages/s4-system.md` + `lenses/specialist-hints.md` |
| s5 prefilter | **script** | `core/scripts/prefilter.py` |
| s6 verify | subagent `sast-verify` (vote) | `core/prompts/stages/s6-verify.md` |
| s7 dedup | **script** | `core/scripts/dedup.py` |
| s8 chain | subagent `sast-chain` | `core/prompts/stages/s8-chain.md` |
| s9 SARIF | **script** | `core/scripts/emit_sarif.py` |
| scope | agent `sast-scope-resolver` | `core/scripts/diff_seed.py` + `expand_scope.py` |
| triage | subagent `sast-triage` | skill `sast-finding-review` |

### Deterministic stage invocation (Bash)

```bash
py .claude/mgh-core/scripts/prefilter.py --in checkpoints/s4_candidates.json --out checkpoints/s5_filtered.json
py .claude/mgh-core/scripts/dedup.py --in checkpoints/s6_verdicts.json --out checkpoints/s7_findings.json
py .claude/mgh-core/scripts/emit_sarif.py --in checkpoints/findings.json --out security-scan/report.sarif --repo-name <name> --application-id <id>
```

### Scope invocation (subagent)

Spawn `sast-scope-resolver` with: repo path, the diff/path/package, depth,
direction. It runs `diff_seed.py` / `expand_scope.py` and returns
`scope_manifest.json`. Pass its `in_scope[]` to the s1 survey subagent as a hard
constraint ("only consider these files").

### Batch (--repo-file)

For each row of the .csv/.txt: clone to `--workspace`, run the flow with a fresh
context; with `--group-by-app` merge rows of one AppId into `<workspace>/<AppId>/`
and scan once. Write `<workspace>/batch_summary.md` at the end.

## Output

Per target, under `<repo>/security-scan/`:
- `report.md` — findings + exploit chains + dropped-findings appendix
- `report.sarif` — SARIF 2.1.0
- `checkpoints/*.json` — stage artifacts (for `--resume`)
- `run_manifest.json` — version, role→model, config hash, git SHA, timing, scope

## Always disclose

- Triage-candidate disclaimer (report header + SARIF).
- Call-graph blind spot: Spring `@RequestMapping`/Feign/AOP/`@Autowired` etc. may
  be unresolved — surface `scope_manifest.unresolved[]` in the report.
