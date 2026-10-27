# tasks — harden-mgh-init-output-gates

> 执行约定:每节先写红测试再实现(R5.8);脚本改动后跑"改动面→测试文件"映射表的定向
> 回归;收尾 lint 四件套 + bump VERSION/CHANGELOG。

## 1. 锚点解析共享模块(design D2)

- [ ] 1.1 写 `tests/test_anchor_resolve.py`(红):token 三形态解析、解析阶梯
      exact→case→唯一 basename、行号范围、符号逐段子串、归一化匹配;basename 非唯一/
      缺失两类失败形态
- [ ] 1.2 实现 `core/scripts/anchor_resolve.py`(纯标准库、自包含、惰性 basename 索引、
      任意 cwd 安全)使 1.1 绿
- [ ] 1.3 `tests/test_zero_deps.py` / `test_no_compile_warnings` 顺手跑绿

## 2. 证据锚点存在性门(control-discovery · T2 边界)

- [ ] 2.1 扩 `tests/test_validate_inventory.py`(红):三形态各一好例;
      file_missing / line_out_of_range / symbol_absent / by_basename 四类违例各一;
      stdout 分类计数键;stderr 首 N 示例含控制名
- [ ] 2.2 扩 `core/scripts/validate_inventory.py`(导入 anchor_resolve;`--inventory`
      契约不变,新增退出条件与输出字段)使 2.1 绿;同步脚本 docstring 与
      `core/contracts/init/inventory.md` 的边界描述
- [ ] 2.3 回归:`tests/test_validate_t1_records.py`(兄弟边界不受影响)

## 3. 覆盖对账门 + 缺口披露(rules-emission · 装配边界)

- [ ] 3.1 扩 `tests/test_assemble_rules.py`(红):全呈现 → 通过 + 受管块「覆盖:M/M」
      披露行且幂等;未呈现 → 不写盘/退出码 2/stderr 按 category 计数 + 首 N 名单;
      `--accept-coverage-gaps` → 写盘 + 「覆盖:N/M」+ 台账 coverage_gaps_accepted;
      claude 面对账同判
- [ ] 3.2 扩 `core/scripts/assemble_rules.py`(对账复用 anchor_resolve;披露行整行幂等
      替换;报告/manifest coverage 小节)使 3.1 绿
- [ ] 3.3 契约同步:`core/contracts/init/rules-assembly*.md`(或装配所在契约)补对账
      节;`core/prompts/fragments/init-stage/t3.md`/`done.md` 补"对账失败 → T3 受影响
      类别重派一轮;仍失败 → assemble --accept-coverage-gaps 收口并披露"指引
- [ ] 3.4 回归:`tests/test_recipe_visibility.py`、`test_distributed_md_purity.py`、
      `python tools/check_distributed_prompt_budget.py`

## 4. marker↔记录对账(control-discovery · 枚举器 + resume)

- [ ] 4.1 扩 `tests/test_list_scout_batches.py`(红):`.done` 在记录缺 → 该批回
      `pending[]` + `marker_without_record` 计数;重派认领删旧 `.done`
- [ ] 4.2 扩 `tests/test_list_clusters.py`(红):t1 同判;`pack__` 前缀豁免不误报;
      checkpoint 目录未知文件(如设计外记账文件)输出告警计数(不失败)
- [ ] 4.3 扩 `tests/test_resume_state.py`(红):`--check` 对 marker-without-record 报
      退出码 2 + 计数 + recipe(重派自愈);豁免闭集(pack/t3/t2 终结标记)零误报
- [ ] 4.4 实现三处(枚举器 pending 判定 + 计数字段;resume 违例;未知文件告警)使
      4.1–4.3 绿;同步 `core/contracts/init/scout-plan.md`/`clusters.md` 的 pending 语义
      与 resume-state 契约
- [ ] 4.5 回归:`tests/test_stuck_run_selfheal.py`、`test_init_runtime.py`

## 5. 合法 JSON 校验通道 + 禁自发账本(control-discovery · 模板与守卫)

- [ ] 5.1 扩 `tests/test_block_adhoc_scripts.py`(红):`py -m json.tool <子树内路径>`
      运行域内放行;`py -c` 仍拦;若现状已放行则用例固化为回归锚
- [ ] 5.2 守卫解释器规则按 5.1 结果最小改(模块白名单窄口,判定仍在守卫单一真源;
      三端 parity 副本字节级同步 + `test_opencode_hook_parity`/
      `test_dsh_hook_parity` 跑绿)
- [ ] 5.3 五个 `core/prompts/fragments/fanout/*-task.md` 各加"写入后 `py -m json.tool`
      只读校验,失败即单元失败(NEVER 摸 .done、NEVER 为过校验改内容)"指令;t1-task
      Form B 加"NEVER 写包级账本/清单/manifest 文件"一行
- [ ] 5.4 扩 `tests/test_init_native_dispatch.py` 静态锚(五模板校验指令行 + t1 禁令行;
      更新"共享任务模板"相关既有断言);`test_agent_stage_contract` 如涉模板锚同步
- [ ] 5.5 回归:`tests/test_fanout_runner.py`(harness 传 `--cooldown-s  0`)、
      `test_fanout_stale.py`、`test_scout_plan.py`、`test_plan_aggregate.py`

## 6. 收口

- [ ] 6.1 lint 四件套:`check_contracts` / `check_distributed_purity` /
      `check_distributed_prompt_budget` / `check_plain_language`(存量 exit 2 三旧
      proposal 之外零新增)
- [ ] 6.2 三面壳核查:opencode/claude/dsh 壳的 assemble 调用行不变、新失败形态只住
      fragment;`test_dsh_command_surface.py` 跑绿
- [ ] 6.3 bump VERSION + CHANGELOG;本文件逐项勾选
- [ ] 6.4 定向回归总跑(本 tasks 涉及的全部测试文件清单逐一执行,全绿)
