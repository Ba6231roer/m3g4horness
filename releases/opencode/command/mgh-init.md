---
description: Discover existing reusable security controls in a project (input-validation / data-masking / authentication / authorization / crypto / rate-limiting / csrf / audit-logging) and emit agent-consumable rules (opencode: concise AGENTS.md lazy index + per-category detail files under docs/security-controls/; claude: path-scoped .claude/rules/*.md). Three-tier isolation-first pipeline (deterministic discover → T1 per-cluster induct → T2 synthesis → T3 per-category rules → T4 consistency). --format claude|opencode required (structures differ, never mix). Supports --scope/--resume/--merge and large-file sharding. Findings are LLM-induced candidates needing human review.
---

# /mgh-init — discover existing security controls → agent rules

> 编排器 = 你(宿主 agent):按本提示词,用自身工具(Bash / Agent / Read / Write / Edit)把流水线**跑出来**,而非写成代码——确定性逻辑已在 `discover_controls.py` / `chunk_sources.py` / `plan_scout.py` / `merge_scout.py` / `assemble_rules.py` 里,直接 `Bash` 调用即可,无需 `Read` 其源码,也不要另写 `.py` 去包装或重实现。opencode 下 T3 每 category 直写**详述文件**(`docs/security-controls/<cat>.md`,独立 H1 文档),`assemble_rules.py` 扫该目录建 `AGENTS.md` 简洁**惰性索引块**(按需加载,见步骤 6b)。

> **运行域 + hook**:`install.sh` 向目标项目 `.opencode/plugins/` 注入 `tool.execute.before` 插件(`block-adhoc-scripts`),
> 事件归一化后管道喂**同一** Python 守卫(`.opencode/hooks/block_adhoc_scripts.py`,与 claude 端零差异);运行域内拦 `py -c` 内省、
> 一切脚本扩展名写入、子树外 `Write`/`Edit`(命中阻断)。**守卫激活 = `MGH_INIT_ACTIVE=1` env 或磁盘哨兵 `<target>/.mgh-init/.active`**——
> 哨兵关闭了 opencode「插件进程不继承 mid-session env」的可靠性边界,使守卫整 run 可靠激活(哨兵写法见 step 0;纪律见 orchestrator-discipline fragment)。
> opt-out = `install.sh --no-enforce-hook`(纪律仍由 orchestrator-discipline fragment + 边界校验兜底)。

You are the **orchestrator** of the mgh-init pipeline. Carry it out by running the
deterministic leaf scripts (Bash) and spawning stage subagents. Shared assets live
at `.opencode/mgh-core/` (mirrored from `core/`).

> **Output is LLM-induced, not confirmed. Controls are "existing", not "effective".**
> Human review required. State this in every summary.

## Parse arguments (validate BEFORE spending tokens)

- `--target <dir>` (default `.`)
- `--format opencode|claude` — **required** (mutex). Missing → error + STOP.
- `--out <path>` (opencode default `<target>/AGENTS.md`; claude default `<target>/.claude/rules`)
- `--rules-dir <path>` (opencode default `<target>/docs/security-controls`; 详述文件目录,透传给 `list_rule_jobs.py`/`assemble_rules.py`)
- `--scope path:<dir>|package:<pkg>|file:<glob>` + `--scope-mode defined|applicable` (default `defined`)
- `--language <lang>`, `--max-files <N>`, `--big-file-bytes <N>` (default 200KB), `--sample <N>` (default 8), `--progress-every <N>` (默认 1000), `--large-repo-threshold <N>` (默认 15000;超阈值则前置建议 `--scope`+`--merge`)
- `--include-dotfiles` (默认关;扫描点前缀路径 `.opencode`/`.claude`/`.codegraph`/`.github`/`.env`。默认跳过——tooling/VCS/IDE/build/config/索引 非一方业务代码;控制定义点落在 `.xxx` 内时传此 flag 纳入)
- `--include-tests` (默认关;扫描测试源码树 `src/test`/`src/tests`(Maven/Gradle/Kotlin)与 `tests`/`__tests__`/`__mocks__`/`spec`/`specs` 目录段。默认跳过——测试代码对「发现生产安全控制」是净噪声:mock/stub(`@MockBean SecurityConfig`、`mock(SecurityChecker)`)把安全组件物化成调用图里的伪控制、故意写脆弱的测试夹具(渗透训练 `VulnerableApp`、禁用 TLS / 放宽 CORS / 占位密钥 / dummy JWT issuer)命中成真实控制特征、且测试码不上线;控制定义点落在测试目录内时传此 flag 纳入)
- `--resume` · `--rebuild-cache` · `--merge <partials-dir>` · `--skip-consistency` · `--config <profile>` (default `init`)
- `--no-scout` (skip LLM scout discovery; legacy regex-only) · `--scout-budget <N>` (0=全量) · `--scout-batch-bytes <N>` (默认 96KB) · `--scout-batch-cap <N>` (默认 40) · `--scout-audit-pct <N>` (默认 15)
- **请求上下文预算**(`request-context-budget`,确定性边界强制每次大模型请求 ≤ 阈值;单位字节):`--max-unit-bytes <N>`(单 fan-out 单元物化输入上限,默认 192KB;oversize 簇切 `::shard-<n>`、scout 批/T3 category 标 `oversize`)· `--orch-budget-bytes <N>`(编排器单次请求可见的待办壳页上限,默认 64KB;超则自动分页收紧,stdout `shrunk:true`)· `--max-aggregate-bytes <N>`(聚合输入上限,默认 256KB;T2/scout-merge 经 `plan_aggregate.py` **硬阈值**——> 预算自动 map-reduce;T4 仍软边界 + `--scope`/`--merge` 回退;触发 + shard 数进 `boundaries[]`/`report.md`)
- `--no-codegraph` (skip optional codegraph enrichment; legacy behavior). codegraph 检测默认 `auto`:仅当 `<target>/.codegraph/` 存在**且** PATH 有 `codegraph` 才启用;`--no-codegraph` 或不可用 → 富化 off(行为等价于引入 codegraph 前)

**No actionable args / `--help`** → print the flag table and STOP (zero tokens).

## Orchestrator discipline

> **REQUIRED SUB-SKILL: Use orchestrator-discipline** — 跑流水线前先加载完整编排纪律(opencode `.opencode/mgh-core/prompts/fragments/orchestrator-discipline.md`):三条 `NEVER` 硬边界(脚本扩展名 Write / `py -c` 内省 / Read 叶脚本源码)、implementation-intention recipe、fan-out 刚性三元组、`.failed` 终态、长跑 Bash per-call `timeout`、resume-from-disk、Re-entrancy & compaction。

编排器 = 宿主 agent(非物化脚本);完整纪律见上述 fragment。本壳下文 stage 流给 init 专属实例(确切 `list_steps.py`/`list_clusters.py`/`list_scout_batches.py`/`list_rule_jobs.py`/`resume_state.py`/`write_runconfig.py` 调用行、产物清单、`MGH_INIT_ACTIVE` + `.mgh-init/.active` 哨兵、init 边界披露)。

> **REQUIRED SUB-SKILL: Use init-stage-flow** — 加载 mgh-init stage 流逐步细节(opencode `.opencode/mgh-core/prompts/fragments/init-stage-flow.md`):step 0–8 的 run_config 写、哨兵生命周期、codegraph 检测、discover/scout/T1/T2/T3/T4 的 fan-out 刚性三元组与 `--check` 校验、聚合硬阈值、级联失效与失败落账。

## Orchestration flow

> **完整 stage 流逐步细节(step 0–8)见 init-stage-flow fragment**(上方 SUB-SKILL 指令):parse+self-check → run_config+哨兵+codegraph 检测(step 0)→ discover(2)→ init-survey opt(3)→ SCOUT FAN-OUT(3b)→ init-resolve opt(3c)→ T1 FAN-OUT(4)→ T1→T2 闸门(4b)→ T2(5)→ T3 FAN-OUT(6)→ BUILD INDEX+LINT(6b)→ T4(7)→ manifest+report+收尾(8)。下方 Stage→组件表给全图概览。

### Stage → component map

| script inventory | subagent inventory |
|---|---|
| `discover_controls` · `chunk_sources`(大文件切片)· `describe_artifact`(瞄结构合法出口)· `list_clusters`/`list_scout_batches`/`list_rule_jobs`(fan-out 枚举)· `plan_scout`/`merge_scout` · `validate_inventory`(T2 边界)· `validate_t1_records`(T1→T2 闸门)· `assemble_rules`(opencode: 扫 `<rules-dir>/*.md` 建 `AGENTS.md` 惰性索引 + `--check` 纯净 lint)· `resume_state`/`write_runconfig`/`plan_aggregate` | `init-survey`(opt)· `init-resolve`(opt,codegraph-gated)· `init-induct`(T1)· `init-synthesis`(T2)· `init-rulewriter`(T3)· `init-rules-consistency`(T4,opt)· `init-scout`/`init-scout-merge`/`init-scout-audit`(scout) |

- 绝对脚本路径由 `list_steps.py` 运行时给(stage 流内调用行即契约面);**非平凡复用**:`expand_scope.py`(discover 复用)、`merge_scout.py` 复用 `discover_controls.form_clusters`(簇形成语义无漂移)。
- 每 stage 产物经产出者 `--check` 校验(`discover_controls`/`plan_scout`/`merge_scout`/`validate_inventory`/`validate_t1_records`/`assemble_rules`)。

### Resume / cache
- **`--resume` 首步** = `py .opencode/mgh-core/scripts/resume_state.py --target <target>` → 读 stdout `step`/`next_action`/`tiers` 继续(进度纯从磁盘 `<target>/.mgh-init/` 重派生;**NEVER** 靠对话记忆判步骤)。`--check` 可在起步校验磁盘状态自洽(退出码 2 = 不自洽)。
- **过期凭证 recipe**:起步 `resume_state.py --check` 若报「scout 启用 + scout 未完 + 下游 t2/t3/t4 `.done`」违例(退出码 2)= 下游 marker 是基于 regex-only 输入的**过期凭证** → 先 `py .opencode/mgh-core/scripts/resume_state.py --target <target> --invalidate-stale --dry-run` 预览,再 `--invalidate-stale` 清除,然后续跑——NEVER 手工 `del` 下游 marker、NEVER 静默跳过已过期 tier。
- **新 session 运行域 env 重注入**:`--resume` 走同一命令壳 step 0 → 重新 `export MGH_INIT_ACTIVE=1`;并在 fan-out 前从既有 `controls_candidates.json::repo` 重设 `MGH_TARGET`(产物在盘上、`describe_artifact.py --field repo`,无需重跑 discover)。**确定性脚本本身不读 env**(flag + 磁盘驱动),env 仅影响 hook 子树守卫强度。
- **launch-cwd 前置(跨 session 纪律)**:step 0 首调 `list_steps.py` 用相对 `.opencode/mgh-core/scripts/` 路径,解析于编排器 Bash cwd(命令壳加载处 = 目标项目根)。下游工具路径经其 stdout `script_abs` 已全钉死绝对,但**首调本身**依赖从目标项目根发起;从歧义 cwd 调用可使首调命中错 install 副本。新 session 续跑前确认 cwd。
- Work units: i1 per file, **scout per batch**, T1 per cluster, T2/T4 whole, T3 per category.
- `<target>/.mgh-init/checkpoints/<tier>/<unit>.json.done`(成功)**或** `.failed`(确认失败)= 终态,gate `--resume`(均跳过、不重派);`run_config.json` 使 `--resume` 免重输 flag。
- `--rebuild-cache` forces call-graph rebuild.

## Output (per `<target>/.mgh-init/`)

- `controls_candidates.json`(regex + scout,带 `source`)· `skeleton.json` · `scout_plan.json` · `scout_candidates.json` · `clusters.json` · `controls_inventory.json` (`design_controls`-compatible)
- `clusters.json` 包装结构 `{repo,clusters[],truncated}` 见 `core/contracts/init/clusters.md`(T1 经 `list_clusters.py` 枚举,禁手搓内省)
- `checkpoints/**` (resume) · `inputs/<tier>/<unit>.input.json`(per-unit 物化扇出输入,subagent 自读;≤ `--max-unit-bytes`;随 `.mgh-init/` gitignore;见 `core/contracts/init/unit-inputs.md`)· `init_manifest.json` · `report.md` (+「competing controls」section)
- rules → opencode:`<target>/AGENTS.md` 简洁**惰性索引块** `<!-- security-controls:begin --> … :end -->` + 每实现 category 一个详述文件 `<target>/docs/security-controls/<cat>.md`(由 `assemble_rules.py` 扫 `<rules-dir>/*.md` 建索引;详述文件按需加载);claude:`<target>/.claude/rules/security-*.md`

## Always disclose
- LLM-induced candidates — human review required.
- **Existence ≠ effectiveness** (CVE-2025-41248).
- Call-graph textual/AST — misses AOP/reflection/DI/framework-routing; surface `unresolved[]`.
- **Scout coverage is partial, not whole-repo**;scout 非确定(簇数 run-to-run 可能变化);残留盲区见 `report.md`。
- 面向人读的非代码内容(`report.md`、`init_manifest.json::boundaries[]` 文案、rules 正文)用**简体中文**;锚点/路径/frontmatter 保持原样。

> 其余边界细节(dotfiles/tests 默认跳过、宿主 shell 超时、codegraph 富化辅助、请求上下文预算、大仓 `--scope`/`--merge`)由脚本写入 `init_manifest.json::boundaries[]` + `report.md`(运行时落盘),摘要**复述**命中项即可,NEVER 遗漏**实际触发**的边界触发计数。

