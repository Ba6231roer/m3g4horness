---
description: 9-stage agentic SAST (survey → threat-model → decompose → deep-dive → prefilter → verify → dedup → chain → SARIF). Full-repo, incremental (--diff), directory/package scope (--path/--package), batch (--repo-file). Faithful zero-dependency reimplementation of vvaharness. Findings are triage candidates, not confirmed vulnerabilities.
---

# /mgh-sast — agentic SAST pipeline (opencode)

> 人类读者:通俗说明见 `docs/man/mgh-sast.md`。

> 编排器 = 你(宿主 agent):按本提示词,用自身工具(bash / spawn agent / read / write / edit)把流水线**跑出来**,而非写成代码——确定性逻辑已在 `prefilter.py` / `dedup.py` / `emit_sarif.py` / `list_chunks.py` / `list_verify_jobs.py` / `describe_artifact.py` 里,直接 `bash` 调用即可,无需 `read` 其源码,也不要另写 `.py` 去包装或重实现。

> **运行域 + hook**:`install.sh` 向本仓 `.opencode/plugins/` 注入 `tool.execute.before`
> 插件(`block-adhoc-scripts`),在 `/mgh-sast` 运行域内拦 `py -c`/`python -c` 内省与**一切脚本扩展名写入**
> (`.py`/`.ps1`/`.sh`/`.ts`/…;叶脚本 read-only)、子树外 `Write`/`Edit`(命中阻断 + stderr recipe 指向合法出口)。
> 插件归一化后管道喂**同一** Python 守卫(`.opencode/hooks/block_adhoc_scripts.py`,与 claude 端零差异)。编排器**起步先**
> `bash: export MGH_SAST_ACTIVE=1` 标记运行域 + 写磁盘哨兵 `<repo>/security-scan/.active`;opt-out = `install.sh --no-enforce-hook`
> (纪律仍由下方铁律 + 边界校验兜底)。守卫激活 = env **或** 磁盘哨兵——**哨兵关闭了 opencode「插件进程不继承
> mid-session bash 导出的 env」的可靠性边界**(见 `core/contracts/hooks/runtime-enforcement.md`)。

You are the **orchestrator** of a 9-stage SAST pipeline. Spawn stage agents (opencode
subagents) and run deterministic stage scripts (bash). Shared assets live at
`.opencode/mgh-core/` (mirrored from `core/`).

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
- `--controls <path>` — optional/advisory: `controls_inventory.json` (from `/mgh-init`); intake + scope-project, inject into s2/s3/s4/s6/s8. Omit = legacy behavior (zero control injection)
- **请求上下文预算**(`request-context-budget`,确定性边界强制每次大模型请求 ≤ 阈值;单位字节):`--max-unit-bytes <N>`(单 fan-out 单元物化输入上限,默认 192KB;oversize chunk 标 `oversize`+`needs_slice` 切片、verify finding 标 `oversize` 不切)· `--orch-budget-bytes <N>`(编排器单次请求可见的待办壳页上限,默认 64KB;超则自动分页收紧,stdout `shrunk:true`)· `--max-aggregate-bytes <N>`(s1 scope / s2-s3 hypothesis 聚合输入上限,默认 256KB;P0 软边界,超则建议 `--scope`/`--diff` 收窄 + `boundaries[]`/`report.md` 披露)

**No actionable args / `--help`** → print the flag table and STOP (zero tokens).

## Orchestrator discipline(铁律)

编排器 = 宿主 agent,**不写代码**。确定性叶脚本经 `bash` 执行;**NEVER `read` 叶子 `.py` 源码进上下文**(报错看 stderr,不读源码)。

**硬边界(`NEVER`)**:(a) `write`/`edit` 任何 `.py`——大编排器(`mgh_sast.py`)**或**一次性微脚本(`py -c` 产物、`_prep_chunks.py`、`_aggregate_verify.py`、`<run>_helper.py`);(b) `bash: py -c|python -c` 去内省/重派生产物(`import json` / `open(` / `load(` 读 `security-scan/**` / `scope_manifest.json`);(c) `read` 叶子 `.py` 源码。

**`NEVER` 向系统临时目录写中间文件再回读**:确定性脚本 stdout 在 Bash tool result(最后一行是 JSON),直接消费;NEVER 重定向到 `$env:TEMP`/`%TEMP%`/`/tmp` 再回读。

**implementation-intention(需 X → 触发器 Y,NEVER `py -c`)**——每个常被手搓的需求都有合法出口:
- **工作清单** → `list_chunks.py`(s4 fan-out)/ `list_verify_jobs.py`(s6 fan-out);
- **瞄一眼结构** → `describe_artifact.py --keys/--sample/--shape/--field`(**NEVER** `py -c`、**NEVER** `read` 整份大 JSON);
- **派生量** → 该量产出者的 stdout 字段(`prefilter`/`dedup`/`emit_sarif` stdout 的 stats;**NEVER** 自写脚本算)。
- **某 fan-out 单元的完整记录**(chunk 的 `files[]`/`threat_id`/`hypothesis` 或 finding 的 source/sink 锚点)→ `list_chunks.py`/`list_verify_jobs.py` `--materialize <inputs/<tier>>` stdout `pending[]` 每项的 `input_path`(绝对,subagent **自读**;≤ `--max-unit-bytes`);**NEVER** 整份读 `s3_chunks.json`/`s5_filtered.json`(编排器只装 slim 分页待办壳)、**NEVER** `py -c`、**NEVER** 把记录体内联塞进 subagent task(只透传 `input_path`);
- **subagent 用的绝对工具脚本路径**(sast-deepdive 切片用的 `chunk_sources`)→ `list_chunks.py` stdout 顶层 `scripts_dir`(`__file__` 派生 = 当前 install 的 `<mgh-core>/scripts/` 目录);s4 fan-out(已调 `list_chunks`)取该绝对基,把绝对 `chunk_sources` 路径**逐字透传**进 sast-deepdive task(subagent 用该绝对路径 verbatim;**NEVER** 裸名、**NEVER** 相对 `.claude`/`.opencode/mgh-core/scripts/…`——多层 install 下相对路径可上溯到**别的**旧副本;**NEVER** 从 `--target`/`--repo` 拼工具基(install-dir 可与 target 不同)、**NEVER** 从 mid-session env 读(opencode 插件进程不继承)、**NEVER** 调 init 专属的 `list_steps.py`);

**fan-out 刚性三元组**:每个 fan-out 步骤表述为 `[输入产物::字段] → script/subagent → [输出产物::字段]`;doubt 时刻 inline 1 行 shape(如「`s3_chunks.json::chunks[]` 即你的 s4 工作清单,经 `list_chunks.py` 取」)。

**终态声明**:`prefilter.py` 产 `s5_filtered.json`、`dedup.py` 产 `s7_findings.json` 为**终态**——不再二次聚合 / 重切(不出现 `_aggregate_verify.py` 之类重实现)。

**边界校验**:每个确定性 stage 产物跑完执行 `<producer> --check`;失败(退出码 2)→ 回退重跑该步,**不带着破损产物继续**。

## Orchestration flow
```
0. parse + self-check (host agent/model available; else STOP with fix hint)
   · **起步**:`bash: export MGH_SAST_ACTIVE=1`(声明运行域,激活 PreToolUse hook)
   · **哨兵(磁盘激活信号,opencode 可靠激活兜底)**:`mkdir -p <repo>/security-scan && printf '%s' '{"domain":"mgh-sast","target":"","out_roots":[],"v":1}' > <repo>/security-scan/.active`
     (sast 无 step-0 Python abs-repo 源 → `target` 空、子树守卫降级;脚本只读 / 内省守卫经哨兵可靠激活)。
     守卫激活 = `MGH_SAST_ACTIVE=1` env **或** 该哨兵(opencode 插件进程不继承 mid-session env → 哨兵兜底)。
     完成态(step 6)/ 干净停止 `rm <repo>/security-scan/.active`。
1. resolve profile/roles  (.opencode/mgh-core/profiles/<profile>.yaml)
2. IF --estimate: run scope + count only, print, STOP (no LLM)
3. IF scope (--diff/--path/--package):
     spawn agent sast-scope-resolver (runs diff_seed.py / expand_scope.py) → in_scope[] + scope_manifest.json
   ELSE in_scope = full repo
3b. controls intake (only IF --controls <path>):
      py load_controls.py --check <path>        (exit 2 → stderr warn + 跳过 intake,advisory;manifest source="intake-failed")
      py load_controls.py --inventory <path> --repo <repo>
        [--in-scope <repo>/security-scan/scope_manifest.json]   # 有 scope 时传,全仓扫描省略(=全 in_scope)
        → stdout controls_bundle  (source="mgh-init";按 protects/entry_points fnmatch 投影 in_scope,保留 out_of_scope_summary 作 hint)
    no --controls → controls_bundle = null; run_manifest.controls.source = "none"
4. pipeline (checkpoint each stage to <repo>/security-scan/checkpoints/):
   · **控制注入**(仅 controls_bundle ≠ null):spawn **s2 / s3 / s4 / s6 / s8** subagent 时,把
     controls_bundle + inline `prompts/fragments/controls-context.md` 放进**任务消息**
     (NEVER 改 `stages/*.md` 正文;s1 / s5 / s7 / s9 不注入)。控制 = **声称的保护**(存在≠有效,
     CVE-2025-41248):仅当控制 evidence 锚点位于该 finding 数据流**上游**才中和/阻断 chain,否则只降权;
     被控制「下架」的 finding/chain 须在 report.md 单列供人工复核。
   s1 survey (subagent, constrained to in_scope) → checkpoints/s1_context.json
   s2 threat-model (subagent) → checkpoints/s2_threats.json
   s3 decompose (subagent) → checkpoints/s3_chunks.json   (wrapper {rationale,chunks[]}; unit key = chunks[].id)
   s4 FAN-OUT (per chunk) — 经确定性脚本枚举 + 物化(**禁手挖** checkpoints/** / `py -c` / 整份读 `s3_chunks.json`):
     [s3_chunks.json::chunks[]] → list_chunks.py --materialize <repo>/security-scan/inputs/s4 [--repo <repo>] → [stdout slim pending[]]
       pending[] 每项 {chunk_id,files_count,threat_id,needs_slice,input_path,checkpoint_path,done_marker,slice_dir,bytes,oversize};stdout 顶层 `scripts_dir`(绝对工具基,透传 `<scripts_dir>/chunk_sources.py` 给 sast-deepdive)
     按 `offset`/`effective_limit` 翻页(单页 > `--orch-budget-bytes` 时 `shrunk:true`;NEVER wrapper `.py`);
     per chunk in page `pending[]` (--resume 跳过已 .done):
       - spawn sast-deepdive(透传 `input_path` + `slice_dir` + `<scripts_dir 派生的绝对 chunk_sources 路径>`;subagent 读 `input_path`,needs_slice 文件写 `<绝对 chunk_sources> --out <slice_dir>/<safe-stem>.slice.json` 并回读该确切路径,**绝不**整文件喂 LLM)→ 收 JSON 写 checkpoints/s4/<chunk_id>.json + .done
     aggregate all chunk findings → checkpoints/s4_candidates.json  ({"findings":[...]})
   s5 prefilter (bash, deterministic) → s5_filtered.json ({kept[],dropped[],stats})
     · 校验:`prefilter.py --check`(每条 kept finding 有 file/line_start/vuln_class/source_ref/sink_ref;退出码 2 → 回退)
     · **终态**:s5_filtered.json 为终态
   s6 FAN-OUT (per finding, vote) — 经确定性脚本枚举 + 物化(**禁手挖** `s5_filtered.json` / `py -c` / 整份读):
     [s5_filtered.json::kept[]] → list_verify_jobs.py --materialize <repo>/security-scan/inputs/s6 → [stdout slim pending[]]
       pending[] 每项 {finding_id,file,line,vuln_class,input_path,checkpoint_path,done_marker,bytes,oversize}(source/sink 锚点下沉进 input 文件)
     按 `offset`/`effective_limit` 翻页(单页 > `--orch-budget-bytes` 时 `shrunk:true`;NEVER wrapper `.py`);
     per finding in page `pending[]` (--resume 跳过已 .done):
       - spawn sast-verify(透传 `input_path`;subagent 读 `input_path`;≥1 pass,多 pass 做 majority-vote FP 抑制)→ 收 JSON 写 checkpoints/s6/<finding_id>.json + .done
     aggregate verdicts → checkpoints/s6_verdicts.json  ({...finding, verdict, cvss_vector})
   s7 dedup (bash, deterministic) → s7_findings.json ({findings:[canonical...]})
     · 校验:`dedup.py --check`(无明显近重复簇;退出码 2 → 回退)
     · **终态**:s7_findings.json 为终态
   s8 chain (subagent) → checkpoints/s8_chains.json + checkpoints/findings.json
   s9 SARIF (bash, deterministic) → report.sarif
     · 校验:`emit_sarif.py --check`(SARIF 2.1.0 + 每条 run.invocation;退出码 2 → 回退)
   (--stop-after truncates; --resume skips completed)
5. spawn sast-triage → report.md; write run_manifest.json
6. report paths + triage-candidate disclaimer · **收尾移除哨兵** `rm <repo>/security-scan/.active`
```

## Stage → asset (prompts path-referenced from .opencode/mgh-core/prompts/)

| Stage | How | Asset |
|---|---|---|
| s1 survey | subagent `sast-survey` | `prompts/stages/s1-survey.md` |
| s2 threat-model | subagent `sast-threat-model` | `prompts/stages/s2-*.md` |
| s3 decompose | subagent `sast-decompose` | `prompts/stages/s3-decompose.md` |
| s4 deep-dive | subagent `sast-deepdive` (per chunk) | `prompts/stages/s4-system.md` + `prompts/lenses/specialist-hints.md` |
| s4 enumerate | **script** | `scripts/list_chunks.py` (--materialize slim pending[]+input_path/needs_slice;读 s3_chunks.json chunks[]) |
| s5 prefilter | **script** | `scripts/prefilter.py` |
| s6 verify | subagent `sast-verify` (vote) | `prompts/stages/s6-verify.md` |
| s6 enumerate | **script** | `scripts/list_verify_jobs.py` (--materialize slim pending[]+input_path;读 s5_filtered.json kept[]) |
| s7 dedup | **script** | `scripts/dedup.py` |
| s8 chain | subagent `sast-chain` | `prompts/stages/s8-chain.md` |
| s9 SARIF | **script** | `scripts/emit_sarif.py` |
| big-file slice | **script** | `scripts/chunk_sources.py` |
| artifact inspect | **script** | `scripts/describe_artifact.py` (瞄结构合法出口;NEVER `py -c`/`read` 整份大 JSON) |
| scope | agent `sast-scope-resolver` | `scripts/diff_seed.py` + `expand_scope.py` |
| controls intake | **script** (only `--controls`) | `scripts/load_controls.py` (intake + scope 投影 → controls_bundle;`--check` 边界校验) |
| triage | subagent `sast-triage` | skill `sast-finding-review` |
| stage boundary check | **script** | `prefilter`/`dedup`/`emit_sarif` `--check`(每确定性 stage 产物校验) |

## Deterministic invocation (bash)

**长跑 Bash 超时纪律**:给 `prefilter`/`dedup`/`emit_sarif` 等长跑确定性 Bash 调用传一个慷慨的 per-call `timeout`(opencode shell 工具接受毫秒级 `timeout`),勿依赖默认超时(opencode 实测 60s/官方 120s)中途强杀。

```bash
py .opencode/mgh-core/scripts/list_chunks.py --chunks security-scan/checkpoints/s3_chunks.json --checkpoints security-scan/checkpoints/s4 --repo <repo> --materialize security-scan/inputs/s4 --max-unit-bytes 196608 --orch-budget-bytes 65536
py .opencode/mgh-core/scripts/list_verify_jobs.py --findings security-scan/checkpoints/s5_filtered.json --checkpoints security-scan/checkpoints/s6 --materialize security-scan/inputs/s6 --max-unit-bytes 196608 --orch-budget-bytes 65536
py .opencode/mgh-core/scripts/prefilter.py --in security-scan/checkpoints/s4_candidates.json --out security-scan/checkpoints/s5_filtered.json
py .opencode/mgh-core/scripts/prefilter.py --check security-scan/checkpoints/s5_filtered.json
py .opencode/mgh-core/scripts/dedup.py --in security-scan/checkpoints/s6_verdicts.json --out security-scan/checkpoints/s7_findings.json
py .opencode/mgh-core/scripts/dedup.py --check security-scan/checkpoints/s7_findings.json
py .opencode/mgh-core/scripts/emit_sarif.py --in security-scan/checkpoints/findings.json --out security-scan/report.sarif --repo-name <name> --application-id <id>
py .opencode/mgh-core/scripts/emit_sarif.py --check security-scan/report.sarif
# 大文件切片(sast-deepdive 在 s4 fan-out 内调用;--out 钉到 list_chunks stdout 的 slice_dir 树内;脚本路径 = list_chunks stdout scripts_dir 派生的绝对基 + chunk_sources.py,NEVER 裸名/相对):
py <list_chunks stdout scripts_dir 派生的绝对路径>/chunk_sources.py --in <big_file> --big-file-bytes 204800 --line <L> --out <slice_dir>/<safe-stem>.slice.json
py .opencode/mgh-core/scripts/describe_artifact.py --in security-scan/checkpoints/s5_filtered.json --keys
py .opencode/mgh-core/scripts/load_controls.py --check <controls_inventory.json>
py .opencode/mgh-core/scripts/load_controls.py --inventory <controls_inventory.json> --repo <repo> [--in-scope security-scan/scope_manifest.json]
```

## Resume / cache
- Work units: **s4 per chunk** (`checkpoints/s4/<chunk_id>.json.done`), **s6 per finding** (`checkpoints/s6/<finding_id>.json.done`); other stages whole.
- `--resume` skips units whose `.done` exists; fan-out pending comes from `list_chunks.py` / `list_verify_jobs.py` (**NEVER** 手挖 `checkpoints/**` / `py -c`)。

## Output (per `<repo>/security-scan/`)
- `report.md` — findings + exploit chains + dropped-findings appendix
- `report.sarif` — SARIF 2.1.0
- `checkpoints/*.json` — stage artifacts (resume); per-unit `checkpoints/s4|s6/<id>.json.done`
- `inputs/s4/<chunk>.input.json` · `inputs/s6/<finding>.input.json` — per-unit materialized fan-out inputs (subagent 自读;≤ `--max-unit-bytes`;随 `security-scan/` gitignore;见 `core/contracts/sast/fanout-enumeration.md`)
- `run_manifest.json` — version, role→model, config hash, git SHA, timing, scope, `controls` (source/inventory_path/in_scope_count/out_of_scope_count/total; `source="none"` when no `--controls`)

## Always disclose

- **宿主 shell 超时**:opencode 可经环境变量 `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS`(默认 120000)提升全局 shell 超时,但**须在 opencode 启动前就绪**(会话中途 `export` 不被 opencode 插件进程继承);per-call `timeout`(见上方长跑 Bash 超时纪律)是跨宿主公共杠杆、会话内即时生效。claude Bash per-call `timeout` 上限 600000ms。
- **请求上下文预算(确定性边界)**:每次大模型请求 ≤ 配置阈值(`--max-unit-bytes`/`--orch-budget-bytes`/`--max-aggregate-bytes`);`oversize`/`shrunk` 在 `run_manifest.json::boundaries[]` + `report.md` 披露(无静默溢出)。**P0 软边界**:s1 scope / s2-s3 hypothesis 聚合节点目前为「披露 + `--scope`/`--diff` 回退」,分层归约留后续 change;**不声称** P0 已对聚合节点提供硬阈值。s4/s6 扇出 per-unit 输入 + 编排器请求确定性有界。
- Triage-candidate disclaimer + call-graph blind spot (Spring `@*Mapping`/Feign/
  AOP/`@Autowired` in `scope_manifest.unresolved[]`).
- Controls provenance (only when `--controls`): controls are `/mgh-init` LLM-induced
  candidates asserting **existence, not effectiveness** (CVE-2025-41248: `@PreAuthorize`
  bypass on parameterized types). Disclose scope-projection real numbers
  (in_scope / out_of_scope); list control-affected findings/chains separately for review.
