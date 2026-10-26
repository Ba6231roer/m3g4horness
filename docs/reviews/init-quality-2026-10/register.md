# mgh-init 产出质量评审 · 缺陷登记册

> **受众:人类 + agent(双受众)**。本登记册是评审战役的集中台账:每条带问题描述、
> 根因分类(A 模型能力边界 / B 提示词与契约设计 / C 输入切片与信息保真 / D 校验硬度
> 缺口 / E 确定性脚本缺陷)、证据等级([S] 静态推断 / [L] 本机实证 / [E] 企业实证)、
> 状态。评审会话只往里加和核实;修复提案从本册取([L]/[E] 优先)。
> 预置 11 项(2026-10-23 补 #8–#11:锚点/引文无校验、T4 无复检、声明式配置扫描面缺失〔条件项〕、
> 企业模型执行保真失败〔[E] 手抄观测〕)。
> 计划与纪律见
> [评审计划](../../mgh-init-output-quality-review-plan-2026-10-22.md) 与
> [交接文档](../../mgh-init-output-quality-review-handoff-2026-10-22.md)。

| # | 日期 | 阶段 | 问题(自包含描述) | 等级 | 根因类 | 来源锚点 | 状态 | 处置 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-10-21 | T1(pack) | 打包形态的真实会话中,2/11 的 pack 会话违反共享任务模板,额外写了「包级账本 JSON」文件(模板至今无明示禁令;下游把它当垃圾产物) | [E] | B | `openspec/changes/archive/2026-10-21-fix-mgh-init-native-aggregate-dispatch/real-machine-notes.md` §2;模板 `core/prompts/fragments/fanout/t1-task.md` | 未修 | 可提前立项:模板补一条禁令 + 闸门豁免 |
| 2 | 2026-10-21 | T1→T2 闸门 | `validate_t1_records.py` 用 `*.json` 通配收集记录文件,把 #1 的包级账本误读为记录,产生 13 个假违例(退出码 2,误伤外科重派) | [E] | E | 同上;`core/scripts/validate_t1_records.py`(glob 收集处) | 未修 | 可提前立项:收集面排除账本形状或按命名豁免 |
| 3 | 存量 | T3/assemble | 纯净 lint 只覆盖高精度形状(工具内部 token/schema 字段/特征散文);裸通用词、裸层级词、通用脚本名的泄漏非确定性可测,仅提示词护栏 | [S] | D | 根 `AGENTS.md` 诚实边界 | 已披露未修 | C8 评审「终门扩容候选」时一并核 |
| 4 | 存量 | scout-merge | 超字节预算分片时,`evidence_snippet` 等人读字段被确定性截断(锚点不截,`_slimmed` 留痕);摘要可能丢失 competing 成员信息 | [S] | C | 根 `AGENTS.md` 诚实边界;`core/scripts/plan_aggregate.py` 瘦身段 | 已披露未修 | C3 核对留痕如实性与摘要丢失面 |
| 5 | 存量 | scout-merge/T2 | 任一分片失败不 rollup → 候选/控制缺口只在 report.md 披露;终产物消费者(agent)看不到「少了什么」 | [S] | C | 根 `AGENTS.md` 诚实边界 | 已披露未修 | C9「缺口披露链」主题;终门扩容候选(向消费者披露) |
| 6 | 存量 | 消费面 | opencode 面索引块是语义性按需加载:消费 agent 跳过对应 Read 就漏用已有控制(claude 面 `paths:` 是确定性触发,无此问题) | [S] | B | 根 `AGENTS.md` 诚实边界 | 已披露未修 | C9 消费者匹配主题 |
| 7 | 2026-10-13 | T3 | opencode 安装面 agent 权限 `edit: deny` 是否会拦住规则写作孪生的产物落盘,未经 live 验证(若拦,规则根本写不出来) | [S] | D | 2026-10-13 战役交接文档 拍板项 A | 待验证 | C6 动态腿顺带验证(跑一次即知) |
| 8 | 2026-10-23 | T1/T3 | **锚点存在性与证据引文一致性均无确定性校验**:`validate_t1_records` 只查非空、`validate_inventory` 只查 evidence 是非空列表、`assemble_rules` 只做纯净 lint。锚点指向不存在的文件/越界行号/错符号名,或 `evidence_snippet` 根本不是该文件的内容,都一路绿灯到终产物 | [S] | D | `core/scripts/validate_t1_records.py`、`validate_inventory.py`、`assemble_rules.py` | 未修 | P3 注入假锚点/假引文即验;加固第 1 项(与模型无关) |
| 9 | 2026-10-23 | T4 | **T4 编辑后零确定性复检**:checkpoint 无 schema,assemble 的纯净 lint 在 T4 之前已完成;T4 就地 Edit 之后没有任何门 | [S] | D | `core/prompts/fragments/init-stage/t4.md`、`contracts/init/step-manifest.md` | 未修 | 加固第 5 项:补丁式输出 + 编辑后复检 |
| 10 | 2026-10-23 | discover | **扫描面不含声明式配置**:`expand_scope.SOURCE_EXT` 只有源码扩展名(无 `.xml`);OFBiz 实测声明式侧有 40 个 XML / 679 条 `permissionId` / 36 个 `<SecurityGroup>` 当前完全不可见(代码侧 40 个 Java 文件做权限检查,两侧大致对半)。**对企业的重要性未验证**(维护者判断银行比例不大,A4) | [S] | C | `core/scripts/expand_scope.py` `SOURCE_EXT`;OFBiz 本机实测 | 未修(条件项) | 先在内网量比例,过阈值才投入;不得据此选仓或排序 |
| 11 | 2026-10-23 | 编排面/全链 | **企业模型执行保真失败(现场观测,手抄)**:①上下文已给明确目录名仍读错写错,曾生成 `cs-interchange-services`、`cds-interface-services`、`cds-interchange-services\bemp\root` 等不存在目录(当时 hook 不严格);②上下文写明 NEVER 仍会尝试;③上下文指定要读某文档仍被漏过。推断:长任务里"读代码→梳理安全设计"的准确性不可信(本次评审根因) | [E]手抄 | A(补救=D) | 维护者在企业内网的长期观测(手抄带出) | 成立(定性) | P5 探针量化三类通过率;加固第 3 项(保真脚手架) |
| 12 | 2026-10-23 | T1–T3 全链 | **生成式 JSON 的引号保真不稳定(内网实测)**:300KB 上下文下让模型生成 JSON,5 次中 1 次丢失 kv 双引号(内容其余部分正确);另一次把 JSON 内联在 shell 提示词里的测试稳定产出 142 字节的**完全无引号**版本(156→142),但**文件→文件复制 6/6 保真**(字节一致)。结论:**复制式可靠、生成式不可靠**;mgh-init 的 checkpoint 属于"生成",必须假设会坏 | [E]手抄 | A(补救=D) | 维护者内网实测 2026-10-23;**2026-10-26 真实 run 复核:全部 checkpoint(scout 1052 + t1 721 + t4 1)严格解析零失败——隔离测试的失真未在真实管线复现** | 成立(定性;真实管线一次未现) | ①所有 checkpoint 严格解析,失败即单元失败(不宽松修复);②禁止在提示词里内联 JSON 样例;③中期改为带 schema 的工具提交(优先级因实测下调) |
| 13 | 2026-10-23 | T2/T4 | **过程文件缺严格解析**:T4 只有 `consistency.json.done` marker 被检查,`consistency.json` 内容无 schema/validator;T2 map-reduce 的分片摘要只被 rollup 模型消费,无确定性解析 | [S] | D | `core/scripts/list_steps.py` t4 行;`core/contracts/init/aggregate-sharding.md`;**2026-10-26 实测:该 run T4 consistency 可解析 + T4 后 assemble --check 复检通过** | 未修(实测一次未触雷) | 工具 C 项常态化覆盖;加固仍列 P4 |
| 14 | 2026-10-26 | T3 终产物 | **真实仓首跑锚点实测**:8 个详述文件合计 258 个锚点,257 个准确存在(99.6%);唯一缺陷 = input-validation 里 1 个方法名不存在(文件与类均存在)——符号级漂移,与预测的失败形态一致 | [E]手抄 | D(校验缺口) | 维护者 AI 空白上下文逐文件核对;**工具复核交叉验证:规则文件锚点 bad_symbol=1 与手工发现吻合**(工具 v1 对 inventory 单冒号证据格式误报 1179 bad_file,v1.1 已修) | 成立 | 锚点存在性门(加固 #1)可关掉这 0.4% |
| 15 | 2026-10-26 | T3 终产物 | **真实仓语义抽查**:每类抽 1 条安全设计(共 8 条),严格判 5/8 准确、放宽判 7/8;3 条不准中 1 条明确错、2 条略偏。**注意:裁判 = 同一个弱模型(空白上下文),裁判可靠性未知;样本 8 条不可外推为率** | [H]弱信号 | A/B(待归因) | 2026-10-26 | 成立(定性:语义误差存在) | ①3 条被标记规则抄回归类;②扩大抽查前先校准裁判 |
| 16 | 2026-10-26 | 全链 | **真实 run 首页 audit 数字(工具 v1,两处误报已定位)**:checkpoint JSON 严格解析**零失败**(≈1774 文件)、failures=0、结构 8 类 8 文件索引 8/8、T4 后 lint 过——**结构性质量面全绿**;待复核:t1 836 marker vs 721 记录(115 孤儿,sha8 对账随 v1.1 重跑)、scout 1054 marker/1052 记录/52 记录无 marker、inventory 691 控制的规则覆盖数(v1 cover 误报 649 因单冒号解析) | [E]手抄 | D(工具缺陷另记) | `audit_init_run.py` v1 stdout 手抄页 2026-10-26 | 部分成立 | v1.1 重跑后回填;649=cover missing 与 decl hits 两处同值疑似抄误待确认 |
| 17 | 2026-10-26 | discover | **A4 首个量化数字**:该真实仓扫描 1784 个声明式配置文件(xml/properties/ini/yml/xsd,含 skip 目录),10 个文件命中安全声明模式(permissionId=/<SecurityPermission/intercept-url/shiro 等),合计 649 处;代码侧 inventory 691 控制对置 | [E]手抄 | C(若构成盲区) | `--scan-config` 2026-10-26 | 数字成立;**盲区与否待判** | 这 649 处是否已被 Java 侧控制覆盖(声明的是 Java 实现的权限目录)还是不可见控制面,需抽查 1–2 个命中文件定性;不据此改扫描面 |

## 增补区(评审会话追加于此线以下)

<!-- 格式同上表;每行一个发现;[S] 项标注「待动态验证」;5why 记录写进对应评审卡文件,这里只落结论。 -->
