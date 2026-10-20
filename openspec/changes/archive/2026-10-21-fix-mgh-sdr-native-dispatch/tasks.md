## 1. Agent 定义与提示词面

- [x] 1.1 新增 `releases/opencode/agent/sdr-review-native.md`(`mode: subagent`,不 hidden;
  权限镜像 fanout 孪生:read/glob/grep/list/bash allow、edit/external_directory/question
  deny);正文 = 与 `sdr-review-fanout` 同源的 stage 契约 + 原生增补两条标记指令(成功
  touch `done_marker`;失败自写 `failed_marker`,内容 `{unit_id, reason}`)+ 单行回执契约
  (`ok/oversize/failed`);验证:克隆对账断言两孪生 Output schema 行一致、native 额外行仅
  标记指令
- [x] 1.2 新增 `core/prompts/fragments/sdr-native-dispatch.md`(原生波次纪律 fragment:同消
  息派发/逐字转述/标记真相源/重物化重枚举/至多一轮重派/限流等窗/看门狗启动与收尾参数/诚实
  边界);措辞按 R5.5(recipe 化、NEVER 链仅硬边界);验证:purity 零违例、check_contracts
  对 fragment 内脚本 flag 引用通过
- [x] 1.3 `core/prompts/fragments/fanout/sdr-task.md` **零改动确认**(failed_marker 行注释不
  动);验证:git diff 为空 + `test_fanout_runner` 全绿

## 2. 脚本面(最小侵入)

- [x] 2.1 `list_sdr_steps.py`:原生形态判定(画像 native + 计划工件在场佐证)下 fan-out 步
  展开为「物化(bash)→ 波次派发(编排器纪律,fragment 指针)→ 渲染(bash)」;stdout 契约
  同形状扩展;验证:三形态(画像缺失/native/坏画像)步清单快照测试
- [x] 2.2 `resume_sdr_state.py`:原生分支的 step/next_action 派生(进度纯磁盘重派生;恢复
  指引首调状态查询契约不变;native 下 next_action 指到物化/派波次/渲染);验证:标记组合
  (部分完成/有失败/全完成)下的派生快照测试
- [x] 2.3 `render_sdr_report.py`:报告与 manifest 增派发形态披露行(依据 = 计划工件在场 +
  画像);数据源与渲染逻辑零变化;验证:同输入两形态渲染的 canonical 数据 diff 仅披露字段

## 3. 壳面(opencode)

- [x] 3.1 `releases/opencode/command/mgh-sdr.md`:step 0 增画像读取(env_profile 失败按其
  fail-closed 契约透传);fan-out 步增原生条件骨架(紧凑,详情指针到 fragment);claude/dsh
  面各加一行当前形态支持面披露(opencode:子进程+原生;claude/dsh:子进程);验证:预算
  lint 过、三面披露行形状锚测试、check_contracts 过
- [x] 3.2 契约同步:`core/contracts/sdr/pipeline.md` 增原生形态节(形态选择/波次循环/标记
  写者/看门狗接线/披露/版本矩阵);`core/contracts/fanout/runtime.md` native 段补「sdr 为首
  个消费方」与回退关系一句;验证:契约与实现逐项对得上

## 4. 测试(先红后绿)

- [x] 4.1 `test_list_sdr_steps` / `test_resume_sdr_state` 增原生分支用例(形态判定/步展开/
  next_action/坏画像透传);验证:新旧用例全绿
- [x] 4.2 `test_render_sdr_report` 增披露行用例 + 双形态同数据对照;验证:全绿
- [x] 4.3 壳/agent/fragment 形状锚:opencode 壳原生条件步与 fragment 指针在场、三面披露行在
  场、native 孪生克隆对账;验证:删任一锚即红
- [x] 4.4 定向回归:sdr 面 10 文件(`test_diff_group` `test_sdr_context` `test_sdr_tier`
  `test_render_sdr_report` `test_mgh_sdr_launch` `test_list_sdr_steps`
  `test_resume_sdr_state` `test_read_roots_config` `test_sensitive_catalog`
  `test_sdr_failure_chain`)+ 基础件四脚本各自测试面 + `test_zero_deps` /
  `test_no_compile_warnings` + `test_distributed_md_purity` +
  `test_dsh_command_surface`;验证:逐一跑过无失败
- [x] 4.5 lint 四件套 + 壳预算 lint + `openspec validate "fix-mgh-sdr-native-dispatch"
  --strict`;验证:与基线一致(无新增违例)

## 5. 实机闸门(本机 2.1.0)

- [x] 5.1 小仓 6 单元原生全链:画像 native → 立哨兵 → 计划物化+`--check` → 启看门狗 →
  同消息 3 并发派发 → 标记 → 重物化重枚举 → 报告;对照同输入子进程形态 run 的
  `sdr_report_data.json`:findings 集合一致(措辞差异容忍,finding 丢失为零);验证:命令
  与对照结论记入本 change 实机笔记
- [x] 5.2 故障注入五件套:①单单元 `.failed` → 至多一轮重派后缺口披露;②全波限流特征
  (伪 failed_marker reason)→ 等窗指示生效;③权限 ask(关闸门的对照探针)→ 看门狗代答拒
  绝后会话继续;④挂死(长静默会话,小阈值)→ 看门狗中止、单元回待派;⑤中途打断 →
  `resume_sdr_state` 接上且已完成单元不重做;验证:五件套结果入实机笔记
- [x] 5.3 缺省零变化抽查:无画像同仓跑子进程形态,产物与主分支行为一致;看门狗在
  run 落定后自退、无孤儿进程;验证:记录入实机笔记

## 6. 企业闸门(2.0.32,交接内网,不阻塞归档)

- [ ] 6.1 CAS 真仓 6 单元对照(原失败场景):画像 native → 全链 → 报告;附逐步复现步骤与
  预期输出;验证:内网回执 PASS 或问题清单回填(差异进契约版本矩阵)

## 7. 收尾

- [x] 7.1 VERSION bump + CHANGELOG 分组条目(原生接入/标记自写/看门狗接线/三面分歧披露/缺
  省零变化)
- [x] 7.2 根 AGENTS.md 命令族表 mgh-sdr 行与诚实边界补「原生形态(opencode,画像显式)」一
  句;实机笔记归位本 change 目录;验证:`test_distributed_md_purity` 复跑绿
