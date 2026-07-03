---
description: Discover existing reusable security controls in a project (input-validation / data-masking / authentication / authorization / crypto / rate-limiting / csrf / audit-logging) and emit agent-consumable rules. Three-tier isolation-first pipeline (deterministic discover → T1 per-cluster induct → T2 synthesis → T3 per-category rules → T4 consistency). --format claude|opencode required (structures differ, never mix). Supports --scope/--resume/--merge and large-file sharding. Findings are LLM-induced candidates needing human review.
---

# /mgh-init — discover existing security controls → agent rules

> 编排器 = 你(宿主 agent):按本提示词,用自身工具(Bash / Agent / Read / Write / Edit)把流水线**跑出来**,而非写成代码——确定性逻辑已在 `discover_controls.py` / `chunk_sources.py` 里,直接 `Bash` 调用即可,无需 `Read` 其源码,也不要另写 `.py` 去包装或重实现。

You are the **orchestrator** of the mgh-init pipeline. Carry it out by running the
deterministic leaf scripts (Bash) and spawning stage subagents. Shared assets live
at `.opencode/mgh-core/` (mirrored from `core/`).

> **Output is LLM-induced, not confirmed. Controls are "existing", not "effective".**
> Human review required. State this in every summary.

## Parse arguments (validate BEFORE spending tokens)

- `--target <dir>` (default `.`)
- `--format opencode|claude` — **required** (mutex). Missing → error + STOP.
- `--out <path>` (opencode default `<target>/AGENTS.md`; claude default `<target>/.claude/rules`)
- `--scope path:<dir>|package:<pkg>|file:<glob>` + `--scope-mode defined|applicable` (default `defined`)
- `--language <lang>`, `--max-files <N>`, `--big-file-bytes <N>` (default 200KB), `--sample <N>` (default 8), `--progress-every <N>` (默认 1000), `--large-repo-threshold <N>` (默认 15000;超阈值则前置建议 `--scope`+`--merge`)
- `--resume` · `--rebuild-cache` · `--merge <partials-dir>` · `--skip-consistency` · `--config <profile>` (default `init`)

**No actionable args / `--help`** → print the flag table and STOP (zero tokens).

## Orchestration flow

```
0. parse + self-check(发现脚本统计源文件数,超 `--large-repo-threshold` 则建议 `--scope`+`--merge`;扫描期向 stderr 打印进度)
1. IF --merge: merge partial inventories by evidence anchor → STOP
2. i1 discover (Bash):
     py .opencode/mgh-core/scripts/discover_controls.py --repo <target> --out <target>/.mgh-init [--scope .. --max-files ..]
   → controls_candidates.json + clusters.json  (skip on --resume if present & not --rebuild-cache)
3. (optional) init-survey subagent → i1_enriched.json
   · **advisory + non-fatal**:产出仅作审计/T2 参考,**非 T1 输入**(T1 读 `clusters.json`);
     缺失 `i1_enriched.json` **不阻断**、不报致命错。`total` 过大(单 subagent 装不下整仓簇)
     时**跳过**,并在摘要披露。
4. T1 FAN-OUT — 经确定性脚本枚举(**禁手搓** `py -c` 内省;`clusters.json` 是包装字典
   `{repo,clusters[],truncated}`,对顶层 `len()` 得 3 **不是**簇数):
     py .opencode/mgh-core/scripts/list_clusters.py --clusters <target>/.mgh-init/clusters.json --checkpoints <target>/.mgh-init/checkpoints/t1
     → stdout `{repo,total,done,pending[],truncated}`;`total` = 真簇数(= discover stdout `clusters` 字段)
   per cluster in `pending[]`(NOT 顶层)→ (big file: chunk_sources slice first) spawn init-induct
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
| T1 enumerate | **script** | `core/scripts/list_clusters.py` (pending work-list;包 `clusters.json` 包装字典) |
| T1 induct | subagent `init-induct` (fan out per cluster) | `core/prompts/stages/init-induct.md` |
| T2 synthesis | subagent `init-synthesis` | `core/prompts/stages/init-synthesis.md` |
| T3 rulewriter | subagent `init-rulewriter` (fan out per category) | `core/prompts/stages/init-rulewriter.md` + `fragments/rules-format-{claude,opencode}.md` |
| T4 consistency | subagent `init-rules-consistency` (opt) | `core/prompts/stages/init-rules-consistency.md` |

### Deterministic invocation (Bash)

```bash
py .opencode/mgh-core/scripts/discover_controls.py --repo . --out ./.mgh-init
py .opencode/mgh-core/scripts/list_clusters.py --clusters ./.mgh-init/clusters.json --checkpoints ./.mgh-init/checkpoints/t1
py .opencode/mgh-core/scripts/chunk_sources.py --in <big_file> --big-file-bytes 204800 --line <L> --out ./.mgh-init/_slice.json
```

### Resume / cache
- Work units: i1 per file, T1 per cluster, T2/T4 whole, T3 per category.
- `<target>/.mgh-init/checkpoints/<tier>/<unit>.json.done` gates `--resume`.
- `--rebuild-cache` forces call-graph rebuild.

## Output (per `<target>/.mgh-init/`)

- `controls_candidates.json` · `clusters.json` · `controls_inventory.json` (vvah `design_controls`-compatible)
- `clusters.json` 包装结构 `{repo,clusters[],truncated}` 见 `core/contracts/init/clusters.md`(T1 经 `list_clusters.py` 枚举,禁手搓内省)
- `checkpoints/**` (resume) · `init_manifest.json` · `report.md` (+「competing controls」section)
- rules → `<target>/AGENTS.md` (opencode) **or** `<target>/.claude/rules/security-*.md` (claude)

## Always disclose
- 面向人读的非代码内容(`report.md`、`init_manifest.json` 的 `boundaries[]`/文案、rules 正文)
  用**简体中文**;锚点/路径/frontmatter 保持原样。

- LLM-induced candidates — human review required.
- **Existence ≠ effectiveness** (CVE-2025-41248).
- Call-graph textual/AST — misses AOP/reflection/DI/framework-routing; surface `unresolved[]`.
- ≥1.5M-line repos: prefer `--scope` per module + `--merge`.
