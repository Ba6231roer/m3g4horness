<!--
  mgh-sra stage-flow detail (steps 0-7, dsh face). Install mirrors to <mgh-core>/prompts/fragments/sra-flow-dsh.md.
  Loaded lazily by the orchestrator shell (REQUIRED SUB-SKILL) before executing any flow step.
-->

## Orchestration flow

```
0. parse + self-check(宿主 agent/model 可用;否则 STOP 给修复提示)
   · **起步**:`Bash: export MGH_SRA_ACTIVE=1`(声明运行域;激活 block-adhoc-scripts 守卫,供 hook 判树/可观测)
   · **哨兵(磁盘激活信号,dsh 可靠激活兜底)**:`mkdir -p .mgh-sra && printf '%s' '{"domain":"mgh-sra","target":"","out_roots":[],"v":1}' > .mgh-sra/.active`
     (cwd = 项目根;step 0 仅激活,target 待 a1 后填)。守卫激活 = env **或** 该哨兵(dsh shim 进程不继承 mid-session env
     → 哨兵兜底)。完成态(step 7)/ 干净停止 `rm .mgh-sra/.active`。
1. a1 prepare(Bash,确定性):
     py mgh-core/scripts/prepare_augment.py --change <change> [--rules <path>] [--focus <inline-json|path>] [--sensitive-catalog <inline-json|@path|->] --materialize <change-root>/.mgh-sra/inputs/augment [--offset N] [--limit N] [--max-unit-bytes B] [--orch-budget-bytes B] [--dry-run] [--no-interactive]
   → stdout = **slim 分页**摘要(`--materialize`);全量 `change_context.json` 仍落 <change-root>/.mgh-sra/change_context.json 供 a2 单上下文扫全变更读
   · 读该 **slim stdout** 取:`pending[]`(每项绝对 draft_path/done_marker/input_path/bytes/oversize)、`clarify_path`、
     `project_root`、`focus`、`sensitive_catalog`、`requirements_count`、`candidate_controls_count`、`has_memory`、
     `offset`/`limit`/`effective_limit`/`shrunk`(**NEVER** 整份读 `change_context.json`、**NEVER** `py -c` 重挖)。
     `focus` 为 `{dimensions[],facets{},directive}` 或 `null`;`focus.directive`(简体中文句子)是收窄指令——**逐字透传**
     进 a2/a3 subagent task(NEVER 重解析 / NEVER 自拼);`focus: null` = 全 9 维度,不注入指令。`sensitive_catalog` 为
     `{directive,items[],counts{},...}` 或 `null`;**逐字透传**(含 `directive`+`items[]`)进 a2/a3 subagent task
     (NEVER 重算 / NEVER 自拼);`sensitive_catalog: null` = 仅现行 6 facet,不注入目录
   · **翻页**(单页 > `--orch-budget-bytes` 时 stdout `shrunk:true`):按 `offset` += `effective_limit` 重派
     `prepare_augment` 取下一页(翻页循环由编排器,**NEVER** wrapper `.py`);`--resume` 经各 `done_marker` 跳过已 `.done` capability
   · **MGH_TARGET**:取该 stdout `project_root`(绝对项目根)→ `export MGH_TARGET=<project_root>`;
     **重写哨兵 target**(dsh 子树守卫就绪):`printf '%s' '{"domain":"mgh-sra","target":"<project_root>","out_roots":[],"v":1}' > .mgh-sra/.active`
     (project_root 来自 prepare_augment stdout,Windows 原生;**NEVER** bash `pwd`)。
   · **codegraph 检测**(发起任何 LLM subagent 之前;零 LLM token):
     `Bash: if test -d "$MGH_TARGET/.codegraph" && command -v codegraph >/dev/null 2>&1; then echo on; else echo off; fi`
     → `codegraph=on|off`。默认 `auto`(可用即启用);传 `--no-codegraph` 或检测不可用 → `codegraph=off`。该信号
     **逐字透传**进 a2/a3 subagent task 输入(仅 `codegraph=on` 时:sra-clarify 启用 advisory 预解析减问、sra-augment
     启用外科式上下文 + 对已推荐控制做 call-path advisory 确认)。codegraph 是宿主 MCP 工具 / 外部 CLI,**不** import、
     **不**新增 `pip` 依赖;`codegraph_explore`(MCP)/ `codegraph explore`(Bash)**均不**命中 block-adhoc-scripts
     拦截面(非 `py -c`/`Write *.py`/子树外写)——故 **无 hook 改动**。
   · 校验:有 `--rules` 时 `py prepare_augment.py --check <rules-path>`(退出码 2 → 回退或 advisory 无控制继续)
   · `--dry-run`:到此处 STOP(仅 change_context.json + stdout 摘要,不进 a2–a5)
2. a2 clarify(1 subagent,单上下文扫全变更):
     spawn sra-clarify({change_context 摘要 + memory + 维度目录路径 + clarify_path(绝对) + focus.directive(逐字,若非 null) + sensitive_catalog(逐字,若非 null) + codegraph 信号(逐字)})
     → 恰好写 clarify_path:`{"clarifications":[...]}`
     · `codegraph=on`(可选 / codegraph-gated / non-fatal):sra-clarify 经 codegraph 预解析(callers→角色 / callees→敏感
       字段 / domain-sibling→鉴权范式)**减问**——仅减问(codegraph-sourced 事实优先级低于用户/代码/已记,不覆盖)、
       **不增写** codegraph 派生记忆;`codegraph=off` 时无预解析、行为等价引入前
3. 批量澄清交互(dsh 原生批量问 ask_user_question;无问答通道 → 文件回填兜底):
   · 读 clarify_path 的 clarifications[](用 read 工具或 describe_artifact;NEVER `py -c`)
   · `--no-interactive` → 全部取 default_guess;否则**暂停一次**、经宿主 `ask_user_question` 一次性批量呈现
     全部 clarifications(每条带 default_guess,用户可秒批/改/跳过);headless 或问答通道不可用时,改为渲染成
     人读 `<change-root>/.mgh-sra/clarifications.md`(每条:question + why_it_matters + default_guess + 留空 answer),**暂停**等用户回填 answer 字段
   · 收答案(或用默认)→ 写 answers.json → `py merge_memory.py --memory <MGH_TARGET>/.mgh-sra/business_context.json --answers <answers.json>`
   · 无澄清 → 跳过本步
4. a3 augment(per-capability 扇出):
   for each item in 当前页 pending[](读 a1 slim stdout;逐字透传 input_path/draft_path/done_marker):
     spawn sra-augment(隔离上下文;给:该 cap 的 **input_path**(subagent **自读**,含 requirements[] + 业务面
       + candidate_controls 切片 + memory,≤ `--max-unit-bytes`)+ 维度目录路径 + focus.directive(逐字,若非 null)
       + sensitive_catalog(逐字,若非 null) + draft_path(绝对) + done_marker(绝对) + codegraph 信号(逐字))
     → 恰好写 draft_path + touch done_marker
     · oversize capability(`oversize:true`):recipe 分变更跑 / `--focus` 收窄维度(capability **不**切分——a3 原子)
     · `codegraph=on`(可选 / codegraph-gated / non-fatal / bounded):sra-augment 对**已三信号命中、已推荐控制**的缺口做
       call-path advisory 确认(写 `recommended_control.call_path`;`confirmed` 不伪造、不覆盖代码/用户断言;超预算 → 每缺口
       top-1 + `confirmed:null` + 标「部分未确认」)+ data-flow/liveness/domain-sibling advisory 改善 `risk`/`note`/`reason`;
       `codegraph=off` / 无 `--rules` → 不产 `call_path`、无 advisory,三信号主流程不受影响
5. a4 consistency(除非 --skip-consistency;1 subagent):
     spawn sra-consistency({drafts_dir = <change-root>/.mgh-sra/drafts(绝对)}) → 原地覆写各 draft 定稿
6. a5 merge(Bash,确定性):
     py mgh-core/scripts/merge_augment.py --change <change>
   → 受管块幂等追加进 specs/<cap>/spec.md + tasks.md
   · 校验:`py merge_augment.py --check <change>`(仅动受管块;退出码 2 → 回退)
   · 校验:`py merge_memory.py --check <MGH_TARGET>/.mgh-sra/business_context.json`
7. 写 sra_manifest.json(**focus** + **sensitive_catalog** + counts 含 `call_path_confirmed`/`call_path_residual` + boundaries[])+ 打印产物路径 + 边界声明
   · `focus` = 本次聚焦的维度列表(取自 `change_context.focus.dimensions`;`null` = 全 9 维度)
   · `focus` 非 null 时,`boundaries[]` 增一条:**「本次仅扫描聚焦维度,范围外维度未覆盖」**(防用户误以为全量);
     `focus: null` 时无该额外边界
   · `sensitive_catalog` = 本次生效目录的 `counts{items,full,partial,categories}` + `source`(取自
     `change_context.sensitive_catalog`;`null` = 未用目录,仅 6 facet);非 null 时 `boundaries[]` 增一条:
     **「据公司敏感数据目录逐项查脱敏,目录外字段类型仅按现行 6 facet 识别」**(防误以为目录穷尽所有敏感字段)
   · `counts.call_path_confirmed`/`call_path_residual` 取自各 draft `recommended_control.call_path.confirmed` 计数
     (经 `describe_artifact.py` 合法瞄结构出口,**NEVER** `py -c`);`codegraph=off` 时二者均 0
   · **请求上下文预算命中**(取自 a1 slim stdout + a2/a4 信号):有 `oversize:true` capability / `shrunk:true` 页 / a2·a4 聚合超
     `--max-aggregate-bytes` 时,`boundaries[]` 各增一条披露;无命中则无该类边界。a3 per-capability 输入 ≤ `--max-unit-bytes`、
     编排器单页 ≤ `--orch-budget-bytes` 确定性有界
   · **收尾移除哨兵**:`rm .mgh-sra/.active`(run 完成;避免残留哨兵锁死日常开发)
```

