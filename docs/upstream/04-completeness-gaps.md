# 完整性与缺口

> 路径规约:移植侧用相对 `m3g4horness` 根的路径;原项目侧 `vvaharness/...`
> (绝对位置 `C:/DEV/visa-vulnerability-agentic-harness/vvaharness/`)。

**结论先行:** `core/docs/prompt-provenance.md` 声称已迁移原项目 9 阶段 + 共享片段 +
镜头/基线提示词——**逐条核验,9 阶段 SYSTEM 提示词与 4 个共享片段、specialist-hints、
2 个 s2 基线全部已迁移且路径/保真度标注准确**。唯一**漏迁**的是
`s1_autoexclude.py::_SYSTEM`(AI 推导 step1 排除 overlay 的 triage 提示词),且重写版整体
没有 `--auto-step1` 能力。能力面:重写版是"纯 SAST 引擎",**砍掉**了原项目全部运维/企业
能力(doctor/setup/estimate 子命令、多 provider 后端、mTLS、CMDB、CVE feed、
design_controls、redaction、VSVS/Offensive-Priority 评分、restricted-unpickler、
guardrail 检测、`.env` 上行查找等);**新增**增量/作用域扫描与调用链展开。`--repo-file`
批处理、`--group-by-app`、checkpoints/`--resume`、`--application-id`、`run_manifest.json`
等**原项目也有**,非重写版独创。

### 原项目尚未实现/未迁移清单

| # | 原项目能力 | 原项目依据(file::symbol) | 重写版状态 | 核验方式 |
|---|---|---|---|---|
| 1 | **`s1_autoexclude._SYSTEM` 提示词未迁移** | `pipeline/stages/s1_autoexclude.py::_SYSTEM`(L42-56,build/scan triage agent,产出 step1 排除 overlay) | **未迁移** | `core/prompts/**` 仅 16 文件,无 autoexclude;provenance 表未列;`extract_prompts.py` 未抽取此常量 |
| 2 | **`--auto-step1` 能力**(AI 推导每仓库 step1 排除 overlay,写 `checkpoints/step1.yaml`) | `orchestrator/entry.py::--auto-step1`;`s1_autoexclude.py::run` | **缺失** | 全树 grep `auto-step1|autoexclude|step1 overlay` → 0 命中 |
| 3 | **`doctor` 子命令**(静态就绪检查 + 实时后端连通性探针) | `cli.py::_doctor` | **缺失**(命令面无;仅编排内 "self-check") | grep `doctor` 仅命中说明文字 |
| 4 | **`setup` 引导向导**(Python/git/agent/key/gateway/CA 检测、profile 推荐、`.env` 脚手架、`--install-agents`) | `cli.py::_setup`;`util/environment.py::run_checks/recommend_profile/detect_gateway/detect_ca_cert` | **缺失** | glob `*setup*` → 0 |
| 5 | **`estimate` 子命令**(文件/字节/≈token 预览,零花费) | `cli.py::_estimate` | **部分**(仅 `--estimate` 标志,无独立命令) | 命令文档列 `--estimate` 为标志 |
| 6 | **多 provider 后端体系**(cli/sdk/openai 三后端 + 路由 + 本地工具) | `backends/{claude_cli,sdk,oai}.py`;`backends/llm.py::resolve`;`backends/localtools.py` | **缺失**(改由宿主 agent 执行 LLM 阶段) | glob `*provider*`/`backends/` → 0 |
| 7 | **mTLS / 私有网关 / CA 证书** | `backends/_tls.py`;`cli.py::_setup` 网关分支;`util/environment.py::detect_ca_cert` | **缺失** | glob `*tls*`/`*mtls*` → 0 |
| 8 | **CMDB AppProfile 集成**(`--application-id` 驱动 AppProfile 查找,挂入 ctx) | `orchestrator/cmdb.py::_load_app_profile` | **缺失**(`--application-id` 仅写 SARIF property,无 CMDB 查表) | glob `*cmdb*` → 0 |
| 9 | **CVE feed 注入**(s2/s3 消费已知 CVE 做 variant hunting) | `injectors/cve_feed.py::load_cves`;`s3_decompose.py`(消费 `ctx.cves`) | **缺失** | glob `*cve*` → 0(仅 prompt 文本提及) |
| 10 | **design_controls 注入**(auth 边界/沙箱/缓解,影响 s2/s8 排序) | `injectors/design_controls.py::load_controls`;s2/s8 消费 | **缺失** | glob `*design*control*` → 0 |
| 11 | **VSVS / Offensive-Priority 评分**(基于 CVSS + AppInfo) | `orchestrator/enrich_findings.py::_enrich_findings`;`report/enrich.py::vsvs_score/offensive_priority_for` | **缺失**(仅 CVSS base + 官方 band) | grep `vsvs|offensive` → 0 |
| 12 | **redaction / PII 掩码**(落盘前掩码 secret;tool 结果掩码) | `report/redact.py::redact/redact_counts`;`backends/localtools.py::execute` | **缺失** | glob `*redact*` → 0 |
| 13 | **`run_manifest.json` 完整字段** | `manifest.py::capture/_models/_git_sha` | **部分**(命令文档承诺写,但无生成代码/字段完整性未确认) | 无对应 .py 实现 → **未确认** |
| 14 | **checkpoint 安全**(restricted-unpickler,白名单 vvaharness 类) | `orchestrator/checkpoints.py::_RestrictedUnpickler` | **差异**(重写版用 `.json` 文本而非 pickle,故无 unpickle 攻击面;但无等价完整性校验) | `checkpoints/` 用 JSON |
| 15 | **guardrail 检测与处理**(org 内容护栏拒绝 → `GuardrailBlocked`) | `backends/claude_cli.py::_check_guardrail` | **缺失** | grep `guardrail` → 0 |
| 16 | **preflight 实时探针**(每 (model,via) 发最小请求,429/5xx 退避,token-cap 假错识别) | `orchestrator/preflight.py::probe_backends/_probe_agentic_roles/_reachable_despite_token_cap/_safe_permission_mode` | **缺失**(仅 "self-check 确认 host agent 可用") | grep `preflight|probe_backend` → 0 |
| 17 | **`.env` 上行查找 + 攻击目标内 `.env` 拒绝** | `cli.py::_load_dotenv`;`orchestrator/config_paths.py::_path_within` | **缺失**(无 dotenv 加载;config 由宿主 agent 读 profile) | grep `dotenv|find_dotenv` → 0 |
| 18 | **prompt 缓存(cache_control)**(sdk 后端对 s4 重复 SYSTEM 块打 cache 标记) | `backends/sdk.py`(cache_control) | **结构性差异**(靠宿主 agent 自身缓存;s4 SYSTEM 字节稳定设计保留以利缓存) | 无 sdk 后端 |
| 19 | **`--step1-config` overlay**(显式 step1 排除 overlay YAML) | `orchestrator/entry.py::--step1-config` | **缺失**(作用域改由 `--diff/--path/--package` + 调用链引擎表达) | grep `step1-config` → 0 |
| 20 | **`--skip-preflight`** | `orchestrator/entry.py::--skip-preflight` | **不适用**(无 preflight) | — |

> `--repo`、`--repo-file`、`--workspace`、`--keep-clones`、`--group-by-app`、
> `--application-id`、`--config`、`--stop-after`、`--resume`、checkpoints 目录**原项目也有**
> (见 `orchestrator/entry.py` L41-60 + `batch.py` + `checkpoints.py`),不在"未迁移"清单内。

### 重写版相对原项目的差异

| 类别 | 项 | 重写版依据(file::symbol) | 原项目对照 | 判定 |
|---|---|---|---|---|
| **新增** | 增量扫描 `--diff <ref>`(git diff 变更文件作种子) | `core/scripts/diff_seed.py`;`commands/mgh-sast.md::--diff` | 原 `entry.py` argparse 无 `--diff`;无 diff 种子 | **重写版独创** |
| **新增** | 目录/包作用域 `--path <dir>` / `--package <pkg>` | `expand_scope.py`(path/package 种子);命令文档 | 原仅 step1 的 exclude_dirs/exts/globs,无 path/package 种子标志 | **重写版独创** |
| **新增** | **调用链展开引擎**(零依赖文本调用图 + 双向 BFS + Spring/Feign/AOP/DI/JPA framework 提示 + 多语言正则) | `expand_scope.py::build_call_graph/bfs_expand/FRAMEWORK_RX`;skill `sast-call-chain` | 原项目调用图仅 s1 的 source_ref/sink_ref 文本关联,无 BFS、无 framework 提示、无 tree-sitter | **重写版独创** |
| **新增** | `sast-scope-resolver` agent + `scope_manifest.json`(in_scope/framework_hinted/unresolved) | `releases/claude-code/agents/sast-scope-resolver.md` | 无对应 | **重写版独创** |
| **新增** | `--scope-depth` / `--scope-direction`(调用链深度与方向可调) | 命令文档 | 无 | **重写版独创** |
| **新增** | `--models role=id`(单角色模型覆盖) | 命令文档 | 原靠 `--config` 切 profile 实现,无单标志覆盖 | **重写版新增交互**(原通过 profile 等价可达) |
| **等价/两版都有** | `--repo-file` 批处理 + `--group-by-app` + `--keep-clones` + `--workspace` | 命令文档 | `entry.py` L43-60;`batch.py::run_batch/_run_batch_grouped` | **两版都有**(重写版 batch clone 由宿主 agent Bash 执行) |
| **等价/两版都有** | checkpoints + `--resume` + `--stop-after` | 命令文档 | `checkpoints.py`;`entry.py::--resume/--stop-after` | **两版都有**(重写版用 JSON,原版用受限 pickle) |
| **等价/两版都有** | `--application-id` → SARIF `run.properties.applicationId` | `emit_sarif.py`;命令文档 | `entry.py::--application-id` | **两版都有**(原版还驱动 CMDB/VSVS,重写版仅写 property) |
| **等价/两版都有** | s6 多数投票 FP 抑制 | `sast-verify.md`;profiles `majority_vote: true` | `s6_verify.py` + sdk/openai temperature | **两版都有**(原版仅 sdk/openai 后端,cli 单遍) |
| **等价/两版都有** | s5 确定性 prefilter / s7 确定性 dedup / s9 SARIF+CVSS+CWE | `core/scripts/{prefilter,dedup,emit_sarif}.py`;`tests/test_deterministic.py` | `s5_prefilter.py`/`s7_dedup.py`/`report/{cvss,cwe}.py` | **两版都有**(重写版 stdlib 单文件化) |
| **结构差异** | s7 dedup:重写版**纯确定性**(行邻近 + 标题 Jaccard),原版含 **LLM 语义去重** | `core/scripts/dedup.py`(无 LLM) | `s7_dedup.py::SYSTEM`(LLM) | **差异**:重写版 s7 SYSTEM 提示词已迁移但**未被使用** |
| **结构差异** | LLM 阶段执行方:重写版=宿主 agent 子代理;原版=自带后端 | `releases/claude-code/agents/*` | `backends/*` | **核心架构差异**(零运行时依赖的代价) |
| **结构差异** | 配置体系:重写版仅 role→model 的 `core/profiles/*.yaml`,无 `via:` | `core/profiles/{default,cli,full}.yaml` | `config/profiles/*.yaml`(via、temperature、thinking_budget、betas、mTLS) | 重写版 profile **大幅精简** |
| **保真(已核验)** | s1-s8 全部 SYSTEM + 4 片段 + specialist-hints + 2 基线 | `core/prompts/**`(16 文件) | 对应 `vvaharness/pipeline/stages/*::SYSTEM` 等 | **逐条核验迁移到位**(`LANG_HINTS` 42 语言按设计动态消费未扁平化) |

### 关键修正(避免误判)
- `--repo-file` 批处理、`--group-by-app`、checkpoints/`--resume`、`--stop-after`、
  `--application-id`、`run_manifest.json` 均为**原项目已有**,非重写版新增。
- s7 dedup 与 s6 verify 的 SYSTEM 提示词虽已迁移,但 s7 在重写版中**实际走纯确定性脚本**
  (原版为 LLM 语义去重)——**提示词迁移 ≠ 行为等价**。
- 唯一**漏迁提示词**:`s1_autoexclude.py::_SYSTEM`(配套能力 `--auto-step1` 整体缺失)。
- **未确认项**:`run_manifest.json` 在重写版命令文档中承诺产出,但仓库内未见生成代码,
  字段完整性**未确认**。
