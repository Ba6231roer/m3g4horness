# 阶段与提示词映射 (s1–s9)

> 路径规约:**移植侧**(m3g4h⊿rness / `/mgh-sast`)用相对仓库根的路径
> (`core/...`、`releases/...`);**原项目侧**用 `vvaharness/...`
> (绝对位置:`C:/DEV/visa-vulnerability-agentic-harness/vvaharness/`)。

**结论先行。** mgh-sast 把 9 个 LLM 阶段的 **SYSTEM 提示词** 逐字搬运(经核验
`core/docs/prompt-provenance.md` 的保真度标注全部准确),并通过宿主 agent 的
subagent + Bash 脚本复现执行模型。**提示词层 100% 保真**;**程序化前后处理层有取舍**
——s5/s7/s9 的确定性逻辑有 1:1 脚本承接,但 **s1 的配置去重 (config-dedup) 与全仓库
调用图补充 (repo-wide call-graph supplement) 在重写版中没有对应实现**(调用图能力被
移到了 `core/scripts/expand_scope.py`,仅服务于增量/作用域扫描,全量 s1 本身不再回填
调用图)。

---

### s1 — Survey / 攻击面测绘
- **用途**:agentically 探索仓库,输出 `ContextPackage`(语言/模块/入口点/unsafe sinks/调用图)。
- **主源文件**:`vvaharness/pipeline/stages/s1_preprocess.py`
- **SYSTEM 提示词**:`s1_preprocess.py::SYSTEM`(L682-708,静态字符串)
- **重写版提示词**:`core/prompts/stages/s1-survey.md` — verbatim
- **执行组件**:subagent `releases/claude-code/agents/sast-survey.md` + skill `sast-attack-surface`
- **输入输出契约**:USER prompt(CVE 块 + 跳过目录提示)→ JSON `ContextPackage`

| 上游程序化逻辑 | 上游位置 | 重写版承接 | 差异 |
|---|---|---|---|
| 文件清单确定式遍历 + 排除规则 | `_walk_repo` / `_exclusion_sets` / `glob_hit` (L81-199) | 仅靠 subagent 自然语言遵守;无确定式 ground-truth 清单强制 | **遗漏**:上游"Option A"确定式剥离 agent 误报路径的安全网不存在 |
| 配置文件结构去重 | `_dedup_configs` / `_shape_hash` (L210-459) | **无对应实现** | **遗漏**:数千份 near-dup config 不再折叠,下游 token/chunk 膨胀 |
| 调用图验证 + 补充 | `_supplement_call_graph` (L461-679) | 调用图引擎移至 `core/scripts/expand_scope.py`,但**仅服务于 `--diff/--path/--package`** | **部分遗漏**:全量 s1 不回填/验证调用图,影响 s3/s4 精度 |
| 自动派生 step1 排除 overlay | `s1_autoexclude.py`(独立文件,单次 LLM 调用) | **无对应实现** | **遗漏**:每目标仓库噪声目录自动识别未迁移 |

### s2 — Threat Model / 威胁建模
- **用途**:基于 s1 ContextPackage 的实际攻击面,产出应用级威胁模型(assets / trust boundaries / STRIDE)。
- **主源文件**:`vvaharness/pipeline/stages/s2_threatmodel.py`;SYSTEM `::SYSTEM`(L325-377)
- **重写版提示词**:`core/prompts/stages/s2-threat-model.md` + `core/prompts/baselines/s2-{baselines,stride-by-kind}.md`(dict rendered,verbatim)
- **执行组件**:subagent `sast-threat-model.md` + skill `sast-threat-model`
- **差异**:上游 `_gather_evidence`(L213-318)的确定式 budget 截断,重写版由 subagent 自行 Glob/Read 完成。

### s3 — Decompose / 分块策略
- **用途**:strategist 收到 ContextPackage(无源码),产出风险排序的 `TaskManifest`(分块 + 每块研究 lens + 假设)。
- **主源文件**:`vvaharness/pipeline/stages/s3_decompose.py`;SYSTEM `::SYSTEM`(L31-67)
- **重写版提示词**:`core/prompts/stages/s3-decompose.md` — verbatim
- **执行组件**:subagent `sast-decompose.md` + skill `sast-decompose`

| 上游程序化逻辑 | 上游位置 | 重写版承接 | 差异 |
|---|---|---|---|
| catch-all 扫描未分块文件 | `_add_catchall_chunks` (L638-672) | subagent 承接(skill 指示) | 语义保真,无确定式 `_catchall_eligible` 过滤 |
| Taint chunk(入口→sink 路径) | `_add_taint_chunks` / `_bfs_to_sinks` (L306-493) | 依赖 s1 调用图;重写版调用图更稀疏 | taint 覆盖退化 |
| Specialist passes + 门控 | `_add_specialist_chunks` / `_gate_specialists` (L675-814) | skills `sast-lens-{crypto,logic,access-control,batch-iac}` + `lenses/specialist-hints.md` | 默认激活集 `crypto, logic-bug, access-control, batch-etl, iac` 与上游一致 |
| 路径归一化 / 丢弃幻觉路径 | `_normalize_chunk_files` (L142-165) | subagent 自行校验 | 弱化:无 basename 回退 |

### s4 — Deep-Dive / 深度分析
- **用途**:对每个 chunk 深度分析,N 次独立运行 + 多数投票(投票默认禁用)。
- **主源文件**:`vvaharness/pipeline/stages/s4_deepdive.py`;SYSTEM `::SYSTEM`(L113-125)= `"\n\n".join([intro×2, _QUALITY_BAR, EXCLUSION_RULES, SELF_VERIFICATION, SEVERITY_GUIDANCE, EXHAUSTIVENESS, _OUTPUT_SCHEMA])` — **byte-stable 组合**
- **重写版提示词**:`core/prompts/stages/s4-system.md`(composition)+ `s4-{quality-bar,output-schema}.md` + `core/prompts/fragments/{exclusion-rules,self-verification,severity-guidance,exhaustiveness}.md`
- **执行组件**:subagent `sast-deepdive.md`(per-chunk fan-out)+ `lenses/specialist-hints.md` ← `lang/hints.py::SPECIALIST_HINTS`
- **关键设计保真**(provenance "Must-replicate #1"):SYSTEM byte-stable,per-chunk 语言/specialist lens 在 **USER** prompt → prompt-cache hit。`lang/hints.py::LANG_HINTS`(42 语言)运行时按 chunk 动态拼入,**未**扁平化为静态文件。
- **差异**:上游 `_redact_source`(L541-562)、sliding window(`WINDOW_LINES=600`)+ `_neighbor_context`(L578-638)、`_effective_runs` 多数投票(默认禁用)在重写版由 subagent 自主/按 profile 处理。

### s5 — Pre-Filter / 确定性预过滤
- **用途**:纯 Python(无 LLM),机械剔除明显误报。
- **主源文件**:`vvaharness/pipeline/stages/s5_prefilter.py`(`run` L96-170);**无 SYSTEM**
- **重写版**:`core/scripts/prefilter.py`(stdlib)+ skill `sast-prefilter`
- **承接差异**:重写版聚焦证据门控(缺 ref / 低置信 / noise regex);**遗漏** `_is_secret_class`(L70-76,test 路径硬编码密钥保留例外)与 pre-verify 语义去重(`pre_verify_threshold`,L137-158)。

### s6 — Verify / 对抗式验证
- **用途**:对每个幸存 finding 启动全新会话**尝试证伪**,输出 TRUE/FALSE_POSITIVE + CVSS 3.1。
- **主源文件**:`vvaharness/pipeline/stages/s6_verify.py`;SYSTEM `::SYSTEM`(L57-108,**f-string**,插值 `{EXCLUSION_RULES}`)
- **重写版提示词**:`core/prompts/stages/s6-verify.md` — verbatim (f-string),保留 `{EXCLUSION_RULES}` 占位符
- **执行组件**:subagent `sast-verify.md` + skill `sast-adversarial-verify`
- **差异**:`_parse_verdict`(L310-335)解析逻辑移入 skill;CVSS 评分在 s9 统一计算;多 pass 投票按 profile(`majority_vote`)。

### s7 — Dedup / 去重
- **用途**:s6 后折叠描述同一漏洞的 verified findings。
- **主源文件**:`vvaharness/pipeline/stages/s7_dedup.py`;SYSTEM `::SYSTEM`(L111-143)
- **重写版提示词**:`core/prompts/stages/s7-dedup.md` — verbatim(**但见下,未被使用**)
- **执行组件**:`core/scripts/dedup.py` + skill `sast-dedup`
- **重要差异**:上游两阶段——7a 确定性 `_collapse_trivial`(L149-174)+ 7b 语义 `_semantic_dedup`(L266-299,单次 LLM)。**重写版 `dedup.py` 是纯确定性**(file+CWE+line-bucket 聚类 + 标题 Jaccard),**无 LLM 语义去重**;`s7-dedup.md` 提示词虽被提取,但**无 subagent 执行它**(编排表 s7 行只有 `dedup.py` 脚本)。

### s8 — Chain / 利用链构造
- **用途**:看到全部 findings,识别多步利用链、按真实可利用性 + design controls 重排严重度。
- **主源文件**:`vvaharness/pipeline/stages/s8_chain.py`;SYSTEM `::SYSTEM`(L34-79,**f-string**,插值 `{SEVERITY_GUIDANCE}`)
- **重写版提示词**:`core/prompts/stages/s8-chain.md` — verbatim (f-string)
- **执行组件**:subagent `sast-chain.md` + skill `sast-exploit-chain`
- **差异**:`_hydrate_report`(L227-345)/`_final_severity`(L408-419)/`_unranked_report`(L187-224)由 subagent + s9 承接;provenance "Must-replicate #3" CVSS 带权威在 `emit_sarif.py` 落实。**遗漏**:VulContextSeverity(`vsvs_rating`,L417,需 app/CMDB profile)无输入源。

### s9 — SARIF / 报告生成
- **用途**:确定性 SARIF 2.1.0 输出(CVSS 3.1 + CWE)。
- **上游**:SARIF 输出不在 `pipeline/stages/`(9 阶段文件止于 s8);重写版将 SARIF 显式化为 s9。
- **重写版**:`core/scripts/emit_sarif.py`(CVSS base + 官方 severity 带 + CWE 映射)+ skill `sast-sarif`;报告组装:subagent `sast-triage.md` + skill `sast-finding-review`。

---

### 9 阶段映射汇总表

| 阶段 | 用途 | 上游主源::SYSTEM | 重写版提示词 | 保真度 | 执行组件 | 程序化逻辑承接 |
|---|---|---|---|---|---|---|
| **s1** survey | 攻击面测绘 | `s1_preprocess.py::SYSTEM` | `stages/s1-survey.md` | verbatim | `sast-survey` + `sast-attack-surface` | **部分遗漏**:config-dedup / repo-wide 调用图补充 / 确定式清单 / s1_autoexclude 未迁移 |
| **s2** threat-model | 威胁模型 | `s2_threatmodel.py::SYSTEM` | `stages/s2-threat-model.md` + 2 baselines | verbatim | `sast-threat-model` | 证据组装由 subagent 完成,无确定式 budget 截断 |
| **s3** decompose | 分块策略 | `s3_decompose.py::SYSTEM` | `stages/s3-decompose.md` | verbatim | `sast-decompose` | taint chunk 依赖 s1 调用图(更稀疏);specialist 默认集保真 |
| **s4** deep-dive | 深度分析 | `s4_deepdive.py::SYSTEM`(组合) | `stages/s4-system.md` + `s4-{quality-bar,output-schema}.md` + `fragments/*` | verbatim (composition) | `sast-deepdive`(per-chunk) + `lenses/specialist-hints.md` | SYSTEM byte-stable 保真;脱敏/sliding-window/邻居上下文由 subagent 自主 |
| **s5** prefilter | 确定性预过滤 | —(无 SYSTEM) | —(脚本) | N/A | `prefilter.py` + `sast-prefilter` | **遗漏**:secret-class test 路径例外、pre-verify 语义去重 |
| **s6** verify | 对抗验证 | `s6_verify.py::SYSTEM`(f-string) | `stages/s6-verify.md` | verbatim (f-string) | `sast-verify` + `sast-adversarial-verify` | 解析逻辑入 skill;多 pass 投票支持 |
| **s7** dedup | 去重 | `s7_dedup.py::SYSTEM` | `stages/s7-dedup.md` | verbatim | `dedup.py` + `sast-dedup` | **重要差异**:重写版纯确定式,无 LLM 语义去重;提示词文件已提取但无 subagent 执行 |
| **s8** chain | 利用链 | `s8_chain.py::SYSTEM`(f-string) | `stages/s8-chain.md` | verbatim (f-string) | `sast-chain` + `sast-exploit-chain` | CVSS 带权威;**遗漏** VSVS 无 app_profile 输入源 |
| **s9** SARIF | SARIF 2.1.0 | —(上游不在 stages/) | —(脚本) | N/A | `emit_sarif.py` + `sast-sarif`;报告 `sast-triage` + `sast-finding-review` | 显式化为独立阶段 |

---

### 需关注的三处程序化逻辑缺口(非提示词层)
1. **s1 配置去重缺失** — `_dedup_configs`(L210-459,shape-hash 聚类 + secret/insecure 安全网)无对应,大仓 near-dup config 直冲下游,token 与 chunk 数膨胀。
2. **s1 调用图引擎作用域收窄** — `_supplement_call_graph` 能力搬到 `expand_scope.py`,仅 `--diff/--path/--package` 触发;全量 s1 不回填调用图,s3 taint chunk / s4 邻居上下文质量下降。
3. **s7 语义去重降级为纯确定式** — 上游 7b LLM 语义 pass 被标题 Jaccard 近似替代;`s7-dedup.md` 提示词提取但无执行 subagent。

> 上游 `s1_autoexclude.py`(独立预处理模块)整模块未迁移(含其 `_SYSTEM` 提示词——
> 详见 `04-completeness-gaps.md`)。
