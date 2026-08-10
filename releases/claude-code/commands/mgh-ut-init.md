---
description: Discover the test conventions a project actually uses (framework / mock / assertion / fixture / naming / dependency) by classifying the test source tree into layer-groups, sampling each group, and inducing agent-consumable rules (opencode: concise AGENTS.md lazy index + per-category detail files under docs/test-conventions/; claude: .claude/rules/test-*.md). Lean LLM-first pipeline (classify → per-group sample extraction → synthesize → rules). --format claude|opencode required (structures differ, never mix). Weak tests are flagged, NOT promoted as house-style. Rules are LLM-induced candidates needing human review.
allowed-tools: Read, Glob, Grep, Bash, Agent, Write, Edit
---

# /mgh-ut-init — discover existing test conventions → agent rules

> 编排器 = 你(宿主 agent):按本提示词,用自身工具(Bash / Agent / Read / Write / Edit)把流水线**跑出来**,而非写成代码——确定性逻辑已在 `classify_tests.py` / `list_test_groups.py` / `assemble_test_rules.py` / `validate_test_rules.py` / `derive_mutators.py` 里,直接 `Bash` 调用即可,无需 `Read` 其源码,也不要另写 `.py` 去包装或重实现。claude 下 rules tier 直写 `.claude/rules/test-<cat>.md`,由 `assemble_test_rules.py --format claude --check` 做纯净性 lint(见步骤 5)。

> **运行域 + hook**:`install.sh` 向本仓 `.claude/settings.json` 注入 PreToolUse
> hook(`block-adhoc-scripts`),在 `/mgh-ut-init` 运行域内拦 `py -c`/`python -c` 内省、**一切脚本扩展名写入**
> (`.py`/`.ps1`/`.sh`/`.ts`/…;叶脚本 read-only)、**以及 resolved 目标未落入受信子树的 `Write`/`Edit`**
> (ut-init 正向允许清单:`<target>/.mgh-ut-init/**`/`.claude/rules/**`/`docs/test-conventions/**`/`AGENTS.md`/
> 哨兵 `out_roots[]`;命中退出码 2 + stderr recipe 指向 `list_test_groups.py` stdout 的 `checkpoint_path`/`rule_path`)。编排器**起步先**
> `Bash: export MGH_UT_INIT_ACTIVE=1` 标记运行域 + 写磁盘哨兵 `<target>/.mgh-ut-init/.active`,并在起步
> `export MGH_TARGET=<绝对 repo>`(供 hook 判树;缺失则该条降级放行)。opt-out = `install.sh --no-enforce-hook`
> (纪律仍由 orchestrator-discipline fragment + 边界校验兜底)。守卫激活 = env **或** 磁盘哨兵(哨兵绕开 opencode「插件不继承
> mid-session env」的可靠性边界,见 `core/contracts/hooks/runtime-enforcement.md`)。

You are the **orchestrator** of the mgh-ut-init pipeline. Carry it out by running the
deterministic leaf scripts (Bash) and spawning stage subagents (Agent). Shared assets
live at `.claude/mgh-core/` (mirrored from `core/`).

> **Rules are LLM-induced candidates, not confirmed conventions.**
> Human review required. State this in every summary.

## Parse arguments (validate BEFORE spending tokens)

- `--target <dir>` (default `.`)
- `--format opencode|claude` — **required** (mutex). Missing → error + STOP.
- `--out <path>` (claude default `<target>/.claude/rules`; opencode default `<target>/AGENTS.md`)
- `--rules-dir <path>` (opencode default `<target>/docs/test-conventions`; 详述文件目录,透传给 `list_test_groups.py`/`assemble_test_rules.py`)
- `--scope path:<dir>|package:<pkg>|file:<glob>`(限定测试源码树范围)
- `--resume` (skip units whose `.done` **or** `.failed` exists — both terminal) · `--merge <partials-dir>`(本版无 ut 合并 stage;传之仅披露后按单 target 继续) · `--skip-consistency` (skip the consistency pass)
- 抽样预算 flag:`--uniform-sample <N>`(均匀组样本数,默认 4)· `--hetero-sample <N>`(异质组样本数,默认 8)· `--subsplit-threshold <F>`(均匀/异质阈值,默认 0.8)
- **请求上下文预算**:`--max-unit-bytes <N>`(单 fan-out 单元物化输入上限,默认 192KB)· `--orch-budget-bytes <N>`(编排器单次请求可见的待办壳页上限,默认 64KB;超则自动分页收紧,stdout `shrunk:true`)· `--max-aggregate-bytes <N>`(聚合输入上限,默认 256KB;synthesize 为软边界——超则披露 + `--scope` 回退)

**No actionable args / `--help`** → print the flag table and STOP (zero tokens).

## Orchestrator discipline

> **REQUIRED SUB-SKILL: Use orchestrator-discipline** — 跑流水线前先加载完整编排纪律(claude `.claude/mgh-core/prompts/fragments/orchestrator-discipline.md`):三条 `NEVER` 硬边界(脚本扩展名 Write / `py -c` 内省 / Read 叶脚本源码)、implementation-intention recipe、fan-out 刚性三元组、`.failed` 终态、长跑 Bash per-call `timeout`、resume-from-disk、Re-entrancy & compaction。

编排器 = 宿主 agent(非物化脚本);完整纪律见上述 fragment。本壳下文 stage 流给 ut-init 专属实例(确切 `list_ut_steps.py`/`list_test_groups.py`/`resume_ut_init_state.py`/`write_ut_runconfig.py` 调用行、产物清单、`MGH_UT_INIT_ACTIVE` + `.mgh-ut-init/.active` 哨兵、ut-init 边界披露)。

> **stdout 直消费**:Bash tool result 已含 stdout(最后一行是 JSON);NEVER 把确定性脚本输出重定向到 `$env:TEMP`/`%TEMP%`/`/tmp` 再回读——直接取工具返回值。

## Orchestration flow

```
0. parse + self-check(测试源码树统计超阈值则建议 `--scope` 分模块;**花 token 前**前置建议,见 orchestrator-discipline fragment)
   · **起步**:`Bash: export MGH_UT_INIT_ACTIVE=1`(声明运行域,激活 PreToolUse hook,含子树外 Write/Edit 拦截)
   · **run_config(无状态 resume 意图源)**:起步后、花 token 前,**原子写** `<target>/.mgh-ut-init/run_config.json`
     (起始态意图:记决定步骤图的本次 flag;与终态 `ut_manifest.json` 边界清晰、互不替代):
     `py .claude/mgh-core/scripts/write_ut_runconfig.py --target <abs target> --format <fmt> [--scope ..] [--skip-consistency] [--uniform-sample ..] [--hetero-sample ..] [--subsplit-threshold ..] [--max-unit-bytes ..] [--orch-budget-bytes ..] [--max-aggregate-bytes ..]`
     该文件使 `/mgh-ut-init --resume` **无需重输 flag**;`resume_ut_init_state.py` 据它解析分支。
     `--resume` 复用既有 run_config(不覆盖);新 run(`.mgh-ut-init/` 不存在或被清)重写。
   · **哨兵(磁盘激活信号,opencode 可靠激活兜底)**:`write_ut_runconfig.py` stdout 的 `target` 即**绝对项目根**
     (Windows 原生、供守卫 `Path.resolve()` 判树;**NEVER** 用 bash `pwd`,其 MSYS `/c/...` 在 Windows pathlib 误解析)。
     据此写哨兵:
     `printf '%s' '{"domain":"mgh-ut-init","target":"<write_ut_runconfig stdout 的 target>","out_roots":[<非默认 --out/--rules-dir 解析后绝对根,默认产物根不列>],"v":1}' > <target>/.mgh-ut-init/.active`
     完成态(step 7)/ 干净停止 `rm <target>/.mgh-ut-init/.active`;`--resume` step 0 重写覆盖。
   · **MGH_TARGET**(供 hook 判树;= 哨兵 `target`,二者一致):`write_ut_runconfig.py` stdout `target` 即绝对根——
     `export MGH_TARGET=<该 value>`(**NEVER** `py -c` 自算、**NEVER** 用裸 `.` 相对)。`--resume` 时 run_config 仍在 → 同法重设。
   · **步骤图**:`py .claude/mgh-core/scripts/list_ut_steps.py [--step <id>]`(确切脚本调用行;宿主前缀自动派生)
1. classify(确定性,便宜预处理):
     py .claude/mgh-core/scripts/classify_tests.py --repo <target> --out <target>/.mgh-ut-init [--scope .. --subsplit-threshold F]
   → test_groups.json(按被测层/SUT 分桶:controller/service/repository/config/integration/util/other;混合子风格拆子组;每组成员清单 + 均匀度提示 + 断言密度)
   · 派生量直读 classify stdout:`groups/scanned/unclassified`(NEVER `py -c` 自算)
   · 校验:`py .claude/mgh-core/scripts/classify_tests.py --check <target>/.mgh-ut-init`(每个文件恰进一组、清单与磁盘一致;退出码 2 → 回退重跑)
2. EXTRACT FAN-OUT — 经确定性脚本枚举 + 样本物化(**禁手搓**;fan-out 单元 = 层组,非逐文件):
   [test_groups.json::groups[]] → list_test_groups.py --tier extract --materialize → [stdout slim pending[](每项 `group_id`/`input_path`/`checkpoint_path`/`done_marker`/`failed_marker`)]
     py .claude/mgh-core/scripts/list_test_groups.py --tier extract --groups <target>/.mgh-ut-init/test_groups.json --checkpoints <target>/.mgh-ut-init/checkpoints/extract --materialize <target>/.mgh-ut-init/inputs/extract [--sample-uniform N --sample-hetero N]
   按 `offset`/`effective_limit` 翻页(单页 > `--orch-budget-bytes` 时 `shrunk:true`;NEVER wrapper `.py`);per group in page `pending[]`(`--resume` 跳过已 `.done`/`.failed`):
     - spawn ut-extract(透传 `input_path` + checkpoint_path + done_marker + failed_marker;subagent 读 `input_path`,提炼该层约定——框架/mock/断言/夹具/命名/依赖;**识别样本里的应付式弱测试、不把它的模式当约定**,弱测试标记不删)→ 成功则恰好写 `checkpoint_path`(绝对) + touch `done_marker`;失败回 `failed <原因>` ack → 编排器写 `failed_marker`、不重试不阻断(见 orchestrator-discipline fragment「fan-out 单元 `failed` ack」)
   · 终态门:extract tier `done + failed >= total`(读 `resume_ut_init_state.py` stdout `tiers.extract`)
3. synthesize(汇总去重;大仓超 `--max-aggregate-bytes` 则披露 + `--scope` 回退):
   - spawn ut-synthesize(全部 extract 观察,无原始码)→ test_rules_inventory.json + checkpoints/synthesize/.done
   · 校验:`py .claude/mgh-core/scripts/validate_test_rules.py --inventory <target>/.mgh-ut-init/test_rules_inventory.json`(每条 category/name/anchor/evidence/provenance/confidence;退出码 2 → 回退重跑)
4. RULES FAN-OUT — 经确定性脚本枚举 + per-category 物化(**禁手挖** inventory / `py -c`):
   [test_rules_inventory.json::rules[].category] → list_test_groups.py --tier rules --materialize → [stdout slim pending[](每项 `category`/`input_path`/`rule_path`/`done_marker`/`failed_marker`)]
     py .claude/mgh-core/scripts/list_test_groups.py --tier rules --inventory <target>/.mgh-ut-init/test_rules_inventory.json --format <format> --checkpoints <target>/.mgh-ut-init/checkpoints/rules --target <target> --rules-dir <target>/docs/test-conventions --materialize <target>/.mgh-ut-init/inputs/rules
   按 `offset`/`effective_limit` 翻页;per category in page `pending[]`(WITHOUT `.done`/`.failed`;`--resume` 跳过):
     - spawn ut-rulewriter(透传 `input_path` + --format + rule_path + done_marker + failed_marker;subagent 读 `input_path`)
     → 成功则恰好写 `rule_path`(绝对;claude: `.claude/rules/test-<cat>.md`;opencode: 详述文件 `docs/test-conventions/<cat>.md`)+ touch `done_marker`;失败回 `failed <原因>` ack → 编排器写 `failed_marker`、不重试不阻断
5. ASSEMBLE / LINT (Bash, deterministic; uses the run's --format, after rules / before consistency):
     py .claude/mgh-core/scripts/assemble_test_rules.py --target <target> --format <format>
   · opencode: 扫 `<rules-dir>/*.md` 详述文件建 `<target>/AGENTS.md` 简洁**惰性索引块**(幂等、迁移旧 `mgh-ut-init:` 块、内置 lint);正文留详述文件按需加载
   · claude: 无索引(rules tier 已直写文件),仅对 `.claude/rules/test-*.md` 做纯净性 lint
   · lint(fail-loud 退出码 2)= 规则正文泄漏:工具内部 token(`mgh-ut-init`/脚本名/`.mgh-ut-init/`)/ schema 字段
     (`assert_density`/`uniformity`/`weak_dominated`/`group_id`)/ 过程散文(`归类器子分`/`抽样提炼`/`断言密度`)/
     无源码锚点约定;opencode 另查 `---` YAML 围栏(claude `paths:` frontmatter 豁免)。回 rules 修正后重跑。
   · touch `<target>/.mgh-ut-init/checkpoints/assemble/.done`(assemble 完成标记)
6. consistency (unless --skip-consistency): spawn ut-rules-consistency
     → in-place edits to rule files (claude) / detail files (opencode) + checkpoints/consistency/.done
7. 收尾(确定性):
   · `py .claude/mgh-core/scripts/derive_mutators.py --repo <target> --out <target>/.mgh-ut-init`(解析 pitest 配置
     → default_mutators.json;无配置 → `source:"builtin-fallback"` 内置标准集 + 披露)
     · 校验:`py .claude/mgh-core/scripts/derive_mutators.py --check <target>/.mgh-ut-init`
   · 写 ut_manifest.json + report.md(含失败披露 / 边界)
   · **fan-out 失败披露**(任一 tier `failed>0`):据 `resume_ut_init_state.py` stdout `tiers[<tier>].failed`(磁盘真相、**NEVER** 对话记忆)写 `ut_manifest.json::failures`(per-tier `{done,failed,total}`)+ `boundaries[]` + `report.md` 同步披露
   · **收尾移除哨兵**:`rm <target>/.mgh-ut-init/.active`(run 完成;避免残留哨兵锁死日常开发)
```

### Stage → component map

| Stage | How | Asset |
|---|---|---|
| classify | **script** | `core/scripts/classify_tests.py` (分桶 + 均匀度提示 + 断言密度) |
| step enumeration | **script** | `core/scripts/list_ut_steps.py` (确切调用行;`script_abs` 宿主无关) |
| extract enumerate | **script** | `core/scripts/list_test_groups.py` (--tier extract;pending 按组清单) |
| extract | subagent `ut-extract` (fan out per group) | `core/prompts/stages/ut-extract.md` (弱测试不学成家法) |
| synthesize | subagent `ut-synthesize` | `core/prompts/stages/ut-synthesize.md` (跨组去重 + provenance) |
| inventory validate | **script** | `core/scripts/validate_test_rules.py` (synthesize 边界) |
| rules enumerate | **script** | `core/scripts/list_test_groups.py` (--tier rules;pending 按 category) |
| rules | subagent `ut-rulewriter` (fan out per category) | `core/prompts/stages/ut-rulewriter.md` |
| assemble/lint | **script** | `core/scripts/assemble_test_rules.py` (opencode: 建 AGENTS.md 惰性索引块 + 迁移旧块;双格式 `--check` 纯净 lint) |
| consistency | subagent `ut-rules-consistency` (opt) | `core/prompts/stages/ut-rules-consistency.md` |
| mutators | **script** | `core/scripts/derive_mutators.py` (pitest 配置 → default_mutators.json;无配置内置标准集) |
| resume | **script** | `resume_ut_init_state.py` / `write_ut_runconfig.py` (磁盘重派生 step/next_action) |

### Deterministic invocation (Bash)

```bash
py .claude/mgh-core/scripts/write_ut_runconfig.py --target . --format opencode
py .claude/mgh-core/scripts/resume_ut_init_state.py --target .
py .claude/mgh-core/scripts/resume_ut_init_state.py --target . --check
py .claude/mgh-core/scripts/list_ut_steps.py --target .
py .claude/mgh-core/scripts/classify_tests.py --repo . --out ./.mgh-ut-init
py .claude/mgh-core/scripts/classify_tests.py --check ./.mgh-ut-init
py .claude/mgh-core/scripts/list_test_groups.py --tier extract --groups ./.mgh-ut-init/test_groups.json --checkpoints ./.mgh-ut-init/checkpoints/extract --materialize ./.mgh-ut-init/inputs/extract --offset 0 --limit 50 --max-unit-bytes 196608 --orch-budget-bytes 65536
py .claude/mgh-core/scripts/list_test_groups.py --tier rules --inventory ./.mgh-ut-init/test_rules_inventory.json --format claude --checkpoints ./.mgh-ut-init/checkpoints/rules --target . --rules-dir docs/test-conventions --materialize ./.mgh-ut-init/inputs/rules --offset 0 --limit 50 --max-unit-bytes 196608 --orch-budget-bytes 65536
py .claude/mgh-core/scripts/validate_test_rules.py --inventory ./.mgh-ut-init/test_rules_inventory.json
py .claude/mgh-core/scripts/assemble_test_rules.py --target . --format claude --check
py .claude/mgh-core/scripts/derive_mutators.py --repo . --out ./.mgh-ut-init
py .claude/mgh-core/scripts/derive_mutators.py --check ./.mgh-ut-init
```

### Resume / cache
- **`--resume` 首步** = `py .claude/mgh-core/scripts/resume_ut_init_state.py --target <target>` → 读 stdout `step`/`next_action`/`tiers` 继续(进度纯从磁盘 `<target>/.mgh-ut-init/` 重派生;**NEVER** 靠对话记忆判步骤)。`--check` 可在起步校验磁盘状态自洽(退出码 2 = 不自洽)。
- **新 session 运行域 env 重注入**:`--resume` 走同一命令壳 step 0 → 重新 `export MGH_UT_INIT_ACTIVE=1`;并从既有 `run_config.json`/`write_ut_runconfig.py` stdout 重设 `MGH_TARGET`。**确定性脚本本身不读 env**(flag + 磁盘驱动),env 仅影响 hook 子树守卫强度。
- Work units: classify whole, **extract per group**, synthesize whole, **rules per category**, consistency whole, mutators whole.
- `<target>/.mgh-ut-init/checkpoints/<tier>/<unit>.json.done`(成功)**或** `.failed`(确认失败)= 终态,gate `--resume`(均跳过、不重派);`run_config.json` 使 `--resume` 免重输 flag。
- 无 codegraph 解析步骤(ut 步骤图:classify→extract→synthesize→rules→assemble→consistency→mutators→done)。

## Output (per `<target>/.mgh-ut-init/`)

- `test_groups.json` — classify 产物(层组分桶 + 均匀度提示 + 断言密度;fan-out 单元源)
- `checkpoints/extract/*.json` — per-group 观察记录 (resume) · `inputs/extract/<group>.input.json` — 样本物化输入(subagent 自读)
- `test_rules_inventory.json` — 跨组去重后的规则 inventory(每条带 provenance + confidence + weak_dominated)
- `checkpoints/rules/*.json` — per-category 检查点 (resume) · `inputs/rules/<cat>.input.json`
- `default_mutators.json` — pitest mutator 清单(`{source,mutators[],parser_notes[]}`;留 `/mgh-ut --mutators` 消费)
- `ut_manifest.json` — version/format/counts/provenance/boundaries[] · `report.md` — 人读总结
- rules → claude:`<target>/.claude/rules/test-*.md`;opencode:`<target>/AGENTS.md` 简洁**惰性索引块** `<!-- test-conventions:begin --> … :end -->` + 每实现 category 一个详述文件 `<target>/docs/test-conventions/<cat>.md`(均经 `assemble_test_rules.py` 纯净性 lint)

## Always disclose
- 面向人读的非代码内容(`report.md`、`ut_manifest.json` 的 `boundaries[]`/文案、rules 正文)
  用**简体中文**;锚点/路径/frontmatter 保持原样。

- **Rules are LLM-induced candidates, not confirmed conventions — human review required.**
- **Rules are 提示、非完备规约**:抽样提炼必有遗漏(均匀组只读代表性少数样本、异质组多样本/子分),后续 `/mgh-ut` 的 LLM 写测试时会看到真实测试、自适应。
- **弱测试只标记不删**:识别出的应付式弱测试(零断言/同义反复/mock 被测对象本身/只 happy-path/近重复模板)在观察记录标记、**不修改/删除被测源码**、不学成家法;弱信号主导约定标低置信 + 需人评。
- **fan-out 失败披露**:任一 tier `failed>0` → `ut_manifest.json::failures` + `boundaries[]` + `report.md`(fan-out 单元确认失败、已跳过、终局需人评);`.failed` 为终态、resume 不重派。
- **pitest mutator 清单仅作默认**:`source:"builtin-fallback"` 表示未发现 pitest 配置、用内置标准集;后续 `/mgh-ut --mutators` 以此为默认消费口。
- **JVM-only**:本版只扫 Java/Kotlin/Scala/Groovy 测试源码树;其余语言不覆盖。
- **宿主 shell 超时**:opencode 可经环境变量 `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS`(默认 120000)提升全局 shell 超时,但**须在 opencode 启动前就绪**(会话中途 `export` 不被 opencode 插件进程继承);per-call `timeout`(见 orchestrator-discipline fragment 长跑 Bash 超时纪律)是跨宿主公共杠杆、会话内即时生效。claude Bash per-call `timeout` 上限 600000ms。
- **请求上下文预算(确定性边界)**:每次大模型请求 ≤ 配置阈值(`--max-unit-bytes`/`--orch-budget-bytes`/`--max-aggregate-bytes`);`oversize`/`shrunk`/聚合超限在 `ut_manifest.json::boundaries[]` + `report.md` 披露(无静默溢出)。synthesize 聚合为软边界(披露 + `--scope` 回退)。
- **从目标项目根调用 `/mgh-ut-init`**(launch-cwd 前置):step 0 首调 `list_ut_steps.py` 用相对 `.claude/mgh-core/scripts/` 路径,解析于编排器 Bash cwd(命令壳加载处 = 目标项目)。下游工具路径经其 stdout `script_abs` 已全钉死绝对,但**首调本身**依赖从目标项目根发起。
