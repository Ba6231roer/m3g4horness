# Tasks — add-skill-dev-experience-doc

> 产出物:`docs/skill-dev-经验总结.md`(一份)。取材已完成:20 次归档迭代逐个挖通(见会话研究
> 结果);本任务清单据此把文档写出来。承 R3(简练、表格优先、索引化、禁长代码块)。

## 1. 定稿结构与取材校验

- [x] 1.1 据设计 D2 的 11 条通病主线,确认每条都已对应到真实变更夹名(research 报告已覆盖;缺则补查 `openspec/changes/archive/<夹名>/proposal.md` + `design.md`)
- [x] 1.2 定稿文件名:中文 `docs/skill-dev-经验总结.md`(与兄弟文档 `mgh-*-工作流程详解.md` 一致);确认 git/CI 对中文文件名无异议(仓内已有先例)
- [x] 1.3 列出文档章节大纲(Header/边界声明 → 通病 1–11 → 前提出错 → 可迁移清单 → 维护说明),作为写作骨架

## 2. 文档头部 + 边界声明

- [x] 2.1 写文档标题 + 一句话定位(受众:未参与本仓的工程师;目标:可迁移到新「大 skill」)
- [x] 2.2 写「与现有文档边界」段:明确互补 `README.md` / `docs/r5-plain-language.md` / `docs/mgh-*-工作流程详解.md`,不复述其正文(对应 spec「与现有文档边界清晰」)
- [x] 2.3 写「怎么读」+ 术语表(hook、subagent、AST、`tool.execute.before`、fail-loud / fail-soft、recipe、bright-line 等首次中文释义)

## 3. 通病章节(主体,每条四要素:通病 → 案例 → 机制 → 可迁移)

- [x] 3.1 通病① 过度热情 codegen + 触发词误读(「Implement」→ 真写代码;cite `fix-mgh-init-stability` FD7)
- [x] 3.2 通病② 禁令打错失败形状(禁 `mgh_init.py` 却拦不住 `py -c`/`_prep_*.py`;cite `harden-mgh-init-orchestration-discipline` FD1,本档最高杠杆教训)
- [x] 3.3 通病③ 没有合法内省出口 → 手搓 `py -c`(无契约 JSON 被 `len()` 顶层;`_prep_scout_batches.py` 是填真实脚本空洞;cite `fix-mgh-init-cluster-fanout`、`harden-mgh-init-orchestration-discipline`;机制:`list_*` 枚举器 + `describe_artifact.py`)
- [x] 3.4 通病④ 路径/任意 cwd 漂移到盘符根(两 agent 各拼一次路径;cite `harden-mgh-init-fanout-output-paths`;机制:`pending[].checkpoint_path` 绝对 + `MGH_TARGET` 子树守卫)
- [x] 3.5 通病⑤ 上下文有限 + 整份读聚合(426KB `ReadAllBytes`;cite `harden-mgh-init-context-budget`;机制:按单元物化 `input_path` + `--offset/--limit` + token 硬预算)
- [x] 3.6 通病⑥ 单发不可恢复 + 默认超时墙被 SIGKILL(cite `harden-mgh-init-shell-timeout`;机制:原子写 + 软时限 `partial:true`/退出码 0 + per-call `timeout` + `--resume`)
- [x] 3.7 通病⑦ LLM 产物可畸形(丢字段 / 非法 JSON;cite `fix-mgh-init-scout-merge-robustness`;机制:R5.9 `--check` 覆盖关键字段 + 退出码对齐闸门 + 消费侧兜底 + 生产侧结构上避免)
- [x] 3.8 通病⑧ 纯净性逐轮出新形状(schema 字段名抄成 front matter / 过程散文泄漏;cite `fix-mgh-init-rules-purity`、`fix-mgh-init-opencode-agents-md-noise`、`purify-distributed-md`;机制:R5.10 高精度 lint + 提示词护栏)
- [x] 3.9 通病⑩ 上游引用保真(移植类 skill 溯源;cite `add-mgh-sast` 全程;机制:R1 + `extract_prompts.py`)
- [x] 3.10 通病⑪ 同代命令不自动继承硬化(mgh-sast 原样复现 FD1;cite `harden-mgh-sast-orchestration-discipline`;机制:横向复制纪律覆层、不动移植正文)

## 4. 「前提出错」专章(最高教学价值)

- [x] 4.1 opencode 无 hook → 实为 `tool.execute.before` 插件(cite `harden-mgh-opencode-hook-parity`;引原话「误判 opencode「无 hook 能力」」)
- [x] 4.2 `opencode.json instructions` 省 token → 实为 eager 全装载(cite `improve-mgh-init-opencode-lazy-rules`)
- [x] 4.3 `::` 是 NTFS ADS 分隔符、写盘 errno 22(cite `harden-mgh-init-context-budget`;引 `core/scripts/list_clusters.py:128-133` + `tests/test_init_clusters.py:331-334`)
- [x] 4.4 opencode 插件进程不继承 mid-session env(`MGH_*_ACTIVE` 仅启动前就绪;cite `harden-mgh-init-shell-timeout` FD1 + `simplify-agents-r5` D4)
- [x] 4.5 章末收口:「动手前先验证平台事实」的可迁移提示

## 5. 可迁移清单 + 维护说明

- [x] 5.1 写「做新「大 skill」前置检查表」:该前置哪些约束、配哪些兜底(hook / `list_*` / `--check` / `--resume` / 原子写 / token 预算 / 双端 parity)、哪些必须 install 时就位而非靠 agent 自觉
- [x] 5.2 写「诚实边界」段:如实标注哪些护栏仍是**非确定性可测**(提示词级纯净性、opencode 惰性索引语义触发、LLM 判别),承 AGENTS.md 末段
- [x] 5.3 写「一次性分享快照」声明:本文非维护契约、未来可整份删除;**不**写回灌要求(对应 spec「一次性分享快照,不挂反向指针」)

## 6. 优化 docs/r5-plain-language.md(可读性 pass)

- [x] 6.1 通读全篇,标出半英半中 / 术语堆砌 / 未释义缩写处(如 `argparse`/`Usage:` docstring、`sys.path.insert(0, dir-of-__file__)`、`OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS`、`shell.ts::shellEnv`、RFC-2119、`Path.resolve()` 等)
- [x] 6.2 逐条规则改写:保留四要素(说什么 / 为什么 / 违反后果 / 兜底)结构与 R5.1–R5.10 编号;每条先用一句大白话开场,再上细节;长术语拆成「大白话 + 括号术语释义」
- [x] 6.3 文首补术语表:把重复出现的缩写集中释义(hook、subagent、AST、CLI、stdout/stderr、fail-loud / fail-soft、recipe、bright-line、RFC-2119 等)
- [x] 6.4 自检:**只改表述、不改语义、不删教训**(受 `agents-md-discipline` spec「R5 refactor safety」约束);`git diff` 确认无规则弱化或编号变动
- [x] 6.5 术语一致性:与 AGENTS.md R5 正文、新 `skill-dev-经验总结.md` 用词对齐(同一术语同释义)

## 7. 校验与收尾

- [x] 7.1 对照 spec 六条 Requirement 逐条自检(存在与定位 / 通病主线+cite / 含前提出错 / 边界不重复 / 非分发可引开发态 / 一次性分享快照不挂指针)
- [x] 7.2 承 R3 自检(两份文档):无长代码块(≤3–5 行)、表格优先、案例以 `文件:行号`/变更夹名索引、无寒暄废话
- [x] 7.3 通读一遍确认「大白话中文」基调(技术词首次给中文释义)、未参与本仓的工程师能独立读懂
- [x] 7.4 确认**未**在 README / docs 索引 / AGENTS.md 加任何指向 `docs/skill-dev-经验总结.md` 的指针(整份可删);`openspec validate add-skill-dev-experience-doc --strict` 通过
