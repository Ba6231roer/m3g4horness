# Tasks — add-mgh-ut-init

> 实现顺序按依赖;每个任务可验证。新脚本全部 Python ≥3.10 标准库、零依赖、自包含(自定位兄弟导入、
> utf-8 读写、任意目录可直接 `py` 跑)、`--check` 边界校验(退出码 0/2)、stdout=JSON/stderr=进度严格分流。

## 1. 归类器(确定性,便宜预处理)

- [x] 1.1 `core/scripts/classify_tests.py`:按被测层/SUT 类型把测试文件分桶(controller/service/repository/
  config/util/…);归类信号 = 实际注解 + import + 包路径 + 文件名(不靠名字猜);混合子风格(`@WebMvcTest`
  vs `@SpringBootTest`+`TestRestTemplate`)拆子组;输出每组成员清单 + 均匀度提示 + 廉价质量提示(组内断言密度);
  `--repo`/`--out`/`--scope`/`--check`;stdout=JSON、stderr=进度、退出码 0/1/2。
- [x] 1.2 pin 归类桶集 + 均匀度阈值 + Util 异质组子分策略(design Open Questions 落地)。

## 2. fan-out 工作清单 + 复用冒烟

- [x] 2.1 `core/scripts/list_test_groups.py`:读归类产物,产 fan-out 工作清单(stdout slim `pending[]`,每项
  含样本物化 `input_path`/`checkpoint_path`/`done_marker`/`failed_marker`,均 `Path.resolve()` 绝对)+ 分页 flag
  (`--materialize`/`--offset`/`--limit`/`--max-unit-bytes`/`--orch-budget-bytes`)。
- [x] 2.2 抽样物化:均匀组取代表性少数样本、异质组多样本/子分,物化到 `inputs/extract/<group>.input.json`
  (≤ 单元字节预算)。
- [x] 2.3 复用冒烟:断言 `plan_aggregate.py`/`chunk_sources.py`/`describe_artifact.py` 经 ut 路径参数零改动复用,
  输出落 `.mgh-ut-init/`;若某脚本有名字绑定阻断复用 → 记录并改走新建薄壳。

## 3. 提炼 / 汇总 subagent 提示词

- [x] 3.1 `core/prompts/stages/ut-extract.md`:读组样本,提炼该层约定(框架/mock/断言/夹具/命名/依赖);
  **识别弱测试、不学成家法**(可证伪 checklist:零断言/同义反复/mock 被测对象本身/只 happy-path/近重复模板);
  弱测试标记不删;产 per-group 观察 JSON。
- [x] 3.2 `core/prompts/stages/ut-synthesize.md`:跨组观察去重归并成 rules(每层/每约定一条)+ provenance
  (从哪组样本归纳、强/弱信号计数);弱信号主导约定标低置信 + `boundaries[]`。
- [x] 3.3 `core/prompts/stages/ut-{rulewriter,rules-consistency}.md`:逐层写规则 + 一致性 pass。

## 4. rules 组装 + 校验 + mutator 派生(确定性收尾)

- [x] 4.1 `core/scripts/assemble_test_rules.py`:opencode 建 `<target>/AGENTS.md` 惰性索引块(迁移旧块、幂等)
  + 双格式纯净 lint(ut 专属 token + schema 字段 + 过程散文 + YAML 围栏[opencode]);`--target`/`--format`/`--check`
  (fail-loud 退出码 2);claude 侧仅 lint `.claude/rules/test-*.md`。
- [x] 4.2 `core/scripts/validate_test_rules.py`:校验 rules schema(每条指向具体文件/类/方法 + provenance +
  confidence∈[0,1] + weak_dominated);`--inventory <path>`(退出码 0/1/2;该脚本本身即 synthesize 边界
  校验器,无 `--check` 子模式)。
- [x] 4.3 `core/scripts/derive_mutators.py`:解析 `pom.xml`/`build.gradle`/`build.gradle.kts` pitest 配置 →
  `default_mutators.json` `{source,mutators[],parser_notes[]}`;无配置 → `source:"builtin-fallback"` 内置标准集
  + `boundaries[]` 披露。pin fallback 集成员(pitest 官方默认组)。

## 5. ut resume / 起始态 / step 枚举(拷贝自 init)

- [x] 5.1 `core/scripts/resume_ut_init_state.py`:拷贝 `resume_state.py` 改 ut 步骤图(含「归类」前置、无 codegraph
  解析、ut 产物名);`--target`/`--init-dir`/`--run-root`(默认 `.mgh-ut-init`)/`--check`;stdout
  `{step,next_action,tiers,notes}`;`run_config.json` 缺失 → 退出码 2 + recipe。**init 的 `resume_state.py` 零改动。**
- [x] 5.2 `core/scripts/write_ut_runconfig.py`:持久化 ut 起始态 flag;`--target`/`--format`/`--init-dir`/`--run-root`
  (默认 `.mgh-ut-init`);原子写 `<target>/.mgh-ut-init/run_config.json` + stdout `target`(绝对,供哨兵)。
- [x] 5.3 `core/scripts/list_ut_steps.py`:ut step 枚举 + `script_abs` 绝对脚本路径派生(`<mgh-core>/scripts/`)。

## 6. 第 5 hook 域(双端)

- [x] 6.1 `releases/{claude-code/hooks,opencode/hooks}/block_adhoc_scripts.py`:`_DOMAINS` 加
  `("mgh-ut-init", "MGH_UT_INIT_ACTIVE", ".mgh-ut-init")`;`_WORKLIST["mgh-ut-init"]` = `list_test_groups.py`;
  `_AGGREGATES["mgh-ut-init"]` = ut 多单元聚合产物;判定逻辑不改,只扩域表 + recipe + 受信子树集。
- [x] 6.2 写入受信子树:正向允许清单参数化(复用 init 的判定逻辑),ut-init 受信集 `.mgh-ut-init`/`.claude/rules`/
  `docs/test-conventions`/`AGENTS.md` ∪ 哨兵 `out_roots[]`。
- [x] 6.3 `tests/test_opencode_hook_parity.py` 扩第 5 域双端 byte-identical parity;`tests/test_block_adhoc_scripts.py`
  扩 ut-init 激活/越树/根污染断言。

## 7. 命令壳(双端薄壳)

- [x] 7.1 `releases/claude-code/commands/mgh-ut-init.md` + `releases/opencode/command/mgh-ut-init.md`:顶部
  `REQUIRED SUB-SKILL: Use orchestrator-discipline` 引 fragment;`description`/`allowed-tools` frontmatter;壳内
  步骤流(归类→抽样提炼→汇总→组装→[一致性])+ 确切脚本调用行 + `MGH_UT_INIT_ACTIVE`/`.mgh-ut-init/.active` 哨兵
  + `MGH_TARGET` 重设 + 边界披露;≤500 行 / ≤5000 tokens。
- [x] 7.2 stage→component map + Deterministic invocation + Resume/cache + Output + Always disclose 段(镜像 mgh-init
  壳结构,换 ut 实例)。
- [x] 7.3 与在途 `add-mgh-telemetry-seam` 协调:ut-init 两壳成功末步的运行回执脚本调用(谁先 apply 另一方补)。

## 8. 契约(core/contracts/ut-init/)

- [x] 8.1 镜像 `core/contracts/init/` 目录结构新建 ut 契约:分组清单 / 样本输入 / rules / mutators / resume-state /
  unit-inputs;换 test-convention schema。
- [x] 8.2 `core/contracts/hooks/runtime-enforcement.md` 扩第 5 域 mgh-ut-init(run-root `.mgh-ut-init`、env
  `MGH_UT_INIT_ACTIVE`、正向允许清单子树)。

## 9. 工具 + install 自检

- [x] 9.1 `tools/check_contracts.py`:加 `UT_INIT_SHELLS`、ut 新脚本 CLI 契约断言(每 flag 跑 `--help`);
  `LIST_SCRIPTS` 类覆盖 `list_test_groups.py`;resume/writeconfig/list_steps 类覆盖 ut 三个拷贝脚本。
- [x] 9.2 `install.sh` 共定位自检清单加 ut 脚本族;自检 fail-soft、CI 必 fail。
- [x] 9.3 `tools/check_distributed_purity.py` 扫描集覆盖 ut-init 壳 + `core/prompts/stages/ut-*.md`。

## 10. 测试

- [x] 10.1 `tests/test_classify_tests.py`:分桶(按实际注解/import,非名字)+ 混合子风格拆分 + 均匀度提示 +
  `--check`。
- [x] 10.2 `tests/test_ut_init_runtime.py`:归类产物形状 + fan-out 工作清单 + 复用脚本路径透传(任务 2.3)。
- [x] 10.3 `tests/test_resume_ut_init_state.py`:ut 步骤图(含归类前置、无 codegraph 解析)/`.failed` 终态/
  `--check` 自洽/`run_config` 缺失退出码 2。
- [x] 10.4 `tests/test_ut_init_ack_contract.py`:ut 壳调用的脚本 flag 全在 `--help`。
- [x] 10.5 `tests/test_test_rules_purity.py`:`assemble_test_rules.py --check` 对泄漏 token/schema/无锚点约定 fail-loud。
- [x] 10.6 扩 `tests/test_distributed_md_purity.py`(ut 壳 + ut stage 提示词)。

## 11. 版本 bump + 全回归 + 三项检查

- [x] 11.1 bump 涉事 `.md`/脚本版本号。
- [x] 11.2 跑既有全套回归测(`test_deterministic.py`/`test_init_runtime.py`/`test_resume_state.py`/
  `test_write_runconfig.py`/`test_sra_prepare.py`/`test_srr_report.py`/`test_init_ack_contract.py`/
  `test_distributed_md_purity.py`/`test_opencode_hook_parity.py` 等)全绿——确认既有命令零回归(尤其
  `resume_state.py`/`write_runconfig.py` 未被本变更改动)。
- [x] 11.3 三项检查全绿:`tools/check_contracts.py`(契约)、`tools/check_distributed_purity.py`(分发纯净)、
  零依赖 AST 扫描(新脚本无第三方 import)。
- [x] 11.4 `install.sh` 自检 fail-soft 通过(ut 脚本族共定位);CI 必 fail 配置就绪。

## 12. 评审修复(docs/review-add-mgh-ut-init.md,F1–F9;F10 暂缓)

> 承接 2026-08-06 评审:10 条 spec/契约/壳/实现漂移(无运行时破坏)。spec delta 修正已随本 change 原地落:
> F1/F2/F3/F4/F8/F9 在 `test-convention-discovery` ADDED delta;F5/F7 在 `runtime-hook-enforcement` MODIFIED
> delta;design.md 工作流 Step 3 + 本节 4.2 的 `--check`→`--inventory` 措辞已改。下列为实现侧 + 校验侧任务。

- [x] 12.1 **F3/F4 双壳**:`releases/{claude-code/commands,opencode/command}/mgh-ut-init.md` Parse-args 段删
  `--language`、`--config`(step-0 `write_ut_runconfig` 调用行本就未传 `--language`)。`write_ut_runconfig.py`
  保留 `--language`(默认 JVM、reserved、不广告,不破 `check_contracts` 的 write_ut_runconfig flag 断言)。
- [x] 12.2 **F6 契约**:`core/contracts/hooks/runtime-enforcement.md` 哨兵 `out_roots[]` 行「init only」→
  「init & ut-init」(ut 受信子树表 line 97 已列 out_roots,标注意与之一致)。
- [x] 12.3 **F5 baseline Purpose**:`openspec/specs/runtime-hook-enforcement/spec.md` Purpose「跨四命令」→
  「跨五命令」(`openspec show` 读 baseline → 保即时一致;delta 侧 `## Purpose` 已落 MODIFIED delta)。
- [x] 12.4 **F9 resume 回读**:`core/scripts/resume_ut_init_state.py` `resolve()` 回读 `run_config.json` 的
  `uniform_sample`/`hetero_sample`/`subsplit_threshold`;extract tier `next_action` 携带
  `--sample-uniform <U>`/`--sample-hetero <H>`;state 增 `sampling` 字段透出。保持退出码契约(0/2)不变。
- [x] 12.5 **F9 测试**:扩 `tests/test_resume_ut_init_state.py`——首跑 `--uniform-sample 8 --hetero-sample 16`
  → 中断 → `--resume`:extract `next_action` 携带回读值、state `sampling` 透出、用户免重输;且 init 的
  `resume_state.py` 零改动零回归。
- [x] 12.6 **F3/F4 契约测**:扩 `tests/test_ut_init_ack_contract.py`——断言双壳 Parse-args 不再广告
  `--language`/`--config`;保留的 `write_ut_runconfig.py --language` 仍在其 `--help`(reserved)。
- [x] 12.7 **F1 措辞校验**:grep 确认全仓无残留 `validate_test_rules.py --check`(design.md / tasks.md /
  双壳 / 契约均应为 `--inventory`)。
- [x] 12.8 bump 涉事 `.md`/脚本版本号;跑全套回归(尤 `test_resume_ut_init_state.py`/`test_resume_state.py`/
  `test_ut_init_ack_contract.py`/`test_block_adhoc_scripts.py`/`test_opencode_hook_parity.py` 零回归)+ 三项检查
  (`tools/check_contracts.py`/`tools/check_distributed_purity.py`/零依赖 AST 扫描)。
- [x] 12.9 `openspec validate add-mgh-ut-init --strict` 全绿(ADDED + MODIFIED delta well-formed);
  `openspec show runtime-hook-enforcement --type spec` Purpose 显五域(F5 即时校验);grep delta 文件确认
  F1(validate Requirement)/F2(阻塞序列)/F7(degrade)/F8(--rules-dir)/F9(回读契约)均落位。
