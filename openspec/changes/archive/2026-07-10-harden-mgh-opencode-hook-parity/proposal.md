## Why

`add-mgh-telemetry-seam` 的调研已核实(2026-07,据 opencode 官方 plugins/tools 文档):**opencode 有 hook 机制**——JS/TS 插件(`.opencode/plugins/*.ts`)订阅 `tool.execute.before`(pre-tool,可阻断,等价 Claude Code `PreToolUse`)/ `tool.execute.after`(post-tool,等价 `PostToolUse`)。此前本仓**误判 opencode「无 hook 能力」**,导致运行时纪律守卫 `block-adhoc-scripts` 只在 Claude Code 注入,opencode 侧降级为「install warn+跳过 + 靠命令壳明线 + `--check` 兜底」。后果有二:① opencode 用户缺失与 claude 对等的运行时强制(微脚本内省 / 越权 `Write *.py` / 子树外写入在 opencode 端无人拦);② 多份引导文档(install.sh、3 份 opencode 命令壳、`control-discovery` spec)留下「opencode 无 PreToolUse 能力 / capability unsupported」的**错误前提**,会误导后续编程任务继续放弃 opencode hook 路径。本变更纠正前提并把守卫真正移植到 opencode,达成双端对等。

## What Changes

- **移植 `block-adhoc-scripts` 守卫到 opencode**:新增 `releases/opencode/plugins/block_adhoc_scripts.ts`——订阅 `tool.execute.before` 的**薄 shim**,把 opencode 事件输入**归一化**为 Claude Code PreToolUse 的 stdin 形态(`{tool_name, tool_input}`),管道喂给**既有、不改**的 `block_adhoc_scripts.py`(单一守卫逻辑、零漂移);shim 据脚本退出码 2 阻断该工具调用、否则放行。环境门控(`MGH_{INIT,SAST,SRA}_ACTIVE`)、正则、白名单、子树守卫**全部复用**,不重写。
- **install 双端对等注入**:`install.sh --opencode` 由「warn+跳过」改为经新增 `tools/install_opencode_plugin.py` **幂等落** `.ts` 插件进目标 `.opencode/plugins/`(合并不覆盖用户既有插件);注入失败仍 fail-soft(install 不阻断,CI 必 fail)。
- **删错误前提(全仓)**:install.sh 注释与消息、`openspec/specs/control-discovery/spec.md`(requirement + scenario 各 1 处)、3 份 opencode 命令壳(`mgh-{init,sra,sast}.md`)中「opencode 无 PreToolUse 能力 / capability unsupported」一律改为准确表述——opencode 等价 hook = `tool.execute.before` 插件形态;当前是**移植缺口**(本变更即补),非能力缺口。
- **README + AGENTS.md 收口**:AGENTS.md R5.7 补 opencode 插件形态与移植缺口说明,并对 `.ts` shim 做出 R2 定性(opencode 原生胶水,非 Python 运行时依赖;守卫逻辑仍单一来源在 Python 标准库脚本);README 目录布局补 opencode `plugins/`,安装/hook 描述改双端对等。
- **测试 + 版本**:新增 opencode 插件注入单测;守卫 `block_adhoc_scripts.py` 不改故其单测不动(shim 归一化层另测);bump 版本号(承 R5.8)。

## Capabilities

### New Capabilities
<!-- 无。运行时纪律 hook 已是既有能力(control-discovery 的 "Runtime enforcement hook" 要求;sast-orchestration-discipline 复用同一 hook)。本变更是把既有能力从 claude 单端扩展到 opencode 端对等,而非新增能力。 -->

### Modified Capabilities
- `control-discovery`: "Runtime enforcement hook for orchestrator script discipline" 要求从「claude 注入 PreToolUse;`--opencode` 无等价能力 → stderr warn 并跳过」改为「双端对等注入——claude = `.claude/settings.json` 的 PreToolUse 命令,opencode = `.opencode/plugins/` 的 `tool.execute.before` `.ts` 插件(调同一 Python 守卫);仅当 opencode 插件无法核验/注册时才 fail-soft」。

## Impact

- **代码**:新增 `releases/opencode/plugins/block_adhoc_scripts.ts` + `tools/install_opencode_plugin.py`;`install.sh` opencode 分支改注入插件;`block_adhoc_scripts.py` **不改**(shim 归一化复用)。
- **文档(删错误前提)**:`install.sh` 注释/消息 · `openspec/specs/control-discovery/spec.md` · `releases/opencode/command/mgh-{init,sra,sast}.md`;**收口**:`AGENTS.md`(R5.7)· `README.md`(目录布局 + 安装/hook 描述)· `CHANGELOG.md`。
- **测试/CI**:新增 `tests/test_install_opencode_plugin.py`;零依赖 AST 扫描只扫 `*.py`、纯净性 lint 只扫既定 `*.md` 目录——`.ts` 与新增插件路径均不在扫描集,R2/R5.10 自检不破。
- **依赖/R2**:`.ts` 插件是 opencode 原生胶水(由 opencode 自带 Bun 运行,非 `pip` 依赖);阻断判定逻辑仍单一来源在 Python 标准库 `block_adhoc_scripts.py`——「零运行时依赖」字面不变(承 `add-mgh-telemetry-seam` 已立的「`.ts` shim 调 Python」模式)。
- **风险(诚实)**:opencode `tool.execute.before` 的**阻断 API 语义**与**可靠性**(社区 issue #1706 报「before hook 不触发」)须在真实 opencode 上核验;核验不过则 opencode 端退为「装插件(best-effort)+ 明线/`--check` 兜底」(fail-soft 行为不变,但前提已纠正、不再误判为能力缺失)。
