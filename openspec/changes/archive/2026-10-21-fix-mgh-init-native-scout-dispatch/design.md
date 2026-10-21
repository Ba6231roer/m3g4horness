## Context

动机与范围见 proposal。当前实现约束（均已核对源码/归档）：

- 前六个 native 基础件已归档并可用：`env_profile.py`（画像读取/fail-closed）、
  `emit_native_plan.py`（计划物化：任务文件 + 波次表 + 短号，`--tier` 闭集已含 `scout`）、
  `mgh_dispatch.ts`（令牌展开钩子 + `mgh_dispatch` 工具；本 change 只用其展开钩子）、
  `native_watchdog.py`（常驻看门狗）、权限闸门插件、sdr 原生派发。
- 最新已归档 change `fix-mgh-sdr-native-default-dispatch` 把 `env_profile` 升级为
  「宿主安装面 × 消费者」统一解析器：当前缺省表里仅 `consumer=sdr ∧ host=opencode` 解析
  `native`；`consumer=generic`（未接原生的其它命令）与 claude/other 面缺省仍
  `runner`。**用户已拍板 mgh-init 全流程也走 opencode 缺省原生**，所以本 change 在解析器
  上增 `consumer=init`、把 `consumer=init ∧ host=opencode` 的缺省解析设为 `native`（显式
  `runner` 仍回退；`generic`/claude/other 不变），scout 是第一个落地的 init 原生步。
- 最新 change 的原生资产门（`require_native_assets`）是 sdr 专用（检查
  `sdr-review-native` agent + sdr fragment）。scout 必须复用同一「单一资产门」原则但按
  surface 检查自己的 `init-scout-native` agent/fragment；直接调用 sdr 门会查错资产，
  自己内联检查会破单源。
- scout 现行链：`plan_scout.py` → `list_scout_batches.py --materialize` →
  `fanout_runner.py --tier scout` → 批 `.done/.failed` → `plan_aggregate --node
  scout-merge` → `init-scout-merge`/rollup/audit → `merge_scout.py` fold-in →
  `controls_candidates.json::provenance.scout_merged`。
- `emit_native_plan.py --tier scout` 已能物化：tier 表复用、模板逐字填充、锚树校验、
  短号、`--check` 都通；**但一次物化只覆盖枚举器当前 64KB 页**（实测 400 批 → 81 单元），
  这是本 change 必须显式处理的页语义。
- `init-scout.md` 已是 `mode: subagent`，但失败语义是「子代理失败不写标记，派发方写
  `.failed`」；原生形态要让子代理自写失败标记（与 sdr 原生一致），因此需要独立孪生，
  而不是改共享 stage prompt。
- 共享任务模板 `fanout/scout-task.md` 的 `failed_marker` 行明确写「reference only; the
  dispatcher writes it」；runner 行为与模板零改动是硬约束。
- `mgh_dispatch` 自定义工具（通道 B）要求计划 `agent` 为 `mode: subagent` 孪生，而
  `emit_native_plan` 当前写 `tier["agent"]`（scout = `init-scout-fanout`，primary）。本
  change 走通道 A（内置子代理工具 + 令牌展开），不消费该字段；通道 B 与 900 批大仓留给
  后续 init aggregate change 标准化。

## Goals / Non-Goals

**Goals:**

- scout 在 opencode 面、`consumer=init` 解析为 native（缺省或显式）时端到端可用：
  物化 → 同消息并发 → 标记自写 → 重物化重枚举 → 既有 scout-merge/fold-in。
- `consumer=init ∧ host=opencode` 缺省原生（用户拍板）；显式 runner、claude/dsh/other、
  `consumer=generic`、runner 行为、共享模板、merge/fold-in 保持不变。
- 步骤/恢复/纪律/报告能识别原生形态；进度仍纯磁盘重派生。
- 无人值守闭环：权限闸门 + 看门狗 + 标记真相源。

**Non-Goals:**

- 不做通道 B（`mgh_dispatch` 工具）、不做 900 批大仓零 LLM 波次；本 change 只保证通道 A
  的小/中仓路径。
- 不改 t1/t2/t3/scout-merge 的实现；它们在本 change 期间仍 runner，aggregate change 接入
  后继承 `consumer=init` 的缺省原生。
- 不改 `plan_scout.py`/`list_scout_batches.py`/`merge_scout.py`/`discover_controls.py`/
  `emit_native_plan.py`/`fanout_runner.py` 行为。
- 不做 claude/dsh 原生实现；只披露。
- 不改共享任务模板的失败标记行；不改 runner 的 `.failed` 写者语义。
- 不改 `consumer=generic`、claude/other 的缺省（仍 runner）。

## Decisions

### D1 激活 = 解析形态 native；opencode 面 `consumer=init` 缺省原生（用户已拍板）

- **决策**：`list_steps.py`/`resume_state.py` 用
  `env_profile.resolve(target, consumer="init")`。解析器增 `init` 消费者，并把
  `consumer=init ∧ host=opencode` 的缺省解析设为 `native`——**没有画像文件时也原生**；
  显式 `dispatch_mode:"runner"` 回退子进程；`consumer=generic`、claude/dsh/other 面仍
  `runner`。只有 `res.form == "native"` 且 `res.host_face == "opencode"` 时 scout 走
  原生。
- **理由**：用户已明确 mgh-init 全流程转向 opencode 缺省原生（企业内网 runner 99% 不可用）；
  sdr 已用同一模式落地。把 init 的缺省策略放在解析器层，后续 aggregate change 接入
  t1/t2/t3/scout-merge 时直接继承，不需要每层重复判断。显式 runner 保留为可审计的回退
  开关；claude/dsh 未验证原生面，仍 runner。
- **这是有意的默认变更**：本 change 不再承诺「opencode init 无画像 = 子进程」；零变化承诺
  只覆盖显式 runner 与 claude/dsh/other 面。回滚 = 画像写 `runner`（或删除 native 资产后
  会 fail-closed，需显式 runner 才能跑）。
- **备选否决**：用 `consumer=generic` 维持显式 opt-in（与用户「全流程缺省原生」的决定
  冲突）；把 `generic` 整体改为 native（会波及未接入原生的其它命令）；claude/dsh 也切原生
  （未验证，虚假披露）。

### D2 通道 A（内置子代理 + 令牌展开），本 change 不接通道 B

- **决策**：编排器用内置子代理工具逐波派发，任务体是单行令牌
  `mgh-dispatch: plan=<plan_path> unit=<短号>`，由已安装的 `mgh_dispatch.ts`
  `execute.before` 钩子展开为任务全文；旧版安装缺钩子时回退为「固定句 + task_file 绝对
  路径逐字透传」。
- **理由**：与 sdr 原生形态同构，保留内置子代理的权限/深度/完成/取消语义；不需要在
  插件里重新实现 `mgh_dispatch` 的那套语义；长路径不进模型输出（令牌展开后只剩短号）。
- **备选否决**：本 change 直接用 `mgh_dispatch` 工具（计划 `agent` 仍是 primary，工具会
  拒绝；且它一次调用跑完计划全部波次，与「页循环 + 每波重物化」的 scout 语义需要额外
  适配；900 批也不是本 change 目标）。通道 B 的接入留给 `fix-mgh-init-native-aggregate-
  dispatch`，届时统一 `native_agent` 字段。

### D3 物化复用 `emit_native_plan --tier scout`；页循环不假设一次覆盖全部批

- **决策**：每轮运行
  `emit_native_plan.py --tier scout --scout-plan <init>/scout_plan.json --checkpoints
  <init>/checkpoints/scout --inputs-dir <init>/inputs/scout --profile <target>`，
  随后同参 `--check`；派完当前计划页后**重物化**取下一页，直到 `units_total == 0`。
  `units_total == 0` 时跳过派发，直接进入 scout-merge/audit/fold-in。
- **理由**：枚举器的 `--orch-budget-bytes` 会把 `pending[]` 收紧成一页（实测 400→81）；
  重物化即重枚举，pending 由磁盘标记重派生，不造第二份进度账本；与 sdr 的
  「每轮重物化 = 重枚举」同构。
- **`--check` 的时机**：物化后、派发前跑；任何单元完成后计划按设计变 stale（退出码 2），
  此时用重物化修复，不要把 `--check` 失败当故障；fragment 明确写这一条。
- **备选否决**：给 `emit_native_plan` 加 `--orch-budget-bytes` 转发（会污染共享
  `list_args`，改变子进程形态行为）；手工翻 `scout_plan.json`（违反枚举器单一来源）。

### D4 原生孪生 `init-scout-native` + 失败标记自写

- **决策**：新增 `releases/opencode/agent/init-scout-native.md`（`mode: subagent`），
  权限镜像 `init-scout`（read/glob/grep/list/bash allow、edit/external_directory/question
  deny）+ `doom_loop: deny`；正文引用同一 `stages/init-scout.md`，额外承载：
  成功 touch `done_marker`；失败自写 `failed_marker`（`{unit_id, reason}`）；单行回执
  `ok/oversize/failed`。
- **理由**：共享模板是双形态面，改它的失败行会触碰 runner/子进程子代理行为；agent 定义
  是 per-unit 行为的钦定居所（模板头注释）；sdr 原生已验证这条路径。孪生独立文件也让
  「原生自写 / 子进程派发方写」两种语义各自单一写者。
- **备选否决**：复用 `init-scout.md` 并改其失败语义（手派/子进程回退行为被改，零变化
  承诺破）；改共享模板（runner 行为破）。

### D5 步骤/恢复/纪律的形态感知，最小侵入

- **决策**：
  - `list_steps.py`：仅当 `env_profile.resolve(target, consumer="init")` 的
    `form == "native"` 时，把 scout 步的 `script`/`invocation` 换为
    `emit_native_plan.py`，并加 `native_arc`（materialize → waves）与顶层 `dispatch`
    字段；`extra_invocations` 的 scout-merge 段保留。显式 runner / claude / other 面 →
    stdout 逐字节不变。
  - `resume_state.py`：原生时 scout 的 `next_action` 指向「重物化 → 派当前波」；顶层加
    `dispatch`（与 `list_steps` 同形）；`discipline_reminders` 用原生变体；坏画像
    fail-closed 退出码 2。进度仍纯磁盘重派生。
  - `dispatch` 形状与 sdr 对齐：
    `{form, source, profile_exists, host_face, consumer, profile_path, plan_present,
    native_agent, discipline_fragment}`；scout 的 `consumer` 恒为 `"init"`，
    `source` 区分 `profile`/`host-default`（无画像的 opencode init 是
    `host-default`）。
  - `discipline_core.py`：新增 init scout 的 `form="native"` 表（计划自检、波次、标记、
    重派、看门狗、等窗的 recipe/NEVER）；`get_discipline("scout", domain="init",
    form="native")` 分支。
- **理由**：三脚本的 stdout 形状是编排器/守卫的锚；原生分支以加性字段/新步形落，既有
  字段语义不动。与 sdr 的 `dispatch`/`native_arc` 形状对齐，减少维护面。
- **备选否决**：为原生另起一套步骤/恢复脚本（两套真相源）；只读原始
  `dispatch_mode`（绕过最新 change 的宿主面 × 消费者解析，会与 sdr 的答案漂移）。

### D5.1 Scout 原生资产门（`env_profile` 按 surface 扩展）

- **决策**：`env_profile.py` 的资产门增加 `surface` 维度（sdr 现有行为不变）：
  `missing_native_assets(root, surface)` / `require_native_assets(root, surface)`；
  `surface="init"` 检查 `agent/init-scout-native.md` 与
  `prompts/fragments/init-scout-native-dispatch.md`。`list_steps`/`resume_state` 在
  native 判定后调用；缺一退出码 2 + 重装/显式 runner recipe，NEVER 静默回退。
- **理由**：最新 change 已立「单一资产门」原则，但实现是 sdr 专用；scout 自己复制一份
  检查会破单源，直接调用 sdr 门又会查错资产（sdr 缺资产误拦 scout / scout 缺资产漏检）。
  按 surface 参数化是唯一不破坏 sdr 的形态；后续 aggregate change 把 init aggregate 的
  assets 加进同一 surface 列表。
- **备选否决**：scout 脚本内联检查（双源）；把 `init-scout-native` 塞进 sdr 门
  （查错资产）。

### D6 看门狗原样复用，`--run-dir` = init 目录

- **决策**：第一波前以宿主后台形态启动 `native_watchdog.py --run-dir <init-dir>`；根会话
  取宿主注入的 `OPENCODE_SESSION_ID`；阈值缺省；run 落定自退。看门狗零改动。
- **理由**：看门狗的作用域是「根会话 + 后代」，与 init 的 `<init-dir>/watchdog/` 留痕
  目录天然匹配；根会话环境变量是宿主机制，零手工传参。
- **备选否决**：波次边界 `--once` 巡检（父被前台子代理阻塞时到不了下一波边界）。

### D7 报告/清单的派发形态披露

- **决策**：`init_manifest.json` 的 `scout` 段在原生形态下增
  `dispatch: {form:"native", plan_path, plan_present, native_agent}`；`report.md` 与
  `boundaries[]` 增一句派发形态 + 计划工件在场证据。值取自 `list_steps.py`/
  `resume_state.py` stdout，不靠模型记忆。子进程形态不出现该字段（既有 manifest 形状
  不变）。
- **理由**：读者要能区分「这次怎么派的」与「查了什么」；原生形态的止损/单点/路径残余
  必须可见。
- **备选否决**：只在报告里写自然语言（机器不可对账）；改既有 `scout` 段所有字段（破坏
  兼容）。

### D8 三面分歧显式披露

- **决策**：opencode 壳加原生条件指针；claude/dsh 壳各加一行「scout 仅子进程形态」；
  `init-stage/scout.md` 加紧凑条件块（opencode + 画像 native 才适用），详情下沉新
  fragment。三面不静默镜像。
- **理由**：原生面当前只在 opencode 2.x 设计/验证；claude/dsh 的宿主机制不同，后续按
  宿主能力接入。
- **备选否决**：三面同步写原生（未验证，虚假）；原生详情全进壳（R5.6 预算破）。

## Risks / Trade-offs

- [一次物化只覆盖当前页（实测 400→81）] → 显式页循环 + `units_total == 0` 终止条件 +
  fragment/gate 文案 + 实机用例（400 批模拟/分页计划）。
- [`--check` 在任一单元完成后必然 stale] → 只要求「物化后、派发前」跑；波次收尾用重物化
  修复，fragment 明说，不把退出码 2 当故障。
- [原生孪生与共享 stage prompt/`init-scout` 漂移] → 克隆对账测试锚定 Output schema/ack
  行一致；native 额外行仅标记自写。
- [共享模板失败行与原生自写语义冲突] → 模板零改动，agent 定义显式声明「native 形态由你
  自己写 `.failed`；模板的 reference-only 行是子进程形态的」；`init_tier`/`resume_state`
  只判 marker 存在性，不读 body。
- [弱模型令牌/路径转述的残余错抄] → 令牌展开后模型只输出短号；回退路径仍可能错抄，防线
  链 = 越树守卫 + 重枚举回待派 + 至多一轮重派；6 单元试点是方向性证据，不是认证。
- [计划文件名 `<init-dir>/native_plan.json` 与未来 t1/t2/scout-merge 原生共用] → 本
  change 只让 scout 原生，当前无冲突；aggregate change 在让第二层原生之前 MUST 引入
  按 tier 的计划命名/子目录（design 已记为约束）。
- [`mgh_dispatch` 的 primary agent 字段缺口] → 本 change 不接通道 B；aggregate change
  统一 `native_agent` 字段时一并修，避免在 scout 里做半套。
- [壳预算] → scout 原生详情下沉新 fragment；壳只加条件指针；预算 lint 入任务。
- [企业 2.x 原生面差异] → 本机 2.1 实机闸门 + 企业 CAS 真仓交接闸门；差异回填契约版本
  矩阵。
- [opencode init 缺省原生是有意的行为变更] → 显式 runner 保留可审计回退；claude/dsh/
  other、`consumer=generic`、sdr 的缺省不变；壳/CHANGELOG/AGENTS 显式披露「无画像也原生」；
  实机闸门含「无画像即原生」与「显式 runner 回退」两条。
- [解析器改动波及 sdr/generic] → `env_profile` 只加 `consumer=init` 与
  `init+opencode=native` 规则；sdr/generic/claude/other 的既有测试作为回归；
  `test_env_profile` 增「sdr 缺省仍 native、generic 仍 runner、claude 仍 runner」对照。
- [scout 误用 sdr 资产门] → 资产门按 `surface="init"` 检查 init-scout agent/
  fragment；补「缺 agent / 缺 fragment」两条 fail-closed 用例；sdr 既有用例不得回归。
- [宿主缺省表未来变化] → 本 change 钉死 `consumer=init ∧ opencode = native`、
  `consumer=generic`/claude/other = runner；任何进一步变化另立 change，不在 apply 期暗改。

## Migration Plan

1. 实现 + 本机 opencode 2.1：**无画像 opencode init 即原生**的小/中仓 scout 全链；显式
   `runner` 回退、claude/dsh runner、`consumer=generic` runner 抽查。
2. 企业 CAS 真仓：无画像即原生 scout 对照（原失败场景）交接内网；若企业需暂时回退，画像
   写 `{"dispatch_mode":"runner"}`（不需要改代码）。
3. 合入分发；无数据迁移（checkpoint/marker 形状不变；`scout_candidates.json` 与
   `controls_candidates.json` 形状不变）；默认变更在 CHANGELOG/AGENTS/壳披露。
4. 回滚：画像显式写 `runner`。**删画像不再等于回退**（opencode init 缺省已原生）；run
   目录产物两形态互通，不需要清理标记。

## Open Questions

- `env_profile` 的 `surface="init"` 当前只列 scout 资产；aggregate change 接入
  t1/t2/t3/scout-merge 时如何扩展同一 surface 列表（逐个加 vs 一次性加）留到那时定；
  不影响本 change 的 scout 门。
- `emit_native_plan` 的摘要目前不含 `shrunk`/全量 `total`；本 change 用「`units_total==0`
  作为页循环终止」已足够。是否在后续 aggregate change 给摘要加页披露，留到那时定。
- `init_manifest.json` 的 `scout.dispatch` 是否要在子进程形态也写 `form:"subprocess"`
  ——本 change 选择不写（保持既有 manifest 形状），读者以「字段缺失 = 子进程」解释；
  若后续需要显式区分，再另立加性字段。
