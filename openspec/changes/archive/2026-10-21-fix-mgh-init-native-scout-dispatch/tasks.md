## 1. Agent 定义与纪律片段

- [x] 1.1 新增 `releases/opencode/agent/init-scout-native.md`（`mode: subagent`，不 hidden；权限镜像 `init-scout`：read/glob/grep/list/bash allow、edit/external_directory/question deny + `doom_loop: deny`）；正文引用同一 `stages/init-scout.md`，额外承载成功 touch `done_marker`、失败自写 `failed_marker`（`{unit_id, reason}`）、单行回执 `ok/oversize/failed`；验证：`test_agent_stage_contract` 克隆对账断言与 `init-scout` 的 Output schema/ack 行一致，native 额外行仅标记自写
- [x] 1.2 新增 `core/prompts/fragments/init-scout-native-dispatch.md`（opencode 面 `consumer=init` 解析为 native 时按需加载）：看门狗先行、物化+`--check`、页循环（`units_total==0` 终止）、同消息并发派发、令牌行/旧版回退、重物化即重枚举、失败批至多一轮重派、限流等窗、标记真相源、scout-merge/fold-in 过渡、诚实边界；验证：purity 零违例、`check_contracts` 对 fragment 内脚本 flag 引用通过、预算 lint 过
- [x] 1.3 `core/prompts/fragments/init-stage/scout.md` 只加紧凑条件指针（→ 新 fragment；明确 opencode 面 `consumer=init` native 才适用；显式 runner 与 claude/dsh 继续走子进程段），详情不进本文件；验证：文件 token 增量在预算内、条件指针在场
- [x] 1.4 确认共享任务模板 `core/prompts/fragments/fanout/scout-task.md` 零改动（`failed_marker` reference-only 行保留）；验证：git diff 为空 + `test_fanout_runner` 全绿

## 2. 脚本面（解析器、步骤、恢复、纪律）

- [x] 2.1 `core/scripts/env_profile.py`：消费者闭集增 `init`；`resolve_form` 在 `consumer ∈ {sdr,init} ∧ host=opencode` 时缺省 `native`，显式 `runner` 仍优先，`generic`/claude/other 仍 `runner`；CLI `--consumer` 增 `init`；资产门增 `surface` 维度（`surface="init"` 检查 `agent/init-scout-native.md` + scout fragment），sdr 既有 surface 行为不变；验证：`test_env_profile` 新用例 + sdr/generic/claude 既有用例不回归
- [x] 2.2 `core/scripts/list_steps.py`：用 `env_profile.resolve(target, consumer="init")`；解析形态 native（含无画像缺省）时 scout 步 `script`/`invocation` 换为 `emit_native_plan.py --tier scout ... --profile <target>`，加 `native_arc`（materialize → waves）与顶层 `dispatch`（sdr 同形字段，`consumer="init"`、`source=host-default|profile`）；native 判定后调用 `require_native_assets(root, surface="init")`，缺资产退出码 2 + recipe；`form=="native"` 但 `host_face != "opencode"` → 退出码 2 + recipe（原生仅 opencode），NEVER 静默按 runner；保留 `extra_invocations` 的 scout-merge 段；显式 runner/claude/other 缺省时 stdout 逐字节不变；验证：五形态快照测试
- [x] 2.3 `core/scripts/resume_state.py`：import `env_profile`；用 `consumer="init"` 解析；native 时 scout 的 `next_action` 指向「重物化 → 派当前波」（plan 未物化 vs 已物化两种子相位）、顶层加 `dispatch`、`discipline_reminders` 用 `get_discipline("scout", domain="init", form="native")`；native 判定后走同一 `surface="init"` 资产门；`form=="native"` 但 `host_face != "opencode"` → 退出码 2 + recipe；坏画像 fail-closed；显式 runner/claude/other 缺省 stdout 逐字节不变；验证：标记组合（部分完成/有失败/全完成/0 批）快照
- [x] 2.4 `core/scripts/discipline_core.py`：新增 init scout 的 `form="native"` 表（计划自检、波次、标记、重派、看门狗、等窗的 gates/path_recipes/nevers）与 `get_discipline` 分支；验证：`test_resume_state`/`test_list_steps` 的 discipline 对齐测试、未知 form 回退 subprocess
- [x] 2.5 确认 `emit_native_plan.py`/`fanout_runner.py`/`plan_scout.py`/`list_scout_batches.py`/`merge_scout.py`/`discover_controls.py` 零改动；验证：git diff 为空 + 既有 scout 测试全绿

## 3. 壳、契约、分发

- [x] 3.1 `releases/opencode/command/mgh-init.md`：step 0 以 `resume_state.py` 的 `dispatch`（内部 `consumer=init` 解析）为准；scout 步以原生为主路径（缺省 native；显式 runner 才走子进程行），并显式披露「本 change 仅 scout 原生；t1/t2/t3/scout-merge 仍 runner」；详情 → 新 fragment；不重复写长纪律；验证：壳预算 lint 过、`check_contracts` 过
- [x] 3.2 `releases/claude-code/commands/mgh-init.md` 与 `releases/dsh/skills/mgh-init/SKILL.md`：各加一行「scout 仅子进程形态；原生缺省仅 opencode + consumer=init」披露；验证：三面披露行形状锚测试
- [x] 3.3 契约同步：`core/contracts/init/step-manifest.md`（scout 原生步形/native_arc）、`core/contracts/init/resume-state.md`（`dispatch` 字段与原生 next_action）、`core/contracts/init/manifest.md`（`scout.dispatch` 可选字段：form/source/profile_exists/host_face/consumer/plan_path/plan_present/native_agent）、`core/contracts/fanout/runtime.md`（init scout 为 native plan 的第二个消费方、页语义、`consumer=init` 缺省原生与回退）；验证：契约与实现逐项对得上
- [x] 3.4 `install.sh` 的 opencode fanout agent 自检清单加 `init-scout-native`；验证：真跑 `install.sh --opencode` 自检通过 + `test_install_*` 相关用例

## 4. 测试（先红后绿）

- [x] 4.1 `tests/test_env_profile.py`：新增 `consumer=init` 用例——opencode 无画像/auto → native（source=host-default）、显式 runner → runner、claude/other → runner、generic → runner、sdr 缺省仍 native（回归）、坏画像 fail-closed、`surface="init"` 缺 agent/缺 fragment 两条资产门；验证：全绿
- [x] 4.2 `tests/test_list_steps.py`：新增原生分支类（无画像 opencode init → native/`dispatch`/`native_arc`；显式 runner → 既有子进程行、无新字段；claude 缺省 → runner；claude + 显式 native → exit 2；坏画像 exit 2；缺 scout 资产 exit 2；dispatch 含 source/profile_exists/host_face/consumer=init）；验证：全绿
- [x] 4.3 `tests/test_resume_state.py`：新增原生分支（无画像 opencode init → plan 缺时物化 next_action、plan 在时派波次；显式 runner → 既有 next_action；部分完成重派生；0 批；坏画像/缺资产/claude+显式 native exit 2；dispatch 字段形状）；验证：全绿
- [x] 4.4 `tests/test_emit_native_plan.py`：新增 scout 计划用例（`--tier scout` 物化 + `--check`、多页/页收缩语义、`units_total==0`）；**不**改既有 `plan["agent"]=="init-scout-fanout"` 断言（本 change 不改该字段）；验证：全绿
- [x] 4.5 `tests/test_agent_stage_contract.py`：`PAIRS` 增 `("opencode","init-scout-native") → stages/init-scout.md`（ack 形式子集）；`tests/test_opencode_hook_parity.py` 的 `EXT_DENY_REQUIRED` 增 `init-scout-native`（question/external_directory deny）；验证：全绿
- [x] 4.6 新增 `tests/test_init_native_dispatch.py`：静态形状锚——新 fragment 含看门狗/重物化/同消息/令牌/标记唯一写者/至多一轮重派/等窗/页语义；孪生 frontmatter 与权限镜像；三面披露行；contracts 字段；删任一锚即红
- [x] 4.7 定向回归：`test_env_profile` `test_scout_batches` `test_list_scout_batches` `test_scout_plan` `test_merge_scout` `test_list_clusters` `test_fanout_runner` `test_init_runtime` `test_init_ack_contract` `test_distributed_md_purity` + `test_zero_deps` `test_no_compile_warnings`；验证：逐一跑过无失败
- [x] 4.8 lint 四件套 + 壳预算 lint + `openspec validate "fix-mgh-init-native-scout-dispatch" --strict`；验证：与基线一致（无新增违例）

## 5. 实机闸门（本机 opencode 2.1）

- [x] 5.1 无画像 opencode init 的 scout 原生全链：`consumer=init` 缺省 native + opencode → 哨兵 → `plan_scout` → `emit_native_plan --tier scout` + `--check` → 启看门狗 → 同消息 3 并发 → 标记 → 重物化（多页循环）→ scout-merge/audit/fold-in；对照同输入子进程形态的 `controls_candidates.json`：候选集合一致（措辞差异容忍，候选丢失为零）；验证：命令与对照结论记入本 change 实机笔记
- [x] 5.2 页循环实证：构造超过一页（`--orch-budget-bytes` 收紧）的 scout 计划，确认 `units_total` 是页大小、派完重物化继续、最终 `units_total==0` 才进 merge；验证：实机笔记记录页数/单元数
- [ ] 5.3 故障注入：①单批 `.failed` → 至多一轮重派后缺口披露；②权限 ask（关闸门对照探针）→ 看门狗/evaluate 拒绝后会话继续；③挂死（长静默）→ 看门狗中止、批回待派；④中途打断 → `resume_state` 接上且已完成批不重做；验证：四件套结果入实机笔记
- [x] 5.4 缺省/回退/资产门抽查：①无画像 opencode init → scout 原生（`source=host-default`）；②显式 `runner` → 子进程行、无 `dispatch`/`native_arc`；③claude/dsh 缺省 → 子进程；④claude + 显式 native → 退出码 2 + recipe（原生仅 opencode）；⑤删 `init-scout-native` agent → 退出码 2 + 重装/显式 runner recipe，NEVER 静默回退；验证：记录入实机笔记
- [ ] 5.5 企业闸门（交接内网，不阻塞归档）：CAS 真仓无画像 scout 原生对照（原失败场景）；附逐步复现步骤与预期输出；验证：内网回执 PASS 或问题清单回填

## 6. 收尾

- [x] 6.1 `VERSION` bump + `CHANGELOG.md` 分组条目（**opencode init 缺省原生**/scout 原生接入/标记自写/页循环/看门狗接线/显式 runner 与 claude/dsh 零变化/三面披露）
- [x] 6.2 根 `AGENTS.md` 命令族 mgh-init 行与诚实边界补「scout 原生形态（opencode + consumer=init 缺省原生；显式 runner 回退；t1/t2/t3/scout-merge 暂仍子进程，aggregate 接入后继承）」；验证：`test_distributed_md_purity` 复跑绿
- [x] 6.3 实机笔记归位本 change 目录；`openspec validate --strict` 通过；归档前核对主规格回写与 `.openspec.yaml`
