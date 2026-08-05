## Context

本仓 `m3g4h⊿rness` 已积累的开发经验目前分散在三处,各有盲区:

- `AGENTS.md` 的 R5.x 铁律 —— 面向**本仓维护者**,密度极高,每条规则带「理由〔…〕」承重教训,
  但**不讲故事**:新读者只看到「MUST / NEVER」,看不到「这条是被哪次真实失败逼出来的」。
- `openspec/changes/archive/`(20+ 次迭代)—— 逐次变更记录,**最接近故事原料**,但是按时间线
  堆叠的变更日志,没有抽取出「这类 skill 开发总会撞上的大模型通病」。
- `docs/r5-plain-language.md` —— 名义上是 R5 规则的大白话版,但**现存半英半中、术语堆砌**(如
  `argparse`/`Usage:` docstring、`sys.path.insert(0, dir-of-__file__)`、
  `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS`、`shell.ts::shellEnv`、RFC-2119 等内联混排),
  对未参与本仓的工程师**仍难读**;且只覆盖规则,不做「通病 → 案例 → 机制」归因,也不含非规则类
  认知纠正(opencode hook、NTFS `::` 等)。本变更顺手优化其可读性(见 D6)。

受众:**团队内部没参与过本仓的工程师**,目标是让他们做下一个「大 skill / agent 工具链」时能
直接复用这些约束与兜底机制,而不是重新踩一遍坑。

约束(承 AGENTS.md):纯文档、零运行时依赖(R2)、简练面向 AI(R3)。本文档**不分发**(install
不装入目标项目),故**可自由引用** R5.x / FDn / 变更夹名等开发态标识(R5.10 管辖的是*分发产物*,
本文件不在其列)。

## Goals / Non-Goals

**Goals:**
- 产出**一份** `docs/skill-dev-经验总结.md`,中文大白话,面向团队分享。
- 以**「大模型通病」为组织主线**(非时间线、非逐条规则),每个主题给出:**通病描述 → 真实迭代
  案例( cite 变更夹名)→ 沉淀出的机制/规约 → 可迁移到新 skill 的清单**。
- 覆盖既有规则类(R5.1–R5.10)与**非规则类**认知纠正(opencode hook、NTFS `::` 等)。
- 与 `r5-plain-language.md` / `README.md` / `docs/mgh-*-工作流程详解.md` **互补不重复**。
- **顺手优化** `docs/r5-plain-language.md`:该文档现存的半英半中、术语堆砌、难懂问题,做一次
  可读性 pass(保留四要素结构与规则语义,见 D6)。

**Non-Goals:**
- 不替代 `README.md`(对外用户文档)。
- 不复述 R5 逐条条文(那是 `r5-plain-language.md` 的职责);只讲**来历 + 通病**。
- 不重写各命令工作流详解(已有 `docs/mgh-*-工作流程详解.md`)。
- 不引入代码、CI、依赖。

## Decisions

**D1 — 单文件 vs 多文件**:选**单文件** `docs/skill-dev-经验总结.md`。理由:分享文档价值在
「一份发出去能读完」;多文件会增加跳转摩擦。备选(每通病一文件)被否:破坏可分享性。详节用
文件内小标题 + 表格分章,长案例以「`文件:行号` / 变更夹名」索引(承 R3),不贴长代码。

**D2 — 组织主线 = 大模型通病优先**(非时间线、非规则序)。理由:目标是**教会识别通病**,时间线
是变更日志、规则序是手册;只有「通病 → 我们怎么撞上的 → 兜底」能迁移到新项目。研究阶段已把
20 次归档迭代逐个挖通,定稿的通病主线(每条都 cite 真实变更夹名):
1. **触发词误读 + 过度热情 codegen**(shell 说「Implement」,agent 真去写代码;把编排器物化成
   `.py`)→ R5.2 黑盒纪律;反例从 `mgh_init.py` 改为 agent 真会写的 `py -c` / `_prep_*.py`
   (承 `fix-mgh-init-stability` FD7、`harden-mgh-init-orchestration-discipline` FD1)。
2. **禁令打错失败形状**(禁的是 `mgh_init.py`,agent 写的是 `py -c "import json"`,不模式匹配)
   → R5.5① recipe 取代 prohibition;明线 MUST 落在真实失败形状上(同 FD1,本档最高杠杆教训)。
3. **没有合法内省出口 → 手搓 `py -c`**(无契约 JSON 被 `len()` 顶层;无 `--checkpoints` 出口 →
   写 `_prep_scout_batches.py` 填真实脚本空洞)→ `list_*` 枚举器模板 + `describe_artifact.py`
   「合法 peek」原语(承 `fix-mgh-init-cluster-fanout`、`harden-mgh-init-orchestration-discipline`)。
4. **路径/任意 cwd 漂移**(两个 agent 各拼一次路径 → 漂到 Windows 盘符根)→ R5.3(b) 扇出路径
   recipe:`pending[].checkpoint_path` 绝对 + `MGH_TARGET` 子树守卫(承 `harden-mgh-init-fanout-output-paths`)。
5. **上下文有限 + 整份读聚合**(弱模型 `ReadAllBytes` 426KB 进编排器上下文)→ 按单元物化有界输入
   `input_path` + `--offset/--limit` + token 硬预算(承 `harden-mgh-init-context-budget`、
   `harden-mgh-{sast,sra,srr}-context-budget`)。
6. **单发不可恢复 + 默认超时墙被 SIGKILL** → 原子写 + 软时限早退(`partial:true`/退出码 0)+
   编排器 per-call `timeout` + `--resume` 重派零全损(R5.4;承 `harden-mgh-init-shell-timeout`)。
7. **LLM 产物可畸形**(丢字段 / 非法 JSON)→ R5.9 `--check` 覆盖关键字段 + 退出码对齐闸门(2)+
   消费侧兜底 + 生产侧把畸形结构上变得不可能(承 `fix-mgh-init-scout-merge-robustness`)。
8. **纯净性逐轮出新形状**(schema 字段名被抄成 YAML front matter、过程散文泄漏)→ R5.10 purity
   lint 高精度 token + 提示词护栏;每堵一洞 LLM 找新洞(承 `fix-mgh-init-rules-purity`、
   `fix-mgh-init-opencode-agents-md-noise`、`purify-distributed-md`)。
9. **认知前提出错**(最高教学价值,单列一节):① 误判「opencode 无 hook」实为 `tool.execute.before`
   插件(`harden-mgh-opencode-hook-parity`);② 误以为 `opencode.json instructions` 省 token 实为
   eager 全装载(`improve-mgh-init-opencode-lazy-rules`);③ `::` 是 NTFS ADS 分隔符、写盘 errno 22
   (`harden-mgh-init-context-budget` 实现期发现);④ opencode 插件进程不继承 mid-session env(`MGH_*_ACTIVE`
   仅启动前就绪生效)。
10. **上游引用保真**(移植类 skill 的溯源纪律)→ R1 / `extract_prompts.py`(承 `add-mgh-sast` 全程)。
11. **同代命令不自动继承硬化**(mgh-init 硬化后 mgh-sast 原样复现 FD1)→ 横向复制纪律覆层、不动移植正文(R1)。

「**前提出错**」(D2-9)单列成章——这类「我们一直以为是 A,查了才发现是 B」最令人谦卑、也最能教会
「动手前先验证平台事实」。

**D3 — 语言**:中文大白话为主;仅当中文表达不准的术语(hook、subagent、AST、CVSS、hook 事件名
`tool.execute.before`、`fail-loud`/`fail-soft` 等)保留英文并首次出现处给中文释义。

**D4 — 取材与归因的诚实边界**:每个案例**必须 cite 一个真实变更夹名或 `AGENTS.md` 规则号**;通病
归因显式标注为「团队回溯性解读」,不冒充上游原始结论。诚实边界(承 AGENTS.md 末段):对仍是
**非确定性可测**的护栏(如提示词级纯净性、opencode 惰性索引的语义触发)如实说明局限。

**D5 — 可迁移清单收尾**:文末一张「做新「大 skill」前置检查表」(该前置哪些约束、配哪些兜底机制、
哪些必须在 install 时就位而非靠 agent 自觉)。

**D6 — 顺手优化 `docs/r5-plain-language.md` 可读性**(用户指出该文档半英半中、难懂)。范围:**保留**
既有四要素(说什么 / 为什么 / 违反后果 / 兜底)结构与规则编号(R5.1–R5.10),**只做可读性 pass**:
内联代码 / 长术语拆成「大白话 + 括号术语释义」、每条规则先用一句大白话开场再上细节、术语表化重复
出现的缩写。**不改**规则语义、**不删**任何教训(受 `agents-md-discipline` spec「R5 refactor safety」
约束)。属编辑性改进、更好满足该 spec 既有「大白话配套文档」要求,**不需 spec delta**。

## Risks / Trade-offs

- [文档定位为一次性分享快照,未来可能删除] → mitigation:本文**不挂任何反向指针**(README /
  docs 索引 / AGENTS.md 均不链接它),可整份删除而不留断链;**不做「活文档维护契约」**(spec 不
  写回灌要求)。
- [与 `r5-plain-language.md` 内容重叠] → mitigation:文档头部声明边界;本文讲「来历+通病」,
  不复述规则正文;且本变更顺手把 r5-plain-language.md 大白话化(D6),两文可读性同步提升。
- [通病归因主观] → mitigation:D4 —— 必 cite 真实来源 + 标注为回溯性解读。
- [优化 r5-plain-language.md 误删 / 软化教训] → mitigation:D6 + `agents-md-discipline` spec
  「R5 refactor safety」约束;只改表述不改语义。

## Migration Plan

无代码迁移。部署 = 提交 `docs/skill-dev-经验总结.md` + 修订 `docs/r5-plain-language.md`;回滚 =
删除 / 还原这两个文件。**本文档不与 README / docs 索引 / AGENTS.md 建立任何指针关联**(定位为
一次性分享快照,未来可整份删除而不留断链)。

## Open Questions

- **文件名**:中文 `docs/skill-dev-经验总结.md`(与兄弟文档 `mgh-*-工作流程详解.md` 一致);仓内
  已有中文文件名先例且 git/CI 表现正常,apply 时定稿。
- (已决)**不**与 README / docs 索引 / AGENTS.md 建立反向指针 —— 文档为一次性分享快照,可能删除。
