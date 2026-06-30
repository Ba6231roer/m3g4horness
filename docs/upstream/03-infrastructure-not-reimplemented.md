# 基础设施:未重写 / 由宿主承接 / 缺口

> 路径规约:移植侧用相对 `m3g4horness` 根的路径;原项目侧 `vvaharness/...`
> (绝对位置 `C:/DEV/visa-vulnerability-agentic-harness/vvaharness/`)。

**结论先行:** mgh-sast 把 vvaharness 的**运行时控制面**(LLM provider 适配、agentic
tool-loop、配置加载/校验、CLI 入口与 setup/doctor 就绪性检查)**整体删除**,改由宿主
agent(Claude Code / opencode)在 `/mgh-sast` 命令文档驱动下承担;**数据面**(CVSS 3.1
计算、CWE 名表)被原样下沉到 `core/scripts/emit_sarif.py`;而**企业注入件**(CVE feed、
design controls、CMDB 评分)与**报告脱敏**是**真空白**,未移植。

### 逐项分析

**1. `vvaharness/backends/` — LLM provider 适配** → (A) 宿主承接
原 `backends/llm.py::resolve/prompt/agentic` 做 dispatcher,按 `via: cli|sdk|openai`
路由到三套后端:`claude_cli.py`(子进程)、`sdk.py`(Anthropic SDK + streaming +
prompt-cache + mTLS via `_tls.py`)、`oai.py`(OpenAI Chat);`localtools.py` 提供
sdk/openai 自带 sandboxed Read/Glob/Grep tool-loop。重写版**完全删除**这一层——LLM
调用、tool-loop、认证、网关/mTLS 全部由宿主 agent 提供。`core/profiles/*.yaml` 只声明
`allowed_tools`(Read/Glob/Grep[/Bash])和 `roles.<role>.model: inherit|<id>`,不再有
`via/sdk/openai` 节。**代价:失去 mTLS / 企业网关 / OPENAI 兼容端点的可配置性。**

**2. `vvaharness/config/__init__.py` + `config/profiles/`** → (A)+(B 混合)
原 `config/__init__.py::Config/load` 是 YAML 加载器(`${ENV:-default}` 展开、
`config.local.yaml` overlay、`_STEP_DEFAULTS` 标量回填、`apply_step1_overlay` 追加合并)。
重写版**无 Python 加载器**(全仓 `*.py` 无 `import yaml`):profile 由宿主 agent 在编排
步骤 1 直接读 `core/profiles/<profile>.yaml`。三份 profile 语义镜像原版但**大幅瘦身**——
只剩 `roles/allowed_tools/budget/majority_vote`,删掉所有 `step1..step8` 调参旋钮、
`config_dedup`、`exclude_dirs/exts/globs`、`inject.*`、`batch.*`。**这些调参能力未移植。**

**3. `vvaharness/models.py` — Pydantic 数据契约(24 个模型)** → (B) 用更简方式替代
原版用 pydantic `BaseModel` 强类型化跨步骤数据并带 `field_validator` 做 LLM 输出强转。
重写版为保"零依赖"弃用 pydantic,改为**JSON 契约文档** `core/contracts/README.md`
(s1–s9 各阶段 JSON 形状 + canonical `Finding` 示例)+ 各 stage prompt 内嵌 output-schema。
无运行时校验——由确定性脚本按字段读取时容错。`CVE`/`Control`/`AppProfile` 三个注入件
模型随 injectors 一起消失。

**4. `vvaharness/manifest.py` — run_manifest.json** → (A) 宿主承接(弱化)
原 `manifest.py::capture` 是 contextmanager,写 tool version / 各 role model /
config sha256 / git SHA / timing。重写版**无 Python 实现**:命令文档仅**指示编排 agent
在收尾时写出** `run_manifest.json`。是否真的写、字段是否齐全,取决于宿主 agent 执行——
**非确定性保证**。

**5. `vvaharness/injectors/` — CVE feed / design controls** → (C) 真空白
`cve_feed.py::load_cves` 和 `design_controls.py::load_controls` 读
`inputs/known_cves.json` / `inputs/design_controls.yaml`,注入已知 CVE 与缓解控制。
全仓搜索重写版**零命中**。功能未移植,明确缺口。

**6. `vvaharness/report/`** → 拆分
- `report/cvss.py`(`score/rating`,FIRST §7)和 `report/cwe.py`(`CWE_NAMES` 字典)→ (B)
  **原样并入** `core/scripts/emit_sarif.py`(`AV/AC/PR_U/PR_C/UI/CIA` 表 + `roundup` +
  `cvss_base` + `severity_band`,逐行对应)。
- `report/enrich.py`(42KB;CMDB lookup、VulContextSeverity 环境评分、OffensivePriority)→ (C)
  **真空白**(零命中 `cmdb|VulContextSeverity|OffensivePriority`)。
- `report/redact.py`(Luhn 卡号 / SSN / 凭据脱敏,在写报告边界施加)→ (C) **真空白**。

**7. `vvaharness/cli.py` — setup/doctor/estimate/scan** → 拆分
- `scan` → (A) 宿主承接:由 `/mgh-sast` 命令文档编排,无 Python orchestrator。
- `estimate`(`_estimate`,按文件大小估 token)→ (A) `--estimate` flag,指示 agent 跑
  scope + count,**不花 token**;无独立可执行实现。
- `setup`/`doctor`(`_setup`/`_doctor`,调 `util/environment.run_checks` +
  `probe_backends` + 网关/CA 自动发现 + `.env` scaffold + `--install-agents`)→ (C)
  **真空白**:无就绪性检查、无网关探测、无 .env 脚手架、无 agent 指令安装;`install.sh`
  只做"零依赖校验 + 复制文件"。命令文档仅有第 3 步一句 "self-check host agent/model"。
- `_load_dotenv` / `_check_python` → (A) 由宿主 agent 环境承接。

**8. `vvaharness/agentdoc.py` — 打包的 agent 操作手册** → (C) 真空白
`AGENT_DOC`/`CLAUDE_SKILL`/`gemini_doc` 无对应物。安装时不再向
`AGENTS.md/CLAUDE.md/.github/copilot-instructions.md/GEMINI.md` 与 `~/.claude/skills/`
投递操作手册——操作约束改由 `commands/mgh-sast.md` 自身的 frontmatter + 正文承载。

### 汇总表

| 原项目 | 作用 | 重写版归属 | 替代/缺口位置 |
|---|---|---|---|
| `backends/llm.py` | LLM 后端 dispatcher | (A) 宿主承接 | 删除;宿主 agent 直接调 LLM |
| `backends/claude_cli.py` | `claude` CLI 子进程后端 | (A) 宿主承接 | 删除 |
| `backends/sdk.py`+`_tls.py` | Anthropic SDK + mTLS + 网关 | (A/C) 宿主承接,**mTLS/网关配置缺口** | 删除;仅靠宿主原生认证 |
| `backends/oai.py` | OpenAI 兼容后端 | (A/C) 宿主承接,**OpenAI 端点缺口** | 删除 |
| `backends/localtools.py` | sandboxed Read/Glob/Grep loop | (A) 宿主承接 | 删除;宿主原生工具 |
| `config/__init__.py` | YAML 加载/overlay/默认值 | (A) 宿主读 profile;**加载器删除** | `commands/mgh-sast.md`;无 py 加载器 |
| `config/profiles/*.yaml` | 全量调参 + backend 选择 | (B) 瘦身镜像 | `core/profiles/{default,cli,full}.yaml`;**step1–8 旋钮未移植** |
| `models.py`(24 模型) | pydantic 跨步契约 | (B) JSON 契约文档替代 | `core/contracts/README.md`;无运行时校验 |
| `manifest.py` | run_manifest.json | (A) 宿主按指示写(弱保证) | `commands/mgh-sast.md`;无 py 实现 |
| `injectors/cve_feed.py` | 注入已知 CVE | **(C) 缺口** | 未移植 |
| `injectors/design_controls.py` | 注入缓解控制 | **(C) 缺口** | 未移植 |
| `report/cvss.py` | CVSS 3.1 base 计算 | (B) 原样并入 | `core/scripts/emit_sarif.py::cvss_base/roundup` |
| `report/cwe.py` | CWE id→名 | (B) 原样并入(小子集 + 重复键 bug) | `core/scripts/emit_sarif.py::CWE_NAMES` |
| `report/enrich.py` | CMDB/VulContextSeverity/OffensivePriority | **(C) 缺口** | 未移植 |
| `report/redact.py` | 卡号/SSN/凭据脱敏 | **(C) 缺口** | 未移植 |
| `cli.py::scan` | 扫描入口 | (A) 宿主承接 | `commands/mgh-sast.md` |
| `cli.py::estimate` | 范围/成本预估 | (A) `--estimate` flag | `commands/mgh-sast.md`;无独立实现 |
| `cli.py::setup/doctor` | 就绪检查/网关探测/.env | **(C) 缺口** | 仅 `commands` 一句 self-check |
| `cli.py::_install_agents` | 投递 agent 操作手册 | **(C) 缺口** | `install.sh` 仅复制文件 |
| `agentdoc.py` | 打包操作手册/skill | **(C) 缺口** | 由命令 frontmatter 替代 |

### 真缺口清单(优先级排序)
1. `report/redact.py`(合规风险最高)
2. `report/enrich.py` + `injectors/*`(企业 CMDB/CVE/控制评分链路)
3. `cli.py::setup/doctor`(企业网关/mTLS/`.env` 就绪性,重写版对企业内网 Claude Code 网关场景缺引导)
4. `config/profiles` 的 step1–8 调参旋钮(影响 s3 分块/s4 投票/s5 阈值等效果项)
