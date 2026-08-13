---
description: Discover existing reusable security controls in a project (input-validation / data-masking / authentication / authorization / crypto / rate-limiting / csrf / audit-logging) and emit agent-consumable rules (opencode: concise AGENTS.md lazy index + per-category detail files under docs/security-controls/; claude: path-scoped .claude/rules/*.md). Three-tier isolation-first pipeline (deterministic discover → T1 per-cluster induct → T2 synthesis → T3 per-category rules → T4 consistency). --format claude|opencode required (structures differ, never mix). Supports --scope/--resume/--merge and large-file sharding. Findings are LLM-induced candidates needing human review.
allowed-tools: Read, Glob, Grep, Bash, Agent, Write, Edit
---

# /mgh-init — discover existing security controls → agent rules

> 编排器 = 你(宿主 agent):按本提示词,用自身工具(Bash / Agent / Read / Write / Edit)把流水线**跑出来**,而非写成代码——确定性逻辑已在 `discover_controls.py` / `chunk_sources.py` / `plan_scout.py` / `merge_scout.py` / `assemble_rules.py` 里,直接 `Bash` 调用即可,无需 `Read` 其源码,也不要另写 `.py` 去包装或重实现。claude 下 T3 直写 `.claude/rules/security-<cat>.md`,由 `assemble_rules.py --format claude --check` 做纯净性 lint(见步骤 6b)。

> **运行域 + hook**:`install.sh` 向目标项目 `.claude/settings.json` 注入 PreToolUse hook(`block-adhoc-scripts`),
> 运行域内拦 `py -c` 内省、一切脚本扩展名写入、子树外 `Write`/`Edit`(命中退出码 2)。**守卫激活 = `MGH_INIT_ACTIVE=1` env 或磁盘哨兵 `<target>/.mgh-init/.active`**(哨兵写法见 bootstrap fragment;纪律见 orchestrator-discipline fragment)。
> opt-out = `install.sh --no-enforce-hook`(纪律仍由 orchestrator-discipline fragment + 边界校验兜底)。

You are the **orchestrator** of the mgh-init pipeline. Carry it out by running the
deterministic leaf scripts (Bash) and spawning stage subagents (Agent). Shared assets
live at `.claude/mgh-core/` (mirrored from `core/`).

> **Output is LLM-induced, not confirmed. Controls are "existing", not "effective".**
> Human review required. State this in every summary.

## Parse arguments (validate BEFORE spending tokens)

- `--target <dir>` (default `.`)
- `--format opencode|claude` — **required** (mutex). Missing → error + STOP.
- `--out <path>` (claude default `<target>/.claude/rules`; opencode default `<target>/AGENTS.md`)
- `--scope path:<dir>|package:<pkg>|file:<glob>` + `--scope-mode defined|applicable` (default `defined`)
- `--language <lang>`, `--max-files <N>`, `--big-file-bytes <N>` (default 200KB), `--sample <N>` (default 8), `--progress-every <N>` (默认 1000), `--large-repo-threshold <N>` (默认 15000;超阈值则前置建议 `--scope`+`--merge`)
- `--include-dotfiles` (默认关;扫描点前缀路径 `.opencode`/`.claude`/`.codegraph`/`.github`/`.env`。默认跳过——tooling/VCS/IDE/build/config/索引 非一方业务代码;控制定义点落在 `.xxx` 内时传此 flag 纳入)
- `--include-tests` (默认关;扫描测试源码树 `src/test`/`src/tests`(Maven/Gradle/Kotlin)与 `tests`/`__tests__`/`__mocks__`/`spec`/`specs` 目录段。默认跳过——测试代码对「发现生产安全控制」是净噪声:mock/stub(`@MockBean SecurityConfig`、`mock(SecurityChecker)`)把安全组件物化成调用图里的伪控制、故意写脆弱的测试夹具(渗透训练 `VulnerableApp`、禁用 TLS / 放宽 CORS / 占位密钥 / dummy JWT issuer)命中成真实控制特征、且测试码不上线;控制定义点落在测试目录内时传此 flag 纳入)
- `--resume` (skip units whose `.done` **or** `.failed` exists — both terminal) · `--rebuild-cache` (rebuild call graph)
- `--merge <partials-dir>` (merge multiple scoped runs; then STOP)
- `--skip-consistency` (skip T4) · `--config <profile>` (default `init`)
- `--no-scout` (skip LLM scout discovery; legacy regex-only behavior) · `--scout-budget <N>` (0=全量目标) · `--scout-batch-bytes <N>` (默认 96KB) · `--scout-batch-cap <N>` (默认 40) · `--scout-audit-pct <N>` (默认 15)
- **请求上下文预算**(`request-context-budget`,确定性边界强制每次大模型请求 ≤ 阈值;单位字节):`--max-unit-bytes <N>`(单 fan-out 单元物化输入上限,默认 192KB;oversize 簇切 `::shard-<n>`、scout 批/T3 category 标 `oversize`)· `--orch-budget-bytes <N>`(编排器单次请求可见的待办壳页上限,默认 64KB;超则自动分页收紧,stdout `shrunk:true`)· `--max-aggregate-bytes <N>`(聚合输入上限,默认 256KB;T2/scout-merge 经 `plan_aggregate.py` **硬阈值**——> 预算自动 map-reduce;T4 仍软边界 + `--scope`/`--merge` 回退;触发 + shard 数进 `boundaries[]`/`report.md`)
- `--no-codegraph` (skip optional codegraph enrichment; legacy behavior). codegraph 检测默认 `auto`:仅当 `<target>/.codegraph/` 存在**且** PATH 有 `codegraph` 才启用;`--no-codegraph` 或不可用 → 富化 off(行为等价于引入 codegraph 前)

**No actionable args / `--help`** → print the flag table and STOP (zero tokens).

## Orchestrator discipline

> **REQUIRED SUB-SKILL: Use orchestrator-discipline** — 跑流水线前先加载完整编排纪律(claude `.claude/mgh-core/prompts/fragments/orchestrator-discipline.md`):三条 `NEVER` 硬边界(脚本扩展名 Write / `py -c` 内省 / Read 叶脚本源码)、implementation-intention recipe、fan-out 刚性三元组、`.failed` 终态、长跑 Bash per-call `timeout`、resume-from-disk、Re-entrancy & compaction。

编排器 = 宿主 agent(非物化脚本);完整纪律见上述 fragment。本壳下文 stage 流给 init 专属实例(确切 `list_steps.py`/`list_clusters.py`/`list_scout_batches.py`/`list_rule_jobs.py`/`resume_state.py`/`write_runconfig.py` 调用行、产物清单、`MGH_INIT_ACTIVE` + `.mgh-init/.active` 哨兵、init 边界披露)。

> **stage 流细节按需加载(per-step fragment,非同时驻留)**:`--step <id>` 只吃 `resume_state.py` stdout `step` 的**命名 id**;NEVER 数字索引。当前步执行前 `py .claude/mgh-core/scripts/resume_state.py --target <target>` → 读 stdout `step` + `stage_flow_files[]` → `py .claude/mgh-core/scripts/list_steps.py --step <step>` 取确切调用行 → **Read `stage_flow_files[0]`**(当前步 fragment `.claude/mgh-core/prompts/fragments/init-stage/<step>.md`)加载该步纪律。**NEVER 整份加载全部 step fragment、NEVER 从对话记忆判当前步**。**fresh-run(首 run,`<target>/.mgh-init/` 不存在 / resume_state exit 1)不走该循环**:Read `.claude/mgh-core/prompts/fragments/init-stage/bootstrap.md`(固定路径)按之执行 bootstrap(run_config 原子写 / 哨兵 / MGH_TARGET / codegraph),再 resume_state → `discover` 进统一循环;NEVER 对 bootstrap 调 `list_steps --step <数字>`。

## Orchestration flow

> **完整 stage 流逐步细节见 per-step fragment 集 `init-stage/{<step>}.md`**(经上方 recipe 按当前步加载):`not-started`(bootstrap)→ `discover` → `survey`(opt)→ `scout` → `resolve`(opt)→ `t1` → T1→T2 闸门 → `t2` → `t3` → `assemble`(BUILD INDEX+LINT)→ `t4` → `merge`(--merge 模式)→ `done`。下方 Stage→组件表给全图概览。

### Stage → component map

| script inventory | subagent inventory |
|---|---|
| `discover_controls` · `chunk_sources`(大文件切片)· `describe_artifact`(瞄结构合法出口)· `list_clusters`/`list_scout_batches`/`list_rule_jobs`(fan-out 枚举)· `plan_scout`/`merge_scout` · `validate_inventory`(T2 边界)· `validate_t1_records`(T1→T2 闸门)· `assemble_rules`(T3 assemble/lint)· `resume_state`/`write_runconfig`/`plan_aggregate` | `init-survey`(opt)· `init-resolve`(opt,codegraph-gated)· `init-induct`(T1)· `init-synthesis`(T2)· `init-rulewriter`(T3)· `init-rules-consistency`(T4,opt)· `init-scout`/`init-scout-merge`/`init-scout-audit`(scout) |

- 绝对脚本路径由 `list_steps.py` 运行时给(stage 流内调用行即契约面);**非平凡复用**:`expand_scope.py`(discover 复用)、`merge_scout.py` 复用 `discover_controls.form_clusters`(簇形成语义无漂移)。
- 每 stage 产物经产出者 `--check` 校验(`discover_controls`/`plan_scout`/`merge_scout`/`validate_inventory`/`validate_t1_records`/`assemble_rules`)。

### Resume / cache
- **`--resume`/压缩后第一步** = `py .claude/mgh-core/scripts/resume_state.py --target <target>` → 读 stdout `step` + `discipline_reminders[]`,**先按该步纪律执行**(gate `--check` 闸门 / 路径配方 / 适用 NEVER),再 `py .claude/mgh-core/scripts/list_steps.py --step <step>`(`--step` 取命名 id;NEVER 数字索引)取确切调用行继续(进度纯从磁盘 `<target>/.mgh-init/` 重派生)——NEVER 靠对话记忆判步骤、NEVER 跳过 gate、NEVER 在 `discipline_reminders[]` 空时静默继续(空纪律仅对 `done` 步合法)。`--check` 可在起步校验磁盘状态自洽(退出码 2 = 不自洽)。
- **过期凭证 recipe**:起步 `resume_state.py --check` 若报「scout 启用 + scout 未完 + 下游 t2/t3/t4 `.done`」违例(退出码 2)= 下游 marker 是基于 regex-only 输入的**过期凭证** → 先 `py .claude/mgh-core/scripts/resume_state.py --target <target> --invalidate-stale --dry-run` 预览,再 `--invalidate-stale` 清除,然后续跑——NEVER 手工 `del` 下游 marker、NEVER 静默跳过已过期 tier。
- **新 session 运行域 env 重注入**:`--resume` 走同一命令壳 bootstrap(not-started)步 → 重新 `export MGH_INIT_ACTIVE=1`;并在 fan-out 前从既有 `controls_candidates.json::repo` 重设 `MGH_TARGET`(产物在盘上、`describe_artifact.py --field repo`,无需重跑 discover)。**确定性脚本本身不读 env**(flag + 磁盘驱动),env 仅影响 hook 子树守卫强度。
- **launch-cwd 前置(跨 session 纪律)**:**首次** `list_steps.py` 调用(discover 步)用相对 `.claude/mgh-core/scripts/` 路径,解析于编排器 Bash cwd(命令壳加载处 = 目标项目根)。下游工具路径经其 stdout `script_abs` 已全钉死绝对,但**首调本身**依赖从目标项目根发起;从歧义 cwd 调用可使首调命中错 install 副本。新 session 续跑前确认 cwd。
- Work units (isolation unit): i1 per file, **scout per batch**, T1 per cluster, T2/T4 whole, T3 per category.
- `<target>/.mgh-init/checkpoints/<tier>/<unit>.json.done`(成功)**或** `.failed`(确认失败)= 终态,gate `--resume`(均跳过、不重派);`run_config.json` 使 `--resume` 免重输 flag。
- Call graph is rebuilt by discover each run; pass `--rebuild-cache` to force (mtime-based skip otherwise).

## Output (per `<target>/.mgh-init/`)

- `controls_candidates.json` — raw deterministic hits + scout candidates(audit trail;每条带 `source`)
- `skeleton.json` — 无损逐文件元数据(scout 输入;纯机械抽取,不含语义判定)
- `scout_plan.json` — scout 批次规划(字节预算 + 包内聚)
- `scout_candidates.json` — merge 后的 scout 候选(`source:"scout"`)+ `unresolved[]`
- `clusters.json` — T1 isolation units (centralized/distributed,regex 簇 + 追加的 scout 簇);包装结构 `{repo,clusters[],truncated}` 见 `core/contracts/init/clusters.md`
- `controls_inventory.json` — structured (`design_controls`-compatible); downstream input for `/mgh-sra`, `/mgh-blst`, future mgh-sast control intake
- `checkpoints/**` — per-unit artifacts (resume)
- `inputs/<tier>/<unit>.input.json` — per-unit materialized fan-out inputs (subagent 自读;≤ `--max-unit-bytes`;随 `.mgh-init/` gitignore;见 `core/contracts/init/unit-inputs.md`)
- `init_manifest.json` — version/format/counts/provenance/unresolved[]/out_of_scope[]/boundaries[]
- `report.md` — human-readable summary (+「competing controls」section)
- rules → claude:`<target>/.claude/rules/security-*.md`;opencode:`<target>/AGENTS.md` 简洁**惰性索引块** `<!-- security-controls:begin --> … :end -->` + 每实现 category 一个详述文件 `<target>/docs/security-controls/<cat>.md`(均经 `assemble_rules.py` 纯净性 lint)

## Always disclose
- LLM-induced candidates — human review required.
- **Existence ≠ effectiveness** (CVE-2025-41248: `@PreAuthorize` bypass on parameterized types).
- Call-graph is textual/AST-level — misses AOP/reflection/DI/framework-routing; surface `unresolved[]`.
- **Scout coverage is partial, not whole-repo**;scout 非确定(簇数 run-to-run 可能变化);残留盲区见 `report.md`。
- 面向人读的非代码内容(`report.md`、`init_manifest.json::boundaries[]` 文案、rules 正文)用**简体中文**;锚点/路径/frontmatter 保持原样。

> 其余边界细节(dotfiles/tests 默认跳过、宿主 shell 超时、codegraph 富化辅助、请求上下文预算、大仓 `--scope`/`--merge`)由脚本写入 `init_manifest.json::boundaries[]` + `report.md`(运行时落盘),摘要**复述**命中项即可,NEVER 遗漏**实际触发**的边界触发计数。

