# Tasks: adopt-mgh-init-fanout-t1-t3

## 1. runner 泛化(`core/scripts/fanout_runner.py`)

- [x] 1.1 tier 映射表 `TIERS`(design D1):`--tier scout|t1|t3` 缺省 scout;scout 既有三 flag
  语义不变,t1 增 `--clusters`/`--candidates`,t3 增 `--inventory`/`--format`/`--rules-dir`;
  必需 flag 缺失 → 退出码 2 + 可操作报错;`--help` 契约面同步(含 tier 调用示例与三级超时
  不变式保留)
- [x] 1.2 `_list_pending` 按 tier 调用兄弟枚举脚本(scout→`list_scout_batches`、t1→
  `list_clusters --materialize`、t3→`list_rule_jobs --materialize`);**退出码 2 透传**
  (design D4:t1 scout 闸门 stderr recipe 原样转发,NEVER 吞成退出码 1 重派空转);stdout
  JSON 消费、每波重派生 pending 逻辑复用
- [x] 1.3 占位符集/path_fields/模板路径/agent 名/marker `tier` 值参数化(design D1/D2):
  `_fill_template`/`_anchor_check`/`_write_failed_marker`/`_spawn_cmd` 从映射表取参;
  t3 字段集 = `input_path/rule_path/done_marker/failed_marker` + `category`/`format`;
  stdout 摘要增 `tier` 字段
- [x] 1.4 sidecar 改名 `fanout_progress.<tier>.json` + body 增 `tier` 字段(design D6);
  原子写/人面语义/「计数与 stdout 摘要同源」单测锚定不变
- [x] 1.5 复核 R5.3b:stdout JSON/stderr 严格分流、退出码 0/1/2、幂等、无 TTY、闭集参数、
  `--purge-audit --dry-run` 守卫——三 tier 全适用(`--dry-run` alone 现确定性 skip dispatch,契约落地)

## 2. 枚举脚本与提示词面

- [x] 2.1 `list_rule_jobs.py` stdout 顶层增 `repo` 字段(`--target` resolve 绝对值,与
  `list_clusters` 同式;design D3);`--help` 文案同步
- [x] 2.2 新模板 `core/prompts/fragments/fanout/t1-task.md` / `t3-task.md`(与 scout-task.md
  同形状:仅输入字段声明 + 指向 `stages/init-induct.md`/`init-rulewriter.md` 的装载指令,
  零行为规则复制;t3 含 `format`/`rule_path`/`category` 字段声明);模板占位符集与
  `TIERS` 映射一致(单测断言)
- [x] 2.3 opencode fanout agent 克隆 `releases/opencode/agent/init-induct-fanout.md` /
  `init-rulewriter-fanout.md`(`mode: primary`,正文 = 既有定义逐字克隆 + fanout 标注;
  design D5);回归测断言克隆正文与非-fanout 定义正文一致
- [x] 2.4 `core/prompts/fragments/init-stage/t1.md`/`t3.md` 派发段改 dispatcher-first
  (design D7:复制 scout.md 已验证结构,换 tier 调用行;`--time-budget-ms` 显式示例 +
  「MUST < 宿主 per-call timeout」+ `partial:true` 重派 + 退出码 2 回退(区分宿主不可用 →
  手派 / scout 闸门 → 先完成 scout)+ 宿主外直跑逃生门;手派路径原文保留;T1→T2 validate
  与 t3 assemble 段不动);token 复测 ≤ 上限

## 3. 契约面与分发

- [x] 3.1 `core/scripts/list_steps.py` t1/t3 步:invocation 增 dispatcher 调用行;
  `core/scripts/discipline_core.py` t1/t3 步 path_recipes 增 fanout-dispatcher recipe(含
  「重派传 per-call `timeout` > `--time-budget-ms`」纪律)
- [x] 3.2 `tools/check_contracts.py`:`FANOUT_RUNNER_REQUIRED_FLAGS` 增 `--tier`/`--clusters`/
  `--candidates`/`--inventory`/`--format`/`--rules-dir` 断言;新增模板文件的存在性断言
- [x] 3.3 `install.sh`:镜像规则覆盖新模板(t1-task/t3-task.md)与 opencode fanout agent
  克隆;自检清单同步;`docs/man/mgh-init.md` sidecar 改名 + t1/t3 手动直跑说明
- [x] 3.4 双壳 `releases/{claude-code,opencode}/command/mgh-init.md`:核对 t1/t3 段引用
  (调用行在 list_steps 契约面,预期不变);token lint 复测
- [x] 3.5 版本号 bump(改动的一切 `.md`/脚本)+ CHANGELOG(sidecar 改名一次性破坏标注)

## 4. 回归与冒烟

- [x] 4.1 `tests/test_fanout_runner.py` 扩展:既有 21 用例全绿(scout 语义等价);新增 tier
  参数化用例(t1/t3 模板填充与占位符集、锚树校验含 t3 `rule_path` 双格式、list 退出码 2
  透传、sidecar per-tier 命名与 stdout 摘要一致性、marker body `tier` 值、必需 flag 缺失
  退出码 2)——当前 49 用例全绿(21 scout 基线语义等价 + 28 新增)
- [x] 4.2 既有回归全绿(test_deterministic + test_init_runtime + test_list_steps +
  test_resume_state + test_list_scout_batches + test_init_ack_contract + test_zero_deps +
  test_distributed_md_purity 等)+ 契约 lint + 纯净性 lint + 双壳 token lint——完整套件
  923 用例全绿
- [x] 4.3 真机冒烟(小仓,双宿主各一轮,scout+t1+t3):dispatcher 路径产 t1 checkpoint 与
  t3 rule 文件,marker 集合与手派路径等价;`partial:true` 早退 + 重派接续;sidecar
  `fanout_progress.t1.json` 可见推进;大仓长跑面由维护者复跑确认
  ——真实 list 脚本集成 + `--dry-run` 冒烟(t1/t3 各一轮:audit 副本 + sidecar `tier` 字段 +
  退出码 0;t1 scout 闸门真实退出码 2 透传 + recipe 转发 + 零 spawn);live-LLM 产物面
  (真实 subagent 写 checkpoint/rule + marker 等价)与大仓长跑由维护者复跑确认
