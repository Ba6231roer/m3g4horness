---
description: Run a security design review on a branch diff: git diff base..branch, interface-dimension grouping, fan-out 6-dimension review against the existing security design (mgh-init rules), and a Simplified-Chinese report at the project root. LLM candidates needing human review. Default: current branch vs master; launcher (mgh_sdr_launch.py) is the zero-prompt preferred entry for multi-branch sweeps.
---

# /mgh-sdr — 需求分支安全设计符合性复核(security design review)

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
- `--max-interface-bytes <N>`(默认 256KB,interface 单元超限确定性拆 `-partN` 续单元)
- `--include-excluded`(兜底:不套排除集(测试树/构建产物/静态资源/锁文件/构建脚本),
  恢复全量评审;默认排除且 stdout `excluded{count,by_reason}` + 报告诚实边界披露)
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
     `external_repos[]`/`external_skipped`/`pending_approval[]`(**NEVER** 自行解析 AGENTS.md 重算;
     NEVER 读外部仓原文)。仅**已配置**于项目 `<repo>/.mgh/read-roots.json` 的声明仓才被检索。
   · **`pending_approval[]` 非空(外部仓待批)→ 宿主会话停下问用户**(逐仓绝对路径 + 用途:
     存量设计声明的外部目录,批准后经脚本持久写入项目配置,只读、以后每次 run 直接放行):
     - 同意 → 逐仓
       `py .claude/mgh-core/scripts/read_roots_config.py --target <abs> --add <abs-外部仓>`
       (脚本 stderr 打印变更)后**重跑本步同参**(已配置仓即被检索并进哨兵);
     - 拒绝 → **NEVER** 写配置,按降级继续(该仓零读取),报告如实披露。
   · **有 external_repos → 重写哨兵**(把已确认外部根写入 read_roots;subagent 跨树读放行声明根,
     Bash 搜索动词仍仅限 MGH_TARGET):
     `printf '%s' '{"domain":"mgh-sdr","target":"<abs>","out_roots":[],"read_roots":["<ext1>","<ext2>"],"v":1}' > .mgh-sdr/.active`
     (read_roots 最小化:只写 sdr_context 实际检索过的根(=已配置仓),**NEVER** 透传任意路径。)
   · 无 external_repos 且 external_skipped 非空 → 记住该披露(报告会声明)。
   · `export MGH_TARGET=<abs>`;`--dry-run` → 到此处 STOP(跑 `--check` 后移除哨兵)。
2. diff_group(Bash,确定性;pending 唯一来源):
     py .claude/mgh-core/scripts/diff_group.py --repo <abs> --base <ref> --branch <ref> --checkpoints <run-dir>/markers --materialize <run-dir>/slices
   · stdout `empty:true` → 跳过 fan-out,直接 step 4(渲染「无变更」报告);`empty:false`
     但 `total==0` 且 `excluded.count>0` = 全部文件被排除(非零 diff),stderr 有说明,照常渲染。
   · 诊断读 stdout `excluded{count,by_reason}` 与 `codegraph_stats{anchors_changed,
     anchors_upstream,chain_merged,edges_*}`(codegraph 是否生效/锚定多少,从此可观测;
     probe 失败原因在 stderr)。
   · `export MGH_SDR_CODEGRAPH=on|off`(auto 检测:`test -d "$MGH_TARGET/.codegraph" && command -v codegraph`;
     `--no-codegraph` 或检测不可用 → off)——信号经 run 目录 `run_config.json`(no_codegraph 字段,
     printf 写入,确定性)传给 dispatcher,NEVER 拼进 task 消息。
   · 校验:`py .claude/mgh-core/scripts/diff_group.py --check <run-dir>`(退出码 2 → 回退)。
3. fan-out(dispatcher;逐字转发调用,**NEVER** 手工循环):
     py .claude/mgh-core/scripts/fanout_runner.py --tier sdr --repo <abs> --base <ref> [--branch <ref>] --checkpoints <run-dir>/markers --inputs-dir <run-dir>/slices --time-budget-ms 480000 --call-timeout-s 360 --stall-timeout-s 300 [--resume]
   · 四级超时不变式(spawn 前 fail-loud,违反退出码 2):`--call-timeout-s` MUST 显式传且
     < budget×0.8,`--stall-timeout-s`(≥60) MUST < `--call-timeout-s`;带 per-call `timeout`
     ≥ `--time-budget-ms` 跑。STALLED → 报告 degraded,非 ok 单元证据在
     `<run-dir>/markers/sdr/<unit>.run.log`。
   · 软时限早退(stdout `partial:true`)→ 同参重派(resume 语义);STALLED(退出码 2)→
     停止重派,报告 degraded(诚实披露)。gate 形退出码 2 → 转述 stderr recipe,停止。
   · **快败风暴三层(配额限流形态)**:① `stalled:true` 且 `resume_state.py --check` 无磁盘异常 →
     provider 拥塞形态 → 直接同参重派(runner 已内建快败冷却与熔断前一次退避),NEVER 改写输入/
     删 marker/写微脚本;② stdout `rate_limited:true` + `rate_limited_crashes[]` → 等满一个配额
     窗口(如 10 分钟)再同参重派;③ 收尾 `failed>0` 且该单元 run.log(`markers/sdr/<unit>.run.log`)
     呈 provider 瞬断(429/rate limit/quota)→ **至多一次** 同参重派加 `--retry-failed`(自动携
     枚举器 `--include-failed`,认领删 marker),再失败接受缺口并在报告 degraded 披露。
4. render(Bash,确定性):
     py .claude/mgh-core/scripts/render_sdr_report.py --run-dir <abs-run-dir> --repo <abs>
   → `<project>/mgh-sdr-<branch>-<ts>.md`(结构:章节一简报表(行=单元,列=入口/调用链/
     前端两列/6 维度)+ 章节二问题详述(P-NN 编号)+ 章节三分支调用链图)+ `<run-dir>/sdr_manifest.json`;
     NEVER 写 openspec/
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
py .claude/mgh-core/scripts/read_roots_config.py --target <abs> --add <abs-外部仓>
py .claude/mgh-core/scripts/read_roots_config.py --target <abs> --list
py .claude/mgh-core/scripts/read_roots_config.py --target <abs> --check
py .claude/mgh-core/scripts/diff_group.py --repo <abs> --base master --branch feature-pay --checkpoints .mgh-sdr/runs/<ts>/markers --materialize .mgh-sdr/runs/<ts>/slices
py .claude/mgh-core/scripts/diff_group.py --check .mgh-sdr/runs/<ts>
py .claude/mgh-core/scripts/fanout_runner.py --tier sdr --repo <abs> --base master --checkpoints .mgh-sdr/runs/<ts>/markers --inputs-dir .mgh-sdr/runs/<ts>/slices --time-budget-ms 480000 --call-timeout-s 360 --stall-timeout-s 300
py .claude/mgh-core/scripts/render_sdr_report.py --run-dir .mgh-sdr/runs/<ts> --repo <abs>
py .claude/mgh-core/scripts/render_sdr_report.py --check .mgh-sdr/runs/<ts>
```

## Always disclose

- **发现是 LLM 候选,非确认漏洞**;覆盖受基线投影与启发式分组上界约束。
- **接口分组是注解启发式**:未识别接口/链退入目录聚簇单元(粒度粗、覆盖不丢);非 java web
  项目整体退化为 standalone 模式,仍可运行。
- **排除集(闭集)默认生效**:测试树/构建产物/静态资源/锁文件/构建脚本不进入评审;计数与
  分类在 stdout `excluded` + 报告披露,疑似误伤用 `--include-excluded` 兜底重跑。
- **外部仓结论是检索时点快照**(不保证前端分支同步);同名分支缺失回退默认分支;
  不可达降级 = 前端相关检查面未覆盖(报告披露)。简报表前端两列由 route join
  `external_repos[].route_hits[]` 三态判定(是+N 处 / 否+— / 未知+—)。
- **外部仓授权是用户拍板制**:声明仓只有写入项目配置 `.mgh/read-roots.json`(用户同意后经
  `read_roots_config.py --add` 一次写入,只读、持久)才会被检索;未配置 = 零读取跳过并进
  `pending_approval` 待批。降级区分 `not-found`(不可达)/ `unapproved`(未授权),报告披露;
  **NEVER 未经用户同意写配置**。
- **敏感目录分歧(与 sra/srr 的显式行为分歧)**:项目目录 `.mgh-sra/sensitive_catalog.json`
  存在 → 复用;缺失 → **回退默认模板**(37 项,不收窄 6 facet——复核域漏检代价不对称)。
  来源在报告 + manifest 披露。
- **基线经字节预算投影**(32KB 默认,优先级截断):低优先级维度的存量设计细节可能未全量投影。
- **宿主 shell 超时**:opencode 全局 shell 超时 env 须启动前就绪;per-call `timeout` 是跨宿主公共
  杠杆。claude Bash per-call 上限 600000ms。
