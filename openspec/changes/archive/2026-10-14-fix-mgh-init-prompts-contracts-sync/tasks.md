# fix-mgh-init-prompts-contracts-sync — Tasks

> 实施纪律:先红后绿;本机用 `python`;壳改动必跑三面镜像 diff + budget/contracts lint;
> 提示词/契约改动必跑 purity。实现顺序 = 组号(H11 代码面先——它解锁独立可测的行为红绿;
> parity 随 base agent 删即转绿;文档批在后,以 lint 收口)。

## 1. H11(b) `--merge` 显式拒绝(代码面)

- [x] 1.1 红测:`test_write_runconfig` 增——传 `--merge <dir>` → 退出码 2 + stderr 含
      「无确定性实现/独立落盘」recipe(现状静默写 mode=merge → 红);成功 run_config payload
      无 `mode`/`merge_partials_dir` 键(现状有 → 红)
- [x] 1.2 红测:`test_resume_state` 增——①步词表/docstring 无 `merge` 源形态断言;②遗留旧
      run(mode=merge 的 run_config)→ 正常磁盘派生、step 词表无 merge(现状路由 merge 步 → 红);
      `test_list_steps` 增——stdout/steps 清单无 merge 行(现状有 merge_inventories.py 死引用 → 红)
- [x] 1.3 实现:write_runconfig 遇 `--merge` → exit 2 + recipe,payload 删两字段;resume_state
      删 merge 短路分支 + 词表;list_steps 删 merge 行;跑 1.1/1.2 转绿
- [x] 1.4 fragment 删除:`init-stage/merge.md` 删;`resume_state` stage_flow/`_FRAGMENT_STEPS`
      与 bootstrap 点名处同步;install 自检 inventory 断言核对(不点名 merge.md → 零影响)

## 2. ack 枚举收口(三.15)

- [x] 2.1 红测已存在:`tests/test_fanout_runner.py::TestAgentCloneParity` 在 HEAD 即红——
      本组转绿即完成红绿闭环
- [x] 2.2 实现:base agent 六面(opencode/claude 的 init-scout/induct/rulewriter)回传 ack 行删
      `oversize <绝对路径>`(与克隆侧同句式对齐);跑 TestAgentCloneParity 转绿
- [x] 2.3 面核:`test_agent_stage_contract` + `test_dsh_command_surface` 零回归(dsh 面 ack 形态
      本就无 oversize)

## 3. 壳面与契约词表(H11 文档面)

- [x] 3.1 三面壳:flag 表删 `--merge <partials-dir>` 行、description 句去 `--merge`、stage 流程
      清单去 `merge` 步、advice 措辞(`--scope`/`--merge` 回退 → `--scope` 分模块产物独立);
      三面逐字镜像 diff 白名单外零漂移
- [x] 3.2 契约:step-manifest.md(词表 ×2 + merge 行删 + 101-102 注记改述)、resume-state.md
      (词表去 merge);`test_dsh_command_surface` / `test_init_flag_table_contract` /
      `check_contracts` 过(壳删 --merge 与 write_runconfig 保留声明,子集方向成立)
- [x] 3.3 `check_distributed_prompt_budget` 过(壳缩句后只减不增)

## 4. 提示词七修(P1-P7)

- [x] 4.1 P1:init-scout.md 中文化对象枚举删 `evidence_snippet`;init-resolve.md 同形段同判
- [x] 4.2 P2:init-induct.md 补 Form B pack 指引(对齐 t1-task.md 的 pack_id/members[] 字段)+ 
      schema 段补 canonical 8 类与「自造类名被闸门拒」句
- [x] 4.3 P3:init-survey.md 第 1 步两文件路径改绝对;读侧白名单补列该两文件(消互斥)
- [x] 4.4 P4:init-rulewriter.md 补读侧三件套段(镜像 init-survey Sanctioned tools 形态)
- [x] 4.5 P5:init-rules-consistency.md「managed block」→ 详述文件表述
- [x] 4.6 P6:rules-format-claude/opencode.md「any leak」→ FORBIDDEN_TOKENS 实况枚举
- [x] 4.7 P7:init-scout.md 删 `regex_known[]` 幽灵输入字段引用
- [x] 4.8 L1/L2:t2.md `openmode`→`opencode`;controls-context.md `中和` 中文措辞
- [x] 4.9 面收:`test_recipe_visibility` + `check_distributed_purity` +
      `test_distributed_md_purity` 全绿

## 5. 契约九修(C1-C9,以源码为准)

- [x] 5.1 C1 clusters.md:对照 `discover_controls.form_clusters` 真实公式改写 cluster_id 两行
      (4 段含 file 槽位;sha1 前 12 hex;sha8 字样全消)
- [x] 5.2 C2 scout-plan.md:flag 名改 `--batch-bytes`/`--batch-cap`;补 plan 自描述 + `--check`
      优先 plan 记录值(批次 5 实况)
- [x] 5.3 C3 candidates.md:source 枚举删 `regex+scout`
- [x] 5.4 C4 unit-inputs.md:done 检测改 forward marker 实况;bytes/oversize 按 tier 分列
      (scout=声明值,t1/t3=st_size)
- [x] 5.5 C5 manifest.md:删「unit record」幻影形状;resolve 行注记 optional/subagent 写
- [x] 5.6 C6 三枚举器契约:补各脚本 argparse 实况 flag 清单 + 分页四字段 + 恒等式改述 +
      cluster-enumeration 补 pack 模式(`--pack-bytes/--pack-max`/members[]/簇级计数)
- [x] 5.7 C7 resolved.md:补「additive 并入无确定性出口」披露
- [x] 5.8 面收:`test_init_ack_contract` / `test_recipe_visibility` 过

## 6. 回归与收尾

- [x] 6.1 定向面全绿:test_write_runconfig / test_resume_state / test_list_steps /
      test_stuck_run_selfheal / test_fanout_runner(TestAgentCloneParity 绿;TestRateLimitStorm
      存量失败不追查)/ test_agent_stage_contract / test_dsh_command_surface /
      test_init_flag_table_contract / test_recipe_visibility / test_distributed_md_purity +
      test_zero_deps + test_no_compile_warnings
- [x] 6.2 lint 四件套:check_contracts / check_distributed_prompt_budget /
      check_distributed_purity / openspec validate --strict(+ validate --specs 全过)
- [x] 6.3 `git diff --stat` 涉改面核对(3 脚本 + 3 壳 + 6 agent + 8 提示词 + 2 fragment + 10 契约
      + delta 2 能力 + VERSION/CHANGELOG/交接文档);守卫三镜像零触碰
- [x] 6.4 VERSION bump(0.1.73 → 0.1.74)+ CHANGELOG(按 H11/ack/提示词七/契约九/笔误 分组条目)
- [x] 6.5 实机冒烟(建议):`write_runconfig --merge x` exit 2 + recipe;三面壳 `--help`/参数表
      无 --merge;install 到 scratch 目标自检过(merge.md 删除后 inventory 断言不红)

## 7. 归档与战役落账

- [x] 7.1 specs 回写:control-discovery 7 MODIFIED + request-context-budget 1 MODIFIED
      (块替换引擎,场景名保留);`openspec validate --specs` 全过
- [ ] 7.2 change 移 archive/2026-10-14-fix-mgh-init-prompts-contracts-sync;归档 commit
      (按仓内 fix-mgh-* 归档风格,正文如实叙述全组收口 + 测试与 lint 结果)
- [ ] 7.3 交接文档落账:批次 7 ✅(commit hash + VERSION);战役七批全清宣告 + 遗留清单
      (批次 4 拍板项 A/B、H11 若未来有真实诉求可选 (a) 独立立项、TestRateLimitStorm 存量、
      三.16 工具事故教训);情报节订正孤儿 fragment 结论(三.17)
- [ ] 7.4 push
