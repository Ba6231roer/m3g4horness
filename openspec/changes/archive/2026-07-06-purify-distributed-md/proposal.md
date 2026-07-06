## Why

`install.sh` 把 `core/` 整树镜像进目标业务项目的 `<target>/.claude/mgh-core/`(或
`.opencode/mgh-core/`),连同 `releases/<platform>/{commands,agents}` 一起作为工具提示词
被宿主/subagent **读进上下文**。这些 shipped md 里散落着只对本仓研发有意义的编号——
`R5.2`、`R5.9`、`R3`、`FD8`、`AGENTS.md R1–R4` 等。在业务项目里它们是**悬空指针**:既
浪费 token,又可能误读(业务项目常有自己的 `AGENTS.md` 与无关的 `R5.2`,subagent 会去
读客户那份)。需确立「分发产物纯净性」铁律并把现存引用清掉。

## What Changes

经 6-agent 全量审计(读全部 ~92 shipped md,超越 `R5.*`/`FD.*`),确认并修复完整 8 类
dev-only 溯源 / 悬空引用:

- **剥离 8 类**(前 7 类由 lint 强制,第 8 类人工):
  1. 规则编号 `R5.x`/`R3`/`R1–R4`;2. 失败 ID `FD8`/`FD3`;3. **决策 ID `D2/D12`(新发现)**;
  4. **openspec 变更夹名 `improve-mgh-init-llm-discovery` 等(新)**;5. **内部上游文档
  `glasswing_docs/09`(新)**;6. **仓根开发态文件 `task.260630.md`(新,在 sra/blst)**;
  7. **dev-meta `承 R5.x`/`范式锚点`/`本仓`(新)**;8. 上游溯源行话 `vvah`/`design_controls`
  作归因(人工)。
- **删或嫁接二选一(承用户:不只是删,必需内容要内联)**:被引内容目标**不需要** → 删;
  **必需** → 把**最简** 1–2 行内容嫁接到恰当位置再删指针(省 token 优先)。审计已识别的
  嫁接:`init-scout-audit` 保留 "assume WRONG until confirmed" 删 `mirrors s6`;fragment
  保留 `.opencode/AGENTS.md NOT loaded` 删 `GitHub issue #11454`;survey 保留 `core/contracts/init/`
  (分发)删 `AGENTS.md R1–R4`;inventory alias 表保留表体剥 `vvah` 词。
- **保留操作语义 + 输出产物路径**:`--check`/退出码 2/`<target>/AGENTS.md`/runtime 脚本路径/
  阶段标签 `T1`/`s1`..`s9`。
- **零误伤受保护归因类**:`Source: vvaharness/...` 头(R1)、skills Apache 归因、
  `core/docs/prompt-provenance.md`、操作性 `design_controls`、`CVE-2025-41248`。
- **新增 AGENTS.md 铁律 R5.10**(覆盖完整 8 类)+ **确定性 lint** `tools/check_distributed_purity.py`
  (前 7 类硬边界)+ **回归测** `tests/test_distributed_md_purity.py` + install 自检 fail-soft。
- **bump 版本号**(R5.8);**脚本 `.py` 豁免**(用户:注释可留溯源)。
- **`/mgh-sast` 分发物经审计确认 CLEAN**(sast 壳/agent/skills/prompts 零违例);仅 sra/blst
  骨架有 `task.260630.md` 悬空指针需清。

## Capabilities

### New Capabilities

- `distribution-purity`: 规定所有经 `install.sh` 装入目标项目的 md 工具产物(命令壳、agent
  定义、subagent stage 提示词、I/O 契约、skills)SHALL 不含 dev-only 溯源 / 悬空引用——规则
  编号 `R5.x`、失败/决策 ID `FDn`/`Dn`、openspec 变更夹名、`glasswing_docs/`、仓根 `task.*.md`、
  dev-meta(`承/兑现 R5.x`/`范式锚点`)、上游溯源行话作归因——以及指向本仓过程文档
  (`AGENTS.md` 研发手册、`openspec/`)的交叉引用。悬空引用按「删或嫁接」处理(必需内容最简
  内联,省 token);PRESERVE 操作语义、输出产物路径、受保护归因类(`Source:` 头 / Apache /
  归因记录 / 操作性 `design_controls` / CVE)。由确定性 lint 强制(上游行话人工)。

### Modified Capabilities

<!-- 无。control-discovery / rules-emission 的 spec级行为不变;rules-emission 既有
     「Shipped rules exclude tool-internal content」管的是「产出的 rules 正文」纯净性,
     与本变更管的「工具自身 shipped 提示产物」纯净性是不同对象,不重叠。 -->

## Impact

- **改动的 shipped md**(6-agent 审计枚举,~76 处):
  - 命令壳 `releases/{claude-code/commands,opencode/command}/mgh-init.md`
  - agent 定义 `releases/{claude-code/agents,opencode/agent}/init-*.md`(含 induct/synthesis/scout-audit 的决策 ID)
  - stage 提示词 `core/prompts/stages/init-*.md`(8 文件)
  - fragments `core/prompts/fragments/rules-format-{claude,opencode}.md`
  - I/O 契约 `core/contracts/init/{inventory,candidates,clusters,skeleton,scout-plan,scout-enumeration,rule-jobs,describe,rules-parts,manifest}.md`
  - **sra/blst 骨架** `releases/{claude-code/commands,opencode/command}/{mgh-sra,mgh-blst}.md`(剥 `task.260630.md`)
- **审计确认 CLEAN(不改)**:全部 mgh-sast 分发物(壳/agent×2/skills/stage prompts/baselines/lens/fragments)、`core/docs/prompt-provenance.md`(R1 受保护)。
- **新增**:`tools/check_distributed_purity.py`、`tests/test_distributed_md_purity.py`、AGENTS.md R5.10 段落。
- **install.sh**:接入 purity lint 自检(fail-soft warn,CI 必 fail,承 R5.8)。
- **零行为变更**:不改脚本 CLI 契约、流水线阶段、产物 schema;仅文本剥离/嫁接 + 规则 + lint。
- **零运行时依赖**(R2):lint 仅用标准库 `re/pathlib/json/sys/argparse`。
