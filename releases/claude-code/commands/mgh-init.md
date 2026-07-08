---
description: Discover existing reusable security controls in a project (input-validation / data-masking / authentication / authorization / crypto / rate-limiting / csrf / audit-logging) and emit agent-consumable rules. Three-tier isolation-first pipeline (deterministic discover → T1 per-cluster induct → T2 synthesis → T3 per-category rules → T4 consistency). --format claude|opencode required (structures differ, never mix). Supports --scope/--resume/--merge and large-file sharding. Findings are LLM-induced candidates needing human review.
allowed-tools: Read, Glob, Grep, Bash, Agent, Write, Edit
---

# /mgh-init — discover existing security controls → agent rules

> 编排器 = 你(宿主 agent):按本提示词,用自身工具(Bash / Agent / Read / Write / Edit)把流水线**跑出来**,而非写成代码——确定性逻辑已在 `discover_controls.py` / `chunk_sources.py` / `plan_scout.py` / `merge_scout.py` / `assemble_rules.py` 里,直接 `Bash` 调用即可,无需 `Read` 其源码,也不要另写 `.py` 去包装或重实现。claude 下 T3 直写 `.claude/rules/security-<cat>.md`,由 `assemble_rules.py --format claude --check` 做纯净性 lint(见步骤 6b)。

> **运行域 + hook**:`install.sh` 向本仓 `.claude/settings.json` 注入 PreToolUse
> hook(`block-adhoc-scripts`),在 `/mgh-init` 运行域内拦 `py -c`/`python -c` 内省、越权
> `Write *.py`、**以及 resolved 目标不在 `MGH_TARGET` 子树内的 `Write`/`Edit`**(子树外写入,
> 如盘符根;命中退出码 2 + stderr recipe 指向 `list_*` stdout 的 `checkpoint_path`)。编排器**起步先**
> `Bash: export MGH_INIT_ACTIVE=1` 标记运行域,并在 discover 后 `export MGH_TARGET=<绝对 repo>`(供 hook
> 判树;缺失则该条降级放行)。opt-out = `install.sh --no-enforce-hook`(纪律仍由下方铁律 + 边界校验兜底)。

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
- `--no-scout` (skip LLM scout discovery; legacy regex-only behavior) · `--scout-budget <N>` (0=全量目标) · `--scout-batch-bytes <N>` (默认 96KB) · `--scout-batch-cap <N>` (默认 40) · `--scout-audit-pct <N>` (默认 15)

**No actionable args / `--help`** → print the flag table and STOP (zero tokens).

## Orchestrator discipline(铁律)

编排器 = 宿主 agent,**不写代码**。确定性叶脚本经 `Bash` 执行;**NEVER `Read` 叶子 `.py` 源码进上下文**(报错看 stderr,不读源码)。

**硬边界(`NEVER`)**:(a) `Write` 任何 `.py`——大编排器(`mgh_init.py`)**或**一次性微脚本(`py -c` 产物、`_prep_scout_batches.py`、`_aggregate_scout.py`、`<run>_helper.py`);(b) `Bash: py -c|python -c` 去内省/重派生产物(`import json` / `open(` / `load(` 读 `.mgh-init/**`);(c) `Read` 叶子 `.py` 源码。

**implementation-intention(需 X → 触发器 Y,NEVER `py -c`)**——每个常被手搓的需求都有合法出口:
- **工作清单** → `list_clusters.py`(T1)/ `list_scout_batches.py`(scout)/ `list_rule_jobs.py`(T3);
- **某 fan-out 单元的输出路径** → `list_*` stdout `pending[]` 每项的 `checkpoint_path`(scout/T1)/ `rule_path`(T3)+ `done_marker`(均**绝对**);**NEVER** 自拼 `<target>/<id>`、**NEVER** `py -c` 算路径、**NEVER** 相对路径;
- **瞄一眼结构** → `describe_artifact.py --keys/--sample/--shape/--field`(**NEVER** `py -c`、**NEVER** `Read` 整份大 JSON);
- **派生量** → 该量产出者的 stdout 字段(`discover` stdout `big_files`/`unresolved_count`;`plan_scout` stdout/`scout_plan.json` `regex_known_count`);**NEVER** 自写脚本算。

**fan-out 刚性三元组**:每个 fan-out 步骤表述为 `[输入产物::字段] → script/subagent → [输出产物::字段]`;输出路径 = `list_*` stdout 的 `checkpoint_path`/`rule_path`(绝对),编排器**逐字透传**进 subagent task、subagent **恰好写该绝对路径**(零拼装、零占位符)。doubt 时刻 inline 1 行 shape(如「`scout_plan.json::batches[]` 即你的工作清单,经 `list_scout_batches.py` 取;每项 `checkpoint_path` 即该批产物绝对路径」)。

**终态声明**:`merge_scout.py`/foldin 完成后,`scout_candidates.json` / `controls_candidates.json` / `clusters.json` 为**终态**——不再二次聚合 / 重切批(不出现 `_aggregate_scout.py` 之类重实现)。

**边界校验**:每个 stage 产物跑完执行 `<producer> --check`(或独立 `validate_inventory.py`);失败(退出码 2)→ 回退重跑该步,**不带着破损产物继续**。

## Orchestration flow

```
0. parse + self-check (host agent/model available; else STOP with fix hint;发现脚本统计源文件数,超 `--large-repo-threshold` 则建议 `--scope`+`--merge`,扫描期向 stderr 打印进度)
   · **起步**:`Bash: export MGH_INIT_ACTIVE=1`(声明运行域,激活 PreToolUse hook,含子树外 Write/Edit 拦截)
   · **MGH_TARGET**(供 hook 判树):discover(step 2)写出的 `controls_candidates.json::repo` 即**绝对项目根**;编排器**逐字读**该字段并 `export MGH_TARGET=<repo>`,在 fan-out 前设置。取值经 `describe_artifact.py --field repo`(合法瞄结构出口),**NEVER** `py -c` 自算、**NEVER** 用裸 `.` 相对。hook 在 `MGH_TARGET` 缺失时该条**降级放行**(不阻断)。
1. IF --merge: merge partial inventories by evidence anchor → STOP
2. i1 discover (Bash, deterministic, streaming):
     py .claude/mgh-core/scripts/discover_controls.py --repo <target> --out <target>/.mgh-init
        [--scope .. --scope-mode .. --language .. --max-files .. --big-file-bytes .. --sample ..]
   → controls_candidates.json (regex, `source:regex`) + clusters.json + skeleton.json  (skip on --resume if present & not --rebuild-cache)
   · 派生量直读 discover stdout:`candidates/clusters/unresolved_count/big_files`(NEVER `py -c` 自算)
   · **MGH_TARGET**:discover 后取其产物 `repo` 字段(绝对根)——
     `py .claude/mgh-core/scripts/describe_artifact.py --in <target>/.mgh-init/controls_candidates.json --field repo`
     → stdout `{"value":"<绝对 target>"}`;`export MGH_TARGET=<该 value>`(供 hook 判树;NEVER `py -c` 自算)。
   · 校验:`py .claude/mgh-core/scripts/discover_controls.py --check <target>/.mgh-init`(wrapper + 每条 `source` + cluster_id 唯一;退出码 2 → 回退重跑)
3. (optional) init-survey subagent → i1_enriched.json
   · **advisory + non-fatal**:产出仅作审计/T2 参考,**非 T1 输入**(T1 读 `clusters.json`);
     缺失 `i1_enriched.json` **不阻断**、不报致命错。`total` 过大(单 subagent 装不下整仓簇)
     时**跳过**,并在摘要披露。
3b. SCOUT FAN-OUT (除非 `--no-scout`)——让 LLM 找出 regex 闸门漏掉的自研控制:
     [skeleton.json + controls_candidates.json] → plan_scout.py → [scout_plan.json::batches[]]
     py .claude/mgh-core/scripts/plan_scout.py --skeleton <target>/.mgh-init/skeleton.json \
        --candidates <target>/.mgh-init/controls_candidates.json --out <target>/.mgh-init/scout_plan.json \
        [--batch-bytes .. --batch-cap .. --budget ..]
     · 批数涌现 = ceil(Σtarget_bytes / --scout-batch-bytes);按包内聚切批,每批字节≤预算且文件数≤cap。派生量 `regex_known_count` 在 stdout / `scout_plan.json` 顶层(NEVER 自算)。
     · 校验:`py .claude/mgh-core/scripts/plan_scout.py --check <target>/.mgh-init/scout_plan.json`(batches 非空除非 0 target、每批 bytes≤预算、needs_slice 仅含超批文件;退出码 2 → 回退)。
     [scout_plan.json::batches[]] → list_scout_batches.py → [stdout pending[](每项含**绝对** `checkpoint_path`/`done_marker`)](禁手挖 `scout_plan` / `py -c`)
     py .claude/mgh-core/scripts/list_scout_batches.py --scout-plan <target>/.mgh-init/scout_plan.json --checkpoints <target>/.mgh-init/checkpoints/scout
     per batch in `pending[]`(并行 ≤ max_concurrent,**每批一个隔离 subagent 上下文**;`--resume` 跳过已 `.done`):
       - if batch.needs_slice:先 `chunk_sources.py` 切片(**绝不**整文件喂 LLM)
       - spawn init-scout({batch, repo root, regex_known[], checkpoint_path, done_marker}) → 恰好写 `checkpoint_path`(绝对) + touch `done_marker`
     spawn init-scout-merge(只见全部 scout 批记录,无原始码)→ scout_candidates.json + checkpoints/scout/merge.json.done
     · 校验:`py .claude/mgh-core/scripts/merge_scout.py --check <target>/.mgh-init/scout_candidates.json`(每条 `source:"scout"` + file:line;退出码 2 → 回退)。
     spawn init-scout-audit(随机 ≈--scout-audit-pct 的 scout 拒绝项)→ checkpoints/scout/audit.json + .done
     py .claude/mgh-core/scripts/merge_scout.py --candidates <target>/.mgh-init/controls_candidates.json \
        --scout <target>/.mgh-init/scout_candidates.json --audit <target>/.mgh-init/checkpoints/scout/audit.json \
        --clusters <target>/.mgh-init/clusters.json
     · 候选集并入 `source:"scout"`;clusters.json **追加** scout 簇(regex 簇与其 usage_sites 不变)。复用 `discover_controls.form_clusters`,无逻辑漂移。
     · **终态**:`scout_candidates.json` / `controls_candidates.json` / `clusters.json` 此时为终态——不再二次聚合 / 重切批(NEVER `_aggregate_scout.py`)。
4. T1 FAN-OUT — 经确定性脚本枚举(**禁手搓** `py -c` 内省;`clusters.json` 是包装字典
   `{repo,clusters[],truncated}`,对顶层 `len()` 得 3 **不是**簇数):
   [clusters.json::clusters[]] → list_clusters.py → [stdout pending[](每项含**绝对** `checkpoint_path`/`done_marker`)]
     py .claude/mgh-core/scripts/list_clusters.py --clusters <target>/.mgh-init/clusters.json --checkpoints <target>/.mgh-init/checkpoints/t1
     → stdout `{repo,total,done,pending[],truncated}`;`total` = 真簇数(= discover stdout `clusters` 字段)
   for each cluster in `pending[]`(NOT in `clusters.json` 顶层;`--resume` 跳过已 `.done`):
     - if any evidence_file is big (> --big-file-bytes): run chunk_sources.py to get slices
     - spawn init-induct (one isolated context per cluster) with the cluster record (+ slices, + checkpoint_path, + done_marker)
     → 恰好写 `checkpoint_path`(绝对) + touch `done_marker`
5. T2: spawn init-synthesis (sees all T1 records, no raw code)
     → controls_inventory.json + checkpoints/t2/.done
   · 校验:`py .claude/mgh-core/scripts/validate_inventory.py --inventory <target>/.mgh-init/controls_inventory.json`(`design_controls` 兼容字段 + 每条 evidence 锚点 + category→kind 归一;退出码 2 → 回退重跑)
6. T3 FAN-OUT — 经确定性脚本枚举(**禁手挖** inventory / `py -c`):
   [controls_inventory.json::controls[].category] → list_rule_jobs.py --format <format> → [stdout pending[](每项含**绝对** `rule_path`/`done_marker`)]
     py .claude/mgh-core/scripts/list_rule_jobs.py --inventory <target>/.mgh-init/controls_inventory.json --format <format> --checkpoints <target>/.mgh-init/checkpoints/t3 --target <target>
     → stdout `{total,done,pending[],format}`;`pending[]` 每项 `{category,format,rule_path,done_marker}`(均绝对)
   per category in `pending[]`(WITHOUT `.done`;`--resume` 跳过):
     - spawn init-rulewriter (one isolated context per category) with --format + rule_path + done_marker
     → 恰好写 `rule_path`(绝对;claude: `.claude/rules/security-<cat>.md`;opencode: 暂存 fragment `.mgh-init/rules-parts/<cat>.md`)+ touch `done_marker`
6b. ASSEMBLE / LINT (Bash, deterministic; uses the run's --format, after T3 / before T4):
     py .claude/mgh-core/scripts/assemble_rules.py --target <target> --format <format>
   · opencode: 合并全部暂存 fragment 进 `<target>/AGENTS.md` 单个中性受管块(幂等、迁移旧 `mgh-init:` 块、内置 lint)
   · claude: 无装配(T3 已直写文件),仅对 `.claude/rules/security-*.md` 做纯净性 lint
   · 命中禁用 token(工具名/脚本名/层级/内部路径)= 规则正文泄漏;fail-loud(退出码 2),回 T3 修正后重跑
7. T4 (unless --skip-consistency): spawn init-rules-consistency
     → in-place edits to rule files (claude) / staged fragments (opencode) + checkpoints/t4/.done
8. i4: write init_manifest.json + report.md; print artifact paths + disclaimers
```

### Stage → component map

| Stage | How | Asset |
|---|---|---|
| i1 discover | **script** | `core/scripts/discover_controls.py` (+ `expand_scope.py` reuse) |
| i1 big-file slice | **script** | `core/scripts/chunk_sources.py` |
| artifact inspect | **script** | `core/scripts/describe_artifact.py` (瞄结构合法出口;NEVER `py -c`/`Read` 整份大 JSON) |
| i1 survey (opt) | subagent `init-survey` | `core/prompts/stages/init-survey.md` |
| T1 enumerate | **script** | `core/scripts/list_clusters.py` (pending work-list;包 `clusters.json` 包装字典) |
| T3 enumerate | **script** | `core/scripts/list_rule_jobs.py` (pending 按-category 清单;禁手挖 inventory) |
| T1 induct | subagent `init-induct` (fan out per cluster) | `core/prompts/stages/init-induct.md` |
| T2 synthesis | subagent `init-synthesis` | `core/prompts/stages/init-synthesis.md` |
| T3 rulewriter | subagent `init-rulewriter` (fan out per category) | `core/prompts/stages/init-rulewriter.md` + `fragments/rules-format-{claude,opencode}.md` |
| T3 assemble/lint | **script** | `core/scripts/assemble_rules.py` (opencode: single neutral block + legacy migration; both formats: `--check` purity lint) |
| T4 consistency | subagent `init-rules-consistency` (opt) | `core/prompts/stages/init-rules-consistency.md` |
| scout plan | **script** | `core/scripts/plan_scout.py` (byte-budget + pkg-co-located batches) |
| scout enumerate | **script** | `core/scripts/list_scout_batches.py` (pending 批清单;闭合与 T1 的不对称) |
| scout reader | subagent `init-scout` (fan out per batch) | `core/prompts/stages/init-scout.md` |
| scout merge | subagent `init-scout-merge` | `core/prompts/stages/init-scout-merge.md` |
| scout audit | subagent `init-scout-audit` (opt) | `core/prompts/stages/init-scout-audit.md` |
| scout fold-in | **script** | `core/scripts/merge_scout.py` (reuses `discover_controls.form_clusters`) |
| inventory validate | **script** | `core/scripts/validate_inventory.py` (T2 边界;`design_controls` 兼容 + evidence 锚点 + kind 归一) |
| stage boundary check | **script** | `discover_controls`/`plan_scout`/`merge_scout` `--check`(每 stage 产物校验) |

### Deterministic invocation (Bash)

```bash
py .claude/mgh-core/scripts/discover_controls.py --repo . --out ./.mgh-init
py .claude/mgh-core/scripts/discover_controls.py --check ./.mgh-init
py .claude/mgh-core/scripts/describe_artifact.py --in ./.mgh-init/controls_candidates.json --keys
py .claude/mgh-core/scripts/list_clusters.py --clusters ./.mgh-init/clusters.json --checkpoints ./.mgh-init/checkpoints/t1
py .claude/mgh-core/scripts/chunk_sources.py --in <big_file> --big-file-bytes 204800 --line <L> --out ./.mgh-init/_slice.json
py .claude/mgh-core/scripts/plan_scout.py --skeleton ./.mgh-init/skeleton.json --candidates ./.mgh-init/controls_candidates.json --out ./.mgh-init/scout_plan.json --batch-bytes 98304 --batch-cap 40
py .claude/mgh-core/scripts/plan_scout.py --check ./.mgh-init/scout_plan.json
py .claude/mgh-core/scripts/list_scout_batches.py --scout-plan ./.mgh-init/scout_plan.json --checkpoints ./.mgh-init/checkpoints/scout
py .claude/mgh-core/scripts/merge_scout.py --candidates ./.mgh-init/controls_candidates.json --scout ./.mgh-init/scout_candidates.json --audit ./.mgh-init/checkpoints/scout/audit.json --clusters ./.mgh-init/clusters.json
py .claude/mgh-core/scripts/merge_scout.py --check ./.mgh-init/scout_candidates.json
py .claude/mgh-core/scripts/validate_inventory.py --inventory ./.mgh-init/controls_inventory.json
py .claude/mgh-core/scripts/list_rule_jobs.py --inventory ./.mgh-init/controls_inventory.json --format claude --checkpoints ./.mgh-init/checkpoints/t3 --target .
py .claude/mgh-core/scripts/assemble_rules.py --target . --format claude --check
```

### Resume / cache
- Work units (isolation unit): i1 per file, **scout per batch**, T1 per cluster, T2/T4 whole, T3 per category.
- `<target>/.mgh-init/checkpoints/<tier>/<unit>.json.done` gates `--resume`.
- Call graph is rebuilt by discover each run; pass `--rebuild-cache` to force (mtime-based skip otherwise).

## Output (per `<target>/.mgh-init/`)

- `controls_candidates.json` — raw deterministic hits + scout candidates(audit trail;每条带 `source`)
- `skeleton.json` — 无损逐文件元数据(scout 输入;纯机械抽取,不含语义判定)
- `scout_plan.json` — scout 批次规划(字节预算 + 包内聚)
- `scout_candidates.json` — merge 后的 scout 候选(`source:"scout"`)+ `unresolved[]`
- `clusters.json` — T1 isolation units (centralized/distributed,regex 簇 + 追加的 scout 簇);包装结构 `{repo,clusters[],truncated}` 见 `core/contracts/init/clusters.md`
- `controls_inventory.json` — structured (`design_controls`-compatible); downstream input for `/mgh-sra`, `/mgh-blst`, future mgh-sast control intake
- `checkpoints/**` — per-unit artifacts (resume)
- `init_manifest.json` — version/format/counts/provenance/unresolved[]/out_of_scope[]/boundaries[]
- `report.md` — human-readable summary (+「competing controls」section)
- rules → claude:`<target>/.claude/rules/security-*.md`;opencode:`<target>/AGENTS.md` 单个中性受管块 `<!-- security-controls:begin --> … :end -->`(均经 `assemble_rules.py` 纯净性 lint)

## Always disclose
- 面向人读的非代码内容(`report.md`、`init_manifest.json` 的 `boundaries[]`/文案、rules 正文)
  用**简体中文**;锚点/路径/frontmatter 保持原样。

- LLM-induced candidates — human review required.
- **Existence ≠ effectiveness** (CVE-2025-41248: `@PreAuthorize` bypass on parameterized types).
- Call-graph is textual/AST-level — misses AOP/reflection/DI/framework-routing; surface `unresolved[]`.
- For ≥1.5M-line repos: prefer `--scope` per module + `--merge` over a single full-repo run.
- **Scout coverage is partial, not whole-repo**:`init_manifest.json` 记 `scout.{skeleton_total, scout_targets, batches, deep_read_files, audit_sampled, audit_found}`;只声称「审视/深读/自检」的真实数字,**不声称全仓覆盖**。
- Scout 非确定:簇数 run-to-run 可能变化(regex 来源簇仍确定)。残留盲区:泛型包 + 泛型类名 + 无安全导入 + 低扇因的控制可能漏(`--no-scout` 回退纯 regex)。
