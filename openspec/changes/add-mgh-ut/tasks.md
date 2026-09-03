# Tasks — add-mgh-ut

> 实现顺序按依赖;每个任务可验证。新脚本全部 Python ≥3.10 标准库、零依赖、自包含(自定位兄弟导入、
> utf-8 读写、任意目录可直接 `py` 跑)、`--check` 边界校验(退出码 0/2)、stdout=JSON/stderr=进度严格分流。
> run-config/resume 挂共享 `runconfig_core`/`resume_core`(前置变更 `extract-ut-shared-helpers`)。

## 1. diff 单元抽取(确定性)

- [ ] 1.1 `core/scripts/extract_diff_units.py`:`git diff --unified=3 <base>..<head> -- <src>` → 行为变更
  方法单元;方法级优先(codegraph 增强;缺席降级到类/文件级);行为变更判定 = 方法体非空白/非注释字符
  超阈值(默认 >20)+ 排除 cosmetic/delete/move/rename;`--repo`/`--base`/`--head`/`--out`/`--check`;
  stdout=JSON、stderr=进度、退出码 0/1/2。
- [ ] 1.2 pin 阈值 + rename/move 检测相似度阈值 + codegraph 缺席降级路径(design Open Questions 落地)。

## 2. mgh-ut run-config / resume(挂共享 core)

- [ ] 2.1 `core/scripts/resume_ut_state.py`:挂 `resume_core`,mgh-ut 步骤图 = extract→audit→generate→
  consistency→done;`--target`/`--init-dir`/`--run-root`(默认 `.mgh-ut`)/`--check`;stdout
  `{step,next_action,tiers,notes}`;`run_config.json` 缺失 → 退出码 2 + recipe。
- [ ] 2.2 mgh-ut run_config 写(挂 `runconfig_core`,`--run-root .mgh-ut`):持久化 base/head/mutators/rules/
  change/skip-consistency;使 `--resume` 免重输 flag。

## 3. fan-out 工作清单(每行为变更单元)

- [ ] 3.1 `core/scripts/list_ut_units.py`(或复用/扩展既有 `list_*` 模式):读 diff 单元产物,产 fan-out
  工作清单(stdout slim `pending[]`,每项含 `checkpoint_path`/`done_marker`/`failed_marker`,均
  `Path.resolve()` 绝对)+ 分页 flag(`--offset`/`--limit`/`--max-unit-bytes`/`--orch-budget-bytes`)。
- [ ] 3.2 产物物化:每单元物化审计输入(覆盖测试定位信息 + diff hunks)到 `inputs/audit/<unit>.input.json`。

## 4. subagent 提示词 + agent 定义

- [ ] 4.1 `core/prompts/stages/ut-audit.md` + agent(`ut-audit`):定位覆盖测试(codegraph 符号引用/命名约定);
  审计弱信号(断言虚弱/有执行无验证/过度 Mock/Mock 不足/仅 happy-path/变异脆弱代理/模板复制)+ **mutator
  透镜**(「flip 这运算符测试还会过吗」);产 per-unit findings;无覆盖 → 报告 + 继续补缺。
- [ ] 4.2 `core/prompts/stages/ut-generate.md` + agent(`ut-generate`):据 findings + rules + mutator 清单
  生成增强提案(新测试/强化断言杀 mutator + 覆盖分支);**MUST 按发现的 mock 约定 mock 协作者**(DB/HTTP/
  外部服务/静态依赖/时间;存量 mock 不足 = 必须修正项);无 rules → 从 diff 邻近测试惰性发现约定;
  产出暂存 `.mgh-ut/proposals/<unit>.proposal.json` + `.md`。
- [ ] 4.3 `core/prompts/stages/ut-consistency.md` + agent(`ut-consistency`):跨单元一致性 pass(可选,
  `--skip-consistency` 跳过)。
- [ ] 4.4 claude(`releases/claude-code/agents/`)与 opencode(`releases/opencode/agent/`)双端 agent 定义。

## 5. SDD-spec 富化(openspec 优先,MVP 仅 openspec)

- [ ] 5.1 富化读取器(确定性/编排):读未归档 openspec change(`--change <name>` 显式,缺省最新未归档)
  的 `proposal.md`/`design.md` 作富化输入;无 openspec / 指定名称不存在 → 跳过富化、无 spec 路径继续。
- [ ] 5.2 富化上下文注入 `ut-audit`/`ut-generate`(仅作可选上下文,非模式开关)。

## 6. 第 6 hook 域 + parity

- [ ] 6.1 `block_adhoc_scripts.py` 域表加 `("mgh-ut", "MGH_UT_ACTIVE", ".mgh-ut")`;受信子树/out-of-tree
  逻辑更新(六域);契约 `core/contracts/hooks/runtime-enforcement.md` 同步。
- [ ] 6.2 扩 `tests/test_block_adhoc_scripts.py` + `tests/test_opencode_hook_parity.py`(第 6 域双端对等)。

## 7. 壳 + 契约 + 工具 + 自检

- [ ] 7.1 新壳 `releases/claude-code/commands/mgh-ut.md` + `releases/opencode/command/mgh-ut.md`:薄壳,
  `REQUIRED SUB-SKILL` 引用 orchestrator-discipline;stage 流 + 确切脚本调用行 + `MGH_UT_ACTIVE`/哨兵 +
  边界披露(LLM 候选需人评 / proposals 暂存 / 变异硬化非已验证 / 启发式 / 富化可选 / JVM-only)。
- [ ] 7.2 契约 `core/contracts/ut/*.md`(diff-units / findings / proposals / mutators / resume-state)。
- [ ] 7.3 `tools/check_contracts.py` 加 ut 断言;`install.sh` 自检清单加 ut 脚本族。
- [ ] 7.4 `tests/test_extract_diff_units.py`、`test_ut_runtime.py`、`test_resume_ut_state.py`;扩分发纯净测。

## 8. 收尾

- [ ] 8.1 bump 版本号;跑全套回归 + 三项 lint(契约 / 分发纯净 / 零依赖);`install.sh` 自检 fail-soft。
- [ ] 8.2 诚实边界汇总(对用户输出):测试增强是 LLM 候选需人评;proposals 暂存 `.mgh-ut/proposals/` 不
  直写 `src/test`;变异硬化是设计上抗变异、非已验证杀死变异(不跑 pitest);行为变更判定启发式;SDD 富化
  可选且 MVP 仅 openspec;JVM-only。
