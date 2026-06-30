# 上游引用索引 — mgh-sast ↔ vvaharness

> **用途**:这是 mgh-sast 与原项目 **vvaharness**(Visa / Project Glasswing,
> Apache-2.0)之间的**功能实现与提示词对应关系总索引**。设计目的:原项目更新时,
> 能**高效、低风险地把上游变更同步到 mgh-sast**,避免无谓改写。
>
> **AGENTS.md 规定:本文件及 `docs/upstream/` 下的分文档「非必要不改」**——它们记录的是
> 与原项目的逐项对应关系,改动会破坏同步锚点。新增功能不在此列。

## 一句话定位

mgh-sast 是 vvaharness 9 阶段 LLM SAST 流水线的**零运行时依赖重写**:LLM 阶段改由宿主
agent(Claude Code / opencode)的 subagent 执行,确定性阶段改由 Python ≥3.10 标准库脚本
执行;**提示词逐字移植,程序化前后处理有取舍,运维/企业能力整体砍掉**。

## 路径规约

| 侧 | 写法 | 绝对位置 |
|---|---|---|
| 移植侧(mgh-sast) | 相对仓库根:`core/...`、`releases/...`、`tools/...` | `C:/DEV/m3g4horness/` |
| 原项目侧(vvaharness) | `vvaharness/...` | `C:/DEV/visa-vulnerability-agentic-harness/vvaharness/` |

> 上游同步工具 `tools/extract_prompts.py` 默认 `--vvaharness` 即指向上表原项目绝对位置。

## 分文档索引(逐功能详析)

| 文档 | 范围 | 关键结论 |
|---|---|---|
| [`upstream/01-stages-prompts.md`](upstream/01-stages-prompts.md) | 9 阶段(s1–s9)与提示词 | **提示词层 100% 保真**;s1 config-dedup / repo-wide 调用图补充 / s1_autoexclude 未迁移;s7 语义去重降级为纯确定式 |
| [`upstream/02-deterministic-engine-callchain.md`](upstream/02-deterministic-engine-callchain.md) | 确定性脚本 + 调用链引擎 | `dedup/prefilter/emit_sarif` 是有取舍的移植;`expand_scope/diff_seed` 是**全新**(上游无);**tree-sitter 未接入**;CVSS 计算可无脑 pull,SARIF 结构不要直接同步 |
| [`upstream/03-infrastructure-not-reimplemented.md`](upstream/03-infrastructure-not-reimplemented.md) | backends/config/models/manifest/injectors/report/cli/agentdoc | 控制面整体由宿主承接;数据面(CVSS/CWE)下沉 `emit_sarif.py`;**真缺口**:redact / enrich(CMDB,VSVS)/ injectors / setup-doctor |
| [`upstream/04-completeness-gaps.md`](upstream/04-completeness-gaps.md) | 完整性核对 + 未实现清单 + 差异表 | 唯一漏迁提示词 `s1_autoexclude._SYSTEM`;`--repo-file`/batch/checkpoints 等**原项目也有**非独创;新增的是 `--diff/--path/--package`+调用链 |

## 提示词保真度速查(对照 `core/docs/prompt-provenance.md`)

| 重写版提示词 | 上游来源 | 保真度 |
|---|---|---|
| `core/prompts/stages/s1-survey.md` | `s1_preprocess.py::SYSTEM` | verbatim |
| `core/prompts/stages/s2-threat-model.md` + `baselines/s2-{baselines,stride-by-kind}.md` | `s2_threatmodel.py::SYSTEM`/`_BASELINES`/`_STRIDE_BY_KIND` | verbatim |
| `core/prompts/stages/s3-decompose.md` | `s3_decompose.py::SYSTEM` | verbatim |
| `core/prompts/stages/s4-system.md` + `s4-{quality-bar,output-schema}.md` + `fragments/*` | `s4_deepdive.py::SYSTEM`(组合) + `util/prompts.py` 片段 | verbatim (composition) |
| `core/prompts/stages/s6-verify.md` | `s6_verify.py::SYSTEM`(f-string) | verbatim (f-string) |
| `core/prompts/stages/s7-dedup.md` | `s7_dedup.py::SYSTEM` | verbatim(**已提取但未被使用**——s7 走纯脚本) |
| `core/prompts/stages/s8-chain.md` | `s8_chain.py::SYSTEM`(f-string) | verbatim (f-string) |
| `core/prompts/lenses/specialist-hints.md` | `lang/hints.py::SPECIALIST_HINTS` | verbatim (dict rendered) |

> `lang/hints.py::LANG_HINTS`(42 语言)按设计**运行时动态**拼入 s4 USER prompt,未扁平化。

## 原项目未实现/未迁移清单(汇总)

> 完整带核验依据的表见 [`upstream/04-completeness-gaps.md`](upstream/04-completeness-gaps.md)。
> 按优先级:

1. **`s1_autoexclude._SYSTEM` 提示词 + `--auto-step1` 能力** — 唯一漏迁的提示词(整模块未迁移)。
2. **`report/redact.py`** — 卡号/SSN/凭据脱敏(合规风险最高)。
3. **`report/enrich.py` + `injectors/{cve_feed,design_controls}.py`** — CMDB/VSVS/Offensive-Priority 评分 + CVE/控制注入链路。
4. **`cli.py::setup/doctor`** — 就绪检查 / 网关探测 / `.env` 脚手架(企业内网 Claude Code 网关场景缺引导)。
5. **多 provider 后端 + mTLS** — `backends/{sdk,oai,claude_cli,_tls}.py`(改由宿主承接,mTLS/网关/OpenAI 端点可配置性丢失)。
6. **`config/profiles` 的 step1–8 调参旋钮** — 影响 s3 分块 / s4 投票 / s5 阈值等效果项。
7. **guardrail 检测、preflight 实时探针、`.env` 上行查找** — 运维侧能力(重写版仅一句 self-check)。
8. **`run_manifest.json` 完整字段** — 命令文档承诺但无生成代码,字段完整性未确认。

## 上游同步操作指引

```bash
# 1) 重抽提示词(默认 --vvaharness 指向原项目位置)
py tools/extract_prompts.py --out ./core/prompts

# 2) 重新生成 lens skills / opencode agents(从 claude-code shell 派生)
py tools/gen_lens_skills.py
py tools/gen_opencode_agents.py

# 3) 跑零依赖自检 + 确定性单测
grep -rnE "^[[:space:]]*(import[[:space:]]+vvaharness|from[[:space:]]+vvaharness[[:space:]]+import)" --include=*.py .   # 应无输出
py tests/test_deterministic.py
```

**同步取舍备忘**(详见分文档 02):
- 可直接 pull:CVSS 系数表 / roundup / rating 公式(`report/cvss.py` → `emit_sarif.cvss_base`)。
- 不要直接同步:`generate_sarif` 结构(上游耦合 CMDB/VSVS/redact,重写版刻意砍掉)。
- 上游无、无需反向同步:`expand_scope` / `diff_seed` 全套增量逻辑。
- tree-sitter 接入点:`expand_scope.build_call_graph` 的 `DEF_CALL` 表替换处(非上游 `s1_preprocess`)。
- 建议修:`emit_sarif.CWE_NAMES` 的 `CWE-79` 重复键 bug;可从 `cwe.py::CWE_NAMES` 取全量 65 条替换。
