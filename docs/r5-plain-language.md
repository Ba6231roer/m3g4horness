# R5 大白话版(development-only,不分发)

> 这是 `AGENTS.md` R5 段(「Agent 工具命令稳定性」铁律)的**人类/新人桥梁**。AGENTS.md 面向 AI、简练;本文面向人,把每条规则拆成**四要素**:这条**说什么** / **为什么**有这条 / **违反会怎样** / **哪个工具或 hook 兜底**。
>
> **不分发**:`docs/` 在 `tools/check_distributed_purity.py::SCAN_DIRS` 之外(见该文件 L52–62 注释),install 不装进目标项目。本文是研发仓内部文档。
>
> R5 管辖范围:**新增/修改任何对外分发的 `mgh-*.md` 命令壳 + 随 install 落地的 `core/scripts/*.py`**。`mgh-*` 像 openspec 的 `opsx:*`,装进**别人**项目当命令用 —— 稳定性是产品特性,不是可选优化。

## 怎么读 + 术语表

每条规则先用**一句话大白话**开场,再上细节。下面这些术语在全文反复出现,集中释义一次:

| 术语 | 大白话释义 |
|---|---|
| **agent / subagent** | agent = 跑这些命令的 AI(Claude Code / opencode);subagent(子 agent)= 由主 agent 派生、拥有独立上下文的子任务执行者。 |
| **编排器** | 把多阶段流水线串起来的东西。本仓的编排器**就是宿主 agent 自己**(按命令 `.md` 用自身工具跑),不是一段代码。 |
| **hook(钩子)** | 宿主在工具调用前后插入的自定义拦截逻辑。本仓用它在运行时拦下 agent 的越权操作。claude 侧是 `PreToolUse` 命令,opencode 侧是 `tool.execute.before` 插件。 |
| **CLI(命令行接口)** | 脚本接受参数(flag)的入口。本文里多指脚本支持哪些 `--flag`。 |
| **stdout / stderr** | 进程的两条输出流。stdout(标准输出)走结构化数据(本仓是 JSON);stderr(标准错误)走诊断/进度日志。**严格分流**,否则下游 JSON 解析会炸。 |
| **退出码 0 / 1 / 2** | 进程结束信号。0 = 成功;1 = 通用错误;2 = 误用(参数错、契约校验失败)。fail-loud = 出错立即非 0 退出并停止;fail-soft = 出错只警告、不阻断流程。 |
| **零运行时依赖** | 不需要 `pip install` 任何第三方包,只用 Python 标准库。内网可零联网运行,是产品特性。 |
| **AST(抽象语法树)** | 把源码解析成树状结构的内存表示。本仓用 AST 静态扫描来**机械验证「零依赖」**(扫描 `import` 语句)。 |
| **fan-out(扇出)** | 一项任务拆成多个并行子单元,每个 subagent 跑一个(如 mgh-init 的 T1 per-cluster、scout per-batch)。 |
| **recipe / prohibition** | recipe = 正引导(「该做什么」);prohibition = 禁令(「别做 X」)。R5.5 偏好 recipe,只有硬边界才用 prohibition。 |
| **bright-line(明线)** | 清晰、不留模糊空间的硬边界(如「零依赖」「跨格式产物不混」)。 |
| **RFC-2119** | 一组规范动词约定(`MUST/SHALL/SHOULD/MAY`),可被机器检测。本仓规则用 `MUST/SHALL` 取代口语「应该/可以」。 |
| **cwd(当前工作目录)** | 进程运行时所在目录。脚本要对**任意 cwd** 安全(无论从哪个目录被 `py` 启动)。 |
| **front matter / YAML 围栏** | 文件头部的 `---` 元数据块。opencode 命令定义用它,误抄 schema 字段名进去会触发纯净性 lint。 |
| **T1 / scout / T3** | mgh-init 的分层阶段标签:T1 = per-cluster 归纳;scout = 分批探查;T3 = per-category 出 rules。 |

---

## R5.1 契约单一真相源 + 机械化 lint

**一句话:脚本的命令行参数是唯一合同,命令壳和脚本两头必须一一对应。**

- **说什么**:脚本的命令行接口(CLI)是唯一合同。命令壳 `.md` 里写的调用示例必须跟脚本实际支持的 flag **一一对应**,不能多写、不能少写。agent 是靠跑 `--help`(帮助输出)学接口的(不读源码),所以 `--help` 就是合同面。
- **为什么**:壳里写了个脚本不存在的 flag,agent 照跑就报错;反之脚本改了 flag 壳没跟上,agent 还在用旧 flag。两头漂移 = 装进别人项目就炸。
- **违反后果**:目标项目里 agent 调 mgh-* 命令时 flag 对不上,流水线第一步就失败,且报错指向不存在的 flag,难排查。
- **兜底**:`tools/check_contracts.py` 自动提取双壳(claude + opencode)MD 里所有 `*.py --flag`,对每个 flag 跑 `py <script>.py --help` 断言存在。CI 必跑。

## R5.2 编排器 = 宿主 agent + 黑盒纪律

**一句话:「编排器」就是宿主 agent 自己,不是代码;别把它物化成 `.py`,别手搓微脚本内省,也别读叶子脚本源码。**

- **说什么**:"编排器"不是一段代码,就是宿主 agent 自己(Claude Code / opencode)按命令 `.md` 用自身工具跑流水线。所以**别把它物化成 `.py` 脚本**。三条明线 `NEVER`:
  - (a) 别 `Write`(写文件)任何 `.py` 编排器/包装器(反例:`mgh_init.py`);
  - (b) 别 `Write` 一次性微脚本(`py -c`(命令行直接跑 Python 代码)产物 / `_prep_*.py` / `_aggregate_*.py` / `<run>_helper.py`,以及用 `py -c` / `python -c` 内省或重派生产物去读 `.mgh-init/**`);
  - (c) 别 `Read`(读文件)叶子脚本 `.py` 源码进编排器上下文(报错看 stderr 就够,不读源码)。
  - **合法出口**:要工作清单 → `list_clusters` / `list_scout_batches` / `list_rule_jobs`;要瞄结构 → `describe_artifact.py`;要派生量 → 看产出者 stdout 字段。
- **为什么**:省上下文 + 防 agent 误改脚本 + 平台无关。真机首跑的失败,全是一次性微脚本内省造成的(不是大编排器)。
- **违反后果**:agent 上下文被脚本源码撑爆;或 agent 顺手"优化"了叶子脚本,破坏零依赖/契约;或微脚本写死路径在别的盘符/cwd 上炸。
- **兜底**:runtime hook(`block_adhoc_scripts.py`)+ `MGH_*_ACTIVE` 判运行域,越权 `Write`/微脚本/子树外写直接拦(fail-loud)。双端(claude `PreToolUse` + opencode `.ts` 插件)对等。

## R5.3 确定性脚本稳定性契约

**一句话:确定性脚本要「自包含、I/O 分流、扇出走枚举器、路径用绝对」——四条缺一不可。**

- **说什么**:三层。
  - (a) **runtime 自包含**:零运行时依赖(承 R2)、`sys.path.insert(0, dir-of-__file__)`(把脚本自身所在目录插到模块搜索路径,实现「兄弟导入」自定位)、读写一律 `encoding="utf-8"`、任意 cwd 能直接 `py`、别要 `python -c exec` 绕行。
  - (b) **CLI I/O 合同**:stdout = 结构化 JSON、stderr = 诊断/进度**严格分流**;退出码 `0/1/2`(成功/通用错/误用);幂等(create-if-not-exists);禁交互式 TTY(只吃 flag/env/stdin);闭集参数拒歧义输入 + 可操作报错;破坏性操作带 `--dry-run`;大输出默认摘要 + `--offset` 分页。
  - (c) **可恢复性** → 见 R5.4(长跑机制的权威表述;本条仅占位指针)。
- **扇出与路径(R5.3(b) 子项)**:所有 fan-out(扇出,见术语表)必须经 `list_*`/`describe_*` 脚本产 `pending[]` 清单(T1→`list_clusters`、scout→`list_scout_batches`、T3→`list_rule_jobs`),编排器对清单迭代,**绝不**直接挖 JSON / `py -c` 内省。`pending[]` 每项必须含 `checkpoint_path`(scout/T1)/ `rule_path`(T3)+ `done_marker`,且均 `Path.resolve()`(转成绝对路径)绝对(对 subagent 任意 cwd 安全,含 Windows 盘符相对)。编排器**逐字透传**、subagent **逐字写**,**绝不**自拼路径 / 用占位符(`<target>`/`<id>`)/ 写相对路径。`MGH_TARGET`(= discover `repo` 绝对根)供 hook 判树:运行域内 `Write`/`Edit` 的目标路径不在其子树 → fail-loud(退出码 2)。
- **为什么**:跨宿主(claude/opencode)+ 对任意 cwd 安全 + 防 Windows 盘符根漂移(真实失败形状:输出路径漂到 D 盘根)。
- **违反后果**:subagent 在不同 cwd 跑时路径解析错,产物写到盘符根或拼出无效路径;或 stdout 混进诊断文本,编排器 JSON 解析炸。
- **兜底**:脚本自验 + 回归测 `tests/`;`MGH_TARGET` 子树守卫 hook。

## R5.4 大仓可观测 + 长跑可恢复(权威处)

**一句话:扫大仓要「单遍、可中断、可续点」——软时限早退 + 编排器重派 `--resume`,绝不靠单次调用跑完。**

- **说什么**:扫大仓要单遍 I/O、每候选 O(1);进度走 `stderr`、产物 JSON 走 `stdout`(契约不变);扫之前先廉价计数,命中阈值前置建议 `--scope`+`--merge`(取代"跑满再超时");真要截断必须**显式告警并继续**。**长跑确定性 Bash SHALL 传 per-call `timeout`**(claude Bash / opencode shell 都接受毫秒级 `timeout`,会话内即时生效;opencode 的 `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS`(默认超时环境变量)默认 120000 但须**启动前**就绪)。`discover` 这类不假设单次调用跑完 —— `--time-budget-ms`(软时限)在安全边界落缓存 + 续点后 `exit 0` + stdout `partial:true`(部分完成标记),编排器 **Bash 重派 `--resume`** 推进直至 `partial:false`。**绝不**写 wrapper `.py` 循环(承 R5.2 黑盒)。
- **为什么**:跨宿主 + 零全损(不依赖单次调用跑完)+ 大仓不撑爆超时。
- **违反后果**:大仓跑到一半被超时 `SIGKILL`(强制杀死)→ 零产物零 checkpoint(历史上 `discover_controls.py` 单发不可恢复就是这个坑);或 agent 写了 wrapper `.py` 去轮询,违反黑盒纪律。
- **兜底**:编排器 Bash 纪律(per-call `timeout` + `--resume` 重派);`--time-budget-ms` 软时限 + cache/续点。

> 注:opencode 插件进程**不继承** mid-session(会话中途)bash 导出的 env(`shell.ts::shellEnv` 只读 `process.env` 不回写),故 `MGH_*_ACTIVE` / 超时 env 须 opencode 启动前就绪 —— 详见 R5.7 段 B「可靠性边界」。

## R5.5 指令性 MD 措辞(给 subagent 的提示词 / 命令壳纪律段)

**一句话:写给 subagent 的规则要「正引导优先、不留例外口子、用可机器检的动词、验收可证伪」——禁令清楚就不举例。**

- **说什么**:五条措辞纪律。
  - ① **shaping 失败用 recipe 不用 prohibition**:`Don't X`(别做 X)改写成"该做什么";只有**硬边界**(跨 format 产物不混、零依赖)才用 `NEVER`。
  - ② **禁 nuance/exemption 子句**(`Don't X unless…`(除非…)、"此限制不适用代码块")。
  - ③ 显式废对冲词 + RFC-2119 动词(`MUST/SHALL` 取代 `should/may`,机器可检)。
  - ④ 验收用可证伪清单 + schema 示例(非散文);命令行示例逐字可执行;无长代码块(承 R3)。
  - ⑤ **禁令清楚则不举例**:抽象规则醒目无歧义时,枚举反例是冗余;只在 agent 可能猜不到边界时才给最小反例。
- **为什么**:省 token + 防 agent 钻空子(exemption 子句)+ 让规则机器可检(RFC-2119)。
- **违反后果**:agent 抓住"unless…"子句乱发挥;或散文式验收让"完成"无法判定;或一堆冗余反例撑爆 token。
- **兜底**:提示词护栏 + R3(文档简练)。⑤ 是格式要点:别给已经清楚的禁令配反例。

## R5.6 命令壳薄壳 + token 硬预算

**一句话:命令壳 `.md` 越薄越好(≤500 行/≤5000 tokens),每次会话它都进上下文,胖壳 = 每次都浪费。**

- **说什么**:壳 `.md` 只放 编排流 + stage→组件表 + 确切确定性调用 + 边界披露;正文 ≤500 行 / ≤5000 tokens(Codex 硬上限 8KB;`description:` ≤1536 chars);详情移 `core/prompts/`(只深一级、按域分文件);禁 `@` 强制内联(改用 `REQUIRED SUB-SKILL: Use X` 标记);`--help`/无参 → 打印 flag 表并 STOP(花 token 前先校验)。
- **为什么**:壳本身每次会话都进上下文,壳胖 = 每次都浪费。
- **违反后果**:壳太大顶到 Codex 8KB 上限直接被拒;或 agent 没先 `--help` 校验就猛跑,flag 错了才发现。
- **兜底**:设计纪律 + `description:` 长度限制。

## R5.7 评估驱动 + TDD-for-docs / hook 强制闭环(同号两段)

**段 A — 评估方法论(TDD-for-docs)**:
- **一句话**:改提示词不能拍脑袋,要先建数据 baseline,blind A/B 对比才知道改好了还是改坏了。
- **说什么**:改 `core/prompts/**` 前先建 baseline(无该提示词跑 ≥5 次 capture 失败模式,variance(方差,这里指波动)是指标)→ blind A/B 对比 pass rate / tokens → 新命令由 A 实例写、全新 B 实例大仓首跑、观察漂移 → 新失败模式回灌本节。
- **为什么**:提示词改动不能拍脑袋,要有数据 baseline 才知道是改好了还是改坏了。
- **违反后果**:自测一两次"感觉挺好"就上线,真机大仓首跑发现漂移已晚。
- **兜底**:流程纪律(baseline + A/B + 全新实例首跑)。

**段 B — hook 强制闭环**:
- **一句话**:能用运行时 hook 强制的纪律,绝不写进 MD 靠 agent 自觉;每个命令的 #1 违例 MUST 配双端对等 hook。
- **说什么**:能用 hook 做确定性闭环的,不写进 MD 靠 agent 自觉。每个 `mgh-*` 命令的 #1 违例 MUST 配 runtime hook(install 时注入目标仓、**双端对等**):claude = `.claude/settings.json` 的 `PreToolUse`;opencode = `.opencode/plugins/` 的 `tool.execute.before` `.ts` 插件(opencode 的 hook 面即 JS/TS 插件,**移植缺口非能力缺口**)。`.ts` 插件是 opencode 宿主原生胶水(自带 Bun 运行、**非 `pip` 依赖**,类比 claude 的 settings.json hook 配置),仅做事件归一化 + 管道 + 据退出码阻断;**判定逻辑单一来源在 Python 标准库守卫 `block_adhoc_scripts.py`**(双端字节级 parity(对等)守卫,`tests/test_opencode_hook_parity.py`)。hook 缺席 = CI fail(对齐 R5.8)。当前兑现:`block-adhoc-scripts`(四运行域 `MGH_{INIT,SAST,SRA,SRR}_ACTIVE`)。
- **可靠性边界(opencode)**:opencode 插件进程**不继承** mid-session(会话中途)bash 导出的 env(`shell.ts::shellEnv` 只读 `process.env` 不回写),故 `MGH_*_ACTIVE` 仅在 opencode 启动时就绪才激活守卫;未激活时 fail-soft,纪律由命令壳明线 + R5.9 边界校验兜底。
- **为什么**:纪律靠 agent 自觉 = 一定会被违反;要运行时强制。双端对等是为了 claude/opencode 体验一致。
- **违反后果**:没 hook,#1 违例(微脚本内省/越权 `.py`/子树外写)在目标项目里照样发生,没人拦。
- **兜底**:双端 runtime hook + CI(hook 缺席 = CI fail)。

## R5.8 安装自检 + 回归单测

**一句话:install 装进别人项目,装坏了是产品事故——所以 install 自检 + 回归测兜底,版本号追踪每次改动。**

- **说什么**:`install.sh` 镜像后校验脚本族同目录共存 + fail-soft(自检失败只 warn 不阻断 install,CI 必 fail);任何 `.md`/脚本改动 bump 版本号;回归测覆盖 契约等价 / 导入鲁棒(非脚本目录 cwd 子进程)/ 性能不退化 / 零依赖 AST 扫描 / R5.1 CLI lint。
- **为什么**:install 装进别人项目,装坏了是产品事故,但也不能因为目标环境小毛病就阻断 install(故 fail-soft,CI 兜底)。
- **违反后果**:install 后脚本缺兄弟文件 / 导入路径在目标 cwd 下解析错 / 偷偷引入了 pip 依赖,目标项目一跑就炸。
- **兜底**:`install.sh` 自检 + `tests/` 回归测 + 版本号 bump 追踪。

## R5.9 边界校验泛化(承 openspec validate-at-boundary)

**一句话:每个 stage 的产出者都要暴露 `--check`,编排器跑完一步、进下一步前必校验,失败就回退——绝不带着破损产物继续。**

- **说什么**:每个 stage 产物的产出者 MUST 暴露 `--check`(或独立 validator,如 `validate_inventory.py`);编排器跑完一步、进下一步前 MUST 运行之,失败 fail-loud(退出码 2)回退重跑,**绝不带着破损产物继续**。当前覆盖:`discover_controls`/`plan_scout`/`merge_scout` `--check` + `validate_inventory.py` + `prefilter`/`dedup`/`emit_sarif` `--check`(/mgh-sast)+ `prepare_augment`/`merge_augment`/`merge_memory` `--check`(/mgh-sra)+ `ingest_requirements`/`render_report` `--check`(/mgh-srr)。
- **为什么**:上游产物破损会污染下游所有 stage,越往后越难定位;在每个 stage 边界校验,早发现早回退。
- **违反后果**:带着破损 inventory/scout 产物继续跑,下游 rules 全是垃圾,最后才发现要从 T1 重跑。
- **兜底**:各产出者 `--check` + 退出码 2 + 编排器"跑完一步必校验"纪律。

## R5.10 分发产物纯净性

**一句话:装进目标项目的 md 只放操作性内容,绝不带本仓研发态的悬空引用(规则号、变更夹名、内部文档等八类)——否则在别人项目里指向不存在的东西,误导 agent。**

- **说什么**:经 `install.sh` 装入目标项目的 md(命令壳 / agent 定义 / stage 提示词 / I/O 契约 / skills)MUST 仅含对目标 agent 有用的操作性内容,**绝不**携带只在本仓研发语境才有意义的悬空引用 —— 在目标项目里它们指向不存在的手册/编号/文件,浪费 token 且误导 agent。禁引完整**八类**:① 研发铁律编号(`R5.x`/`R3`/`R1–R4`);② 失败/发现 ID(`FDn`);③ 设计决策 ID(`Dn`,含 `D9 = D12` 形态);④ openspec 变更夹名(`(add|fix|harden|improve|purify)-mgh-(init|sast|sra|blst)-…`);⑤ 内部上游文档(`glasswing_docs/`);⑥ 仓根开发态文件指针(`task.*.md`,install 不分发);⑦ dev-meta 措辞(`承/兑现 R5.x`、`范式锚点`、指本研发仓时的"本仓");⑧ 上游溯源行话作谱系归因(`vvah`/`design_controls` 当归因词,非操作性 schema 字段)。按「删或嫁接」处理:目标不需要 → 删标记/引用句;目标必需 → 把最简 1–2 行内容内联到恰当位置再删指针(省 token 优先,**绝不**整段搬运)。**保留**操作语义与输出产物路径(`--check`/退出码 2/`<target>/AGENTS.md`/runtime 脚本调用 `.claude/mgh-core/scripts/*.py`/阶段标签 `T1`/`s1`..`s9`)。**受保护归因**(`core/prompts/**` 头的 `Source: vvaharness/...`、skills Apache 归因、`core/docs/prompt-provenance.md`、操作性 `design_controls`、`CVE-*`)不在禁列,**绝不**当 dev-only 溯源剥除。
- **为什么**:省 token + 防目标项目误读(目标项目常有自带 `AGENTS.md` 与无关编号)+ 平台无关。
- **违反后果**:目标项目里的 mgh-* 命令壳出现 `承 R5.7`、`范式锚点`、`task.260630.md` 之类的悬空引用,agent 去找这些不存在的文件/手册,浪费 token 还走偏。
- **兜底**:前 7 类 + dev-meta(`承/兑现`/`范式锚点`)由 `tools/check_distributed_purity.py` 确定性强制;第 8 类与"本仓"与受保护归因同形、机器难辨,由提示词护栏 + 人工清理覆盖(install 自检 fail-soft、CI 测 `tests/test_distributed_md_purity.py` 必 fail)。

---

## 附:R5 强制面索引(哪条规则由什么兜底)

| 规则 | 强制机制 | 入口 |
|---|---|---|
| R5.1 契约 lint | 机械化 flag 存在断言 | `tools/check_contracts.py` |
| R5.2 黑盒纪律 | runtime hook 阻断越权 Write/微脚本 | `block_adhoc_scripts.py` + `MGH_*_ACTIVE` |
| R5.3 脚本稳定性 | 自包含 + I/O 契约(脚本自验) | 回归测 `tests/` |
| R5.4 长跑可观测 | per-call `timeout` + `--resume` 重派 | 编排器 Bash 纪律 |
| R5.7 hook 闭环 | 双端 runtime hook + CI | `block_adhoc_scripts.py` + CI |
| R5.8 自检 + 回归 | install 自检 + 回归测 | `install.sh` + `tests/` |
| R5.9 边界校验 | `--check` fail-loud(exit 2) | 各产出者 `--check` |
| R5.10 分发纯净 | purity lint | `tools/check_distributed_purity.py` |
