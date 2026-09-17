# 大 skill 开发经验总结(团队内部分享)

> 一句话定位:这是 m3g4h⊿rness 做「大 skill」(多角色 subagent + 确定性工具脚本 + 编排)过程中踩过的坑和沉淀的兜底,**面向没参与过本仓的工程师**,目标是让你做下一个 agent 工具链 / 复杂 skill 时能直接复用这些约束,而不是重新踩一遍。
>
> **这不是维护契约**,是一次性分享快照,未来可整份删除(详见文末)。本仓内部文档,**不分发**(install 不装进目标项目),故可自由引用 R5.x / FDn / 变更夹名等开发态标识。

## 与现有文档的边界(先读这段,免得重复)

| 文档                          | 讲什么                         | 与本文关系                          |
| --------------------------- | --------------------------- | ------------------------------ |
| `README.md`                 | 对外用户怎么用 mgh-* 命令            | 本文不讲用法                         |
| `docs/r5-plain-language.md` | R5.1–R5.10 逐条规则的「大白话四要素」    | 本文讲**规则的来历**(被哪次失败逼出来),不复述规则正文 |
| `docs/mgh-*-工作流程详解.md`      | 各命令流水线节点怎么走                 | 本文不讲流水线节点                      |
| **本文**                      | 规则的**来历 + 大模型通病归因 + 可迁移清单** | 互补,不重叠                         |

## 怎么读 + 术语表

通读即可。每个「通病」按**四要素**写:**通病**(大模型的什么可复现行为)→ **案例**(本仓哪次真实迭代撞上,cite 变更夹名)→ **机制**(沉淀出的兜底)→ **可迁移**(你做新 skill 时该前置什么)。

> **诚实声明**:通病归因是**团队回溯性解读**——我们把失败归结到「大模型的某条通用特性」上,便于迁移;它不是 LLM 厂商或上游(vvaharness)的原始结论。每个案例都 cite 真实变更夹名 / `AGENTS.md` 规则号 / `文件:行号`,可回溯核实。

术语表(与 `r5-plain-language.md` 同释义):

| 术语 | 大白话 |
|---|---|
| agent / subagent | agent = 跑命令的 AI(Claude Code / opencode);subagent = 主 agent 派生的、独立上下文的子任务执行者 |
| 编排器 | 把流水线串起来的角色。本仓的编排器**就是宿主 agent 自己**,不是代码 |
| hook(钩子) | 宿主在工具调用前后插入的拦截逻辑。claude = `PreToolUse`;opencode = `tool.execute.before` 插件 |
| 零运行时依赖 | 不 `pip install` 任何第三方包,只用 Python 标准库(产品特性,内网零联网) |
| AST(抽象语法树) | 源码的树状内存表示,本仓用 AST 静态扫描验证「零依赖」 |
| fan-out(扇出) | 一项任务拆成多个并行子单元,每个 subagent 一个 |
| recipe / prohibition | 正引导(「该做什么」)/ 禁令(「别做 X」) |
| bright-line(明线) | 清晰不留模糊的硬边界 |
| RFC-2119 | 规范动词约定(MUST/SHALL/SHOULD/MAY),可机器检测 |
| fail-loud / fail-soft | 出错立即非 0 退出并停止 / 出错只警告不阻断 |
| stdout / stderr | 标准输出(走结构化 JSON)/ 标准错误(走诊断日志),严格分流 |
| cwd | 当前工作目录,脚本要对任意 cwd 安全 |
| T1 / scout / T3 | mgh-init 的分层阶段标签 |

---

## 第一部分:大模型通病(本仓撞上的 8 条)

### 通病① 过度热情 codegen + 触发词误读

- **通病**:LLM 看到「implement / 实现」这类词,默认动作是**真去写代码**;给它编排任务,它倾向于把编排器物化成一个 `.py`。这是 codegen 训练的本能——「写代码」是它最熟练的输出。
- **案例**:本仓第一次真机大仓首跑(opencode 跑 21,611 文件的 Java 仓),编排器把叶子脚本 `.py` 源码 `Read` 进上下文、还尝试 `python -c "exec(...)"` 绕行,引发 5 个级联故障。`fix-mgh-init-stability` 的 **FD7** 把这条从「弱信号黑盒提示」升级为「正文首条硬铁律 + 具名反例 + 角色澄清」(原话:「FD5 的『黑盒』是被忽略的弱信号;FD7 把它升级为正文首条硬铁律」)。
- **机制**(→ R5.2):三条明线 `NEVER`——别 `Write` `.py` 编排器、别 `Write` 一次性微脚本、别 `Read` 叶子脚本源码。编排器**就是宿主 agent 自己**,按命令 `.md` 用自身工具(Bash 调脚本、Agent 派 subagent)跑。
- **可迁移**:新 skill 的命令壳顶部**显式声明「编排器 = 宿主 agent,非代码」**,并给出 agent 真会写的反例形状。措辞上**用「执行/跑」替代「implement」**(trigger 词易诱发 codegen)。

### 通病② 禁令打错失败形状(本档最高杠杆教训)

- **通病**:你写「别做 X」,agent 做的是 Y;只要 Y 和 X 字面不模式匹配,禁令就**完全失效**。禁令必须落在 agent **真实会写的形状**上,不能落在你以为它会写的形状上。
- **案例**:本仓先禁了 `mgh_init.py`(大编排器)。结果真机首跑里 agent 一个大编排器都没写——它写的是 `py -c "import json …"`、`_prep_scout_batches.py`、`_aggregate_scout.py` 这些**一次性微脚本**。旧禁令 `grep -niE "py -c|内省|introspect" AGENTS.md` **零命中**——规则根本没落在真实失败上。`harden-mgh-init-orchestration-discipline` 的 **FD1** 标题就是「失败形状错配是根因(非规则不够)」。
- **机制**(→ R5.5①):明线从「别写 `mgh_init.py`」改成「别写 `py -c` 产物 / `_prep_*.py` / `_aggregate_*.py` / `<run>_helper.py`」(agent 真会写的形状)+ recipe「该做什么」(合法出口:`list_*` 取清单、`describe_artifact.py` 瞄结构、产出者 stdout 取派生量)。配 runtime hook 真拦。
- **可迁移**:**每次加禁令前先 grep 既有规则,看它禁的形状和真实失败形状是否对得上**。禁令要落在 agent 真实输出的字面模式上(recipe 优先,只有硬边界才 prohibition)。

### 通病③ 没有合法内省出口 → 手搓 `py -c`

- **通病**:agent 需要某个派生量(「待跑单元清单」「簇数」),但**没有现成脚本给它**,它就手搓 `py -c` 或临时微脚本去挖 JSON——而手搓内省没有契约,会犯低级错(对包装字典顶层 `len()`)。
- **案例**:T1 扇出时编排器要数簇,手搓 `len(c)=3`(顶层包装字典的键数),实际簇数是 `len(c["clusters"])=360`;又因缺合法清单出口,被迫写 `_prep_scout_batches.py` 填真实脚本的空洞(`fix-mgh-init-cluster-fanout` D1–D4、`harden-mgh-init-orchestration-discipline` FD3)。
- **机制**:`list_*` 枚举器模板(`list_clusters` / `list_scout_batches` / `list_rule_jobs`)——产出带 `total/done/pending[]` 的权威清单;`describe_artifact.py` 提供「合法 peek」瞄结构;派生量走产出者 stdout 字段。编排器只对清单迭代,**禁挖 JSON / 禁 `py -c`**。
- **可迁移**:新 skill 凡是要 fan-out 的层,**先备好 `list_*` 枚举器**(产 pending 清单 + 每单元确切输出路径),别留空洞让 agent 自己填。

### 通病④ 路径 / 任意 cwd 漂移到盘符根

- **通病**:输出路径写成「模板」(占位符 / 相对路径),**两个 agent 各拼一次**(编排器传、subagent 收),任一处 cwd 错位就漂移——本仓实测漂到 Windows D 盘根。
- **案例**:3b/scout、T1、T3 的 subagent 偶尔把 checkpoint 写到项目目录之外(盘符根)。根因:路径在提示词里是 `<target>/.../<id>.json` 占位符,枚举脚本 stdout 也没给绝对路径(`harden-mgh-init-fanout-output-paths` FD1–FD5)。原话:「路径是『模板』不是『值』——占位符 / 相对路径要被两个 agent 各拼一次,任一处 cwd 错位即漂移」。
- **机制**(→ R5.3(b)):枚举脚本 stdout 每项含 `checkpoint_path` / `rule_path`(均 `Path.resolve()` 绝对);编排器**逐字透传**、subagent **逐字写**,**禁自拼路径 / 禁占位符 / 禁相对路径**;`MGH_TARGET`(= 目标仓绝对根)供 hook 判树,运行域内 `Write`/`Edit` 目标不在子树 → fail-loud(退出码 2)。
- **可迁移**:fan-out 的输出路径**只能由确定性脚本以绝对值产出**,提示词里 NEVER 出现占位符或相对路径;配一个「子树守卫」hook 拦越界写。

### 通病⑤ 上下文有限 + 整份读聚合

- **通病**:弱模型会把聚合产物**整份读进编排器上下文**(如 `ReadAllBytes` 一个 426KB 的清单),把后续每个 LLM 请求都顶过窗口上限。
- **案例**:opencode 宿主 agent(DeepSeek-V4-Flash)把 `.mgh-init/t1_pending.json`(426KB)整份读进上下文,后续请求全超窗口。根因是契约空洞(枚举脚本只回 *lite* 外壳,但阶段提示词要 *full* 记录)+ 全程无阈值(`harden-mgh-init-context-budget` D1–D8)。
- **机制**:按单元物化有界输入——`list_*` 加 `--materialize` 把每单元 full 输入写到 `<target>/.mgh-init/inputs/<tier>/<unit>.input.json`,subagent 读自己的 `input_path`(编排器只传路径);`--max-unit-bytes` / `--orch-budget-bytes` / `--max-aggregate-bytes` 三级字节预算 + `--offset/--limit` 分页。
- **可迁移**:凡是 fan-out + 聚合的流水线,**把「整份读聚合」从结构上变不可能**(每单元独立输入文件 + 路径传递 + 字节阈值),而不是靠提示词劝。

### 通病⑥ 单发不可恢复 + 默认超时墙被 SIGKILL

- **通病**:长跑脚本若「单发不可恢复」(跑完才在末尾写产物),被宿主默认超时 `SIGKILL` 后,**零产物零 checkpoint**,`--resume` 也无从续起。
- **案例**:opencode shell 默认超时(实测约 60s / 官方 120s)`SIGKILL` 了 `discover_controls.py`(walk→index→callgraph→scan 全跑完才在 `main()` 末尾写产物)。结果零产物,stderr 进度被宿主吞,用户只看到 `(no output)`。Claude Code Bash 同样 120s 墙(`harden-mgh-init-shell-timeout` FD1–FD8)。
- **机制**(→ R5.4):原子写(`.tmp`+`os.replace`)+ callgraph 缓存(mtime 失效)+ scan 续点 + 软时限 `--time-budget-ms`(安全边界干净早退:**退出码 0** + stdout `partial:true`)+ 编排器 per-call `timeout` + Bash 重派 `--resume` 推进至 `partial:false`。
- **可迁移**:长跑脚本**必须支持「跨多次调用零全损推进」**(缓存 + 续点 + 软时限早退);编排器 **Bash 重派推进**,NEVER 写 wrapper `.py` 轮询。

### 通病⑦ LLM 产物可畸形

- **通病**:LLM 产出的 JSON 会**丢字段**或**非法转义**(证据片段里嵌原始代码),消费侧若直接索引或裸 `json.loads` 就抛 traceback。
- **案例**:`merge_scout.py` 在两种畸形 `scout_candidates.json` 上崩溃:① 缺 `category`(`--check` 只校验了 `source/file/line`,放行后 `_normalize` 直接索引 → `KeyError`);② 非法 JSON(`--check` 返回**退出码 1 而非 2**,编排器闸门只对 2 回退,放行进 `main()` 裸 `json.loads` → `JSONDecodeError`)(`fix-mgh-init-scout-merge-robustness` D1–D6)。
- **机制**(→ R5.9):`--check` 覆盖关键字段(category 非空)+ **broken-JSON 退出码 1→2**(对齐编排器闸门)+ 消费侧 `try/except` 兜底(结构化错、无 traceback)+ 生产侧提示词把畸形**结构上变不可能**(强制 `category` 必在、`evidence_snippet` 单行安全子串)。**三层闭环**:边界校验 + 消费兜底 + 生产避免。
- **可迁移**:每个 stage 边界 `--check` 校验 + 退出码语义对齐(误用/校验失败一律 2)+ 消费侧兜底 + 生产侧在提示词里把畸形形状禁掉。

### 通病⑧ 纯净性逐轮出新形状(每堵一洞,LLM 找新洞)

- **通病**:你禁一类泄漏,LLM 下一轮就换一类形状泄漏——纯净性是**逐轮军备竞赛**,单次清理挡不住。
- **案例**:① 先堵工具名/脚本名/层级词泄漏(`fix-mgh-init-rules-purity` D1–D5);② 下一轮冒出 schema 字段名被抄成 YAML front matter(`---category:…---`)、扫描器过程散文、「控制缺失」散文(`fix-mgh-init-opencode-agents-md-noise` D1–D5);③ 再把研发态悬空引用(R5.x / FDn / 变更夹名 / `task.*.md` / `承 R5.x`)系统化禁掉(`purify-distributed-md` D1–D9,审了 ~92 个 md、~76 处修)。
- **机制**(→ R5.10):`tools/check_distributed_purity.py` 高精度 token lint(确定性强制 7/8 类)+ 提示词护栏(第 8 类与受保护归因同形、机器难辨,靠人工)+ 「删或嫁接」处理规则。
- **可迁移**:分发产物的纯净性**必须有确定性 lint 兜底**,不能只靠提示词;且 lint 要持续扩高精度 token(每轮新形状回灌)。区分「受保护归因」(`Source:` / Apache / CVE,**不删**)与「dev-only 溯源」(R5.x / FDn,**删**)。

---

## 第二部分:「前提出错」专章(最高教学价值)

> 这一章全是「我们一直以为是 A,查了才发现是 B」。这类错误最令人谦卑,也最能教会**动手前先验证平台事实**。

### 前提① 误判「opencode 无 hook」——实为 `tool.execute.before` 插件

- **出错前提**:之前以为 opencode 没有 hook 能力,所以 `block-adhoc-scripts` 守卫只注入了 Claude Code,opencode 侧降级成「install 时 warn+skip」。
- **查证纠正**:为 `add-mgh-telemetry-seam` 查 opencode 官方插件文档时发现——**opencode 有 hook**,机制是 `.opencode/plugins/*.ts` 插件订阅 `tool.execute.before`(可阻断,等价 Claude 的 PreToolUse)。原话:「**opencode 有 hook 机制**……此前本仓**误判 opencode『无 hook 能力』**」(`harden-mgh-opencode-hook-parity` D1–D7)。
- **机制**:写薄 `.ts` 垫片把 opencode 事件归一化成 Claude PreToolUse stdin,管道给**同一个** `block_adhoc_scripts.py`(判定逻辑单一来源、双端零漂移);install 从「warn+skip」改成真注入。
- **可迁移**:**别据「记忆」断言某宿主缺某能力**——查官方文档 / 实测。能力缺口和移植缺口要分开(移植缺口 = 换个等价机制,不是真没有)。

### 前提② 误以为 `opencode.json instructions` 省 token——实为 eager 全装载

- **出错前提**:以为把详述规则文件列进 `opencode.json` 的 `instructions` 能按需加载、省 token。
- **查证纠正**:opencode 文档明示 "All instruction files are combined with your `AGENTS.md`"——**eager 全量并入**,启动即装载,**不省上下文**。D1 直接否决该方案:「eager 全量并入,不省上下文,违目标」。**只有手动 `@file` 懒加载才真按需**(`improve-mgh-init-opencode-lazy-rules` D1–D6)。
- **机制**:opencode 受管块从「全量内联」改成「简洁索引(分类清单 + `@<rel-path>` + 懒加载指令)」,规则正文移到 `<target>/docs/security-controls/<cat>.md`,靠手动 `@` 引用按需加载。
- **可迁移**:别假设宿主某个配置字段的语义符合直觉——**读它的加载模型文档**(eager vs lazy 差一个数量级的 token)。

### 前提③ `::` 是 NTFS ADS 分隔符——写盘 errno 22

- **出错前提**:`<cid>::shard-<n>` 这种带 `::` 的单元 id 当文件名写盘,以为没问题。
- **查证纠正**:`::` 是 NTFS 的 **Alternate Data Stream(备用数据流)分隔符**,Windows 上写盘直接 errno 22 失败。这是 `harden-mgh-init-context-budget` **实现期**才发现的(D4 引入 `::shard-<n>` id,D1 物化成文件名时撞上)。守卫见 `core/scripts/list_clusters.py:128-133` 的 `_safe_name`(`/ \ :`→`_`),测试见 `tests/test_init_clusters.py:331-334`。
- **机制**:文件名经 `_safe_name` 消毒;**规范 id 保留原样**(作 envelope 身份 + checkpoint `unit` 字段),只对**输入文件名**编码。
- **可迁移**:凡 id 派生文件名的写盘路径,**消毒 `/ \ :`**(尤其 Windows);消毒只作用在文件名,id 本身不动。

### 前提④ opencode 插件进程不继承 mid-session env

- **出错前提**:以为会话中途 `export MGH_*_ACTIVE=1` 能让 opencode 的 hook 守卫立刻生效。
- **查证纠正**:opencode 插件进程**不继承** mid-session bash 导出的 env(`shell.ts::shellEnv` 只读 `process.env` 不回写)。bash 的 `export` 只影响子进程,不回写 opencode 主 `process.env`。所以 `MGH_*_ACTIVE` / 超时 env **只在 opencode 启动前就绪才激活**守卫(`harden-mgh-init-shell-timeout` FD1 + `harden-mgh-opencode-hook-parity` 风险段 + `simplify-agents-r5` D3/D4 段 B)。
- **机制**:设计上优先 **per-call `timeout`**(跨宿主主杠杆,不依赖 env 继承);env 依赖项降级为「须启动前就绪」,未激活时 fail-soft(命令壳明线 + R5.9 边界校验兜底)。
- **可迁移**:别假设宿主插件进程会继承会话中途的 env——**优先用「每次调用显式传参(per-call flag/timeout)」这种不依赖隐式状态的控制面**。

### 章末收口:动手前先验证平台事实

这四条共性是:**凭记忆/直觉断言平台能力或语义,结果错了**。迁移到新 skill 的工作方式:涉及宿主能力(hook 事件、加载模型、env 继承、文件系统限制)的任何前提,**先查官方文档或实测**,别直接采信既有记忆。这条比任何单条规则都值钱。

---

## 第三部分:两条「纪律类」通病

### 通病⑩ 上游引用保真(移植类 skill 的溯源纪律)

- **通病**:从上游(vvaharness)移植提示词/逻辑,容易随手改、丢溯源,后续无法判断「这段是上游原样还是本仓改的」。
- **案例**:`/mgh-sast` 全程移植 vvaharness 9 阶段流水线——逐字移植 LLM 阶段提示词、确定性阶段零依赖重写、不 import 上游代码。逐项映射(条目 → vvah 来源 → 保真度)见 `docs/upstream-index.md`,这是本仓的同步锚点。
- **机制**(→ R1):`core/prompts/**` 每个 `.md` 头部留 `Source: vvaharness/...` 溯源注释(有意保留、**不删**);重抽用 `tools/extract_prompts.py`,不手改正文;`docs/upstream-index.md` 是同步锚点。
- **可迁移**:移植类工作**给每个移植件标溯源 + 提供重抽工具**,改逻辑走受管流程,不手改上游正文。

### 通病⑪ 同代命令不自动继承硬化

- **通病**:给 A 命令加了硬化,它**不会自动**出现在同代的 B 命令上——B 会**原样复现** A 已修过的失败。
- **案例**:mgh-init 硬化后(`harden-mgh-init-orchestration-discipline`),mgh-sast **原样复现 FD1**(无「编排器 = 宿主 agent」声明、无三条 NEVER、无枚举脚本、无 `--check`、hook 只在 `MGH_INIT_ACTIVE` 下激活)。`harden-mgh-sast-orchestration-discipline` FD1–FD8 把同一套 5 层防御**横向复制**过去(同 hook、同 regex、同白名单,只扩 `MGH_SAST_ACTIVE` 域),**不动移植正文**(承 R1)。
- **机制**:硬化纪律做成**可横向复制的覆层**(声明 + 三条 NEVER + 枚举脚本 + hook 域扩展 + `--check` + subagent 合法工具),新同代命令接入时整套搬。
- **可迁移**:做出一条硬化,**主动检查所有同代命令是否复现同一失败**,把硬化模板化、横向复制;别假设「修了 A 就等于修了 B」。

---

## 做新「大 skill」前置检查表

> 做新 agent 工具链 / 复杂 skill 前,过一遍这张表。**install 时就位的项**(靠 hook/契约/CI,不靠 agent 自觉)标 ⚙️。

| 类别 | 前置项 | 对应通病/规则 | install 就位? |
|---|---|---|---|
| 编排定位 | 命令壳顶部显式声明「编排器 = 宿主 agent,非代码」+ 具名反例 | ① / R5.2 | 否(措辞) |
| 合法出口 | 凡 fan-out 层,备好 `list_*` 枚举器(pending 清单 + 每单元绝对输出路径)+ `describe_*` peek | ③ / R5.3(b) | 是(脚本) |
| 路径绝对 | 输出路径只由脚本以**绝对值**产出;提示词 NEVER 占位符/相对路径 | ④ / R5.3(b) | 是(脚本 + 子树守卫 ⚙️) |
| 黑盒纪律 | runtime hook 拦越权 `Write`/微脚本/子树外写(双端对等) | ①② / R5.2 | 是 ⚙️ |
| 契约 lint | 命令壳 flag 与脚本 `--help` 一一对应,`check_contracts.py` 强制 | R5.1 | 是(CI) |
| 薄壳预算 | 命令壳 ≤500 行/≤5000 tokens,详情下沉 `core/prompts/` | ⑤ / R5.6 | 否(设计纪律) |
| 边界校验 | 每个 stage 产出者暴露 `--check`,退出码 2 对齐编排器闸门 | ⑦ / R5.9 | 是(脚本) |
| 长跑可恢复 | 缓存 + 续点 + 软时限早退(`partial:true`/退出码 0);per-call `timeout` + `--resume` 重派 | ⑥ / R5.4 | 是(脚本 + Bash 纪律) |
| 上下文预算 | 按单元物化输入 + 字节阈值 + 分页,「整份读聚合」结构上变不可能 | ⑤ | 是(脚本 + 契约) |
| 纯净性 | 分发产物确定性 lint + 提示词护栏,持续扩高精度 token | ⑧ / R5.10 | 是(lint ⚙️ + CI) |
| 安装自检 | `install.sh` 镜像后校验脚本族共存(fail-soft,CI 兜底)+ 版本号 bump | R5.8 | 是(install + CI) |
| 双端对等 | claude / opencode 行为对等(hook、加载模型);查证宿主能力别凭记忆 | 前提①②④ | 是(双端 hook ⚙️) |
| 平台事实 | 涉及宿主能力/文件系统/env 继承的前提,动手前查官方文档/实测 | 前提①–④ | 否(工作方式) |
| 上游溯源 | 移植件标溯源 + 重抽工具 | ⑩ / R1 | 否(纪律) |
| 同代继承 | 硬化模板化,横向复制到所有同代命令 | ⑪ | 否(纪律) |

**核心判断**:能用 hook / 契约 / lint 做**确定性闭环**的,绝不写进 MD 靠 agent 自觉(承 R5.7 段 B)。agent 自觉 = 一定会被违反。

## 诚实边界(哪些护栏仍是非确定性可测)

承 `AGENTS.md` 末段,如实标注以下护栏**仍是概率性的、非确定性可测**:

- **提示词级纯净性**:第 8 类(dev-only 溯源 vs 受保护归因)与裸通用词(`category`/泛指「锚点」)与裸层级词(`T1`/`scout`)机器难辨,靠提示词护栏 + 人工,lint 只覆盖**高精度形状**。
- **opencode 惰性索引的语义触发**:opencode 无路径作用域,按需加载是**语义性**的(索引块指令驱动,非路径自动触发)——agent 若跳过对应 Read 可能漏掉控制。claude 侧 `paths:` 路径作用域为确定性触发。
- **LLM 判别本身**:发现/归纳/规则写作仍是 LLM 非确定输出,需人工复核;「存在 ≠ 有效」永远成立。

确定性可强制的部分(hook 拦截、`--check` 退出码、契约 lint、纯净性 lint、`--resume` 续点)是**硬护栏**;其余是**软护栏**(提示词 + 纪律),会漂移。

## 一次性分享快照声明

本文**不是维护契约**,是一次性团队分享快照,未来可整份删除。**不在** `README.md` / docs 索引 / `AGENTS.md` 建立任何反向指针——这样未来删除不留断链。本文**不需要**随 R5 迭代回灌(无回灌要求)。规则的正文本体在 `AGENTS.md` R5 + `docs/r5-plain-language.md`,本文只讲来历与通病。
