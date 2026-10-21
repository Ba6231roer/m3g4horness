> **人话序** 现象:企业内网里 `/mgh-init` 的 scout 层(把 regex 没扫到的源码分批交给子代理深读、找自研安全控制)一直靠「脚本另起子进程」派发;在企业的登录鉴权体系下,子进程几乎都起不来(维护者确认 99% 不可用)。前六个 change 已经把地基铺好——守卫插件能在新宿主上加载、权限询问不再弹、确定性计划能物化、看门狗能兜住挂死、sdr 已经改用原生子代理派发——但 init 的 scout 层还是老形态。根因:scout 的步骤清单、断点恢复、壳与纪律片段都只认 `fanout_runner.py --tier scout`,不知道「原生派发」这种形态。改什么:只改 scout 这一层——**opencode 面缺省原生**(用户已拍板 mgh-init 全流程转向原生;显式 runner 仍可回退),scout 改为「确定性物化计划 → 编排器在同一回合并发派原生子代理 → 子代理自写完成/失败标记 → 重物化重枚举」;t1/t2/t3/scout-merge 在本 change 期间仍走 runner(它们还没有原生分支),下一 change 接入后继承同一缺省策略。怎么验证:opencode 无画像时 scout 即原生;显式 runner 与 claude/dsh 仍子进程;小/中仓 scout 原生跑通且 `scout_candidates.json` 与子进程形态可比;故障注入(单批失败、权限询问、挂死、续跑)按契约收口。

## Why

- 企业内网子进程派发因鉴权不可持续(维护者已拍板转向原生,实测 99% 不可用);sdr 原生派发已归档落地并已改为 opencode 缺省原生;init 是下一个主力命令,而 scout 是 init 最大、最独立的扇出层。
- 用户已拍板 **mgh-init 全流程也走 opencode 缺省原生**;本 change 先把 init 消费者的缺省策略与 scout 步落地,后续 aggregate change 把 t1/t2/t3/scout-merge 接入并继承同一策略。
- scout 当前形态钉死在 `fanout_runner.py --tier scout`:步骤清单、`resume_state` 的下一步、壳与纪律片段都只给子进程调用行;原生计划工件、短单元号、标记自写、看门狗无人值守这些基础件没有消费方。
- scout 的**发现本体**(目标剪枝、字节预算切批、六类候选 schema、证据锚点、merge/fold-in)与派发形态无关;本次只换「怎么派」,不换「查什么、怎么记」。

## What Changes

- **形态选择(opencode 面缺省原生;用户已拍板)**:`/mgh-init` 经
  `env_profile.resolve(<target>, consumer="init")` 解析;`consumer=init ∧
  host=opencode` — 缺文件/`auto` 也解析 `native`;显式 `dispatch_mode:"runner"` 回退
  子进程;claude/dsh/other 面仍 `runner`。这是**有意的默认变更**(企业内网 runner 已
  99% 不可用),不再是「缺省零变化」;零变化承诺只覆盖 claude/dsh 面与显式 runner。
  原生形态要求安装树存在 `init-scout-native` agent 与 scout 原生纪律 fragment,缺一
  退出码 2 + 重装/显式 runner recipe,NEVER 静默回退。t1/t2/t3/scout-merge 在本 change
  期间仍走 runner(它们还没有原生分支),下一 change 接入后继承同一缺省。若解析形态为
  native 但宿主面不是 opencode(例如 claude 面显式 `native`),init 编排面 SHALL 退出码 2
  + recipe(原生仅 opencode;改 runner 或换 opencode 面),NEVER 静默按子进程运行。
- **原生 scout 派发(opencode 面)**:
  - 物化:`emit_native_plan.py --tier scout --scout-plan ... --checkpoints ... --inputs-dir ... --profile <target>` 产出 `native_plan.json` + 每批 `task.md`;物化后跑同参 `--check`;
  - 波次:编排器**同一条 assistant 消息**并发派当前波全部原生子代理(新 agent `init-scout-native`,`mode: subagent`),`description` = 计划短号,任务体 = 单行令牌 `mgh-dispatch: plan=<plan_path> unit=<短号>`(令牌展开钩子换成任务全文;旧版安装回退为固定句 + 任务文件绝对路径逐字透传);
  - 页语义:一次物化只覆盖当前 pending 页(枚举器的 `--orch-budget-bytes` 会收紧页),派完该页后**重物化**取下一页,循环直到 pending 清零——不假设一次计划覆盖全部批;
  - 标记:子代理成功 touch `.done`,失败**自写** `.failed`(带原因;指令只在新 agent 定义);计划、看门狗、编排器不写标记;失败批至多重派一轮,再败接受缺口并在 merge 前披露;
  - 无人值守:第一波前后台启动看门狗(`native_watchdog.py --run-dir <init-dir>`,根会话取宿主注入的会话环境变量),run 落定自退;
  - 收尾:pending 清零后回到既有 scout-merge/audit/fold-in 段(**不改**),scout-merge 仍按当前形态执行。
- **步骤/恢复/纪律的形态感知**:`list_steps.py` 在原生形态下把 scout 步展开为「物化(bash)→ 波次(subagent)→ 既有 scout-merge 段」并给 `native_arc`;`resume_state.py` 的 `next_action`/`dispatch` 增原生分支(进度仍纯磁盘重派生);`discipline_core.py` 增 init scout 的原生纪律表。
- **壳与片段**:`releases/opencode/command/mgh-init.md` 以 `resume_state.py` 的 `dispatch`（内部 `consumer=init` 解析）为准，scout 步增原生条件指针；新 fragment `core/prompts/fragments/init-scout-native-dispatch.md` 承载波次纪律；`core/prompts/fragments/init-stage/scout.md` 只加紧凑条件指针；claude/dsh 壳各加一行「仅子进程形态」披露。
- **契约**:`core/contracts/init/step-manifest.md`、`init/resume-state.md`、`init/manifest.md`、`fanout/runtime.md` 增原生 scout 步形/`dispatch` 字段/计划工件披露;共享任务模板 `fanout/scout-task.md` 与 `fanout_runner.py` 派发行为**零改动**。
- **分发与自检**:`install.sh` 的 opencode fanout agent 自检清单加 `init-scout-native`;VERSION/CHANGELOG 按惯例 bump。

**非目标**:

- 不改 t1/t2/t3/scout-merge 任何层的实现;它们在本 change 期间仍走 runner,原生化与资产门留给后续 init aggregate change(接入后继承 `consumer=init` 的缺省原生)。
- 不改 `plan_scout.py`/`list_scout_batches.py`/`merge_scout.py`/`discover_controls.py` 的行为。
- 不接通道 B(`mgh_dispatch` 自定义工具):本 change 只走内置子代理工具 + 令牌展开;900 批大仓的零 LLM 波次留给后续 init aggregate change。
- 不改共享任务模板的失败标记行(仍写「reference only; the dispatcher writes it」),不改 runner 的任何行为。
- 不做 claude/dsh 的原生实现;只做披露。
- 不改 `consumer=generic`、claude/other 的缺省;它们仍 runner。
- 不在本 change 把 t1/t2/t3/scout-merge 也切原生;但 `consumer=init` 的缺省策略在本 change 就设为 opencode 原生,后续步骤接入时直接继承。

## Capabilities

### New Capabilities

<!-- 无。 -->

### Modified Capabilities

- `control-discovery`: ①MODIFIED「Fan out scout across parallel isolated byte-bounded batches」——派发升级为双形态(子进程回退 + opencode 面 `consumer=init` 缺省原生的原生派发),原生形态的 agent/令牌中继/标记自写/页循环语义入约,scout 发现本体与 merge/fold-in 不变;②ADDED「原生 scout 派发的波次纪律与无人值守闭环」——波次循环、重物化即重枚举、页语义、至多一轮重派、限流等窗、看门狗接线、标记真相源、三面分歧与诚实边界披露。
- `native-dispatch-core`: MODIFIED「环境画像的读取、缺省与 fail-closed」——消费者集合增 `init`;`consumer=init ∧ host=opencode` 缺省解析 `native`(与 sdr 同一宿主缺省规则),显式 `runner` 仍回退,`consumer=generic`/claude/other 仍 `runner`;扩展解析结果与 CLI 的消费者闭集,坏画像 fail-closed 语义不变。

## Impact

- **代码**:`core/scripts/env_profile.py`(消费者闭集增 `init` + 缺省规则扩展 + 按 surface 的 scout 原生资产门;sdr/generic/claude/other 行为不变);`core/scripts/list_steps.py`、`resume_state.py`、`discipline_core.py`;新增 `releases/opencode/agent/init-scout-native.md` 与 `core/prompts/fragments/init-scout-native-dispatch.md`;`core/prompts/fragments/init-stage/scout.md`、`releases/opencode/command/mgh-init.md`、`releases/claude-code/commands/mgh-init.md`、`releases/dsh/skills/mgh-init/SKILL.md`。
- **零改动面**:`fanout_runner.py`(派发行为)、`plan_scout.py`、`list_scout_batches.py`、`merge_scout.py`、`discover_controls.py`、`emit_native_plan.py`(本 change 不改它)、`native_watchdog.py`、`mgh_dispatch.ts`、共享 `fanout/scout-task.md`、scout-merge 整个 tier。
- **契约**:`core/contracts/init/step-manifest.md`、`init/resume-state.md`、`init/manifest.md`、`fanout/runtime.md`。
- **测试**:`test_list_steps`、`test_resume_state`、`test_env_profile`(consumer=init 缺省 native、generic/claude 仍 runner、scout surface 资产门)、`test_emit_native_plan`(只加 scout 计划/页语义用例,不改 agent 断言)、`test_agent_stage_contract`、`test_opencode_hook_parity`、新增 `test_init_native_dispatch`;回归 `test_scout_batches`/`test_list_scout_batches`/`test_scout_plan`/`test_merge_scout`/`test_list_clusters`/`test_fanout_runner`/`test_init_runtime`/`test_init_ack_contract`/`test_distributed_md_purity`;`install.sh` 改动后跑 `test_install_*`;lint 四件套 + `openspec validate --strict`;壳预算 lint。
- **实机闸门**:本机 opencode 2.1——无画像 opencode init 的 scout 原生全链(物化→并发→标记→重物化→scout-merge→fold-in)对照同输入子进程形态 `controls_candidates.json`;故障注入(单批 `.failed`/权限 ask/挂死 interrupt/中断 resume);无画像原生 / 显式 runner 回退 / claude/dsh runner / 缺资产 fail-closed 抽查;企业 CAS 真仓交接内网执行。
