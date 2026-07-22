## Why

`/mgh-init --format opencode` 把**全部**安全规则合并进目标项目根 `AGENTS.md` 的单个受管块
(`<!-- security-controls:begin --> … :end -->`)。opencode 启动时**整份** `AGENTS.md` 进根上下文
(文档明示 "included in the LLM's context")——大项目下这块几乎全是安全内容,直接撑爆 AI 编码任务的
根上下文。opencode 文档([rules](https://opencode.ai/docs/rules/))给出的正解是:**保持 AGENTS.md
简洁,引用详细指南,确保仅在特定任务需要时才加载**。

关键约束(决定方案):opencode 加载外部文件只有两条路——`opencode.json` 的 `instructions`
(**eager**:文档明示 "All instruction files are combined with your `AGENTS.md`",启动即全量并入,
**不省上下文**);以及 `AGENTS.md` 内手动 `@file` 引用 + 显式「按需 lazy 加载」指令(**lazy**:agent
按任务需要 Read)。故**只有手动 lazy 模式真正达成「按需加载」**。claude 侧已天然 lazy
(`.claude/rules/security-*.md` 的 `paths:` 路径作用域,T3 直写、按路径触发加载)——本变更**仅改 opencode**。

## What Changes

- **opencode 输出重构(核心,BREAKING)**:根 `AGENTS.md` 的受管块由「全量规则内联」改为**简洁索引**——
  category 清单 + `@<rules-dir>/<cat>.md` 引用 + 一段「按需 lazy 加载」强制指令(逐字对齐 opencode 文档
  "Manual Instructions in AGENTS.md" 范式)。规则正文移入**每 category 一个独立详述文件**,agent 仅在
  任务涉及该领域时 Read。
- **新增 shipped 详述目录** `<target>/docs/security-controls/<category>.md`(默认;`--rules-dir` 可覆盖)。
  可见、可提交、团队共享(对齐文档 "shared across your team");**不**放 `.mgh-init/`(工作/缓存目录,
  常被 gitignore,放 shipped 规则会丢共享语义)。
- **T3 直写详述文件(对齐 claude 模式)**:`init-rulewriter` opencode 下直接写
  `<rules-dir>/<cat>.md`(**独立 H1 文档**,非「嵌进块的 H3 暂存 fragment」);**NEVER** 直写 `AGENTS.md`
  (既有硬边界保留)。废弃 `.mgh-init/rules-parts/` 暂存目录。
- **`assemble_rules.py` 角色重塑**:不再「合并 fragment 进单个内联块」;改为 (a) 扫 `<rules-dir>/*.md`
  建 `AGENTS.md` 简洁索引块(每项取详述文件首条 `#` 标题为展示名,回退 filename stem)、(b) 对详述文件
  跑既有纯净性 lint(token + opencode `---` 围栏检查)。**复用既有 `<!-- security-controls:begin/end -->`
  哨兵** → 旧版内联块被幂等替换为索引块(天然迁移,如旧 `mgh-init:` 块迁移范式)。
- **`list_rule_jobs.py` 契约调整**:opencode `rule_path` 由 `.mgh-init/rules-parts/<cat>.md` 改为
  `<abs target>/<rules-dir>/<cat>.md`(仍绝对、仍 `Path.resolve()`、仍逐字透传给 subagent)。
- **CLI 契约(R5.1)**:`assemble_rules.py` 的 `--parts` → **`--rules-dir`**(默认 `<target>/docs/security-controls`);
  `list_rule_jobs.py` 新增同名 `--rules-dir`。两壳 bash 示例 + `tools/check_contracts.py` 同步。
- **claude 不变**:已 lazy;仅同步披露措辞,`paths:` 结构与 `.claude/rules/` 落点不动。
- **manifest + 诚实边界**:`init_manifest.json` 记 `rules_dir` + `rules_layout:"lazy-index"`;
  `AGENTS.md` 诚实边界段更新 opencode 输出形态。VERSION bump(承 R5.8)。

## Capabilities

### New Capabilities
<!-- 无。本变更重构 opencode 既有 rules 输出形态,不引入新能力。 -->

### Modified Capabilities
- `rules-emission`:opencode 的「single root AGENTS.md 内联受管块」要求改为「简洁 AGENTS.md 索引块 +
  每 category 独立详述文件 + 按需 lazy 加载指令」;`assemble_rules.py` 的「合并 fragment 进单块」职责改为
  「扫详述目录建索引 + lint 详述文件」;`list_rule_jobs.py` opencode `rule_path` 指向详述目录。

## Impact

- **脚本**:`core/scripts/assemble_rules.py`(索引生成 + 详述文件 lint + `--parts`→`--rules-dir`)、
  `core/scripts/list_rule_jobs.py`(opencode `rule_path` + `--rules-dir`)。零新增 pip 依赖(承 R2)。
- **提示词**:`core/prompts/stages/init-rulewriter.md`(opencode 直写详述文件,独立 H1)、
  `core/prompts/fragments/rules-format-opencode.md`(emission flow + 独立文档模板 + lazy 引用语义)。
- **命令壳**:两壳步骤 6/6b 披露 + bash 示例(`list_rule_jobs`/`assemble_rules` 新 `--rules-dir`)。
- **契约/安装**:`tools/check_contracts.py` 覆盖新 `--rules-dir`;`install.sh` 自检清单已含两脚本(无新脚本);
  VERSION bump。
- **测试**:`tests/test_assemble_rules.py` 重写(索引生成、详述文件 lint、哨兵幂等替换/旧内联块迁移、空目录)。
- **下游零感知**:`controls_inventory.json` schema 不变;T1/T2/T4 契约不变;哨兵字符串不变(复用)。
- **研发铁律对齐**:R5.1(CLI 契约双壳镜像 + check_contracts)、R5.3(脚本稳定性 + 扇出经 `list_*` 枚举)、
  R5.5①②③(recipe + `NEVER` + RFC-2119)、R5.7(能确定性的结构/lint 仍确定性;lazy 加载本身语义性、
  opencode 唯一机制,文档背书)、R5.8(VERSION + 回归测)、R5.10(shipped 产物纯净性,lazy 指令文本干净)。
