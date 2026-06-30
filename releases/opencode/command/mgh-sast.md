---
description: 9-stage agentic SAST (survey → threat-model → decompose → deep-dive → prefilter → verify → dedup → chain → SARIF). Full-repo, incremental (--diff), directory/package scope (--path/--package), batch (--repo-file). Faithful zero-dependency reimplementation of vvaharness. Findings are triage candidates, not confirmed vulnerabilities.
---

# /mgh-sast — agentic SAST pipeline (opencode)

You are the **orchestrator** of a 9-stage SAST pipeline. Spawn stage agents
(opencode subagents) and run deterministic stage scripts (bash). Shared assets
live at `.opencode/mgh-core/` (mirrored from `core/`).

> **Findings are LLM-generated triage candidates, not confirmed vulnerabilities.**
> Human review required. State this in every summary.

## Parse arguments (validate BEFORE spending tokens)

- `--repo <path>` | `--repo-file <f>` (mutex; one required)
- `--diff <ref>` · `--path <dir>` · `--package <pkg>` (scope; combinable)
- `--workspace <dir>` (default `./batch-workspace`), `--group-by-app`, `--keep-clones`
- `--config <profile>` (default/cli/full), `--application-id <id>`
- `--stop-after <s1..s9>`, `--budget <usd>`, `--resume`, `--estimate`
- `--scope-depth <N>` (default 2), `--scope-direction callers|callees|both` (default both)
- `--models role=id`

No actionable args / `--help` → print flag table, STOP (zero tokens).

## Flow
```
1. resolve profile/roles  (.opencode/mgh-core/profiles/<profile>.yaml)
2. IF --estimate: scope + count only, print, STOP
3. self-check host agent/model; else STOP with fix hint
4. IF scope: spawn agent sast-scope-resolver -> in_scope[] + scope_manifest.json
5. pipeline (checkpoint to <repo>/security-scan/checkpoints/):
   s1 survey(constrained to in_scope) -> s2 -> s3 -> s4(per chunk) -> s5(prefilter.sh)
     -> s6(verify, vote) -> s7(dedup.sh) -> s8(chain) -> s9(sarif.sh)
   (--stop-after truncates; --resume skips completed)
6. spawn sast-triage -> report.md; emit_sarif.py -> report.sarif; write run_manifest.json
7. report paths + triage-candidate disclaimer
```

## Stage → asset (prompts are path-referenced from .opencode/mgh-core/prompts/)
s1 `prompts/stages/s1-survey.md` · s2 `prompts/stages/s2-*.md` · s3 `prompts/stages/s3-decompose.md`
s4 `prompts/stages/s4-system.md` + `prompts/lenses/specialist-hints.md`
s6 `prompts/stages/s6-verify.md` · s8 `prompts/stages/s8-chain.md`
s5/s7/s9 scripts: `scripts/{prefilter,dedup,emit_sarif}.py` via bash.

## Deterministic invocation (bash)
```bash
py .opencode/mgh-core/scripts/prefilter.py --in checkpoints/s4_candidates.json --out checkpoints/s5_filtered.json
py .opencode/mgh-core/scripts/dedup.py --in checkpoints/s6_verdicts.json --out checkpoints/s7_findings.json
py .opencode/mgh-core/scripts/emit_sarif.py --in checkpoints/findings.json --out security-scan/report.sarif --repo-name <name> --application-id <id>
```

## Always disclose
Triage-candidate disclaimer + call-graph blind spot (Spring `@*Mapping`/Feign/
AOP/`@Autowired` in `scope_manifest.unresolved[]`).
