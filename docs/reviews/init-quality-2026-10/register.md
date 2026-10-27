# mgh-init 产出质量评审 · 缺陷登记册

> **受众:人类 + agent(双受众)**。本登记册是评审战役的集中台账:每条带问题描述、
> 根因分类(A 模型能力边界 / B 提示词与契约设计 / C 输入切片与信息保真 / D 校验硬度
> 缺口 / E 确定性脚本缺陷)、证据等级([S] 静态推断 / [L] 本机实证 / [E] 企业实证)、
> 状态。评审会话只往里加和核实;修复提案从本册取([L]/[E] 优先)。
> 现有 22 项。**待办区(维护者将另开修复任务,本战役不修)**:#21 守卫拦掉写入时 JSON
> 校验(子代理退化为 wc -c/ls 存在性检查);#22 守卫 heredoc 内容误伤(yyyy/MM/dd 误判
> 越树路径、>2000/$ 误判重定向,已致记录内容被改写)。#18 已结案(良性 pack marker)。
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
| 16 | 2026-10-26 | 全链 | **真实 run audit 数值(v1.1 复核)**:checkpoint JSON 严格解析**零失败**复证;结构 8 类 8 文件索引 8/8;T4 后 lint 过;t2 分片 19/19(子目录递归后对上,与周五手数 18 接近);t3 的 8 个孤儿 marker 判定**良性**(原生 t3 任务模板只要求写规则文件 + touch marker,无 checkpoint 记录文件——设计内);scout 差异 = merge/rollup 编排工件 + 1 个 `scout-338` 待查 | [E]手抄 | D(工具缺陷另记) | audit v1.1 stdout 2026-10-26 | 大部分成立 | scout-338 现场核对(json 与 done 哪个缺);v1.2 重跑补 t1/cover 定量 |
| 17 | 2026-10-26 | discover | **A4 首个量化数字**:该真实仓扫描 1784 个声明式配置文件,10 个文件命中安全声明模式,合计 **469 处**(初抄 649 系笔误,已更正);代码侧 inventory 691 控制对置 | [E]手抄 | C(若构成盲区) | `--scan-config` 2026-10-26 | 数字成立;**盲区与否待判** | 让内网 AI 打开 2 个命中文件答一句"声明的是权限目录/URL 拦截还是别的";不据此改扫描面 |
| 18 | 2026-10-26 | T1 | ~~115 个"有 marker 无记录"待判定~~ **2026-10-27 结案:良性(设计内)**——`init_tier.py` 孤儿审计本就豁免 `pack__` 前缀:pack 是派发单元,**设计上只有终止 marker、无记录文件**;算术吻合:721 记录 = 全部 solo+成员记录(Form B 合规,零覆盖损失),836 marker = 721 + 115 个 pack 级 marker(115 个包)。工具 v1.4 补同款豁免。**衍生新发现**:`checkpoints/pack_manifests/` 下 52 个 json **无任何脚本会写**——模型自发发明的记账文件(#1 pack 账本违例的规模化形态,52/115 包) | [E]手抄+[L]代码核实 | E(卫生)/B(违例) | audit v1.3 + `core/scripts/init_tier.py:110-118`、全脚本 grep 零引用 | 已定性 | 卫生问题随 #1 修复收口(模板禁令+豁免);不升级 |
| 19 | 2026-10-26 | T3 | **终产物对 inventory 的覆盖疑似严重不足**:rulewriter 设计意图 = "一条规则对应一个有锚点的控制"(`init-rulewriter.md`);实测 8 个详述文件锚点引用合计仅 ~258(手工 [E]),inventory 691 条控制;cover(basename 匹配)represented=45/691。差值可能来自:competing/possibly-dead 合法省略、T3 漏写(执行保真)、锚点形态不匹配 | [E]手抄+[L]工具 | A/B/D(待归因) | 手工锚点计数 + audit v1.1/v1.3 cover(45/691 稳定复现) | 嫌疑成立待定量 | detail 按 category 分布;坐实则 inventory↔规则对账门(加固 #2)立项 |
| 20 | 2026-10-27 | scout | **scout-338 记录"写入后消失"**:会话记录(300KB 导出)明确三次尝试后**成功写入 scout-338.json(3210 字节、6 候选)并 touch .done**;但文件现已不在 checkpoints/scout/。目录内留有 `.probe-962`/`.probe.tmp`/`.probe2.tmp` 探路残留。谁删了/写去了别处待查(v1.4 探针打印命中文件名)。`elsewhere=2/cands_hit=1` 受任务文件名与 "merge" 泛词干扰,归属未定 | [E]手抄(会话级) | A/D | 维护者会话取证 2026-10-27 | 观测成立;去向待 v1.4/目录搜索 | 与 #18 机制不同(#18 是设计内);若确认"写后被删",加固 = 记录不可变守卫或事后对账 |
| 21 | 2026-10-27 | 守卫×产物 | **守卫拦掉写入时 JSON 校验 → 产物带病落盘风险后移**:正常批(scout-341)会话显示,子代理先尝试 `cat heredoc` 写入 + `python3 -c`/`node -e` 校验 JSON 语法,**被运行域守卫按设计拦截**(微脚本内省禁令),随后退化为"纯 heredoc 写入 + `wc -c`/`ls` 存在性检查"——**写入时零语法校验成为常态路径** | [E]手抄(会话级) | B/D | scout-341 会话取证 2026-10-27 | 成立 | **待办(维护者另开修复任务)**:给子代理一条合法的语法校验通道(如放行 `py -m json.tool <checkpoint>` 只读校验),否则 malformed JSON 只能靠下游门救 |
| 22 | 2026-10-27 | 守卫×产物 | **守卫对 heredoc 内容误伤(两个新形态,已致记录内容被改写)**:scout-338 会话三次写入尝试中,①JSON 内容含 `yyyy/MM/dd` 被路径净网误判为越树路径(拦截);②含 `>2000` 与 `$` 被误判为重定向(拦截);③**模型为通过守卫改掉了日期片段后成功**——即守卫误伤直接导致记录内容被篡改。机制:Bash 面净网是 regex-over-string,不区分 heredoc 体与命令结构 | [E]手抄(会话级) | E(守卫缺陷) | scout-338 会话取证 2026-10-27 | 成立 | **已立项 `fix-mgh-guard-heredoc-body`(2026-10-27 apply 落地,0.1.103)**:守卫新增 heredoc/here-string 数据体结构剥离(四类结构判定吃剥离文本;解释器喂养按原文先行全拦,顺带补上 `python <<`/`node <<`/`Invoke-Expression @"` 三个原漏拦形态;未终结/未配对保守判全文)。修复采用结构剥离路线,未走日期/数字词表白名单 |

## 增补区(评审会话追加于此线以下)

<!-- 格式同上表;每行一个发现;[S] 项标注「待动态验证」;5why 记录写进对应评审卡文件,这里只落结论。 -->
