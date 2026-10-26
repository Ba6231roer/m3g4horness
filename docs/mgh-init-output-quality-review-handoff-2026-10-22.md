# mgh-init 产出质量评审 · 会话接续手册(2026-10-23 修订)

> **用途**:同一台机器上换新会话继续本战役。**先读**评审计划
> [mgh-init-output-quality-review-plan-2026-10-22.md](mgh-init-output-quality-review-plan-2026-10-22.md),
> 特别是 **§13(2026-10-23 修订)**——它按两条新落定的环境硬约束重定基了整条策略。
> 本手册承载:当前进度、下一步直接可做的事、纪律红线、已核实情报。

## 一、当前进度

| 项 | 状态 |
| --- | --- |
| 评审计划(0.1.91,commit `2b23f96` 已推送) | ✅ 六维标尺 / 方法箱 / 九张评审卡 C1–C9 / Phase / 决策点 |
| **2026-10-23 策略修订(三轮)** | ✅ 计划 §13(替换 §8/§9;§3 改执行保真六问;§13.10 假设 A1–A10;开发人员可评审性边界);第三轮:今晚真实仓首跑观察表 + 周一检查工具范围。随 0.1.95 提交 |
| 缺陷登记册 | ✅ 预置 13 项(`docs/reviews/init-quality-2026-10/register.md`) |
| P0 定标 | ⬜ 未开始(裁约束画像 + 仓准备 + 仪器设计) |
| P1 静态卡 C1–C9 | ⬜ 未开始,可立即开跑 |
| P2/P3 动态(约束仿真/缺陷注入) | ⬜ 未开始,不依赖任何外部条件,本机可做 |
| P5 内网取证 | ⬜ 依赖内网作业窗口;仪器(P4 自审工具 + 探针包)要先备好 |

## 二、三条前提(决定所有方法选择)

1. **弱模型不可得**:原生 DeepSeek V4 Flash 0731 在公网经长期使用实测很强;企业内网
   150K 部署版在公网找不到替代。→ 不做"弱模型保真"评测,改做**硬约束仿真 + 缺陷注入**。
2. **企业版确实弱,弱在"执行保真"**:维护者现场观测到 — 上下文给了明确目录名仍读错写错
   (曾造出 `cs-interchange-services`、`cds-interface-services` 这类不存在的目录)、
   写明 NEVER 仍尝试、指定必读文档被漏过。→ 加固重点不是"教它想明白",而是
   **凡逐字复现交给脚本、凡记得做必须有痕迹、凡 NEVER 必须有执行者**(计划 §13.3)。
3. **内外网通道不对称**:内网→外网**只能手抄短文**(历次归档问题都是这样带出的);
   外网→内网可传 **≤100MB 文件**(OFBiz 工作树 95MB 实测可过,`.git` 768MB 不能带)。
   → 仪器整包带进去,裁决按**手抄友好格式**(≤15 行 `KEY=value`)带出来(计划 §13.7)。

一句话策略:**测的不是"企业模型会不会写错",而是"它写错了管线拦不拦得住"**。前者不可
测,后者可测且与模型无关。

**假设纪律**:任何未测量的判断先登记进计划 §13.10(A1–A8),未验证假设不得单独支撑
选仓/加固排序。已因此回溯过一次:声明式 XML 盲区从"可能比模型能力更贴近风险"降为
"条件项,先进内网量比例"。

## 三、下一步(按性价比排序,全部本机可做)

1. **P1 静态卡**:按 C7 → C2 → C4 → C5 → C6 → C8 → C1 → C3 → C9 顺序,每卡一个新会话。
   产出填进 `docs/reviews/init-quality-2026-10/C*.md`,发现进登记册。
   *新增用途*:每卡要顺手回答「这个阶段的失误长什么样、怎么注入」——这是 P3 的素材。
2. **P2 约束仿真**(1–2 会话):本机跑 RuoYi(或 OFBiz)全链,人为施加企业约束——
   按 token 的 150K 硬顶、调低压缩阈值触发中途 compact、关结构化输出、输出长度上限。
   记录静默溢出与纪律丢失点。
3. **P3 缺陷注入**(核心,2–3 会话):快照一次完整 run → 按计划 §13.6 的清单逐类注入 →
   只删下游 marker 重跑 → 产出**门矩阵**。这张表直接是 P4 的加固排序。
4. **P4 门加固**(可与 P3 交错):计划 §13.8 前 8 项都不需要模型证据,可立即 openspec
   立项。优先级:锚点+引文双重校验 > inventory↔规则对账门 > **保真脚手架**(读证明、
   预期产物集合、NEVER 要么有 hook 要么删)> 硬预算处处生效 > T4 补丁式约束。
5. **P0 仪器**(随时可做):自审工具的 `--summary` 手抄格式、探针题库与评分脚本、内网
   一页表单、异常追问清单。不必等静态卡全跑完。

## 四、纪律红线

- **`DEEPSEEK_API_KEY` 未经维护者在当次对话明确授权,禁止触碰**(用户级全局指令)。
- **评审只读产品文件**:不改 `core/`、`releases/`、`tools/`、`tests/`;修复走后续
  openspec change。评审可写:`docs/reviews/init-quality-2026-10/**` 与计划/交接文档。- **证据等级**:[S] 不得直接进修复提案;[L] 本机实证 / [E] 企业实证才有资格。
  每条登记项必须落根因类 A–E。
- **单向推断**:本机失败 ⟹ 企业必失败;本机通过 ⇏ 企业通过。不得把本机通过写成质量
  结论(计划 §10)。
- **没有模型证据之前不改提示词**(R5.7 段 A 要求 baseline + blind A/B;当前不具备条件)。
- **开发人员不是评审员**:不请他们看过程文件(T1/T2/T3 记录、checkpoint、synthesis.json);
  只对最终 `AGENTS.md` 问三个问题,意见记 [H] 弱信号,不参与数值、不作 ground truth
  (计划 §2 / §13.7)。
- 换会话先探测解释器:`py --version`(本机 `py` 可用;`python` 是 Store 占位)。
- 产出文档遵守 R3(人类面、受众声明、术语先查 `docs/glossary.md`)。

## 五、逐卡快速启动索引

| 卡 | 主要读 | 静态产出 | 可注入的缺陷(P3 素材) |
| --- | --- | --- | --- |
| C7 T4 | `core/prompts/stages/init-rules-consistency.md`、`fragments/init-stage/t4.md`、`contracts/init/step-manifest.md` | T4 价值/风险裁决 | 静默改坏正确规则 |
| C2 scout | `stages/init-scout.md`、`init-scout-audit.md`、`plan_scout.py`、`merge_scout.py` | 语义兜底缺口 | 整批 0 候选 / 误报进簇 |
| C4 T1 | `stages/init-induct.md`、`fragments/fanout/t1-task.md`、`contracts/init/t1-record-schema.md`、`validate_t1_records.py` | prose 质量 rubric | 假锚点 / 错 category / 空 usage / 漏簇 |
| C5 T2 | `stages/init-synthesis.md`(+partial/rollup)、`plan_aggregate.py`、`validate_inventory.py` | 双路径不对称定量 | 误并 / 错 canonical / 丢簇 |
| C6 T3 | `stages/init-rulewriter.md`、`fragments/rules-format-*.md`、`contracts/init/rules-detail.md`、`assemble_rules.py` | 覆盖对账缺口 | 漏写控制 / 锚点漂移 / frontmatter 结构坏 |
| C8 assemble | `assemble_rules.py` lint 词表、`tests/test_assemble_rules.py` | 终门扩容候选清单 | 裸词泄漏 / 索引与详述失配 |
| C1 discover | `discover_controls.py` 特征面、`chunk_sources.py`、`expand_scope.py` 的 `SOURCE_EXT` | 扫描面盲区 | 见下条 XML 发现 |
| C3 scout-merge | `stages/init-scout-merge.md`(+partial/rollup)、`plan_aggregate.py` | 去重正确性抽检 | 丢整批 / 错并 |
| C9 横切 | 两个 native-dispatch fragments、五只 `init-*-native` agent、`orchestrator-discipline.md` | 消费者匹配结论 | 错标记 / 跳页 |

## 六、本会话已核实的情报(勿重复考古)

1. **语义质量从未被评估**:2026-10-13 战役(七批,0.1.68–0.1.74)全为机制面;R5.7 段 A
   的 baseline/A-B 从未执行;企业交接清单从未勾选。
2. **兜底现状**(计划 §5 表):T4 编辑后零复检;scout 语义层零确定性兜底;T1 形状闸强但
   锚点存在性/prose 零校验;T2 role 裁决不查、单上下文软预算;T3 无 inventory↔规则对账;
   scout-merge 相对最严。
3. **指令负担量级**(实测,stage+模板+agent):scout ≈4.2–4.7K tok / NEVER 32;T1
   ≈4.5–5.0K;T3 ≈4.3–5.2K;T2/T4 ≈1.0–1.8K——负担与兜底不成比例。
4. **OFBiz 实测(2026-10-23)**:`C:\DEV\ofbiz-framework` = 1257 个 Java 文件 / 37.6 万行
   Java / 1052 个 XML;**工作树 95MB**(去 `.git`,恰在 100MB 通道内;`.git` 768MB 不能带)。
   声明式与代码两侧都有授权定义:40 个 XML / 679 条 `permissionId` / 36 个
   `<SecurityGroup>`;同时 40 个 Java 文件做权限检查(`@RequirePermission`、`@Valid` 均 0)。
   `SOURCE_EXT` 不含 `.xml` → **声明式那一侧不可见**(登记册 #10)。
   **边界**:「银行大量用 XML 声明鉴权」是未验证假设 A4(维护者判断比例不大),**不得**
   据此选仓或排序;正确做法是进内网跑计数脚本、手抄两个数,过阈值才投入。OFBiz 单独跑
   产出偏薄是预期内的,必须与 RuoYi/植入仓配对解释。
5. **测试仓组合**(计划 §13.5):植入真值仓(待建)+ RuoYi(贴近,约 4 万行)+ OFBiz(规模/
   老栈,95MB 可进内网)+ Fineract(117 万行;克隆 123MB,去 `.git` 后是否 ≤100MB 需实测,
   超限就只带一个模块用 `--scope`)。调研报告的分支数/CVE 维度对 init 不适用。
6. **缺陷注入成本可行**:进度纯磁盘 marker 重派生 → 快照 run 后每次注入只重跑下游
   2–4 阶段,几十次注入在配额内可承受(计划 §13.6)。
7. 双形态(原生/子进程)只改派发载体,不改各阶段判断内容与提示词——按阶段审即可,
   派发纪律归 C9。

## 七、当务之急(建议今天/本会话就做)

1. 定 P0 约束画像里已知的部分:企业有效窗口是否确实 150K、有无 JSON mode、输出上限;
   不知道的标"未知"并按最坏设计。
2. 决定第一个测试仓:建议**先建植入真值仓**(约 30 个控制,Apache-2.0 风格骨架),
   它是 P2/P3 的基础;RuoYi 次之。
3. 开 C7(T4 一致性)——静态卡里危险度最高、读的文件最少、可当天出结论。
4. **设计自审工具的 `--summary` 手抄格式**(≤15 行 `KEY=value`,ASCII,失败项只报类别
   计数)——它是内网取证和普通用户质量保障的共同载体;格式定不下来的话,后面所有内网
   数据都不可靠。
5. 若近期有内网作业窗口:把「声明式控制条目 vs 代码内控制条目」计数脚本一起带上,
   两个数字回来即可把假设 A4 从"未验证"变成"已量"。

## 八、真实仓首跑(2026-10-23 夜)——已跑完,实录回填(2026-10-26)

**运行健康(全部 [E] 级,手抄)**:

| 项 | 实录 |
| --- | --- |
| 目标仓规模 | 非测试 Java 12,798 文件 / 243 万行;XML/SQL/properties/xsd 约 4,700 文件 / 70 万行 |
| 形态/参数 | opencode + opencode2 派发(原生,全程未用 `fanout_runner.py`);其余参数全默认;全新 run |
| 模型 | DeepSeek V4 Flash 0731,窗口阉割 150K |
| 时长 | 10-23 18:00 起 ~36 小时,**无人值守一次性跑完,零 `.failed`** |
| compact | 有,次数不可数(导出会话 4MB,关键词 "next move" 出现 21 次,仅参考) |
| 各 tier | scout 1052/1052 · t1 done 836 vs json 721(待工具对账,疑似 pack 成员级 marker)· t2 18/18 · t3 8 · t4 1/1 |
| 产物 | AGENTS.md 971B(惰性索引)+ 8 个详述文件(审计日志/认证/授权/crypto/CSRF/数据脱敏/输入校验/限流、批量上限与并发互斥),文件内均有锚点 |

**产物质量初测**:

- **锚点(AI 空白上下文逐文件核对,确定性可复算)**:8 文件合计 258 个锚点,257 个准确存在(99.6%);唯一缺陷 = input-validation 内 1 个方法名不存在(文件、类均在)→ 登记册 #14。
- **语义抽查(每类抽 1 条,共 8 条)**:严格 5/8、放宽 7/8(裁判 = 同弱模型,[H] 弱信号,样本不可外推)→ 登记册 #15。**待办:把 3 条被标记规则的原文+锚点+判错理由抄回(每条几行),用于归类失误模式。**
- 开发人员未介入;按计划只做最终 AGENTS.md 三问,不看过程文件。

**意义**:36h 无人值守零失败 = 原赌注的"流程稳定性"腿被 [E] 级实证成立;问题被干净隔离为纯质量面——锚点 99.6% 已接近可接受的机械保障线,语义面是唯一主战场。`report.md` = `<target>/.mgh-init/report.md`,done 步写的简体中文人读"诚实边界披露"(扫描范围/跳过/截断/competing controls);打开看小节标题,抄行数即可。

## 九、周一工具:范围与产出(先约定,免得跑完才设计)

工具名暂定 `audit_init_run.py`。零依赖、只读、独立于安装版本,`py <脚本>` 直接跑,任意
cwd 可用。输入是跑完的 `<target>/.mgh-init/` 和规则目录;输出两样:

- stdout 一页 `KEY=value`(≤15 行,纯 ASCII,手抄用)
- 本地 `audit_report.json`(明细留在内网,不外发)

检查项(你点名的两个 + 已确认的空洞):

| 代号 | 检查 | 现状 |
| --- | --- | --- |
| A | 全 tier checkpoint JSON 严格解析:哪层几个坏 | 现在只有 T1 闸门会解析,其余层不定 |
| B | **T2 `checkpoints/t2/synthesis.json`** 能否解析;map-reduce 时各 shard 摘要路径是否存在且可解析 | 分片摘要目前只被 rollup 模型消费,无确定性解析 |
| C | **T4 `checkpoints/t4/consistency.json`** 能否解析;T4 之后规则文件是否仍通过 `assemble_rules --check` | T4 后零复检(登记册 #9) |
| D | 锚点存在性 + 证据引文一致性(T1 记录与最终规则) | 完全缺失(登记册 #8) |
| E | inventory↔规则覆盖对账(缺几个、多几个、按 category) | 完全缺失 |
| F | 运行健康:manifest、marker 计数、failed reason、boundaries | 散落在多个文件,无汇总 |

输出示例(v1.1 手抄页的实际形态;2026-10-26 首页实测:json_bad=0、结构 8/8、
T4 后 lint 过;工具 v1 的 anchors bad_file=1179 / cover missing=649 为**单冒号证据
解析误报**,v1.1 已修,以重跑为准):

```
AUDIT v1.1 fmt=opencode
markers scout=…/0 t1=…/0 t2=…/0 t3=…/0 t4=…/0
records scout=…(files=…) t1=…(files=…) …
orphan_json t1=…(sha_hit=…) scout=… t2=… t3=… other_marker=… rec_no_scout=… rec_no_total=…
json_bad total=… scout=… t1=… t2=… t3=… t4=…
t2 shards=… shard_bad=… synthesis=absent
t4 consistency=ok post_t4_lint=ok
anchors total=… ok=… bad_file=… bad_line=… bad_symbol=… unchecked=…
snippets checked=… mismatch=…
inv controls=… cats=… files=… missing_files=… extra_files=…
cover represented=… missing=…
index links=… files=…
manifest boundaries=… failures=… report_md=… cfg_scout=on
scout_mismatch_examples=…(仅 scout 有差异时)
decl_cfg scanned=… hit_files=… hits=…(--scan-config 时)
```

验收:不修改任何文件;退出码 0 = 已产出报告(发现问题不算失败)、2 = 用法错;对缺失的
可选文件(如未走 map-reduce 时的 shard 摘要)按"不适用"处理,不报错。
