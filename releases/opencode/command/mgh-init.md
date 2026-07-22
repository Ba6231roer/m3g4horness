---
description: Discover existing reusable security controls in a project (input-validation / data-masking / authentication / authorization / crypto / rate-limiting / csrf / audit-logging) and emit agent-consumable rules (opencode: concise AGENTS.md lazy index + per-category detail files under docs/security-controls/; claude: path-scoped .claude/rules/*.md). Three-tier isolation-first pipeline (deterministic discover → T1 per-cluster induct → T2 synthesis → T3 per-category rules → T4 consistency). --format claude|opencode required (structures differ, never mix). Supports --scope/--resume/--merge and large-file sharding. Findings are LLM-induced candidates needing human review.
---

# /mgh-init — discover existing security controls → agent rules

> 编排器 = 你(宿主 agent):按本提示词,用自身工具(Bash / Agent / Read / Write / Edit)把流水线**跑出来**,而非写成代码——确定性逻辑已在 `discover_controls.py` / `chunk_sources.py` / `plan_scout.py` / `merge_scout.py` / `assemble_rules.py` 里,直接 `Bash` 调用即可,无需 `Read` 其源码,也不要另写 `.py` 去包装或重实现。opencode 下 T3 每 category 直写**详述文件**(`docs/security-controls/<cat>.md`,独立 H1 文档),`assemble_rules.py` 扫该目录建 `AGENTS.md` 简洁**惰性索引块**(按需加载,见步骤 6b)。

> **运行域 + hook**:`install.sh` 向本仓 `.opencode/plugins/` 注入 `tool.execute.before`
> 插件(`block-adhoc-scripts`),在 `/mgh-init` 运行域内拦 `py -c`/`python -c` 内省、越权
> `Write *.py`、**以及 resolved 目标不在 `MGH_TARGET` 子树内的 `Write`/`Edit`**(子树外写入,
> 如盘符根;命中阻断 + stderr recipe 指向 `list_*` stdout 的 `checkpoint_path`)。插件把事件归一化后
> 管道喂**同一** Python 守卫(`.opencode/hooks/block_adhoc_scripts.py`,与 claude 端零差异)。编排器**起步先**
> `Bash: export MGH_INIT_ACTIVE=1` 标记运行域,并在 discover 后 `export MGH_TARGET=<绝对 repo>`(供 hook
> 判树;缺失则该条降级放行)。opt-out = `install.sh --no-enforce-hook`(纪律仍由下方铁律 + 边界校验兜底)。
> **可靠性边界**:opencode 插件进程**不继承** mid-session bash 导出的 env,故 `MGH_INIT_ACTIVE` 仅在 opencode
> 启动时已就绪才激活守卫;未激活则纪律由下方铁律 + 各 producer `--check` 兜底。

You are the **orchestrator** of the mgh-init pipeline. Carry it out by running the
deterministic leaf scripts (Bash) and spawning stage subagents. Shared assets live
at `.opencode/mgh-core/` (mirrored from `core/`).

> **Output is LLM-induced, not confirmed. Controls are "existing", not "effective".**
> Human review required. State this in every summary.

## Parse arguments (validate BEFORE spending tokens)

- `--target <dir>` (default `.`)
- `--format opencode|claude` — **required** (mutex). Missing → error + STOP.
- `--out <path>` (opencode default `<target>/AGENTS.md`; claude default `<target>/.claude/rules`)
- `--rules-dir <path>` (opencode default `<target>/docs/security-controls`; 详述文件目录,透传给 `list_rule_jobs.py`/`assemble_rules.py`)
- `--scope path:<dir>|package:<pkg>|file:<glob>` + `--scope-mode defined|applicable` (default `defined`)
- `--language <lang>`, `--max-files <N>`, `--big-file-bytes <N>` (default 200KB), `--sample <N>` (default 8), `--progress-every <N>` (默认 1000), `--large-repo-threshold <N>` (默认 15000;超阈值则前置建议 `--scope`+`--merge`)
- `--include-dotfiles` (默认关;扫描点前缀路径 `.opencode`/`.claude`/`.codegraph`/`.github`/`.env`。默认跳过——tooling/VCS/IDE/build/config/索引 非一方业务代码;控制定义点落在 `.xxx` 内时传此 flag 纳入)
- `--resume` · `--rebuild-cache` · `--merge <partials-dir>` · `--skip-consistency` · `--config <profile>` (default `init`)
- `--no-scout` (skip LLM scout discovery; legacy regex-only) · `--scout-budget <N>` (0=全量) · `--scout-batch-bytes <N>` (默认 96KB) · `--scout-batch-cap <N>` (默认 40) · `--scout-audit-pct <N>` (默认 15)
- `--no-codegraph` (skip optional codegraph enrichment; legacy behavior). codegraph 检测默认 `auto`:仅当 `<target>/.codegraph/` 存在**且** PATH 有 `codegraph` 才启用;`--no-codegraph` 或不可用 → 富化 off(行为等价于引入 codegraph 前)

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
0. parse + self-check(发现脚本统计源文件数,超 `--large-repo-threshold` 则建议 `--scope`+`--merge`;扫描期向 stderr 打印进度)
   · **起步**:`Bash: export MGH_INIT_ACTIVE=1`(声明运行域,激活 PreToolUse hook,含子树外 Write/Edit 拦截)
   · **MGH_TARGET**(供 hook 判树;守卫未激活时该条空转):discover(step 2)写出的 `controls_candidates.json::repo` 即**绝对项目根**;编排器**逐字读**该字段并 `export MGH_TARGET=<repo>`,在 fan-out 前设置。取值经 `describe_artifact.py --field repo`(合法瞄结构出口),**NEVER** `py -c` 自算、**NEVER** 用裸 `.` 相对。
   · **codegraph 检测**(花 token 之前):`Bash: if test -d <target>/.codegraph && command -v codegraph >/dev/null 2>&1; then echo on; else echo off; fi`
     → `codegraph=on|off`。默认 `auto`(可用即启用);传 `--no-codegraph` 或检测不可用 → `codegraph=off`。该信号**逐字透传**进
     scout/induct/survey/resolve subagent task 输入(仅 `codegraph=on` 时这些 stage 启用 codegraph 外科式上下文 + 执行 `init-resolve` stage)。
1. IF --merge: merge partial inventories by evidence anchor → STOP
2. i1 discover (Bash):
     py .opencode/mgh-core/scripts/discover_controls.py --repo <target> --out <target>/.mgh-init [--scope .. --max-files ..]
   → controls_candidates.json (regex, `source:regex`) + clusters.json + skeleton.json  (skip on --resume if present & not --rebuild-cache)
   · 派生量直读 discover stdout:`candidates/clusters/unresolved_count/big_files`(NEVER `py -c` 自算)
   · **MGH_TARGET**:discover 后取其产物 `repo` 字段(绝对根)——
     `py .opencode/mgh-core/scripts/describe_artifact.py --in <target>/.mgh-init/controls_candidates.json --field repo`
     → stdout `{"value":"<绝对 target>"}`;`export MGH_TARGET=<该 value>`(供 hook 判树;NEVER `py -c` 自算)。
   · 校验:`py .opencode/mgh-core/scripts/discover_controls.py --check <target>/.mgh-init`(wrapper + 每条 `source` + cluster_id 唯一;退出码 2 → 回退重跑)
3. (optional) init-survey subagent → i1_enriched.json
   · **advisory + non-fatal**:产出仅作审计/T2 参考,**非 T1 输入**(T1 读 `clusters.json`);
     缺失 `i1_enriched.json` **不阻断**、不报致命错。`total` 过大(单 subagent 装不下整仓簇)
     时**跳过**,并在摘要披露。
3b. SCOUT FAN-OUT (除非 `--no-scout`)——让 LLM 找出 regex 闸门漏掉的自研控制:
     [skeleton.json + controls_candidates.json] → plan_scout.py → [scout_plan.json::batches[]]
     py .opencode/mgh-core/scripts/plan_scout.py --skeleton <target>/.mgh-init/skeleton.json \
        --candidates <target>/.mgh-init/controls_candidates.json --out <target>/.mgh-init/scout_plan.json \
        [--batch-bytes .. --batch-cap .. --budget ..]
     · 批数涌现 = ceil(Σtarget_bytes / --scout-batch-bytes);按包内聚切批,每批字节≤预算且文件数≤cap。派生量 `regex_known_count` 在 stdout / `scout_plan.json` 顶层(NEVER 自算)。
     · 校验:`py .opencode/mgh-core/scripts/plan_scout.py --check <target>/.mgh-init/scout_plan.json`(batches 非空除非 0 target、每批 bytes≤预算、needs_slice 仅含超批文件;退出码 2 → 回退)。
     [scout_plan.json::batches[]] → list_scout_batches.py → [stdout pending[](每项含**绝对** `checkpoint_path`/`done_marker`)](禁手挖 `scout_plan` / `py -c`)
     py .opencode/mgh-core/scripts/list_scout_batches.py --scout-plan <target>/.mgh-init/scout_plan.json --checkpoints <target>/.mgh-init/checkpoints/scout
     per batch in `pending[]`(并行 ≤ max_concurrent,**每批一个隔离 subagent 上下文**;`--resume` 跳过已 `.done`):
       - if batch.needs_slice:先 `chunk_sources.py` 切片(**绝不**整文件喂 LLM)
       - spawn init-scout({batch, repo root, regex_known[], checkpoint_path, done_marker}) → 恰好写 `checkpoint_path`(绝对) + touch `done_marker`
     spawn init-scout-merge(只见全部 scout 批记录,无原始码)→ scout_candidates.json + checkpoints/scout/merge.json.done
     · 校验:`py .opencode/mgh-core/scripts/merge_scout.py --check <target>/.mgh-init/scout_candidates.json`(每条 `source:"scout"` + file:line;退出码 2 → 回退)。
     spawn init-scout-audit(随机 ≈--scout-audit-pct 的 scout 拒绝项)→ checkpoints/scout/audit.json + .done
     py .opencode/mgh-core/scripts/merge_scout.py --candidates <target>/.mgh-init/controls_candidates.json \
        --scout <target>/.mgh-init/scout_candidates.json --audit <target>/.mgh-init/checkpoints/scout/audit.json \
        --clusters <target>/.mgh-init/clusters.json
     · 候选集并入 `source:"scout"`;clusters.json **追加** scout 簇(regex 簇与其 usage_sites 不变)。复用 `discover_controls.form_clusters`,无逻辑漂移。
     · **终态**:`scout_candidates.json` / `controls_candidates.json` / `clusters.json` 此时为终态——不再二次聚合 / 重切批(NEVER `_aggregate_scout.py`)。
3c. (optional, codegraph-gated) init-resolve — 仅当 `codegraph=on` **且** `unresolved[]` 非空时执行;
     排空文本/AST 图结构性漏掉的框架路由 / DI / AOP / interface→impl / 反射控制。**non-fatal + bounded**:
     [controls_candidates.json::unresolved[]] → describe_artifact.py --field → init-resolve subagent → [resolved.json]
     · 取 `unresolved[]` 清单(合法瞄结构出口,**NEVER** `py -c`、**NEVER** `Read` 整份大 JSON):
       `py .opencode/mgh-core/scripts/describe_artifact.py --in <target>/.mgh-init/controls_candidates.json --field unresolved`
       → stdout `{"field":"unresolved","value":["<file>",...]}`;空列表 → 跳过本 stage(摘要披露)。
     · spawn init-resolve({unresolved[], repo root, checkpoint_path=<target>/.mgh-init/resolved.json(绝对),
       done_marker=<target>/.mgh-init/checkpoints/resolve/.done(绝对)}, codegraph=on)
       → 恰好写 `checkpoint_path`(绝对)+ touch `done_marker`(产 `{repo, resolved[]{…source:"codegraph", resolved_path[]}, unresolved_residual[]}`,见 `core/contracts/init/resolved.md`)
     · **additive 并入 T1 候选流**:`resolved[]` 按既有 `category::anchor` 簇键由编排器路由到对应簇的 candidate hits(additive;**不** mutate regex/scout 候选、**不**改任何确定性脚本;簇形成语义与既有 form_clusters 一致)。`source:"codegraph"` 结构标签一路保留进 inventory/manifest。`unresolved_residual[]` 残留计 manifest `codegraph.unresolved_residual`。
     · **MGH_TARGET / 子树守卫**:`resolved.json` 写在 `<target>/.mgh-init/` 下,既有子树守卫覆盖;`checkpoint_path` 是编排器**逐字给定**的绝对路径(NEVER 拼装 `<target>/<id>`、NEVER 占位符、NEVER 相对)。
     · **fail-soft / non-fatal**:`codegraph=off` / `unresolved[]` 为空 / 清单过大超单 subagent 上下文预算 → 跳过整 stage + 摘要披露,流水线**不阻断**、不报致命错(对标 init-survey 的 optional/advisory/non-fatal 语义)。T1 从 `clusters.json` 正常扇出不受影响。
4. T1 FAN-OUT — 经确定性脚本枚举(**禁手搓** `py -c` 内省;`clusters.json` 是包装字典
   `{repo,clusters[],truncated}`,对顶层 `len()` 得 3 **不是**簇数):
   [clusters.json::clusters[]] → list_clusters.py → [stdout pending[](每项含**绝对** `checkpoint_path`/`done_marker`)]
     py .opencode/mgh-core/scripts/list_clusters.py --clusters <target>/.mgh-init/clusters.json --checkpoints <target>/.mgh-init/checkpoints/t1
     → stdout `{repo,total,done,pending[],truncated}`;`total` = 真簇数(= discover stdout `clusters` 字段)
   per cluster in `pending[]`(NOT 顶层;`--resume` 跳过已 `.done`)→ (big file: chunk_sources slice first) spawn init-induct(带 cluster 记录 + slices + checkpoint_path + done_marker)
   → 恰好写 `checkpoint_path`(绝对) + touch `done_marker`
5. T2: init-synthesis (all T1 records, no raw code) → controls_inventory.json
   · 校验:`py .opencode/mgh-core/scripts/validate_inventory.py --inventory <target>/.mgh-init/controls_inventory.json`(`design_controls` 兼容字段 + 每条 evidence 锚点 + category→kind 归一;退出码 2 → 回退重跑)
6. T3 FAN-OUT — 经确定性脚本枚举(**禁手挖** inventory / `py -c`):
   [controls_inventory.json::controls[].category] → list_rule_jobs.py --format <format> → [stdout pending[](每项含**绝对** `rule_path`/`done_marker`)]
     py .opencode/mgh-core/scripts/list_rule_jobs.py --inventory <target>/.mgh-init/controls_inventory.json --format <format> --checkpoints <target>/.mgh-init/checkpoints/t3 --target <target>
     → stdout `{total,done,pending[],format}`;`pending[]` 每项 `{category,format,rule_path,done_marker}`(均绝对)
   per category in `pending[]`(WITHOUT `.done`;`--resume` 跳过)→ spawn init-rulewriter with --format + rule_path + done_marker
   → 恰好写 `rule_path`(绝对;opencode: **详述文件** `docs/security-controls/<cat>.md`,独立 H1、中性、无哨兵,**禁**直写 `AGENTS.md`)+ touch `done_marker`
6b. (opencode only) BUILD INDEX + LINT (Bash, deterministic):
     py .opencode/mgh-core/scripts/assemble_rules.py --target <target> --format opencode [--rules-dir <target>/docs/security-controls]
   → 扫 `<rules-dir>/*.md` 详述文件建 `<target>/AGENTS.md` 简洁**惰性索引块**
     `<!-- security-controls:begin --> … :end -->`(每详述文件一行 `@<rel>` + 按需 Read 指令;
     幂等替换、保留用户内容、迁移旧 `mgh-init:` 块)。opencode 启动整份 `AGENTS.md` 进根上下文,
     故索引保持简洁、正文留在详述文件按需加载(对齐 opencode 文档 "Manual Instructions in AGENTS.md")
   · lint(fail-loud 退出码 2)= 详述文件正文泄漏:T3 禁 front matter / inventory schema
     字段(`found_controls`/`evidence_count`)/ 过程散文(`扫描器模式定义` 等)/ 无源码锚点的控制;
     lint 覆盖工具内部 token + schema 字段 + opencode YAML 围栏(`---`)+ 特征过程散文。回 T3 修正
     该 category 详述文件后重跑 6b
7. T4 (unless --skip-consistency): init-rules-consistency
8. i4: init_manifest.json + report.md; print artifact paths + disclaimers
   · manifest 含 `codegraph:{available,used,resolved_count,unresolved_residual}`:`available`=检测到 `.codegraph/`+CLI;`used`=`codegraph=on` 且 `init-resolve` 实跑;`resolved_count`/`unresolved_residual` 取自 `resolved.json`(经
     `py .opencode/mgh-core/scripts/describe_artifact.py --in <target>/.mgh-init/resolved.json --field resolved --count` 计数,NEVER `py -c`);`codegraph=off` 时 `used=false`/`resolved_count=0`,不出现解析计数。report.md 同步披露 codegraph 用量 + 残留盲区。
```

### Stage → component map

| Stage | How | Asset |
|---|---|---|
| i1 discover | **script** | `core/scripts/discover_controls.py` (+ `expand_scope.py` reuse) |
| i1 big-file slice | **script** | `core/scripts/chunk_sources.py` |
| artifact inspect | **script** | `core/scripts/describe_artifact.py` (瞄结构合法出口;NEVER `py -c`/`Read` 整份大 JSON) |
| i1 survey (opt) | subagent `init-survey` | `core/prompts/stages/init-survey.md` |
| resolve (opt) | subagent `init-resolve` (codegraph-gated, single context) | `core/prompts/stages/init-resolve.md` + `fragments/codegraph-hint.md` |
| T1 enumerate | **script** | `core/scripts/list_clusters.py` (pending work-list;包 `clusters.json` 包装字典) |
| T3 enumerate | **script** | `core/scripts/list_rule_jobs.py` (pending 按-category 清单;禁手挖 inventory) |
| T1 induct | subagent `init-induct` (fan out per cluster) | `core/prompts/stages/init-induct.md` |
| T2 synthesis | subagent `init-synthesis` | `core/prompts/stages/init-synthesis.md` |
| T3 rulewriter | subagent `init-rulewriter` (fan out per category) | `core/prompts/stages/init-rulewriter.md` + `fragments/rules-format-{claude,opencode}.md` |
| T3 assemble (opencode) | **script** | `core/scripts/assemble_rules.py` (build concise lazy index in AGENTS.md from `<rules-dir>/*.md` + legacy migration + `--check` purity lint over detail files: tool tokens + schema fields + YAML fences + discovery prose) |
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
py .opencode/mgh-core/scripts/discover_controls.py --repo . --out ./.mgh-init
# escape hatch: 控制定义点在 .opencode/.claude/.codegraph/.github 等 .xxx 内时才纳入(默认跳过点前缀路径)
py .opencode/mgh-core/scripts/discover_controls.py --repo . --out ./.mgh-init --include-dotfiles
py .opencode/mgh-core/scripts/discover_controls.py --check ./.mgh-init
py .opencode/mgh-core/scripts/describe_artifact.py --in ./.mgh-init/controls_candidates.json --keys
py .opencode/mgh-core/scripts/list_clusters.py --clusters ./.mgh-init/clusters.json --checkpoints ./.mgh-init/checkpoints/t1
py .opencode/mgh-core/scripts/chunk_sources.py --in <big_file> --big-file-bytes 204800 --line <L> --out ./.mgh-init/_slice.json
py .opencode/mgh-core/scripts/plan_scout.py --skeleton ./.mgh-init/skeleton.json --candidates ./.mgh-init/controls_candidates.json --out ./.mgh-init/scout_plan.json --batch-bytes 98304 --batch-cap 40
py .opencode/mgh-core/scripts/plan_scout.py --check ./.mgh-init/scout_plan.json
py .opencode/mgh-core/scripts/list_scout_batches.py --scout-plan ./.mgh-init/scout_plan.json --checkpoints ./.mgh-init/checkpoints/scout
py .opencode/mgh-core/scripts/merge_scout.py --candidates ./.mgh-init/controls_candidates.json --scout ./.mgh-init/scout_candidates.json --audit ./.mgh-init/checkpoints/scout/audit.json --clusters ./.mgh-init/clusters.json
py .opencode/mgh-core/scripts/merge_scout.py --check ./.mgh-init/scout_candidates.json
py .opencode/mgh-core/scripts/validate_inventory.py --inventory ./.mgh-init/controls_inventory.json
py .opencode/mgh-core/scripts/list_rule_jobs.py --inventory ./.mgh-init/controls_inventory.json --format opencode --checkpoints ./.mgh-init/checkpoints/t3 --target . --rules-dir docs/security-controls
py .opencode/mgh-core/scripts/assemble_rules.py --target . --format opencode
```

### Resume / cache
- Work units: i1 per file, **scout per batch**, T1 per cluster, T2/T4 whole, T3 per category.
- `<target>/.mgh-init/checkpoints/<tier>/<unit>.json.done` gates `--resume`.
- `--rebuild-cache` forces call-graph rebuild.

## Output (per `<target>/.mgh-init/`)

- `controls_candidates.json`(regex + scout,带 `source`)· `skeleton.json` · `scout_plan.json` · `scout_candidates.json` · `clusters.json` · `controls_inventory.json` (`design_controls`-compatible)
- `clusters.json` 包装结构 `{repo,clusters[],truncated}` 见 `core/contracts/init/clusters.md`(T1 经 `list_clusters.py` 枚举,禁手搓内省)
- `checkpoints/**` (resume) · `init_manifest.json` · `report.md` (+「competing controls」section)
- rules → opencode:`<target>/AGENTS.md` 简洁**惰性索引块** `<!-- security-controls:begin --> … :end -->` + 每实现 category 一个详述文件 `<target>/docs/security-controls/<cat>.md`(由 `assemble_rules.py` 扫 `<rules-dir>/*.md` 建索引;详述文件按需加载);claude:`<target>/.claude/rules/security-*.md`

## Always disclose
- 面向人读的非代码内容(`report.md`、`init_manifest.json` 的 `boundaries[]`/文案、rules 正文)
  用**简体中文**;锚点/路径/frontmatter 保持原样。

- LLM-induced candidates — human review required.
- **Existence ≠ effectiveness** (CVE-2025-41248).
- Call-graph textual/AST — misses AOP/reflection/DI/framework-routing; surface `unresolved[]`.
- **点前缀路径默认不扫描**(tooling/VCS/IDE/build/config/索引,如 `.opencode`/`.claude`/`.codegraph`/`.github`):控制定义点落在 `.xxx` 内时默认不会被发现,须传 `--include-dotfiles` 才纳入;discover stdout `dotfiles_skipped` 计本次跳过的点前缀源文件数;`report.md` / `init_manifest.json::boundaries[]` 披露该边界。
- ≥1.5M-line repos: prefer `--scope` per module + `--merge`.
- **Scout coverage is partial, not whole-repo**:`init_manifest.json` 记 `scout.{skeleton_total, scout_targets, batches, deep_read_files, audit_sampled, audit_found}`;只声称真实数字,**不声称全仓覆盖**。Scout 非确定(簇数 run-to-run 可能变化);残留盲区:泛型包+泛型类名+无安全导入+低扇因控制可能漏(`--no-scout` 回退纯 regex)。
- **codegraph 富化是可选 + 辅助**:`init_manifest.json` 记 `codegraph.{available,used,resolved_count,unresolved_residual}`;codegraph 解析缩小但**不归零** `unresolved[]`(反射 / DI 容器 / 运行时分派残留),resolved = LLM+codegraph 候选,需人工复核。**不声称全解析**。`--no-codegraph` 一键回退引入前行为。
