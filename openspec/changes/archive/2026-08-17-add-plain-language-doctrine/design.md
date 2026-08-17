## Context

本仓文档当前「面向 AI 阅读」(R3)导致人类可读性长期缺位;`docs/r5-plain-language.md` 是全仓唯一人类可顺畅阅读的长文档(四要素结构 + 术语表),证明模型被要求时写得出人话。动机与 token/压缩证据链见 proposal「Why」及 `docs/review-plain-language-doctrine.md`。本设计只定「怎么改」,不重述 why。

关键约束:
- R5.5 措辞纪律(RFC-2119、NEVER、recipe)是给 subagent 的功能性约束,其承重防御不可因「美化」而软化(R5.6 保真度优先)。
- `docs/` 在 `check_distributed_purity.py::SCAN_DIRS` 之外;但 man 文档一旦分发就**属于** shipped md 集,须反向纳入扫描。
- 4 个在途 change(`harden-mgh-init-scout-path-binding`/`add-mgh-ut`/`extract-ut-shared-helpers`/`add-mgh-telemetry-seam`)均不碰 5 命令壳与 install.sh 的 man 分发面;唯一交集是 `AGENTS.md`(R3 vs scout 的 R5.7 段 B,同文件不同段)。

## Goals / Non-Goals

**Goals:**
- 把「给谁读」写进章程(R3 受众声明制),人类面与 agent 面**按文件**分离。
- 交付纯新增的人类面资产(glossary 种子 + 5 份 man 说明)+ 一套确定性代理 lint + 人话序 convention。
- 全部分发面(man 文档 + 壳指针)通过 purity lint,不破 R5.8/R5.10。

**Non-Goals:**
- **不做** C(终端产物 `report.md` / `docs/security-controls/<cat>.md` 语域人话化)——需 R5.7 A/B 且与在途 `init-scout.md` 同文件冲突,压到后续 change。
- **不做**详述文件 1.3× 软上限(作用对象是终端产物,随 C)。
- **永不**改写壳操作散文 / NEVER 链 / stage 行为段 / JSON schema。
- **不**把 `docs/glossary.md`/`docs/man/` 反挂进任何提示词引用(agent 不加载它们,零 agent 上下文成本)。

## Decisions

### D1 — R3 修订:受众声明制(改 R3 本体,不新增编号)

在 `AGENTS.md` R3「文档输出规范」段内加一小段(非新开 R3.x,避免 R 编号通胀):每份产物声明受众 ∈ {人类/agent/双受众};人类面走人话规范(现象→原因→改法、术语首现给解释、允许冗余);R5.5 措辞纪律**只辖 agent 操作面**;`proposal.md` 是唯一双受众文件。措辞保持 AGENTS.md 简练风格(RFC-2119 动词),它是 agent 读的规则、但内容规定人类面规范(元结构:规则面不人话化,人话化只发生在它**规定**的那些产物上)。

**受众分类表**(写进 R3 或 design 附录,防「人话化蔓延」):
- **人类面**:`docs/man/**`、`docs/glossary.md`、proposal 人话序、终端报告(report.md / 详述文件,C 范围内)。
- **agent 面**:命令壳纪律段、stage 提示词、`core/contracts/**`、JSON schema、NEVER 链、flag 表——**字节不动**。
- **双受众**:`proposal.md`(人话序 + 结构化 why/what/capabilities/impact)。

**替代方案**:新建 R6「可读性」——否决,新增编号会触发 R5.10 编号引用 + 全仓引用面扩张,受众声明是 R3「文档输出规范」的自然延伸,并入 R3 更省。

### D2 — glossary 种子:复用 r5-plain-language 术语表格式,~30–50 条

`docs/glossary.md` 用 `术语 | 大白话释义` 两列表,条源 = AGENTS.md 高频术语 + `docs/r5-plain-language.md`「术语表」。英文术语(`fan-out`/`recipe`/`mid-session`)保留英文但给中文释义(回答评审 Q1:保留英文因它是本仓操作性词汇,释义消除「裸嵌」)。规则「人类面用词前词典必须有,缺则先补」写进 R3。

### D3 — man 文档:结构 + 分发路径 + 壳指针

- **结构**:`docs/man/<cmd>.md` 四段——做什么 / 会动哪些文件 / 产出什么 / 风险边界(诚实边界)。面向人类,人话措辞,零研发态悬空引用(自然规避,由 purity lint 兜底)。
- **分发**:`install.sh` 加一段 `cp -r docs/man/ → <target>/docs/man/`(平台中立,与 mgh-init 已写 `docs/security-controls/` 同层;幂等 `mkdir -p` + `cp`)。
- **壳指针**:每壳(5 命令 ×2 平台 = 10 文件)顶部加一行 `> 人类读者:通俗说明见 docs/man/<cmd>.md`(~20 tok)。**替代方案**:不加法指针、只靠 README 索引——否决,目标项目用户从终端直接看到壳,指针是唯一可达路径;20 tok 噪音级(proposal §6.2 已核)。

### D4 — CI 代理 lint `tools/check_plain_language.py`(stdlib,承 R2/R5.3)

R5.3 契约:`--help` 即契约面、stdout=JSON `{scanned, violations[], warnings[]}`、stderr=诊断、退出码 `0/1/2`、任意 cwd 自定位、`encoding="utf-8"`、零第三方 import。三项检查:

1. **人话序存在性**(fail-loud exit 2):约定 proposal 人话序以 `> **人话序**` 起始的 blockquote 标记;lint 扫 `openspec/changes/*/proposal.md` 断言该 marker 存在(archive/ 不扫)。**判定标记约定**是本次新增,写进 R3(供作者遵循)。**存量豁免**:5 个 pre-doctrine 在途 change 经 `--allowlist`(变更名清单,`tools/plain_language_allowlist.txt`,镜像 purity lint 的逃生口惯例)豁免——新 change MUST NOT 进豁免表,直接写人话序。
2. **术语黑名单**(WARN):完整**词边界**匹配的黑名单表(无编号压缩词:`物化`/`拒识`/`接线`/`治类`/`锚`/`哨兵`/`运行域`…),仅扫人类面文件。**不用子串匹配**——「承」「兑现」单字会误伤「继承」「兑现承诺」,且「承 R5.x/兑现 R5.x」dev-meta 形态已由 `check_distributed_purity.py` 第 8 类覆盖,不重复。
3. **英文原子密度**(WARN):散文行中非标识符 ASCII 词占比超阈值 → WARN;跳过 fenced code block、inline `code`、以 `> ` 开头的引用行、纯路径行(避免 man 文档里合法的 `--check`/`py` 误报)。

**诚实边界**:黑名单只能命中已登记术语,新造词漏网 → 靠 D7 人工闸门兜底;机器测不了真可读性。

### D5 — 严重度两档的根据

存在性检查 fail-loud:proposal 缺人话序是**结构性缺件**,可在 apply 前确定性拦截。黑名单+密度 WARN:合法术语/必要英文(如 `--flag`)有不可避免的假阳,硬失败会阻断本应合入的改动;WARN 让 CI 通过但把信号留给人工 review。

### D6 — SCAN_DIRS 扩 + purity 不变量

`tools/check_distributed_purity.py::SCAN_DIRS` 加 `ROOT / "docs" / "man"`,使「shipped 集 = install.sh 拷贝 source globs = SCAN_DIRS 扫描集」三同源不变量在新增 man 分发后仍成立(承 distribution-purity spec MODIFIED)。man 文档是 shipped md 中第一类**人类面**产物,其「人话」与「纯净」天然相容(人话规避行话),lint 兜底残留。

### D7 — 人工闸门(流程,非机器)

就绪标准加一条(R3):维护者只读 proposal 人话序 + tasks.md 能复述本 change,做不到 = 未就绪。这是唯一能测「真可读性」的闸门,不机器化。

### 时序(与在途 change 的关系)

- `AGENTS.md` R3 段 vs scout-path-binding 的 R5.7 段 B:同文件不同段,git 不同行可并;若 apply 冲突,后合入者 rebase 即可(轻度交集,评审 §7 已核)。
- 5 壳指针行、install.sh man 分发、SCAN_DIRS 扩:4 在途 change 均不触及,零冲突。

## Risks / Trade-offs

- **[黑名单漏网新造词]** → 靠 D7 人工闸门 + glossary「用词前必补」规则兜底;不追求机器全覆盖。
- **[人话化蔓延到 agent 面]** → R3 受众分类表显式列出 agent 面文件;CI lint 只扫人类面,天然不触 agent 面。
- **[man 分发触发 R5.8 版本 bump + 自检面扩大]** → install.sh 只加一段幂等 cp,自检面新增 5 个 md 的 purity 扫描(fail-soft);版本号随本 change bump。
- **[壳指针 20 tok 微增]** → 每壳 +1 行,proposal §6.2 已核为噪音级,不破 R5.6 预算。
- **[`docs/` 在 purity 扫描之外的历史语义被打破]** → 只把 `docs/man`(分发子集)纳入扫描,`docs/` 其余(r5-plain-language、glossary、review-*)仍不进扫描集(研发态 only);glossary 与 r5-plain-language 不分发,不纳入。

## Open Questions

无(范围已由维护者拍板「A+B+分发」;C 与 1.3× 软上限已明确压后)。
