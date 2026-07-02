---
description: Discover existing reusable security controls in a project (input-validation / data-masking / authentication / authorization / crypto / rate-limiting / csrf / audit-logging) and emit agent-consumable rules. Three-tier isolation-first pipeline (deterministic discover → T1 per-cluster induct → T2 synthesis → T3 per-category rules → T4 consistency). --format claude|opencode required (structures differ, never mix). Supports --scope/--resume/--merge and large-file sharding. Findings are LLM-induced candidates needing human review.
---

# /mgh-init — discover existing security controls → agent rules

You are the **orchestrator** of the mgh-init pipeline. Implement it by running
deterministic scripts (Bash) and spawning stage subagents. Shared assets live at
`.opencode/mgh-core/` (mirrored from `core/`).

> **Output is LLM-induced, not confirmed. Controls are "existing", not "effective".**
> Human review required. State this in every summary.

## Parse arguments (validate BEFORE spending tokens)

- `--target <dir>` (default `.`)
- `--format opencode|claude` — **required** (mutex). Missing → error + STOP.
- `--out <path>` (opencode default `<target>/AGENTS.md`; claude default `<target>/.claude/rules`)
- `--scope path:<dir>|package:<pkg>|file:<glob>` + `--scope-mode defined|applicable` (default `defined`)
- `--language <lang>`, `--max-files <N>`, `--big-file-bytes <N>` (default 200KB), `--sample <N>` (default 8)
- `--resume` · `--rebuild-cache` · `--merge <partials-dir>` · `--skip-consistency` · `--config <profile>` (default `init`)

**No actionable args / `--help`** → print the flag table and STOP (zero tokens).

## Orchestration flow

```
0. parse + self-check
1. IF --merge: merge partial inventories by evidence anchor → STOP
2. i1 discover (Bash):
     py .opencode/mgh-core/scripts/discover_controls.py --repo <target> --out <target>/.mgh-init [--scope .. --format opencode]
   → controls_candidates.json + clusters.json  (skip on --resume if present & not --rebuild-cache)
3. (optional) init-survey subagent → i1_enriched.json
4. T1 FAN-OUT: per cluster without .done → (big file: chunk_sources slice first) spawn init-induct
   → checkpoints/t1/<cluster_id>.json + .done
5. T2: init-synthesis (all T1 records, no raw code) → controls_inventory.json
6. T3 FAN-OUT: per category without .done → spawn init-rulewriter with --format
   → rules + checkpoints/t3/<cat>.<format>.json.done
7. T4 (unless --skip-consistency): init-rules-consistency
8. i4: init_manifest.json + report.md; print artifact paths + disclaimers
```

### Stage → component map

| Stage | How | Asset |
|---|---|---|
| i1 discover | **script** | `core/scripts/discover_controls.py` (+ `expand_scope.py` reuse) |
| i1 big-file slice | **script** | `core/scripts/chunk_sources.py` |
| i1 survey (opt) | subagent `init-survey` | `core/prompts/stages/init-survey.md` |
| T1 induct | subagent `init-induct` (fan out per cluster) | `core/prompts/stages/init-induct.md` |
| T2 synthesis | subagent `init-synthesis` | `core/prompts/stages/init-synthesis.md` |
| T3 rulewriter | subagent `init-rulewriter` (fan out per category) | `core/prompts/stages/init-rulewriter.md` + `fragments/rules-format-{claude,opencode}.md` |
| T4 consistency | subagent `init-rules-consistency` (opt) | `core/prompts/stages/init-rules-consistency.md` |

### Deterministic invocation (Bash)

```bash
py .opencode/mgh-core/scripts/discover_controls.py --repo . --out ./.mgh-init --format opencode
py .opencode/mgh-core/scripts/chunk_sources.py --in <big_file> --big-file-bytes 204800 --line <L> --out ./.mgh-init/_slice.json
```

### Resume / cache
- Work units: i1 per file, T1 per cluster, T2/T4 whole, T3 per category.
- `<target>/.mgh-init/checkpoints/<tier>/<unit>.json.done` gates `--resume`.
- `--rebuild-cache` forces call-graph rebuild.

## Output (per `<target>/.mgh-init/`)

- `controls_candidates.json` · `clusters.json` · `controls_inventory.json` (vvah `design_controls`-compatible)
- `checkpoints/**` (resume) · `init_manifest.json` · `report.md` (+「competing controls」section)
- rules → `<target>/AGENTS.md` (opencode) **or** `<target>/.claude/rules/security-*.md` (claude)

## Always disclose
- 面向人读的非代码内容(`report.md`、`init_manifest.json` 的 `boundaries[]`/文案、rules 正文)
  用**简体中文**;锚点/路径/frontmatter 保持原样。

- LLM-induced candidates — human review required.
- **Existence ≠ effectiveness** (CVE-2025-41248).
- Call-graph textual/AST — misses AOP/reflection/DI/framework-routing; surface `unresolved[]`.
- ≥1.5M-line repos: prefer `--scope` per module + `--merge`.
