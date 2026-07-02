---
description: Discover existing reusable security controls in a project (input-validation / data-masking / authentication / authorization / crypto / rate-limiting / csrf / audit-logging) and emit agent-consumable rules. Three-tier isolation-first pipeline (deterministic discover → T1 per-cluster induct → T2 synthesis → T3 per-category rules → T4 consistency). --format claude|opencode required (structures differ, never mix). Supports --scope/--resume/--merge and large-file sharding. Findings are LLM-induced candidates needing human review.
allowed-tools: Read, Glob, Grep, Bash, Agent, Write, Edit
---

# /mgh-init — discover existing security controls → agent rules

> 编排器 = 你(宿主 agent):按本提示词,用自身工具(Bash / Agent / Read / Write / Edit)把流水线**跑出来**,而非写成代码——确定性逻辑已在 `discover_controls.py` / `chunk_sources.py` 里,直接 `Bash` 调用即可,无需 `Read` 其源码,也不要另写 `.py` 去包装或重实现。

You are the **orchestrator** of the mgh-init pipeline. Carry it out by running the
deterministic leaf scripts (Bash) and spawning stage subagents (Agent). Shared assets
live at `.claude/mgh-core/` (mirrored from `core/`).

> **Output is LLM-induced, not confirmed. Controls are "existing", not "effective".**
> Human review required. State this in every summary.

## Parse arguments (validate BEFORE spending tokens)

- `--target <dir>` (default `.`)
- `--format opencode|claude` — **required** (mutex). Missing → error + STOP.
- `--out <path>` (claude default `<target>/.claude/rules`; opencode default `<target>/AGENTS.md`)
- `--scope path:<dir>|package:<pkg>|file:<glob>` + `--scope-mode defined|applicable` (default `defined`)
- `--language <lang>`, `--max-files <N>`, `--big-file-bytes <N>` (default 200KB), `--sample <N>` (default 8), `--progress-every <N>` (默认 1000), `--large-repo-threshold <N>` (默认 15000;超阈值则前置建议 `--scope`+`--merge`)
- `--resume` (skip units whose `.done` exists) · `--rebuild-cache` (rebuild call graph)
- `--merge <partials-dir>` (merge multiple scoped runs; then STOP)
- `--skip-consistency` (skip T4) · `--config <profile>` (default `init`)

**No actionable args / `--help`** → print the flag table and STOP (zero tokens).

## Orchestration flow

```
0. parse + self-check (host agent/model available; else STOP with fix hint;发现脚本统计源文件数,超 `--large-repo-threshold` 则建议 `--scope`+`--merge`,扫描期向 stderr 打印进度)
1. IF --merge: merge partial inventories by evidence anchor → STOP
2. i1 discover (Bash, deterministic, streaming):
     py .claude/mgh-core/scripts/discover_controls.py --repo <target> --out <target>/.mgh-init
        [--scope .. --scope-mode .. --language .. --max-files .. --big-file-bytes .. --sample ..]
   → controls_candidates.json + clusters.json  (skip on --resume if present & not --rebuild-cache)
3. (optional) init-survey subagent → i1_enriched.json
4. T1 FAN-OUT: for each cluster in clusters.json WITHOUT a .done:
     - if any evidence_file is big (> --big-file-bytes): run chunk_sources.py to get slices
     - spawn init-induct (one isolated context per cluster) with the cluster record (+ slices)
     → checkpoints/t1/<cluster_id>.json + .done
5. T2: spawn init-synthesis (sees all T1 records, no raw code)
     → controls_inventory.json + checkpoints/t2/.done
6. T3 FAN-OUT: for each category in the inventory WITHOUT a .done:
     - spawn init-rulewriter (one isolated context per category) with --format
     → rules (claude: .claude/rules/security-<cat>.md ; opencode: AGENTS.md managed block)
       + checkpoints/t3/<cat>.<format>.json.done
7. T4 (unless --skip-consistency): spawn init-rules-consistency
     → in-place edits within managed blocks + checkpoints/t4/.done
8. i4: write init_manifest.json + report.md; print artifact paths + disclaimers
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
py .claude/mgh-core/scripts/discover_controls.py --repo . --out ./.mgh-init
py .claude/mgh-core/scripts/chunk_sources.py --in <big_file> --big-file-bytes 204800 --line <L> --out ./.mgh-init/_slice.json
```

### Resume / cache
- Work units (D9 = isolation unit): i1 per file, T1 per cluster, T2/T4 whole, T3 per category.
- `<target>/.mgh-init/checkpoints/<tier>/<unit>.json.done` gates `--resume`.
- Call graph is rebuilt by discover each run; pass `--rebuild-cache` to force (mtime-based skip otherwise).

## Output (per `<target>/.mgh-init/`)

- `controls_candidates.json` — raw deterministic hits (audit trail)
- `clusters.json` — T1 isolation units (centralized/distributed)
- `controls_inventory.json` — structured (vvah `design_controls`-compatible); downstream input for `/mgh-sra`, `/mgh-blst`, future mgh-sast control intake
- `checkpoints/**` — per-unit artifacts (resume)
- `init_manifest.json` — version/format/counts/provenance/unresolved[]/out_of_scope[]/boundaries[]
- `report.md` — human-readable summary (+「competing controls」section)
- rules → `<target>/.claude/rules/security-*.md` (claude) **or** `<target>/AGENTS.md` (opencode)

## Always disclose
- 面向人读的非代码内容(`report.md`、`init_manifest.json` 的 `boundaries[]`/文案、rules 正文)
  用**简体中文**;锚点/路径/frontmatter 保持原样。

- LLM-induced candidates — human review required.
- **Existence ≠ effectiveness** (CVE-2025-41248: `@PreAuthorize` bypass on parameterized types).
- Call-graph is textual/AST-level — misses AOP/reflection/DI/framework-routing; surface `unresolved[]`.
- For ≥1.5M-line repos: prefer `--scope` per module + `--merge` over a single full-repo run.
