<!--
  mgh-srr stage-flow detail (steps 0-8, dsh face). Install mirrors to <mgh-core>/prompts/fragments/srr-flow-dsh.md.
  Loaded lazily by the orchestrator shell (REQUIRED SUB-SKILL) before executing any flow step.
-->

## Orchestration flow

```
0. parse + self-check(宿主 agent/model 可用;否则 STOP 给修复提示)
   · **起步**:`Bash: export MGH_SRR_ACTIVE=1`(声明运行域;激活 block-adhoc-scripts 守卫,供 hook 判树/可观测)
   · **哨兵(磁盘激活信号,dsh 可靠激活兜底)**:`mkdir -p .mgh-srr && printf '%s' '{"domain":"mgh-srr","target":"","out_roots":[],"v":1}' > .mgh-srr/.active`
     (cwd = 项目根;step 0 仅激活,target 待 r1 后填)。守卫激活 = env **或** 该哨兵(dsh shim 进程不继承 mid-session env
     → 哨兵兜底)。完成态(step 7)/ 干净停止 `rm .mgh-srr/.active`。
1. r1 ingest(Bash,确定性):
     py mgh-core/scripts/ingest_requirements.py --doc <path|dir|-> [--text <str>] [--rules <path>] [--focus <inline-json|path>] [--sensitive-catalog <inline-json|@path|->] [--split] [--out <dir>] --materialize <out-dir>/inputs/augment [--offset N] [--limit N] [--max-unit-bytes B] [--orch-budget-bytes B] [--dry-run] [--no-interactive]
   → stdout = **slim 分页**摘要(`--materialize`);全量 sra-shape `change_context.json` 仍落 <out-dir>/change_context.json 供 a2/a4/render 读
   · 读该 **slim stdout** 取:`pending[]`(每项绝对 draft_path/done_marker/input_path/bytes/oversize)、`clarify_path`、`project_root`、
     `rules_source`、`memory_source`、`has_memory`、`requirements_count`、`candidate_controls_count`、`degraded`、`focus`、`sensitive_catalog`、
     `offset`/`limit`/`effective_limit`/`shrunk`(**NEVER** 整份读 `change_context.json`、**NEVER** `py -c` 重挖)。
     `focus.directive`(简体中文句子;`focus: null` 时缺省)**逐字透传**进 a2/a3 subagent task(NEVER 重解析 / NEVER 自拼);
     `sensitive_catalog`(含 `directive`+`items[]`;`null` 时缺省)**逐字透传**进 a2/a3 subagent task(NEVER 重算 / NEVER 自拼)
   · **翻页**(单页 > `--orch-budget-bytes` 时 stdout `shrunk:true`):按 `offset` += `effective_limit` 重派 ingest 取下一页
     (翻页循环由编排器,**NEVER** wrapper `.py`);`--resume` 跳过已 `.done` 单元
   · **MGH_TARGET**:取该 stdout `project_root`(绝对项目根)→ `export MGH_TARGET=<project_root>`;
     **重写哨兵 target**(dsh 子树守卫就绪):`printf '%s' '{"domain":"mgh-srr","target":"<project_root>","out_roots":[],"v":1}' > .mgh-srr/.active`
     (project_root 来自 ingest_requirements stdout,Windows 原生;**NEVER** bash `pwd`)。
   · **codegraph 检测**(发起任何 LLM subagent 之前;零 LLM token):
     `Bash: if test -d "$MGH_TARGET/.codegraph" && command -v codegraph >/dev/null 2>&1; then echo on; else echo off; fi`
     → `codegraph=on|off`。默认 `auto`(可用即启用);传 `--no-codegraph` 或检测不可用 → `codegraph=off`。该信号
     **逐字透传**进 a2/a3 subagent task 输入。codegraph 是宿主 MCP 工具 / 外部 CLI,**不** import、**不**新增 `pip`
     依赖;`codegraph_explore`(MCP)/ `codegraph explore`(Bash)**均不**命中 block-adhoc-scripts 拦截面——故 **无 hook 改动**。
   · 校验:`py ingest_requirements.py --check <out-dir>/change_context.json`(退出码 2 → 回退重跑)。
     `--rules` 的 inventory well-formed 在 ingest 内自检(畸形即退出 2)。
   · `--dry-run`:到此处 STOP(仅 change_context.json + stdout 摘要,不进 a2–a4/render)
2. a2 clarify(复用 1 subagent,单上下文扫全文):
     spawn sra-clarify({change_context 摘要 + memory + 维度目录路径 + clarify_path(绝对) + focus.directive(逐字,若非 null) + sensitive_catalog(逐字,若非 null) + codegraph 信号(逐字)})
     → 恰好写 clarify_path:`{"clarifications":[...]}`
     · `codegraph=on`(可选 / codegraph-gated / non-fatal):sra-clarify 经 codegraph 预解析**减问**;`codegraph=off` 时无预解析、行为等价引入前
3. 批量澄清交互(dsh 原生批量问 ask_user_question;无问答通道 → 文件回填兜底):
   · 读 clarify_path 的 clarifications[](用 read 工具或 describe_artifact;NEVER `py -c`)
   · `--no-interactive` → 全部取 default_guess;否则**暂停一次**、经宿主 `ask_user_question` 一次性批量呈现
     全部 clarifications(每条带 default_guess,用户可秒批/改/跳过);headless 或问答通道不可用时,改为渲染成
     人读 `<out-dir>/clarifications.md`(每条:question + why_it_matters + default_guess + 留空 answer),**暂停**等用户回填 answer 字段
   · 收答案(或用默认)→ 写 answers.json → `py merge_memory.py --memory <MGH_TARGET>/.mgh-sra/business_context.json --answers <answers.json>`
   · 无澄清 → 跳过本步
4. a3 augment(复用 subagent;per-unit 扇出):
   for each item in pending[] 当前页(读 r1 slim stdout;逐字透传 input_path/draft_path/done_marker):
     spawn sra-augment(隔离上下文;给:该单元的 **input_path**(subagent **自读**,含 requirements[] + 业务面 + candidate_controls
       + memory,≤ `--max-unit-bytes`) + 维度目录路径 + focus.directive(逐字,若非 null) + sensitive_catalog(逐字,若非 null)
       + draft_path(绝对) + done_marker(绝对) + codegraph 信号(逐字))
     → 恰好写 draft_path + touch done_marker
     · oversize 单元(`oversize:true`):recipe `--split` 切更细标题 / 收窄文档(单元**不**切分——评审原子)
     · `codegraph=on`(可选 / codegraph-gated / non-fatal / bounded):sra-augment 对已三信号命中、已推荐控制的缺口做
       call-path advisory 确认(写 `recommended_control.call_path`);`codegraph=off` / 无 `--rules` → 不产 `call_path`
5. a4 consistency(复用 subagent,除非 --skip-consistency):
     spawn sra-consistency({drafts_dir = <out-dir>/drafts(绝对)}) → 原地覆写各 draft 定稿
6. r2 render(Bash,确定性):
     py mgh-core/scripts/render_report.py --drafts-dir <out-dir>/drafts --out <out-dir>
   → security_review_report.md + srr_manifest.json;NEVER 写 openspec/
   · render 读 `change_context.focus`:`focus` 非 null 时报告头注聚焦维度 + `srr_manifest.json` 记 `focus`(维度列表)
     + `boundaries[]` 增一条「本次仅扫描聚焦维度,范围外维度未覆盖」;`focus: null` 时无额外行/边界
   · render 读 `change_context.sensitive_catalog`:非 null 时报告头注目录覆盖范围(字段数 + 类别)+
     `srr_manifest.json` 记 `sensitive_catalog`(`counts`+`source`)+ `boundaries[]` 增一条「据目录逐项查脱敏,
     目录外仅 6 facet」;`sensitive_catalog: null` 时无额外行/边界
   · 校验:`py render_report.py --check <out-dir>`(报告/manifest shape + 无 openspec/ 被触及;退出码 2 → 回退)
   · 校验:`py merge_memory.py --check <MGH_TARGET>/.mgh-sra/business_context.json`
7. 打印产物路径 + 边界声明
   · counts.call_path_confirmed/call_path_residual 取自各 draft(经 describe_artifact 合法瞄结构;NEVER `py -c`);codegraph=off 时二者均 0
   · **收尾移除哨兵**:`rm .mgh-srr/.active`(run 完成;避免残留哨兵锁死日常开发)
```

