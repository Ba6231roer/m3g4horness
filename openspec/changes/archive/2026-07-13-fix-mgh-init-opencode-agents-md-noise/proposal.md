## Why

`/mgh-init --format opencode` 产出的目标项目根 `AGENTS.md` 里混入了**本不该出现在 AGENTS.md
里的内容**(用户 `new_issue0713.txt` 实测),稀释了它唯一的职责——**引导后续 AI 编码任务复用
存量已知安全实现、勿重造**:

1. **YAML front matter 元数据泄漏**:每个 category fragment 顶部冒出
   `---\ncategory:\nfound_controls:\n  - C-*-001\nevidence_count: 1\n---`。这些是
   `controls_inventory.json` 的**结构字段名**,被 T3 当成 front matter 抄进了正文。opencode
   模板本无 front matter(`rules-format-opencode.md` 是裸 `### <Category>` 小节),**提示词从未
   显式禁止**,AI 填了真空。
2. **「如何被发现」过程散文**:正文出现 `C-AUTHN-001(扫描器模式定义)`、`锚点：扫描器内部正则定义`、
   `扫描器定义了@RateLimit*` —— 把**扫描器/正则的定义**写进了规则,且 `锚点:` 字段被误指向
   扫描器内部而非目标项目源码。现有 spec「Shipped rules exclude tool-internal content」虽已禁
   「过程描述」,但提示词只拿工具名/脚本名/层级词举例,**没点名这些具体失败形状**;lint 也漏。
3. **「控制缺失」噪声**:`C-ABS-001（缺失）: 未发现声明式ACL模式……缺口：无声明式访问控制清单机制`。
   mgh-init 只负责**梳理存量、引导复用**;某类控制在目标项目**无具体实现**时,AGENTS.md 留空即可,
   不该用「设计缺失」散文占行(AGENTS.md 有严格篇幅约束)。**spec 与提示词对「无实现的 category」
   完全无指引**,T3 默认补一段说明。

三者同源:**opencode 唯一出口是单根 `AGENTS.md`(无 rules 目录、无 path glob),任何噪声都直接占
用 AI 编码的根上下文**。现有 `fix-mgh-init-rules-purity` 收口了**工具内部标识符**(工具名/脚本名/
层级/路径)泄漏,但**没覆盖 inventory schema 字段泄漏、过程散文的具体形状、缺失项的处理**——本变更是
其针对性补刀。

## What Changes

- **opencode fragment 显式禁 front matter + schema 字段泄漏**:`rules-format-opencode.md` 加硬边界
  ——fragment **SHALL** 以 `### <Category>` 起、**NEVER** 带 YAML `---` 围栏、**NEVER** 出现
  inventory schema 字段名(`found_controls`/`evidence_count`/`category:`/`source:`/`evidence:` 作
  front matter 键)。与 claude(仅 `paths:`)对齐声明:opencode 无 front matter。
- **「无具体实现则省略」硬边界(两格式共享,改 `init-rulewriter.md`)**:一条规则 SHALL 对应目标
  项目里**有具体源码锚点**(`file:class:method` / `file:line`)的**存量可复用实现**;inventory 里
  **无源码锚点**(扫描器/正则期望但源码无实现,如「限流未发现实现」「ACL 缺失」)的控制 → **emit
  no rule**;若整 category 都无实现 → **不产 fragment**(该 category 不进 `AGENTS.md`,不留「缺失」散文)。
- **`锚点:` 字段契约收紧(两格式)**:`锚点:`/Anchor SHALL 指向**目标项目源码**位置;**NEVER** 指向
  扫描器内部/正则定义/「如何发现」。规则以**目标项目实际使用的类/方法/配置名**起头,控制 ID 可选且
  无 `(缺失)`/`(扫描器…)` 后缀。
- **lint 高精度扩展(确定性闭环,承 R5.7)**:`assemble_rules.py` `FORBIDDEN_TOKENS` 增 inventory
  schema 字段(`found_controls`/`evidence_count`)+ 特征过程散文短语(`扫描器模式定义`/
  `扫描器内部正则`/`扫描器定义`/`锚点:扫描器`/`锚点：扫描器`);**新增 opencode 结构检查**:受管块内
  任何 `---` 围栏行(YAML fence)→ fail-loud(退出码 2)。claude 的 `paths:` frontmatter **豁免**
  此结构检查(claude 合法用 front matter)。保持 D4 高精度哲学:裸 `category`/`缺失`/`锚点` 等通用词
  **不入 lint**(误伤风险),由提示词护栏覆盖、非确定性可测(诚实边界下移)。
- **诚实边界更新**:`AGENTS.md` 的 mgh-init 纯净性诚实边界段补一句——lint 现亦覆盖 inventory schema
  字段 + opencode YAML 围栏 + 特征过程散文;裸通用词(`category`/`缺失`/泛指 `锚点`)仍仅提示词覆盖。
- **VERSION bump**(承 R5.8);**回归测**扩 `tests/test_assemble_rules.py` 覆盖新 token + 围栏检测 +
  claude `paths:` 不误报。

非目标(明确不做):**不**改 `controls_inventory.json` schema(无实现项的判定由 T3 读现有 evidence/
role 字段,不新增字段);**不**改 T1–T2 的归纳/聚类逻辑;**不**改 claude 的 `paths:` 结构;**不**新增
CLI flag(`tools/check_contracts.py` 不变);**不**把裸 `缺失`/`category` 入 lint(违 D4 高精度哲学)。

## Capabilities

### New Capabilities
<!-- 无。本变更是对既有 rules-emission 输出纯净性的针对性加固,不引入新能力。 -->

### Modified Capabilities
- `rules-emission`:refine「opencode rules use single root AGENTS.md」——opencode fragment **NEVER**
  带 YAML front matter / inventory schema 字段;refine「Shipped rules exclude tool-internal content」
  ——增「无源码锚点的控制 emit no rule(整 category 无实现则不产 fragment)」「`锚点:` 字段 SHALL 指向
  目标源码、NEVER 指向扫描器内部」「规则以目标项目实际类/方法/配置名起头」要求;refine「Deterministic
  assembly and purity lint」——lint 增 inventory schema 字段 + opencode YAML 围栏结构检查 + 特征过程
  散文短语,claude `paths:` frontmatter 豁免围栏检查。

## Impact

- **提示词**:`core/prompts/fragments/rules-format-opencode.md`(禁 front matter + schema 字段 +
  锚点契约)、`core/prompts/fragments/rules-format-claude.md`(锚点契约对齐,`paths:` 仍唯一 frontmatter)、
  `core/prompts/stages/init-rulewriter.md`(「无实现则省略」+ 锚点=源码 + 无过程散文,两格式共享 core/
  双端对等)。
- **脚本**:`core/scripts/assemble_rules.py`(`FORBIDDEN_TOKENS` 扩 + opencode YAML 围栏结构检查;
  claude 围栏豁免;退出码 2 不变)。
- **契约/安装**:CLI 无新 flag → `tools/check_contracts.py` 不变;`install.sh` 自检清单已含
  `assemble_rules`(无新脚本随装);VERSION bump。
- **文档**:`AGENTS.md` 诚实边界段 + 命令壳(两壳)bump 版本号。
- **测试**:`tests/test_assemble_rules.py` 扩(新 token / 围栏 fail / claude `paths:` 不误报)。
- **下游零感知**:`controls_inventory.json` schema 不变;T1–T4 契约不变;受管块哨兵不变。
- **研发铁律对齐**:R5.7(确定性闭环优先)、R5.9(lint fail-loud 退出码 2 回退重跑)、R5.10(运行时
  产物纯净性,与 install 分发纯净性同精神)、R5.5①②③(recipe + `NEVER` 硬边界 + RFC-2119)、
  R2(零依赖)、R5.8(回归测 + VERSION bump)。
