---
description: Run a security design review on a branch diff: git diff base..branch, interface-dimension grouping, fan-out 6-dimension review against the existing security design (mgh-init rules), and a Simplified-Chinese report at the project root. LLM candidates needing human review. Default: current branch vs master; launcher (mgh_sdr_launch.py) is the zero-prompt preferred entry for multi-branch sweeps.
---

# /mgh-sdr — 需求分支安全设计符合性复核(security design review)

> 人类读者:通俗说明见 `docs/man/mgh-sdr.md`。

> 编排器 = 你(宿主 agent):按本提示词,用自身工具(Bash / Task 子代理 / Read / Write)把流水线
> **跑出来**,而非写成代码。确定性逻辑已在 `diff_group.py` / `sdr_context.py` /
> `render_sdr_report.py` / `fanout_runner.py` 里,直接 `Bash` 调用即可,无需 `Read` 其源码,
> 也不要另写 `.py` 去包装或重实现。

> **输出是 LLM 候选,非已确认漏洞。引用存量控制断言存在、不断言有效。每次总结都声明。**

> **零打断优选入口**:存量设计引用外部前端仓时,首选 `py .claude/mgh-core/scripts/mgh_sdr_launch.py`
> (人/cron 入口,外部仓检索在 launcher 进程完成、宿主会话零权限确认)。本壳是宿主会话内的
> 功能等价兜底:step 1 的外部仓检索发生在宿主 Bash,可能触发一次宿主权限确认(诚实披露)。

## Parse arguments(validate BEFORE spending tokens)

- `--base <ref>`(默认 `master`)
- `--branch <ref>`(默认当前分支;**本壳单分支**——多分支 sweep 是 launcher `--multi-branch` 专属,壳不背多分支状态)
- `--dimensions <inline-json|@path>`(可选:收窄检查面,闭集 6 键 + kebab-case 自由文本扩展;
  非法键 → 退出码 2 早停,任何 LLM 之前)
- `--run-dir <dir>`(可选:显式 run 目录,默认 `<project>/.mgh-sdr/runs/<YYYYMMDD_HHMMSS>/`)
- `--max-standalone-bytes <N>`(默认 64KB,standalone 簇归并上限)
- `--no-codegraph`(可选:跳过 codegraph 减扇出信号;默认 auto:`<project>/.codegraph/` 存在且 PATH
  有 codegraph 才 on;off 时零 codegraph 调用、行为等价)
- `--dry-run`(仅跑 step 0–1(sdr_context + diff_group materialize)+ `--check`,不 fan-out 不渲染)

**无 actionable 参数 / `--help`** → 打印参数表后 **STOP**(零 token、零解析)。

## Orchestrator discipline(铁律)

**硬边界(`NEVER`)**:(a) `Write` 任何脚本扩展名(`.py`/`.ps1`/`.sh`/`.ts`/…)——大编排器或一次性
微脚本;(b) `Bash: py -c|python -c` 内省/重派生产物(`import json`/`open(`/`load(` 读 `.mgh-sdr/**`);
(c) `Read` 叶子 `.py` 源码(报错看 stderr,不读源码)。运行域守卫(`block-adhoc-scripts`)确定性兜底。

**fan-out 刚性三元组**:`[diff_group pending[]::字段] → fanout_runner --tier sdr → [drafts/*.json + markers]`;
路径 = `diff_group` stdout `pending[]` 每项**绝对** `input_path`/`draft_path`/`done_marker`/
`failed_marker`/`baseline_path`/`external_dir`(逐字透传给 dispatcher,dispatcher 逐字填进 subagent
task)——**NEVER** 自拼路径、**NEVER** `py -c` 算路径、**NEVER** 相对路径。

**边界校验**:每步后跑产出者 `--check`;失败(退出码 2)→ 回退重跑该步,**不带着破损产物继续**。
报告/manifest **NEVER** 写进 `openspec/`。

**长跑 Bash 超时纪律**:fanout_runner 与 render 调用传慷慨 per-call `timeout`(毫秒);claude 宿主
建议 `--time-budget-ms 480000`(claude Bash 600s 上限 × 0.8);opencode 宿主建议 720000(900s × 0.8)。

## Orchestration flow

```
0. parse + 运行域声明
   · `Bash: export MGH_SDR_ACTIVE=1`;写磁盘哨兵(**NEVER** bash pwd 取 target,target 来自脚本
     stdout):
     `mkdir -p .mgh-sdr && printf '%s' '{"domain":"mgh-sdr","target":"","out_roots":[],"v":1}' > .mgh-sdr/.active`
   · 解析 run 目录(默认 `<project>/.mgh-sdr/runs/<ts>/`;mkdir -p)。
1. sdr_context(Bash,确定性;外部仓检索在此步、宿主进程内——**可能一次权限确认,诚实披露**):
     py .claude/mgh-core/scripts/sdr_context.py --repo <abs> --run-dir <abs-run-dir> [--base <ref>] [--branch <ref>] [--dimensions <json>]
   · 读 stdout:`baseline_path`/`baseline_truncated`/`sensitive_catalog`/`sensitive_catalog_source`/
     `external_repos[]`/`external_skipped`(**NEVER** 自行解析 AGENTS.md 重算;NEVER 读外部仓原文)。
   · **有 external_repos → 重写哨兵**(把已确认外部根写入 read_roots;subagent 跨树读放行声明根,
     Bash 搜索动词仍仅限 MGH_TARGET):
     `printf '%s' '{"domain":"mgh-sdr","target":"<abs>","out_roots":[],"read_roots":["<ext1>","<ext2>"],"v":1}' > .mgh-sdr/.active`
     (read_roots 最小化:只写 sdr_context 实际检索过的根,**NEVER** 透传任意路径。)
   · 无 external_repos 且 external_skipped 非空 → 记住该披露(报告会声明)。
   · `export MGH_TARGET=<abs>`;`--dry-run` → 到此处 STOP(跑 `--check` 后移除哨兵)。
2. diff_group(Bash,确定性;pending 唯一来源):
     py .claude/mgh-core/scripts/diff_group.py --repo <abs> --base <ref> --branch <ref> --checkpoints <run-dir>/markers --materialize <run-dir>/slices
   · stdout `empty:true` → 跳过 fan-out,直接 step 4(渲染「无变更」报告)。
   · `export MGH_SDR_CODEGRAPH=on|off`(auto 检测:`test -d "$MGH_TARGET/.codegraph" && command -v codegraph`;
     `--no-codegraph` 或检测不可用 → off)——信号经 run 目录 `run_config.json`(no_codegraph 字段,
     printf 写入,确定性)传给 dispatcher,NEVER 拼进 task 消息。
   · 校验:`py .claude/mgh-core/scripts/diff_group.py --check <run-dir>`(退出码 2 → 回退)。
3. fan-out(dispatcher;逐字转发调用,**NEVER** 手工循环):
     py .claude/mgh-core/scripts/fanout_runner.py --tier sdr --repo <abs> --base <ref> [--branch <ref>] --checkpoints <run-dir>/markers --inputs-dir <run-dir>/slices --time-budget-ms 480000 [--resume]
   · 软时限早退(stdout `partial:true`)→ 同参重派(resume 语义);STALLED(退出码 2)→
     停止重派,报告 degraded(诚实披露)。gate 形退出码 2 → 转述 stderr recipe,停止。
4. render(Bash,确定性):
     py .claude/mgh-core/scripts/render_sdr_report.py --run-dir <abs-run-dir> --repo <abs>
   → `<project>/mgh-sdr-<branch>-<ts>.md` + `<run-dir>/sdr_manifest.json`;NEVER 写 openspec/
   · 校验:`py .claude/mgh-core/scripts/render_sdr_report.py --check <run-dir>`。
5. 收尾:打印报告绝对路径 + counts(stdout manifest 字段,**NEVER** `py -c` 挖 JSON);
   声明诚实边界;`rm .mgh-sdr/.active`(完成态/干净停止)。
```

### Stage → component map

| Stage | How | Asset |
|---|---|---|
| 基线投影 + 外部仓检索 + 敏感目录 | **script** | `core/scripts/sdr_context.py` |
| diff 采集 + 接口分组 + slice 物化 | **script** | `core/scripts/diff_group.py` |
| per-unit 复核扇出 | dispatcher `fanout_runner --tier sdr` | `core/prompts/fragments/fanout/sdr-task.md` + agent `sdr-review-fanout`(经 `--agents` inline JSON 派生) |
| 汇总渲染 | **script** | `core/scripts/render_sdr_report.py` |
| stage boundary check | **script** | `sdr_context`/`diff_group`/`render_sdr_report` `--check` |

### Deterministic invocation (Bash)

```bash
py .claude/mgh-core/scripts/sdr_context.py --repo <abs> --run-dir .mgh-sdr/runs/<ts> --base master
py .claude/mgh-core/scripts/diff_group.py --repo <abs> --base master --branch feature-pay --checkpoints .mgh-sdr/runs/<ts>/markers --materialize .mgh-sdr/runs/<ts>/slices
py .claude/mgh-core/scripts/diff_group.py --check .mgh-sdr/runs/<ts>
py .claude/mgh-core/scripts/fanout_runner.py --tier sdr --repo <abs> --base master --checkpoints .mgh-sdr/runs/<ts>/markers --inputs-dir .mgh-sdr/runs/<ts>/slices --time-budget-ms 480000
py .claude/mgh-core/scripts/render_sdr_report.py --run-dir .mgh-sdr/runs/<ts> --repo <abs>
py .claude/mgh-core/scripts/render_sdr_report.py --check .mgh-sdr/runs/<ts>
```

## Always disclose

- **发现是 LLM 候选,非确认漏洞**;覆盖受基线投影与启发式分组上界约束。
- **接口分组是注解启发式**:未识别接口退入 standalone 单元(粒度粗、覆盖不丢);非 java web
  项目整体退化为 standalone 模式,仍可运行。
- **外部仓结论是检索时点快照**(不保证前端分支同步);同名分支缺失回退默认分支;
  不可达降级 = 前端相关检查面未覆盖(报告披露)。
- **敏感目录分歧(与 sra/srr 的显式行为分歧)**:项目目录 `.mgh-sra/sensitive_catalog.json`
  存在 → 复用;缺失 → **回退默认模板**(37 项,不收窄 6 facet——复核域漏检代价不对称)。
  来源在报告 + manifest 披露。
- **基线经字节预算投影**(32KB 默认,优先级截断):低优先级维度的存量设计细节可能未全量投影。
- **宿主 shell 超时**:opencode 全局 shell 超时 env 须启动前就绪;per-call `timeout` 是跨宿主公共
  杠杆。claude Bash per-call 上限 600000ms。
