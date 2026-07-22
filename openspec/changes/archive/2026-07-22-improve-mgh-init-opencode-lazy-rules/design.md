## Context

`/mgh-init --format opencode` 的运行时输出是目标项目根 `AGENTS.md` 的单个中性受管块
(`<!-- security-controls:begin --> … :end -->`):T3 `init-rulewriter` 写暂存 fragment
(`<target>/.mgh-init/rules-parts/<cat>.md`,裸 `### <Category>` 小节),`assemble_rules.py` 把全部
fragment 合并进该块。opencode 启动**整份** `AGENTS.md` 进根上下文——大项目下该块几乎全是安全规则,
直接占用 AI 编码任务的根上下文预算。

opencode 加载外部指令只有两条路(文档 [rules](https://opencode.ai/docs/rules/)):

| 机制                                      | 加载时机                                                                  | 是否省上下文   |
| --------------------------------------- | --------------------------------------------------------------------- | -------- |
| `opencode.json` `instructions`(glob/远程) | **eager**——"All instruction files are combined with your `AGENTS.md`" | ❌ 启动全量并入 |
| `AGENTS.md` 内手动 `@file` + 显式 lazy 指令    | **lazy**——agent 按任务需要 Read("use lazy loading based on actual need")   | ✅ 按需     |

→ **只有手动 lazy 模式真正达成「按需加载」**;`opencode.json` 仅拆文件、仍 eager,不解决问题。
claude 侧已天然 lazy(`.claude/rules/security-*.md` 的 `paths:` 路径作用域)。故本变更**仅改 opencode**。

约束(承 AGENTS.md):R2 零运行时依赖;R5.1(CLI 契约 = `--help`,双壳镜像,`check_contracts` 断言);
R5.3(脚本稳定性 + fan-out 经 `list_*` 枚举 + 绝对输出路径逐字透传);R5.5①②③(recipe + `NEVER` + RFC-2119);
R5.7(能确定性的仍确定性——结构/lint 守住;lazy 加载本身是**语义性**的,opencode 唯一机制,文档背书,
非「靠 agent 自觉」的可确定性事项);R5.8(VERSION + 回归测);R5.10(shipped 产物纯净性)。

## Goals / Non-Goals

**Goals:**
- opencode 根 `AGENTS.md` 受管块由「全量内联」缩为**简洁索引**(category 清单 + `@` 引用 + lazy 指令),
  规则正文移入**每 category 一个独立详述文件**,agent 仅在任务涉及该领域时 Read。
- 详述文件落在**可见、可提交、团队共享**的目录(对齐文档 "shared across your team"),非工作/缓存目录。
- 复用既有 `<!-- security-controls:begin/end -->` 哨兵 → 旧内联块幂等替换为索引块(零额外迁移逻辑)。
- 详述文件沿用既有纯净性 lint(token + opencode `---` 围栏检查),零新增 pip 依赖。

**Non-Goals:**
- 不改 `controls_inventory.json` schema / T1/T2/T4 契约 / 哨兵字符串 / claude `paths:` 结构。
- 不引入 `opencode.json` `instructions`(eager,不省上下文,违本变更目标)。
- 不对 lazy 加载本身加确定性 hook(语义性,opencode 无该机制;由提示词 directive 覆盖,诚实边界明示)。
- 不评估控制「有效性」(CVE-2025-41248 边界不变)。

## Decisions

### D1 — 加载机制:手动 `@file` lazy(非 `opencode.json` eager)

opencode 详述文件经 `AGENTS.md` 索引块内的 `@<rel-path>` 引用 + 一段「按需 Read」强制指令加载(逐字对齐
文档 "Manual Instructions in AGENTS.md" 范式)。索引块示例(由 `assemble_rules.py` 从 `<rules-dir>/*.md`
glob 生成,展示名取各详述文件首条 `#` 标题、回退 filename stem):

```markdown
<!-- security-controls:begin -->
## 安全设计 — 复用,勿重造
本项目已梳理出以下**既有可复用安全控制**(存量实现,勿重新发明)。**按需加载**:仅当要改动的代码
涉及某领域时,用 Read 工具读对应文件;**勿预先全加载**(省上下文)。读后内容即强制指令。
- 认证 → @docs/security-controls/authentication.md
- 授权 → @docs/security-controls/authorization.md
> 涉及以上领域的新代码 MUST 先 Read 对应文件、复用既有实现;无对应文件 = 该领域无梳理出的存量控制。
<!-- security-controls:end -->
```

**否决方案**:(a) `opencode.json` `instructions` 列详述文件——eager 全量并入,**不省上下文**,违目标;
(b) 保持单块内联——即现状问题;(c) opencode 原生不支持 `paths:` 路径作用域,无法像 claude 那样自动
按路径触发,故只能靠 `@` + 指令(语义性 lazy)。

### D2 — shipped 详述目录:`<target>/docs/security-controls/`(默认,`--rules-dir` 可覆盖)

详述文件落在 `<target>/docs/security-controls/<category>.md`。理由:① 对齐文档示例(`@docs/...`);
② 可见、可提交、团队共享(shipped 规则的核心价值);③ 非工作/缓存目录。

**否决方案**:(a) `.mgh-init/rules-parts/`(现状暂存目录)——`.mgh-init/` 是工作/缓存目录,用户常 gitignore,
放 shipped 规则丢共享语义;`.mgh-init/` 亦在 `FORBIDDEN_TOKENS`(防路径泄漏进规则正文),语义不符;
(b) `.opencode/rules/`——工具配置命名空间,opencode 不自动加载该位置,混 shipped 内容语义错位;
(c) 顶层 `security-rules/`——可见但新增顶层目录,部分用户反感;`docs/` 子目录更常规。

### D3 — T3 直写详述文件(对齐 claude,废弃暂存)

`init-rulewriter` opencode 下直接写 `<rules-dir>/<cat>.md`(**独立 H1 文档**),不再写
`.mgh-init/rules-parts/` 暂存 fragment。`assemble_rules.py` 扫该目录建索引 + lint。**NEVER** 直写 `AGENTS.md`
(既有硬边界保留——T3 只产详述文件,索引块归装配脚本)。

**否决方案**:保留暂存 + 装配 promote——暂存与 shipped 内容重复(工作产物 vs shipped 产物分离是好,
但同内容两份冗余);直写更简洁、与 claude 一致、消除冗余。直写不破坏「T3 不写 AGENTS.md」边界
(写 `docs/security-controls/<cat>.md` ≠ 写 `AGENTS.md`)。

### D4 — 索引块由装配脚本从详述目录确定性生成

`assemble_rules.py` 不再读 inventory / 不再拼接 fragment 正文;改为 `glob('<rules-dir>/*.md')` → 每文件
取首条 `#` 标题为展示名(回退 filename stem)+ `@<相对 target 的路径>` 引用 → 拼索引块 → 幂等替换
`AGENTS.md` 内同哨兵块(复用 `_merge_into` 既有逻辑)。**索引 = 详述目录的现实快照**(无详述文件的
category 不进索引;整 category 无实现时 T3 不写文件 → 自然不进索引,承前序 D5「无实现=无输出」)。

### D5 — 详述文件:独立 H1 文档,无 front matter,沿用纯净性 lint

详述文件模板由 `### <Category>`(嵌进块的 H3)改为独立 `# <Category> 安全控制`(H1)。opencode 无
path-scoping → 详述文件**仍无 front matter**(裸 H1 起),lazy 加载由 `AGENTS.md` 索引的语义指令驱动
(非路径触发)。`assemble_rules.py` 的 lint 扩展扫描对象由「装配后的单块」改为「`<rules-dir>/*.md`
详述文件」(token + opencode `---` 围栏检查不变;claude 侧 lint 对象 `.claude/rules/security-*.md` 不变)。

### D6 — CLI 契约:`--parts` → `--rules-dir`(两脚本)

`assemble_rules.py` 的 `--parts`(暂存目录,默认 `.mgh-init/rules-parts`)语义已变(暂存→shipped 详述目录),
**改名 `--rules-dir`**(默认 `<target>/docs/security-controls`),`--out` 仍指 `AGENTS.md` 路径不变。
`list_rule_jobs.py` 新增同名 `--rules-dir`(计算 opencode `rule_path = <abs target>/<rules-dir>/<cat>.md`)。
两壳 bash 示例 + `tools/check_contracts.py` 同步(承 R5.1)。**BREAKING**:`--parts` 移除、opencode 输出
结构变(内联块→索引+文件);但 `--parts` 几乎仅默认使用,影响面小。

## Risks / Trade-offs

- **[lazy 非确定性:agent 不加载 → 重造]** → opencode 唯一的按需机制就是 `@`+指令(无路径自动触发);
  **缓解**:索引块带**强 directive**(「涉及该领域的新代码 MUST 先 Read 对应文件」)+ category 级信号
  (agent 见领域名即知有存量控制);claude `paths:` 已证 lazy 可行;诚实边界明示此为语义性、非确定性部分。
- **[索引引用失效/孤儿文件]** → 详述文件删了但 AGENTS.md 索引未更新;**缓解**:索引由 `assemble_rules.py`
  每次 `glob` 现实快照生成,重跑即自愈;`--check` 校验索引项与目录文件一致(可选)。
- **[哨兵复用迁移:旧内联块]** → 旧版目标的 `AGENTS.md` 含大内联块;**缓解**:同哨兵 → 新版重跑幂等替换为
  索引块(天然迁移,如旧 `mgh-init:` 块迁移范式);不重跑者保留旧块(仍可用,仅非 lazy)。
- **[`--parts` 移除破坏脚本]** → **缓解**:`--parts` 几乎仅默认使用;`--help` 即契约(承 R5.1);check_contracts
  断言新 `--rules-dir`;VERSION bump + 回归测。
- **[详述文件 H1 展示名抽取]** → 文件无 `#` 标题时索引展示名退化;**缓解**:回退 filename stem(`authentication`
  仍可读);`rules-format-opencode.md` 模板强制 H1 起。
- **[索引仍占少量根上下文]** → 索引 ~每 category 一行(8 类 ≈ 8 行),远小于旧全量块;**缓解**:此为「保证
  可见性」的最小代价(agent 至少知哪些领域有存量控制);是否在索引内联主控制名(hybrid 富化)见 Open Questions。

## Migration Plan

1. 脚本 + 提示词改完后,以新版重跑 `mgh-init --format opencode` on 样例仓:T3 直写
   `docs/security-controls/<cat>.md`;`assemble_rules.py` 把旧内联块替换为索引块(同哨兵幂等)。
2. claude 用户:无输出形态变化;`paths:` 结构与 `.claude/rules/` 落点不变(仅披露措辞同步)。
3. 回滚:还原 `assemble_rules.py`/`list_rule_jobs.py`/两提示词;重跑即恢复旧内联块(产物可重生,低风险)。
4. VERSION bump(两命令壳 + 受影响脚本,承 R5.8);回归测覆盖 索引生成 / 详述 lint / 哨兵幂等替换 /
  旧块迁移 / 空目录 / `--rules-dir` 契约。

## Open Questions

- **索引展示名:H1 标题 vs filename stem?** → **决定(D4)**:取详述文件首条 `#` 标题,无则回退 stem。
- **索引是否内联主控制名(hybrid 富化,提升可见性)?** → **决定**:首版**保持简洁**(仅 category + `@` 引用,
  对齐用户「保持 AGENTS.md 简洁」诉求 + 文档范式);hybrid 富化列为后续可选增强(若实测 agent 漏加载)。
- **详述目录默认 `docs/security-controls/` 是否需更短路径?** → **决定**:用 `docs/security-controls/`(文档惯例、
  可提交);`--rules-dir` 可覆盖。
