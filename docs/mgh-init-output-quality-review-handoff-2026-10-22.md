# mgh-init 产出质量评审战役 · 交接文档(2026-10-22)

> **用途**:换环境(晚间/另一台机器/新会话)继续本战役。输入源 =
> [mgh-init-output-quality-review-plan-2026-10-22.md](mgh-init-output-quality-review-plan-2026-10-22.md)
> (评审计划,自包含:六维标尺、弱模型五问、方法箱、九张评审卡、Phase 0–4、待拍板 D1–D4)。
> 本文档承载:当前进度、无需拍板即可开工的缺省路径、逐卡快速启动索引、本会话已核实的关键
> 情报(新会话不必重新考古)、纪律红线。计划文档 + 本文档已随 0.1.91 推送,新环境
> `git pull` 即得全部上下文。

## 一、当前进度(2026-10-22 会话完成)

| 项 | 状态 |
| --- | --- |
| 评审计划文档(0.1.91) | ✅ 已写入 `docs/mgh-init-output-quality-review-plan-2026-10-22.md` 并推送 |
| 术语词典 | ✅ 已补 13 条方法论术语(5why/FMEA/GQM/金标仓/证据等级等) |
| 缺陷登记册 | ✅ 已预置 7 项已知未修/待验证项:`docs/reviews/init-quality-2026-10/register.md`(评审只往里加) |
| D1–D4 拍板 | ⬜ **未拍板**(维护者;选项对比在计划文档 §9) |
| P1 静态评审卡 C1–C9 | ⬜ 未开始(**不依赖拍板,可立即执行**,见下) |
| P2/P3 动态腿(强模型对照/方差/追溯/A-B) | ⬜ 依赖 D1/D2/D3 拍板,拍板前不动 |

## 二、缺省执行路径(维护者未拍板时,晚间会话照此走)

1. **直接开跑 P1 静态卡**,按危险度顺序:**C7 → C2 → C4 → C5 → C6 → C8 → C1 → C3 → C9**。
   每卡一个新会话(上下文隔离,弱上下文环境尤其如此);开会话后先读计划文档 §7 对应卡的
   全文,再按下面 §四 的索引读关键文件。
2. **动态腿不启动**(D1 未拍板 = 没有合法的弱模型证据来源)。静态卡里标 [S] 的项照常登记。
3. 维护者在场拍板后,按计划文档 §9 执行:先 P0(填模型画像表 + 金标仓定档),再 P2/P3。

## 三、纪律红线(评审会话必须遵守)

- **`DEEPSEEK_API_KEY` 未经维护者在当次对话明确授权,禁止触碰**(用户级全局指令;D1 选 ①
  不等于授权,必须在当晚对话里点名同意后才可调用官方 API)。
- **本战役是只读评审**:不修改 `core/`、`releases/`、`tools/`、`tests/` 的任何产品文件;
  修复一律走后续 openspec change(P4 汇总后逐个 propose)。评审可写的只有
  `docs/reviews/init-quality-2026-10/**` 与本登记册。
- **证据等级纪律**:[S] 静态推断不得直接进修复提案;只有 [L] 本机实证 / [E] 企业实证
  有资格;每条登记项必须落根因类 A–E(A 模型能力边界 / B 提示词契约 / C 切片保真 /
  D 校验硬度 / E 脚本缺陷)。
- **不重复 2026-10-13 战役的覆盖面**(机制/形状已清,见
  `docs/review-mgh-init-full-pipeline-2026-10-13.md` 与其交接文档);发现属机制面的问题
  只登记不展开。
- 换环境先探测解释器:`py --version`(Windows Store 占位机上是 `python` 可用)。
- 产出文档遵守 R3(人类面、受众声明、人话);术语先查 `docs/glossary.md`。

## 四、逐卡快速启动索引(关键文件均已核实存在,2026-10-22)

| 卡 | 主要读 | 动态实验(拍板后) | 产出文件名 |
| --- | --- | --- | --- |
| C7 T4 一致性 | `core/prompts/stages/init-rules-consistency.md`、`core/prompts/fragments/init-stage/t4.md`、`core/contracts/init/step-manifest.md`(t4 行) | 强模型腿跑 T4 前后 diff 全量人审 | `C7-t4-consistency.md` |
| C2 scout 读者批+自审 | `core/prompts/stages/init-scout.md`、`init-scout-audit.md`、`core/scripts/plan_scout.py`(--help 面即可)、`core/scripts/merge_scout.py` | 固定批重复 N 次;自审纠错率 | `C2-scout-reader.md` |
| C4 T1 归纳 | `core/prompts/stages/init-induct.md`、`core/prompts/fragments/fanout/t1-task.md`(Form B 双形态)、`core/contracts/init/t1-record-schema.md`、`core/scripts/validate_t1_records.py` | 固定簇重复 N 次;锚点存在性抽验 | `C4-t1-induct.md` |
| C5 T2 综合 | `core/prompts/stages/init-synthesis.md`(+ `-partial`/`-rollup`)、`core/scripts/plan_aggregate.py`、`core/scripts/validate_inventory.py`、`core/contracts/init/inventory.md` | 双路径(单上下文 vs map-reduce)产物 diff | `C5-t2-synthesis.md` |
| C6 T3 规则写作 | `core/prompts/stages/init-rulewriter.md`、`core/prompts/fragments/rules-format-opencode.md` / `rules-format-claude.md`、`core/contracts/init/rules-detail.md`、`core/scripts/assemble_rules.py` | inventory↔规则覆盖手工对账 | `C6-t3-rulewriter.md` |
| C8 assemble 终门 | `core/scripts/assemble_rules.py`(lint 词表与豁免)、`tests/test_assemble_rules.py` | —(静态为主:终门扩容候选清单) | `C8-assemble-gate.md` |
| C1 discover | `core/scripts/discover_controls.py`(特征表/正则面)、`core/scripts/chunk_sources.py` | 金标仓跑 discover 量召回(依赖 D2) | `C1-discover.md` |
| C3 scout-merge | `core/prompts/stages/init-scout-merge.md`(+ `-partial`/`-rollup`)、`core/scripts/plan_aggregate.py`(scout-merge 分支) | 去重对账(强模型腿产物) | `C3-scout-merge.md` |
| C9 横切 | `core/prompts/fragments/init-scout-native-dispatch.md`、`init-aggregate-native-dispatch.md`、`releases/opencode/agent/init-*-native.md`(五只孪生)、`orchestrator-discipline.md` | —(消费者匹配素材供 P3) | `C9-crosscutting.md` |

读脚本守 R5.2 的精神但**本战役例外**:评审是研发会话、不在运行域内,可以读叶脚本源码;
仍建议能靠 `--help` 与契约文件讲清的就少读源码,省上下文。

## 五、本会话已核实的情报(勿重复考古)

1. **语义质量零评估是实锤**:2026-10-13 战役七批(0.1.68–0.1.74)全部机制面;R5.7 段 A
   的 baseline/blind A/B 从未执行(两处 archive 任务未勾:`archive/2026-07-15-improve-mgh-init-codegraph-enrichment/evaluation.md`、
   `archive/2026-09-09-adopt-mgh-init-fanout-t2/tasks.md`);企业交接清单从未勾选,零企业
   侧产物质量观察。
2. **各阶段语义偏差兜底现状**(静态量化,细节在计划文档 §5 表):T4 编辑后零确定性复检、
   checkpoint 无 schema;scout 语义层(category 对错/snippet 真伪/置信校准)零确定性兜底;
   T1 形状闸强但锚点存在性/prose 零校验;T2 的 role 裁决 validator 不查、单上下文路径
   96KB 只是软预算(历史有 269KB 单批撑爆 150K 窗实录,见
   `archive/2026-10-12-harden-mgh-init-scout-merge-dispatch/proposal.md`);T3 无
   inventory↔规则对账门;scout-merge 输入输出边界复检最严,相对最安全。
3. **指令负担量级**(measure_prompts 实测,stage+模板+agent 三段叠加):scout ≈4.2–4.7K
   tok/NEVER 32;T1 ≈4.5–5.0K;T3 ≈4.3–5.2K;T2/T4 最轻(1.0–1.8K)但兜底也最弱——
   **负担与兜底不成比例是本战役的核心叙事线**。
4. **缺陷登记册预置 7 项**已在 `docs/reviews/init-quality-2026-10/register.md`,其中
   #1(pack 会话写包级账本 JSON)/#2(validate_t1_records glob 误读账本)是 2026-10-21
   实机 [E] 级未修,修法明确,P4 前可提前立项(propose 走 openspec 常规流程)。
5. **尺寸/预算默认值**速查(计划文档 §5 表有全量):scout 批 96KB/40 文件;T1 单元帽
   192KB(超限切 shard);聚合硬预算 96KB(T2/scout-merge 走 plan_aggregate;
   **T2 单上下文路径不受此闸**);正则 snippet 160 字符;merge 瘦身帽 4096(`_slimmed`
   留痕,锚点永不截)。
6. 双形态说明:原生派发(0.1.90 起 opencode 缺省)只改**派发载体**,各阶段判断内容与
   提示词不变——评审按阶段审判断质量即可,不必区分派发形态;派发纪律本体归 C9。

## 六、Phase 0 拍板后第一步(备忘)

1. 填计划文档 §3 的模型画像表(有企业口径就填,没有按保守假设);
2. D2 落金标仓:自建玩具 Java Web 仓(手植约 30 个控制)打底,fixture 最终进 `tests/`
   成为质量回归地基;
3. P2 动态基线从强模型对照腿开始(它不需要 D1,只依赖金标仓)——若 D2 拍板晚于 P1 完成,
   P1 全部静态卡照跑不误。
