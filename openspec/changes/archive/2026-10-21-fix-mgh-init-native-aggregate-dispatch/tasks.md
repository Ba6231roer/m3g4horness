## 1. Agent 孪生(四只,releases/opencode/agent/)

- [x] 1.1 `init-induct-native.md` / `init-synthesis-native.md` / `init-scout-merge-native.md`
  (mode: subagent,权限镜像各自子进程孪生,零写权限);`init-rulewriter-native.md`(唯一带
  edit 写权限);四只正文与各自子进程孪生同源 + 原生标记自写指令;验证:克隆对账逐只锚
  (Output schema 一致、rulewriter 独有写权限、其余三只零写权限)

## 2. 纪律 fragment 与壳

- [x] 2.1 init 原生纪律 fragment 扩聚合层(或新增聚合节):通道 B 默认调用形态(计划引用/
  wave/units)、通道 A 回退纪律、各层不变量提示、看门狗参数;措辞 R5.5;验证:形状锚 + 前
  纯净 lint
- [x] 2.2 opencode 面 `mgh-init.md` 聚合步换原生骨架(紧凑);claude/dsh 面一行分歧披露;
  验证:壳预算 lint 过、三面披露行形状锚、check_contracts 过

## 3. 脚本与契约

- [x] 3.1 `list_steps.py` / `resume_state.py` 聚合层原生分支(同形状扩展,进度纯磁盘);
  验证:三形态步清单/派生快照测试
- [x] 3.2 `init_manifest` 与规则产物报告披露派发形态与通道;验证:披露字段快照测试
- [x] 3.3 契约同步:`core/contracts/init/` 流水线契约增聚合层原生形态节;fanout 契约 native
  段消费方清单补四层;验证:契约与实现逐项对得上

## 4. 测试(先红后绿)

- [x] 4.1 各层原生分支用例:`test_list_clusters`(pack 计数/闸门)/ `test_plan_aggregate`
  (零派发不变/rollup manifest)/ `test_list_rule_jobs`(正向判定/孤儿)/ `test_resume_state` /
  `test_list_steps` / `test_validate_t1_records` / `test_assemble_rules`;验证:新旧用例全绿
- [x] 4.2 孪生克隆对账 + fragment 形状锚;验证:删任一锚即红
- [x] 4.3 定向回归:init 面测试族(`test_init_*` `test_scout_*` `test_plan_aggregate`
  `test_assemble_rules` 等)+ 基础件与派发工具测试面 + `test_zero_deps` /
  `test_no_compile_warnings` + `test_distributed_md_purity`;验证:逐一跑过无失败
- [x] 4.4 lint 四件套 + 壳预算 lint + `openspec validate
  "fix-mgh-init-native-aggregate-dispatch" --strict`;验证:与基线一致

## 5. 实机闸门(本机 2.1.0,分层推进)

- [x] 5.1 小仓全链原生 smoke:发现 → scout → t1 → t2 → t3 → rules,产物(inventory/规则/
  manifest)与 runner 形态可比;验证:对照结论入实机笔记
- [x] 5.2 中规模 t1 走派发工具:数百 pack 一次调用跑完,编排器回合数不随簇数线性涨(对照
  记录);摘要与磁盘标记一致;验证:入实机笔记
- [x] 5.3 故障面:单层单元失败→至多一轮重派→缺口披露;scout-merge 缺 shard 不 rollup;
  中断续跑已完成零重做;rulewriter 越树写注入被守卫拦;验证:四项入实机笔记
- [x] 5.4 回退抽查:画像显式 runner 全链回子进程形态;验证:入实机笔记
- [ ] 5.5 企业 2.0.32 真仓全链交接(附步骤与预期,不阻塞归档);验证:内网回执或问题清单
  回填契约版本矩阵

## 6. 收尾

- [x] 6.1 VERSION bump + CHANGELOG 分组条目(四层接入/通道 B 默认/四孪生/不变量保持/回退)
- [x] 6.2 根 AGENTS.md mgh-init 行与诚实边界补聚合层原生一句;实机笔记归位;验证:
  `test_distributed_md_purity` 复跑绿
