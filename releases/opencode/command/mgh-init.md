---
description: Discover existing reusable security controls in a project (input-validation / data-masking / authentication / authorization / crypto / rate-limiting / csrf / audit-logging) and emit agent-consumable rules. Three-tier isolation-first pipeline (deterministic discover → T1 per-cluster induct → T2 synthesis → T3 per-category rules → T4 consistency). --format claude|opencode required (structures differ, never mix). Supports --scope/--resume/--merge and large-file sharding. Findings are LLM-induced candidates needing human review.
---

# /mgh-init — discover existing security controls → agent rules

> 编排器 = 你(宿主 agent):按本提示词,用自身工具(Bash / Agent / Read / Write / Edit)把流水线**跑出来**,而非写成代码——确定性逻辑已在 `discover_controls.py` / `chunk_sources.py` / `plan_scout.py` / `merge_scout.py` / `assemble_rules.py` 里,直接 `Bash` 调用即可,无需 `Read` 其源码,也不要另写 `.py` 去包装或重实现。opencode 下 T3 每 category 写**暂存 fragment**(`.mgh-init/rules-parts/<cat>.md`),由 `assemble_rules.py` 装配进 `AGENTS.md` 单个中性受管块(见步骤 6b)。

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
- `--no-scout` (skip LLM scout discovery; legacy regex-only) · `--scout-budget <N>` (0=全量) · `--scout-batch-bytes <N>` (默认 96KB) · `--scout-batch-cap <N>` (默认 40) · `--scout-audit-pct <N>` (默认 15)

**No actionable args / `--help`** → print the flag table and STOP (zero tokens).

## Orchestration flow

```
0. parse + self-check(发现脚本统计源文件数,超 `--large-repo-threshold` 则建议 `--scope`+`--merge`;扫描期向 stderr 打印进度)
1. IF --merge: merge partial inventories by evidence anchor → STOP
2. i1 discover (Bash):
     py .opencode/mgh-core/scripts/discover_controls.py --repo <target> --out <target>/.mgh-init [--scope .. --max-files ..]
   → controls_candidates.json (regex, `source:regex`) + clusters.json + skeleton.json  (skip on --resume if present & not --rebuild-cache)
3. (optional) init-survey subagent → i1_enriched.json
   · **advisory + non-fatal**:产出仅作审计/T2 参考,**非 T1 输入**(T1 读 `clusters.json`);
     缺失 `i1_enriched.json` **不阻断**、不报致命错。`total` 过大(单 subagent 装不下整仓簇)
     时**跳过**,并在摘要披露。
3b. SCOUT FAN-OUT (除非 `--no-scout`)——让 LLM 找出 regex 闸门漏掉的自研控制:
     py .opencode/mgh-core/scripts/plan_scout.py --skeleton <target>/.mgh-init/skeleton.json \
        --candidates <target>/.mgh-init/controls_candidates.json --out <target>/.mgh-init/scout_plan.json \
        [--batch-bytes .. --batch-cap .. --budget ..]
     · 批数涌现 = ceil(Σtarget_bytes / --scout-batch-bytes);按包内聚切批,每批字节≤预算且文件数≤cap。
     for each batch in scout_plan.json(并行 ≤ max_concurrent,**每批一个隔离 subagent 上下文**):
       - if batch.needs_slice:先 `chunk_sources.py` 切片(**绝不**整文件喂 LLM)
       - spawn init-scout({batch, repo root, regex_known[]}) → checkpoints/scout/<batch_id>.json + .done
     spawn init-scout-merge(只见全部 scout 批记录,无原始码)→ scout_candidates.json + checkpoints/scout/merge.json.done
     spawn init-scout-audit(随机 ≈--scout-audit-pct 的 scout 拒绝项)→ checkpoints/scout/audit.json + .done
     py .opencode/mgh-core/scripts/merge_scout.py --candidates <target>/.mgh-init/controls_candidates.json \
        --scout <target>/.mgh-init/scout_candidates.json --audit <target>/.mgh-init/checkpoints/scout/audit.json \
        --clusters <target>/.mgh-init/clusters.json
     · 候选集并入 `source:"scout"`;clusters.json **追加** scout 簇(regex 簇与其 usage_sites 不变)。复用 `discover_controls.form_clusters`,无逻辑漂移。
4. T1 FAN-OUT — 经确定性脚本枚举(**禁手搓** `py -c` 内省;`clusters.json` 是包装字典
   `{repo,clusters[],truncated}`,对顶层 `len()` 得 3 **不是**簇数):
     py .opencode/mgh-core/scripts/list_clusters.py --clusters <target>/.mgh-init/clusters.json --checkpoints <target>/.mgh-init/checkpoints/t1
     → stdout `{repo,total,done,pending[],truncated}`;`total` = 真簇数(= discover stdout `clusters` 字段)
   per cluster in `pending[]`(NOT 顶层)→ (big file: chunk_sources slice first) spawn init-induct
   → checkpoints/t1/<cluster_id>.json + .done
5. T2: init-synthesis (all T1 records, no raw code) → controls_inventory.json
6. T3 FAN-OUT: per category without .done → spawn init-rulewriter with --format
   → claude: `.claude/rules/security-<cat>.md`;opencode: **暂存 fragment** `.mgh-init/rules-parts/<cat>.md`(中性、无哨兵,**禁**直写 `AGENTS.md`)
   + checkpoints/t3/<cat>.<format>.json.done
6b. (opencode only) ASSEMBLE + LINT (Bash, deterministic):
     py .opencode/mgh-core/scripts/assemble_rules.py --target <target> --format opencode
   → 合并全部 fragment 进 `<target>/AGENTS.md` 单个 `<!-- security-controls:begin --> … :end -->`
     受管块(幂等替换、保留用户内容、迁移旧 `mgh-init:` 块);命中禁用 token 则 fail-loud(退出码 2)
   · lint 失败 = 规则正文泄漏了工具内部信息;回到 T3 修正该 category fragment 后重跑 6b
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
| T3 assemble (opencode) | **script** | `core/scripts/assemble_rules.py` (single neutral block + legacy migration + `--check` purity lint) |
| T4 consistency | subagent `init-rules-consistency` (opt) | `core/prompts/stages/init-rules-consistency.md` |
| scout plan | **script** | `core/scripts/plan_scout.py` (byte-budget + pkg-co-located batches) |
| scout reader | subagent `init-scout` (fan out per batch) | `core/prompts/stages/init-scout.md` |
| scout merge | subagent `init-scout-merge` | `core/prompts/stages/init-scout-merge.md` |
| scout audit | subagent `init-scout-audit` (opt) | `core/prompts/stages/init-scout-audit.md` |
| scout fold-in | **script** | `core/scripts/merge_scout.py` (reuses `discover_controls.form_clusters`) |

### Deterministic invocation (Bash)

```bash
py .opencode/mgh-core/scripts/discover_controls.py --repo . --out ./.mgh-init
py .opencode/mgh-core/scripts/list_clusters.py --clusters ./.mgh-init/clusters.json --checkpoints ./.mgh-init/checkpoints/t1
py .opencode/mgh-core/scripts/chunk_sources.py --in <big_file> --big-file-bytes 204800 --line <L> --out ./.mgh-init/_slice.json
py .opencode/mgh-core/scripts/plan_scout.py --skeleton ./.mgh-init/skeleton.json --candidates ./.mgh-init/controls_candidates.json --out ./.mgh-init/scout_plan.json --batch-bytes 98304 --batch-cap 40
py .opencode/mgh-core/scripts/merge_scout.py --candidates ./.mgh-init/controls_candidates.json --scout ./.mgh-init/scout_candidates.json --audit ./.mgh-init/checkpoints/scout/audit.json --clusters ./.mgh-init/clusters.json
py .opencode/mgh-core/scripts/assemble_rules.py --target . --format opencode
```

### Resume / cache
- Work units: i1 per file, **scout per batch**, T1 per cluster, T2/T4 whole, T3 per category.
- `<target>/.mgh-init/checkpoints/<tier>/<unit>.json.done` gates `--resume`.
- `--rebuild-cache` forces call-graph rebuild.

## Output (per `<target>/.mgh-init/`)

- `controls_candidates.json`(regex + scout,带 `source`)· `skeleton.json` · `scout_plan.json` · `scout_candidates.json` · `clusters.json` · `controls_inventory.json` (vvah `design_controls`-compatible)
- `clusters.json` 包装结构 `{repo,clusters[],truncated}` 见 `core/contracts/init/clusters.md`(T1 经 `list_clusters.py` 枚举,禁手搓内省)
- `checkpoints/**` (resume) · `init_manifest.json` · `report.md` (+「competing controls」section)
- rules → opencode:`<target>/AGENTS.md` 单个中性受管块 `<!-- security-controls:begin --> … :end -->`(由 `assemble_rules.py` 从 `.mgh-init/rules-parts/*.md` 装配);claude:`<target>/.claude/rules/security-*.md`

## Always disclose
- 面向人读的非代码内容(`report.md`、`init_manifest.json` 的 `boundaries[]`/文案、rules 正文)
  用**简体中文**;锚点/路径/frontmatter 保持原样。

- LLM-induced candidates — human review required.
- **Existence ≠ effectiveness** (CVE-2025-41248).
- Call-graph textual/AST — misses AOP/reflection/DI/framework-routing; surface `unresolved[]`.
- ≥1.5M-line repos: prefer `--scope` per module + `--merge`.
- **Scout coverage is partial, not whole-repo**:`init_manifest.json` 记 `scout.{skeleton_total, scout_targets, batches, deep_read_files, audit_sampled, audit_found}`;只声称真实数字,**不声称全仓覆盖**。Scout 非确定(簇数 run-to-run 可能变化);残留盲区:泛型包+泛型类名+无安全导入+低扇因控制可能漏(`--no-scout` 回退纯 regex)。
