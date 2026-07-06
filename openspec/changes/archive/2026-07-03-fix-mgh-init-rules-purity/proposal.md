## Why

mgh-init 生成的 opencode root `AGENTS.md`(以及共享同一 inventory 的 claude
`.claude/rules/*.md`)把**本工具自身的内部信息**泄漏进了目标项目的根上下文:

- 每 category 一对 `<!-- mgh-init:begin:<category> -->` 品牌标记散落其间——对 opencode
  加载**无任何语义**(HTML 注释惰性),纯耗 context,且 `mgh-init` 这个名字对目标项目的
  开发者与读规则的编码 agent 毫无意义;
- 规则正文里出现 `discover_controls.py` / `chunk_sources.py` 等**本工具脚本名**,以及
  「T1/T2 流水线」式的工具运作说明。

opencode 只能用 root `AGENTS.md` 作根上下文(无 rules 目录、无 path glob),这些噪声直接
稀释了它本该承担的唯一职责:**引导安全编码 + 复用存量已知实现**。

根因有二:(1) `rules-format-opencode.md`(单块)与 `init-rulewriter.md:33`(per-category 块)
对受管块结构的约定**互相矛盾**,而 T3 又 per-category 并发 fan-out 写同一文件,最终产出 N
个散落的 `mgh-init:` 块;(2) 全流水线**无任何「输出纯净性」护栏**,T1/scout/survey 提示词
里的脚本名与层级身份框定,经 inventory 人读字段(`usage`/`notes`/`gaps`/`description`)
渗进 T3 规则正文。

## What Changes

- **新增「输出纯净性」硬约束(两种格式)**:T1/T2/T3(+ scout/survey)的人读字段与规则
  正文 SHALL 只含目标项目内容;`NEVER` 出现本工具名(`mgh-init`/`megahorness`)、脚本名
  (`discover_controls.py`/`chunk_sources.py`/`plan_scout.py`/`merge_scout.py`/
  `list_clusters.py`/`assemble_rules.py`)、流水线层级(T1/T2/T3/scout)、`checkpoints/`/
  `.mgh-init` 路径、生成过程描述(承 R5.5①②③:recipe + 硬边界 `NEVER`,无豁免子句)。
- **受管块中性化 + 收敛成单块(仅 opencode)**:`AGENTS.md` 改用**单个**中性受管块
  `<!-- security-controls:begin --> … <!-- security-controls:end -->`,消除 per-category
  散落块与 `mgh-init` 品牌泄漏,并解决 fragment/rulewriter 的结构矛盾。
- **T3 改写暂存 fragment + 确定性装配**:T3 每 category 产出暂存 fragment
  (`<target>/.mgh-init/rules-parts/<category>.md`),由**新增确定性脚本** `assemble_rules.py`
  合并进 `AGENTS.md` 单受管块(幂等替换、保留用户手写内容),顺带消除多 subagent 并发写同一
  文件的竞态。
- **新增生成后确定性 lint**:扫描受管块/规则文件内禁用 token,命中即 fail 并报具体位置——把
  「纯净性」做成确定性闭环(承 R5.7),而非靠 agent 自觉。
- **收紧 opencode fragment 模板**到最小期望形态;claude 格式同步加规则正文纯净性(泄漏源
  共享,两种格式一并修)。

## Capabilities

### New Capabilities

(无——装配与 lint 都归入 `rules-emission`,不引入新能力,保持变更收敛。)

### Modified Capabilities

- `rules-emission`:新增「shipped rules 输出纯净性」要求;修改「非破坏式幂等发射」要求——
  opencode 受管块由 per-category `mgh-init:` 品牌块改为**单个中性** `security-controls:` 块,
  经确定性装配步骤合并;新增「生成后纯净性 lint」要求;refine「opencode 单根 AGENTS.md」要求
  的受管块结构。
- `control-discovery`:新增「inventory 人读字段纯净性」要求——`description`/`usage`/`gaps`/
  `notes`/`competing_clusters[].note` MUST NOT 携带本工具内部引用,从源头切断 T3 规则正文
  的泄漏(防御纵深:inventory 干净 + 规则正文干净)。

## Impact

- **提示词**:`core/prompts/stages/init-{induct,synthesis,rulewriter,rules-consistency,scout,
  scout-merge,scout-audit,survey}.md`、`core/prompts/fragments/rules-format-{opencode,claude}.md`
  加纯净性护栏 + 改标记/模板。
- **新增脚本**:`core/scripts/assemble_rules.py`(确定性、零依赖、承 R5.3 稳定性契约 + R5.4
  可观测);其 `--check` 模式承担生成后 lint。
- **命令壳**:`releases/{claude-code,opencode}/.../mgh-init.md` 编排流改为 T3→暂存 fragment→
  `assemble_rules.py`;stage→组件表 + 确定性调用示例同步;bump 版本号(承 R5.8)。
- **契约**:`core/contracts/init/` 新增 `rules-parts.md`(暂存 fragment 契约);`init_manifest.json`
  记新块名 + lint 结果。
- **测试**:`tests/` 新增 assemble 幂等性 + 旧块迁移 + lint 禁用 token 命中测试(R5.8 回归)。
- **BREAKING**:旧 `<!-- mgh-init:begin* -->` 块不再被新装配器识别;`assemble_rules.py` 在首次
  运行时一次性清扫并迁移旧块(tasks 覆盖),避免孤儿重复内容。
- 零新增 pip 依赖(承 R2);不碰 `core/prompts/**` 溯源注释与上游同步锚点(承 R1)。
