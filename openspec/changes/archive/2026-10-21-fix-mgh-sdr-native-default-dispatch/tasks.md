## 1. 形态解析基础(env_profile)

- [x] 1.1 `core/scripts/env_profile.py`:新增宿主面判断(`opencode` / `claude` / `other`,依据
  脚本安装路径的 `.opencode` / `.claude` 路径段;调用方可显式传宿主面覆盖)与按消费者的解析
  函数(`form ∈ {native, runner}`:显式 `native`/`runner` 覆盖;缺失/`auto` 时仅
  `consumer=sdr ∧ host=opencode` → native,其余 consumer/face → runner);CLI 增
  `--consumer <sdr|generic>`(缺省 generic),stdout 在既有 `profile` 外增 `host_face`、
  `consumer` 与 `form`,`--check` 同样报告;更新模块 docstring 与 `--help`(R5.1 契约面)。
- [x] 1.2 `tests/test_env_profile.py`:补缺省解析用例——`consumer=sdr` + opencode 面缺文件/
  `auto` → native;`consumer=generic` + opencode 面 → runner;claude/other 面无论 consumer
  → runner;显式 `native`/`runner` 覆盖;坏画像仍退出码 2 + recipe;`--check` 只读并报告
  `host_face`/`consumer`/`form`;导入形态可从任意 cwd 调用。
- [x] 1.3 `install.sh` 的 opencode 自检清单增 `releases/opencode/agent/sdr-review-native.md` 与
  `core/prompts/fragments/sdr-native-dispatch.md` 两个条目的在场检查(fail-soft,仅 warn);
  同步自检测试(若已有安装自检用例)。

## 2. 步骤、恢复与报告的形态消费

- [x] 2.1 `core/scripts/list_sdr_steps.py`:形态判断改用解析函数(`consumer=sdr`);opencode
  面缺省画像时 fanout 步仍展开原生 arc(`emit_native_plan.py` + `native_arc` + `dispatch`),
  `dispatch` 增 `source:"profile"|"host-default"`、`profile_exists`、`host_face`、`consumer`;
  runner 形态输出保持既有字节级形状(无 `dispatch` 字段)。
- [x] 2.2 `core/scripts/resume_sdr_state.py`:形态判断改用解析函数(`consumer=sdr`);缺省画像
  的 opencode run 在 fanout 步给原生 `next_action`(计划缺席 → 物化 + 看门狗;计划在场 → 派
  波次),`dispatch` 字段增 `source`/`profile_exists`/`host_face`/`consumer`;runner 形态仍给
  子进程 `next_action`;坏画像仍 fail-closed。
- [x] 2.3 `core/scripts/render_sdr_report.py`:原生披露条件改为「本次 run 的 `native_plan.json`
  在场 ∧ 解析形态(`consumer=sdr`)native」;证据串区分「画像显式 native」与「宿主缺省 native」;
  无计划工件或 runner 形态保持零新字段。
- [x] 2.4 `tests/test_list_sdr_steps.py` / `tests/test_resume_sdr_state.py`:用临时
  `.opencode/mgh-core/scripts` 镜像或等价宿主面注入,断言 opencode 缺省画像 + `consumer=sdr`
  → fanout 原生 arc、`dispatch.source == "host-default"`、`next_action` 不含
  `fanout_runner.py`;显式 runner → 原步子进程输出;claude/other → 与改动前逐字节一致。
- [x] 2.5 `tests/test_render_sdr_report.py`:补「缺省画像 + native_plan 在场」披露用例(报告、
  manifest、数据文件 `dispatch.form == native`);补「无计划工件」与「runner 形态」零披露用例。
- [x] 2.6 原生资产在场检查:`list_sdr_steps.py` / `resume_sdr_state.py` / `mgh_sdr_launch.py`
  在 `consumer=sdr` 且解析形态为 native 时,检查安装树内 `sdr-review-native` agent 与
  `sdr-native-dispatch.md` fragment 在场;缺失 → 退出码 2 + 重装/显式 runner recipe,NEVER 静默
  回退子进程。检查逻辑集中到单一 helper(避免三处各写一份),并补对应失败用例。

## 3. launcher 入口

- [x] 3.1 `core/scripts/mgh_sdr_launch.py`:在 `sdr_context` 后、spawn 宿主前读取画像并以
  `consumer=sdr` 解析形态;opencode + native 时 `_build_prompt()` 生成原生第 3 步(看门狗 →
  物化 + `--check` → 同消息派
  `sdr-review-native` 子代理的令牌行 → 重物化重枚举),给出 `sdr-native-dispatch.md` 绝对路径;
  opencode + runner 与 claude 宿主保持现行子进程提示词;claude 宿主 + 画像显式 native 时退出码 2
  + recipe;坏画像退出码 2;special-auth 凭证块只在子进程提示词出现。
- [x] 3.2 `tests/test_mgh_sdr_launch.py`:补 dry-run 提示词断言——opencode 无画像提示词含
  `emit_native_plan.py`、`sdr-review-native`、`mgh-dispatch:` 令牌且不含 `fanout_runner.py`;
  显式 runner 提示词含子进程调用;claude 提示词与改动前一致;claude + native 画像退出码 2;
  坏画像退出码 2;多分支 dry-run 每分支各自得到正确提示词。
- [x] 3.3 手工 dry-run 抽查:本机 opencode 安装树无画像项目生成的原生提示词与本 change 的
  `design.md` 第 3 步逐项对得上;`--dry-run` 不 spawn 宿主、不产生 `fanout_runner` 进程。

## 4. opencode 命令壳与原生纪律 fragment

- [x] 4.1 重写 `releases/opencode/command/mgh-sdr.md`:step 0 的画像读取改为
  `env_profile.py --target <abs> --consumer sdr`;主流程改为原生派发;删除「fan-out 刚性
  三元组 = 子进程派发器」、stage 表与确定性调用清单里的 `fanout_runner.py` 调用行、以及
  「缺省/回退」措辞;step 3 只展开原生步骤;子进程回退只保留「解析形态为 `runner` 时按
  `list_sdr_steps.py --step fanout` 的 invocation 与 discipline 执行」;`--quota-*` 标为
  runner 回退专用;Always disclose 同步改为 opencode 缺省原生、显式 runner 回退。
- [x] 4.2 `core/prompts/fragments/sdr-native-dispatch.md`:把「仅画像显式 native 才适用」改为
  「opencode 面缺省 native;显式 runner 才回退;claude/dsh 仍子进程」;保留看门狗先行、同消息
  派发、令牌展开、标记真相源、至多一轮重派、限流等窗与诚实边界;确保正文不出现
  `fanout_runner.py` 主路径措辞。
- [x] 4.3 `core/contracts/sdr/pipeline.md`:原生形态节激活条件改为宿主缺省;补 launcher 提示词
  与报告披露的形态一致性;`core/contracts/fanout/runtime.md` 的环境画像段把 `auto` 语义改为
  「按宿主面解析」,并写明显式 runner 回退。
- [x] 4.4 壳预算与纯净性:跑 `tools/check_distributed_prompt_budget.py`(opencode 壳 mid tokens
  ≤ 5,000,目标 < 4,800)与 `tools/check_distributed_purity.py`(分发面零违例);
  `tools/check_contracts.py` 对壳内所有 `*.py --flag` 对账通过。

## 5. 形状锚与定向回归

- [x] 5.1 壳/agent/fragment 形状锚:测试断言 opencode 壳正文不出现 `fanout_runner` 字面量、
  原生三元组在场、step 3 原生动作在场、显式 runner 回退指引在场;`sdr-review-native` agent 与
  fragment 仍在分发树中;删任一锚即红。
- [x] 5.2 消费者边界锚:claude/dsh 的 `list_sdr_steps`/`resume_sdr_state` 在无画像时仍输出
  子进程形态、无 `dispatch` 字段;opencode 缺省画像 + `consumer=sdr` 输出原生形态;
  `env_profile.py` 在 opencode 面 + `consumer=generic` 仍解析 `runner`(init 等命令不受影响);
  三个方向的输出都进测试快照。
- [x] 5.3 launcher 原生提示词锚:opencode 无画像 dry-run 的 `orchestrator_prompt.md` 不含
  `fanout_runner`;显式 runner 的提示词含子进程调用行;两条用例都断言 `--dry-run` 零宿主 spawn。
- [x] 5.4 定向回归:sdr 面 10 文件(`test_diff_group` `test_sdr_context` `test_sdr_tier`
  `test_render_sdr_report` `test_mgh_sdr_launch` `test_list_sdr_steps`
  `test_resume_sdr_state` `test_read_roots_config` `test_sensitive_catalog`
  `test_sdr_failure_chain`)+ `test_fanout_runner`(回退路径与手动 `--cred-file` 不破)+
  `test_env_profile` + `test_install_special_auth` + `test_mgh_credentials` +
  `test_zero_deps` + `test_no_compile_warnings` + `test_distributed_md_purity` +
  `test_dsh_command_surface`;逐一跑过无失败。
- [x] 5.5 lint 四件套:`tools/check_contracts.py`、`tools/check_distributed_purity.py`、
  `tools/check_distributed_prompt_budget.py`、`tools/check_plain_language.py`;与基线一致,
  无新增违例;`openspec validate "fix-mgh-sdr-native-default-dispatch" --strict` 通过。

## 6. 实机闸门(opencode 2.1.0,本机)

- [x] 6.1 真仓无画像原生全链:安装本 change 的 opencode 分发面,项目不写
  `.mgh/env-profile.json`,执行 `/mgh-sdr`(或 launcher 等价入口);确认 step 0 解析
  `form=native`、fan-out 只出现 `emit_native_plan.py` 与 `sdr-review-native`、磁盘有
  `native_plan.json` + `watchdog/state.json`、报告/数据文件披露 `dispatch.form=native`;运行
  期间进程表零 `fanout_runner` 命中。
- [x] 6.2 显式 runner 回退对照:同一仓写 `{"v":1,"dispatch_mode":"runner"}`,同输入跑一次;
  确认 `list_sdr_steps`/`resume` 给子进程调用行、launcher 提示词给子进程步骤、报告不披露原生;
  原生计划与看门狗不启用。
- [x] 6.3 中断恢复:无画像原生 run 跑到部分单元完成后中断,开新会话用
  `resume_sdr_state.py` 接上;确认 `step=fanout`、`dispatch.form=native`、`next_action` 指原生
  物化/派波次、已完成单元不重做、不出现 `fanout_runner.py` 提示。
- [x] 6.4 claude/dsh 不变抽查:同一目标分别以 claude 面脚本与 dsh 面脚本跑
  `list_sdr_steps`/`resume_sdr_state`(无画像),输出与改动前一致(子进程形态、无 `dispatch`
  字段);claude/dsh 壳文本仍如实披露仅子进程。
- [x] 6.5 企业 2.0.32 交接清单:在 change 目录实机笔记记录复现步骤(安装 opencode 面、无画像
  跑 sdr、预期原生、进程表零 fanout_runner、显式 runner 回退对照);内网执行结果回填,不阻塞
  归档(沿用前例)。

## 7. 特殊授权说明退役

- [x] 7.1 `core/scripts/list_sdr_steps.py`:特殊授权探测路径从安装树 `<mgh-core>/mgh-special-auth.md`
  改为项目级 `<target>/.mgh/special-auth.md`(`--target` 从占位参数变为实际探测根);保留
  `special_auth: {present, path}` 字段,docstring 改为「可选项目入口,不预设凭证命令」;三面
  壳的 `list_sdr_steps` 调用清单补 `--target <abs>`,保证入口探测不依赖 cwd。
- [x] 7.2 `core/scripts/resume_sdr_state.py`:删除 runner `next_action` 里的 `cred_source.json`
  / `mgh_credentials.py` / `--cred-file` 凭证准备串;改为项目级说明存在时的一句「先 Read 该
  说明」入口(原生与子进程形态都适用),不存在零动作;不再输出 `credential_expired` 处置分支。
- [x] 7.3 `core/scripts/mgh_sdr_launch.py`:删除 `cred_suffix`、凭证准备块与「step 3 carries
  --cred-file」stderr 提示;改为探测 `<repo>/.mgh/special-auth.md`,存在时在提示词加一句
  「先 Read 该说明,按其鉴权说明执行」,不存在零动作;原生与回退提示词都适用。
- [x] 7.4 三面 sdr 壳(opencode/claude/dsh):删除「special-auth 前置检查」整块与
  `credential_expired` 处置分支,改为一句可选入口「清单 `special_auth.present==true` → 先
  Read `special_auth.path`;本流程不预设 `mgh_credentials.py`/`--cred-file`/`cred_source.json`」;
  Always disclose 同步替换为「特殊授权说明只作可选入口」。
- [x] 7.5 `core/scripts/fanout_runner.py`:`_special_auth_doc_path()` 改为探测项目级
  `<repo>/.mgh/special-auth.md`;派发前 advisory 只提示「说明在场,按需先读;本次不启用静态
  凭证注入」;`--cred-file`/`credential_expired` 行为与测试保留,帮助文本与
  `mgh_credentials.py` docstring 标注「手动/遗留,不在 sdr 流程中使用」。
- [x] 7.6 `install.sh`:删除 `mgh-special-auth.md` 的自动复制;目标里旧的
  `<dest>/mgh-core/mgh-special-auth.md` 被删除并打印迁移提示(改放
  `<项目>/.mgh/special-auth.md`);维护者私有源文件不删除。`tests/test_install_special_auth.py`
  改为「源在场也不复制 + 旧副本清理」的收敛测试。
- [x] 7.7 契约同步:`core/contracts/sdr/pipeline.md` 从正常 run 布局移除
  `cred_source.json`/`cred.json`/`childcfg`/`ocdata`,把特殊授权写为项目级可选入口;
  `core/contracts/fanout/runtime.md` 的 `--cred-file` 段标注手动/遗留,special-auth advisory
  路径改项目级。
- [x] 7.8 测试:`test_list_sdr_steps`/`test_resume_sdr_state`/`test_mgh_sdr_launch` 的特殊授权
  用例改为项目级路径,断言只有一句入口、零 `mgh_credentials.py`/`cred_source.json`/
  `--cred-file`/`credential_expired`;`test_fanout_runner` 保留手动 `--cred-file` 用例;补
  「说明存在/缺席」两条壳与 launcher 形状锚。
- [x] 7.9 实机抽查:在真仓分别放置/移除 `<项目>/.mgh/special-auth.md`,确认 launcher 提示词、
  命令壳与恢复输出只多/少一句入口,零凭证命令;安装一次确认旧安装树副本被清理且新项目不再
  自动出现该文件。

## 8. 收尾

- [x] 8.1 `VERSION` bump(按仓库惯例);`CHANGELOG.md` 增分组条目:opencode 缺省原生、launcher
  原生提示词、步骤/恢复/报告形态一致性、显式 runner 回退、特殊授权退役、claude/dsh 零变化。
- [x] 8.2 根 `AGENTS.md` 命令族表的 mgh-sdr 行与诚实边界同步:opencode 面缺省原生、显式 runner
  回退、claude/dsh 仍子进程、特殊授权只作项目级可选入口;顶部企业环境说明处的
  `mgh-special-auth.md` 描述改为「不再随 install 分发,项目 `.mgh/special-auth.md` 可选放置」;
  不再写「仅画像显式 native 才启用」。
- [x] 8.3 归档前复查:spec delta 与主规格不冲突;所有新增/修改文件过 purity;实机笔记归位本
  change 目录;`openspec status --change "fix-mgh-sdr-native-default-dispatch"` 所有必需工件
  为 done。
