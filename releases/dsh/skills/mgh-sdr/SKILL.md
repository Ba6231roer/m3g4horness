---
name: mgh-sdr
description: Run a security design review on a branch diff: git diff base..branch, interface-dimension grouping, fan-out 6-dimension review against the existing security design (mgh-init rules), and a Simplified-Chinese report at the project root. LLM candidates needing human review. Default: current branch vs master; launcher (mgh_sdr_launch.py) is the zero-prompt preferred entry for multi-branch sweeps.
user-invocable: true
disable-model-invocation: true
---

# /mgh-sdr — 需求分支安全设计符合性复核(security design review)

> 编排器 = 你(宿主 agent):按本提示词,用自身工具(Bash / 子任务 / Read / Write)把流水线
> **跑出来**,而非写成代码。确定性逻辑已在 `diff_group.py` / `sdr_context.py` /
> `render_sdr_report.py` / `fanout_runner.py` 里,直接 `Bash` 调用即可,无需 `Read` 其源码,
> 也不要另写 `.py` 去包装或重实现。

> **输出是 LLM 候选,非已确认漏洞。引用存量控制断言存在、不断言有效。每次总结都声明。**

> **零打断优选入口**:存量设计引用外部前端仓时,首选 `py mgh-core/scripts/mgh_sdr_launch.py`
> (人/cron 入口,外部仓检索在其进程完成、宿主会话零权限确认;**仅 spawn opencode/claude 宿主**,
> dsh-only 部署直接走本壳内路径)。本壳是宿主会话内的功能等价兜底:step 1 外部仓检索在宿主
> Bash,可能触发一次权限确认(诚实披露)。

> **dsh 执行边界(替代 claude 端 `allowed-tools` 白名单)**:dsh 壳无工具白名单声明面;执行边界
> = 守卫三面执法(读/写/Bash 净网,单一判定源 `mgh-core/dsh/block_adhoc_scripts.py`,由 profile
> 受管块经 `mgh-core/dsh/mgh-guard.ts` 接线)+ 宿主 approval/sandbox。越界调用被 deny 时按守卫
> stderr 的 recipe(可执行出口清单)继续,**NEVER** 重试绕行。

> **召唤语义(dsh)**:`/mgh-sdr` 由用户显式召唤(本 skill 对模型自触发关闭);其后同一用户消息的
> 余文即参数,**step 0 从触发消息逐字读取**(dsh 无 `$ARGUMENTS` 模板)。

## Parse arguments(validate BEFORE spending tokens)

- `--base <ref>`(默认 `master`)
- `--branch <ref>`(默认当前分支;**本壳单分支**——多分支 sweep 是 launcher `--multi-branch` 专属,壳不背多分支状态)
- `--dimensions <inline-json|@path>`(默认全部 6 维;可选收窄检查面,闭集 6 键 + kebab-case 自由文本扩展;
  非法键 → 退出码 2 早停,任何 LLM 之前)
- `--run-dir <dir>`(可选:显式 run 目录,默认 `<project>/.mgh-sdr/runs/<YYYYMMDD_HHMMSS>/`)
- `--max-standalone-bytes <N>`(默认 64KB,standalone 簇归并上限)、
  `--max-interface-bytes <N>`(默认 256KB,interface 单元上限)——判据是**切片渲染后的实测
  字节**,非估算。单元超预算按序三级处置:① 多文件单元无损重切为 `-partN` 续单元(内容与
  hunk 一份不丢);② 单文件残渣截断描述性上下文块(注解上下文 / 符号表,切片内留可见截断标记,
  diff 正文与定位头绝不截);③ 仍超预算则**退出码 2 且零派发**(不写任何切片与 grouping.json,
  零子代理被派出,stderr 给出单元 id/上限/实测字节/最大贡献文件与出口)
- `--include-excluded`(兜底:不套排除集(测试树/构建产物/静态资源/锁文件/构建脚本),
  恢复全量评审;默认排除且 stdout `excluded{count,by_reason}` + 报告诚实边界披露)
- `--no-codegraph`(可选:把**信号**标为 off——不传时由 `sdr_context.py` 自动探测:仓库有
  `<project>/.codegraph/` 且 PATH 有 `codegraph` 才 on。该开关**只影响信号**,不改分组:分组阶段
  恒按仓库实际情况自行探测,故传它之后子评审按「单元可能被切开」的保守口径判,而分组本身不变)
- `--dry-run`(默认 off;仅跑 step 0–1(sdr_context + diff_group materialize)+ `--check`,不 fan-out 不渲染)

`--help` → 打印参数表后 **STOP**(零 token、零解析);**无任何参数** → 按参数表逐项标注的
默认集直接进入编排流(base=`master` / branch=当前分支 / 全 6 维),**NEVER** 因缺参停止索取输入。

## Orchestrator discipline(铁律)

**`py` = 规范 token**:本壳所有示例中的 `py` = step 0 探测选定的解释器,实际执行时**逐字
替换**为选中者;选中非 `py` 后所有调用 NEVER 再出现 `py`,NEVER 对流水线脚本逐个换解释器名
试错。

**硬边界(`NEVER`)**:(a) `Write` 任何脚本扩展名(`.py`/`.ps1`/`.sh`/`.ts`/…)——大编排器或一次性
微脚本;(b) 把**内联代码喂进解释器**去内省/重派生产物——三种喂入形态全违纪:`py -c`/`python -c`、
heredoc(`py - <<EOF`…`EOF`,含 `… | python3 - <<'EOF'`)、here-string(`py - <<< '…'`),
heredoc/here-string **按形态即拦**;合法出口是 **stdout 直消费**(读 `.mgh-sdr/**` 亦然,NEVER 经
内联代码或文件中转重派生);(c) `Read` 叶子 `.py` 源码(报错看 stderr,不读源码)。
运行域守卫(`block-adhoc-scripts`)确定性兜底。

**fan-out 刚性三元组**:`[diff_group pending[]::字段] → fanout_runner --tier sdr → [drafts/*.json + markers]`;
路径 = `diff_group` stdout `pending[]` 每项**绝对** `input_path`/`draft_path`/`done_marker`/
`failed_marker`/`baseline_path`/`external_dir`(逐字透传给 dispatcher,dispatcher 逐字填进 subagent
task)——**NEVER** 自拼路径、**NEVER** `py -c` 算路径、**NEVER** 相对路径。

**边界校验**:每步后跑产出者 `--check`;失败(退出码 2)→ 回退重跑该步,**不带着破损产物继续**。
报告/manifest **NEVER** 写进 `openspec/`。

**长跑 Bash 超时纪律**:fanout_runner 与 render 调用传慷慨 per-call `timeout`(毫秒);claude 宿主
建议 `--time-budget-ms 480000`(claude Bash 600s 上限 × 0.8);opencode 宿主建议 720000(900s × 0.8)。

> **dsh 派发面(已接线)**:step 3 扇出经 `fanout_runner --tier sdr` 在 dsh 派发——spawn 形
> `dsh --profile mgh --patch mgh-core/dsh/tiers/sdr.yml -`(tier 装载文件由 install 生成落该目录、
> 任务正文经子进程 env 投递);装载缺件在 spawn 前 fail-loud(退出码 2 + recipe、零子进程)。
> 进度语义不变:磁盘 marker、可跨会话续跑(见「中断恢复」),**NEVER** 用
> 内联执行假装派发、**NEVER** 自写循环替代 dispatcher。

## Orchestration flow

```
0. parse + 解释器探测 + 运行域声明 + 哨兵预武装
   · **解释器探测**(一次定型;本壳示例中 `py` 的语义见 Orchestrator discipline):
     `for c in py python python3; do "$c" --version >/dev/null 2>&1 && echo "PYPROBE $c OK $("$c" --version 2>&1)" || echo "PYPROBE $c UNAVAILABLE"; done`
     ——取 `PYPROBE <c> OK` 行中**第一个**版本 ≥3.10 者为本次 run 的解释器(判据 = 退出码 0
     **且**版本达标,Store stub rc 49 与 2.x 均落选);全部不达标 → 早停披露(转述探测输出 +
     ≥3.10 要求)并按下方干净停止规则 `rm <repo>/.mgh-sdr/.active`(此时哨兵可能尚未武装,
     rm 无操作即可)。探测结果 **NEVER** 落盘(`run_config.json`/哨兵 schema 不动)。
   · `Bash: export MGH_SDR_ACTIVE=1`;解析 run 目录(默认 `<project>/.mgh-sdr/runs/<ts>/`;
     `mkdir -p`)。
   · **零参默认路径**:`--base`/`--branch` 整体省略(脚本 argparse 兜底 master/当前分支),
     run 目录命名只用 `<ts>` 不含分支;后续步骤与报告消费 step 1 stdout 已解析的 `branch`/`base`
     字段,NEVER 在壳里 `git rev-parse` 猜分支。
   · **预武装哨兵**(先于 step 1 唤醒守卫,闭合「step 1 参数即错 → 哨兵未写 → 守卫整段休眠」
     窗口;确定性脚本副作用,**NEVER** 手执行 `printf` 配方写哨兵):
     `py mgh-core/scripts/resume_sdr_state.py --run-dir <abs-run-dir> --repo <abs> --arm-sentinel`
     (同 target 重复执行 = no-op,已细化的 `read_roots[]` 绝不清空)。
   · **干净停止**(step 1 成功前的任何终止路径)MUST 移除残哨:`rm <repo>/.mgh-sdr/.active`
     ——NEVER 留预武装残哨进入日常开发。
   · 哨兵的**细化覆盖**(read_roots = 实际检索根)与 codegraph 信号(`run_config.json`)仍由
     step 1 的 `sdr_context.py` 确定性 co-write(脚本一跑必在)。
   · codegraph 信号由 step 1 的 `sdr_context.py` **自行探测**(仓库有 `.codegraph/` 且 PATH 有
     `codegraph` 才 on;与 `diff_group.py` 分组同一谓词)——本壳**不做**第二份探测、**NEVER** 手写该
     信号;用户显式要求把信号标 off 时给 step 1 加 `--no-codegraph`(该 flag **只**改信号:分组
     仍按仓库实际情况走,子评审因此按保守口径判)。
1. sdr_context(Bash,确定性;外部仓检索在此步、宿主进程内——**可能一次权限确认,诚实披露**):
     py mgh-core/scripts/sdr_context.py --repo <abs> --run-dir <abs-run-dir> [--base <ref>] [--branch <ref>] [--dimensions <json>] [--no-codegraph]
   · **stdout 直消费**(Bash 工具返回值即全部 stdout,最后一行是 JSON,在你的推理里解析;
     **NEVER** 文件中转/内联代码重派生):关注字段 `baseline_path`/`baseline_truncated`/
     `sensitive_catalog`/`sensitive_catalog_source`/`external_repos[]`/`external_skipped`/
     `pending_approval[]`(**NEVER** 自行解析 AGENTS.md 重算;NEVER 读外部仓原文);stdout 过大 →
     同参加 `--summary` 重跑(投影视图:关键量 + 摘要级 `external_repos[]`,落盘产物逐字不变);
     要瞄产物结构 → `py mgh-core/scripts/describe_artifact.py --in <abs-json> --keys`
     (或 `--field a.b.c` / `--sample N`)。仅**已配置**于项目 `<repo>/.mgh/read-roots.json`
     的声明仓才被检索。
   · **本步同时写出**(脚本副作用,失败退出码 2,不静默):哨兵 `<repo>/.mgh-sdr/.active`
     (`target` = 脚本 stdout 的 Windows 原生 `repo`;**read_roots 最小化** = 实际检索过的根 ∪
     操作者 `--read-root`,**NEVER** 透传任意路径)与 `<run-dir>/run_config.json`
     (**唯一载荷** `no_codegraph`;起始态字段 NEVER 写入)。
   · **`pending_approval[]` 非空(外部仓待批)→ 宿主会话停下问用户**(逐仓绝对路径 + 用途:
     存量设计声明的外部目录,批准后经脚本持久写入项目配置,只读、以后每次 run 直接放行):
     - 同意 → **推荐**:step 1 重跑时一条命令闭环批准 + 检索(可重复传,逐仓一个):
       `py mgh-core/scripts/sdr_context.py --repo <abs> --run-dir <abs-run-dir> [--base <ref>] [--branch <ref>] --approve-external <abs-外部仓>`
       ——该 flag **仅在宿主会话获用户明示同意后**传入;脚本与编排器 NEVER 自行批准。等价出口 =
       先逐仓 `py mgh-core/scripts/read_roots_config.py --target <abs> --add <abs-外部仓>`
       再同参重跑 step 1(两条路径最终都持久写入项目配置,只读、以后每次 run 直接放行);
     - 拒绝 → **NEVER** 写配置,按降级继续(该仓零读取),报告如实披露。
   · 无 external_repos 且 external_skipped 非空 → 记住该披露(报告会声明)。
   · `export MGH_TARGET=<abs>`;`--dry-run` → 到此处 STOP(跑 `--check` 后移除哨兵)。
2. diff_group(Bash,确定性;pending 唯一来源):
     py mgh-core/scripts/diff_group.py --repo <abs> --base <ref> --branch <ref> --checkpoints <run-dir>/markers --materialize <run-dir>/slices [--max-standalone-bytes <N>] [--max-interface-bytes <N>] [--include-excluded]
   · stdout `pending[]` **直消费**(Bash 工具返回值即全部 stdout);过大 → 同参加 `--summary`
     重跑(投影视图:计数摘要 + 当页 `pending[]`;物化照常执行、落盘产物逐字不变),分页仅由
     `--offset/--limit` 驱动;要瞄结构 → `py mgh-core/scripts/describe_artifact.py
     --in <run-dir>/grouping.json --keys`。
   · stdout `empty:true` → 跳过 fan-out,直接 step 4(渲染「无变更」报告);`empty:false`
     但 `total==0` 且 `excluded.count>0` = 全部文件被排除(非零 diff),stderr 有说明,照常渲染。
   · 诊断读 stdout `excluded{count,by_reason}` 与 `codegraph_stats{anchors_changed,
     anchors_upstream,chain_merged,edges_*}`(codegraph 是否生效/锚定多少,从此可观测;
     probe 失败原因在 stderr)。
   · 校验:`py mgh-core/scripts/diff_group.py --check <run-dir>`(退出码 2 → 回退)。
3. fan-out(dispatcher;逐字转发调用,**NEVER** 手工循环):
     py mgh-core/scripts/fanout_runner.py --tier sdr --repo <abs> --base <ref> [--branch <ref>] --checkpoints <run-dir>/markers --inputs-dir <run-dir>/slices --time-budget-ms 720000 --call-timeout-s 540 --stall-timeout-s 300 [--resume]
   · 四级超时不变式(spawn 前 fail-loud,违反退出码 2):`--call-timeout-s` MUST 显式传且
     < budget×0.8,`--stall-timeout-s`(≥60) MUST < `--call-timeout-s`;带 per-call `timeout`
     ≥ `--time-budget-ms` 跑。STALLED → 报告 degraded,非 ok 单元证据在
     `<run-dir>/markers/sdr/<unit>.run.log`。
   · 软时限早退(stdout `partial:true`)→ 同参重派(resume 语义);STALLED(退出码 2)→
     停止重派,报告 degraded(诚实披露)。gate 形退出码 2 → 转述 stderr recipe,停止。
   · **快败风暴三层(配额限流形态)**:① `stalled:true` 且
     `py mgh-core/scripts/diff_group.py --check <run-dir>` 退出码 0(分组产物完好:
     grouping.json + slices + markers;该检查校验**产物完整性**、**非**运行进度自洽性) →
     provider 拥塞形态 → 直接同参重派(runner 已内建快败冷却与熔断前一次退避),NEVER 改写输入/
     删 marker/写微脚本;② stdout `rate_limited:true` + `rate_limited_crashes[]` → 等满一个配额
     窗口(如 10 分钟)再同参重派;③ 收尾 `failed>0` 且该单元 run.log(`markers/sdr/<unit>.run.log`)
     呈 provider 瞬断(429/rate limit/quota)→ **至多一次** 同参重派加 `--retry-failed`(自动携
     枚举器 `--include-failed`,认领删 marker),再失败接受缺口并在报告 degraded 披露。
4. render(Bash,确定性):
     py mgh-core/scripts/render_sdr_report.py --run-dir <abs-run-dir> --repo <abs>
   → `<project>/mgh-sdr-<branch>-<ts>.html`(**自包含单文件**:样式/脚本/数据全内嵌,浏览器
     双击即读、离线可用;结构:头部 + 章节一简报表(行=单元,列=入口/调用链/前端两列/维度,
     severity/维度筛选 + P-NN 页内跳转)+ 章节二问题详述 + 章节三内嵌 SVG 分支调用链图(缩放平移))
     + `<run-dir>/sdr_manifest.json` + `<run-dir>/sdr_report_data.json`(canonical 数据文件,
     下游程序消费它;历史 `.md` 报告不迁移不回写;源文件链接在部分浏览器可能下载而非打开);
     NEVER 写 openspec/
   · 校验:`py mgh-core/scripts/render_sdr_report.py --check <run-dir>`。
5. 收尾:打印报告绝对路径 + counts(stdout manifest 字段,**NEVER** `py -c` 挖 JSON);
   声明诚实边界;`rm .mgh-sdr/.active`(完成态/干净停止)。
```

## 中断恢复(崩溃 / 压缩后 / 新会话)

恢复**必须带同一个 run 目录**(新建目录 = 已完成单元的 marker 不在其中 = 全部重做):

     py mgh-core/scripts/resume_sdr_state.py --run-dir <abs-run-dir>

读 stdout 的 `step`(语义 = **当前待办步**)/ `next_action` / `discipline_reminders` / `notes`,
按该步纪律(闸门 → 路径配方 → 硬边界)继续即接上流水线。进度与纪律**纯从磁盘重派生**,与对话
记忆是否保留无关。选中解释器不确定(压缩/新会话)→ **重跑 step 0 探测命令**重建该事实(单条、
廉价),NEVER 逐命令换解释器试错。`--run-dir` 必填;推不出时脚本 fail-loud,**NEVER** 猜步骤。run 进行中
(`step ∈ group|fanout|render`)哨兵却缺失 = 守卫休眠 → `--check` 退出码 2 + re-arm recipe:

     py mgh-core/scripts/resume_sdr_state.py --run-dir <abs-run-dir> --check
     py mgh-core/scripts/resume_sdr_state.py --run-dir <abs-run-dir> --rearm-sentinel

### Stage → component map

| Stage | How | Asset |
|---|---|---|
| 基线投影 + 外部仓检索 + 敏感目录 | **script** | `core/scripts/sdr_context.py` |
| diff 采集 + 接口分组 + slice 物化 | **script** | `core/scripts/diff_group.py` |
| per-unit 复核扇出 | dispatcher `fanout_runner --tier sdr` | `core/prompts/fragments/fanout/sdr-task.md` + agent `sdr-review-fanout` |
| 汇总渲染 | **script** | `core/scripts/render_sdr_report.py` |
| stage boundary check | **script** | `sdr_context`/`diff_group`/`render_sdr_report` `--check` |

### Deterministic invocation (Bash)

```bash
py mgh-core/scripts/sdr_context.py --repo <abs> --run-dir .mgh-sdr/runs/<ts> --base master
py mgh-core/scripts/sdr_context.py --repo <abs> --run-dir .mgh-sdr/runs/<ts> --approve-external <abs-外部仓>
py mgh-core/scripts/describe_artifact.py --in .mgh-sdr/runs/<ts>/grouping.json --keys
py mgh-core/scripts/resume_sdr_state.py --run-dir .mgh-sdr/runs/<ts> --repo <abs> --arm-sentinel
py mgh-core/scripts/read_roots_config.py --target <abs> --add <abs-外部仓>
py mgh-core/scripts/read_roots_config.py --target <abs> --list
py mgh-core/scripts/read_roots_config.py --target <abs> --check
py mgh-core/scripts/diff_group.py --repo <abs> --base master --branch feature-pay --checkpoints .mgh-sdr/runs/<ts>/markers --materialize .mgh-sdr/runs/<ts>/slices --max-standalone-bytes 65536 --max-interface-bytes 262144
py mgh-core/scripts/diff_group.py --check .mgh-sdr/runs/<ts>
py mgh-core/scripts/fanout_runner.py --tier sdr --repo <abs> --base master --checkpoints .mgh-sdr/runs/<ts>/markers --inputs-dir .mgh-sdr/runs/<ts>/slices --time-budget-ms 720000 --call-timeout-s 540 --stall-timeout-s 300
py mgh-core/scripts/render_sdr_report.py --run-dir .mgh-sdr/runs/<ts> --repo <abs>
py mgh-core/scripts/render_sdr_report.py --check .mgh-sdr/runs/<ts>
py mgh-core/scripts/resume_sdr_state.py --run-dir <abs-run-dir>
py mgh-core/scripts/resume_sdr_state.py --run-dir <abs-run-dir> --check
py mgh-core/scripts/list_sdr_steps.py --step fanout
```

## Always disclose

- **零参默认执行口径**:不带参数 = 按 base=`master` / 当前分支 / 全 6 维直接跑完整流水线
  (含 fan-out);低成本试跑出口 = `--dry-run`(仅 step 0–1 + `--check`,不派发不渲染)。
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
- **宿主 shell 超时**:dsh per-call 超时 = 工具调用显式毫秒 `timeout` 入参(受部署上限收敛);opencode 全局 shell 超时 env 须启动前就绪;per-call `timeout` 是跨宿主公共
  杠杆。claude Bash per-call 上限 600000ms。
- **报告形态是自包含单文件 HTML**(样式/脚本/数据全内嵌,离线双击可读):报告数据同步落
  `<run-dir>/sdr_report_data.json`,下游程序消费该数据文件(NEVER 去解析 HTML);历史 `.md`
  报告不迁移不回写;源文件链接是仓内相对路径,部分浏览器对 `.java` 等扩展名可能下载而非打开。
- **launcher 重跑会新建 run 目录**:`mgh_sdr_launch.py` 无 `--resume` / `--run-dir`,每次调用按当前
  时刻新建 `<repo>/.mgh-sdr/runs/<ts>-<branch>/`,上一次 run 的 marker **不被复用**——**NEVER 宣称
  「重跑 launcher 即续跑」**。续跑由调用方带着**同一个** run 目录路径回来经 `resume_sdr_state.py`
  进行(见「中断恢复」)。
- **`--dimensions` 收窄当前不下发**:该开关只在 `sdr_context` 做闭集校验,**不**进入评审单元的任务
  消息——即收窄后的检查面**未生效**,评审仍按全部 6 维进行。
