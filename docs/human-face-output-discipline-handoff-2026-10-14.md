# 人类面输出纪律 — 交接与扩展手册(2026-10-14,fix-mgh-sdr-report-human-readability 已 apply)

> 受众:维护者与后续接入命令的 apply agent。本文记录 0.1.78 落了什么、其他命令怎么接入、
> 词表怎么增长、还剩什么没验证。规格锚点 = 能力 `human-facing-output-discipline`
> (openspec/specs,归档 fix-mgh-sdr-report-human-readability 后落位);机制论证见该
> change 的 proposal/design(五污染入口、三层防线、增长闭环)。

## 0.1.78 落了什么(一行版)

词表单源模块(`human_face_vocab.py`:核心 10 词条 + 按域补充词 + `scan_text`)、两面守卫
(确定性文案 = 回归测试 fail;模型文本 = `--check` stderr 计数告警)、mgh-sdr 报告确定性
文案平实化、draft 可选 `repro`/`fix_diff` 字段与问题卡片渲染、读者模拟评审(文本束 →
建议文件 → 「可读性自检」折叠小节,尽力而为)、`sdr-task.md` 写作纪律、三面壳/agent
定义/契约同步。测试 31 新增(18 vocab + 13 render),先红后绿。

## 其他命令怎么接入(每命令一个 change)

登记表在能力 `human-facing-output-discipline` 的「人类面表面登记与校准读者」要求里,
当前两行(mgh-sdr 的 HTML 报告 + 数据文件人类字段)。接入一个命令 =

1. **登记**:在自己的 change 里给登记表加一行(命令、表面、受众类别;双受众 SHALL 声明
   以哪面为主——mgh-init/ut-init 的 AGENTS.md 受管块属此类,取舍预案见该 change design
   的 D11:受管块保持紧凑索引但语言平实,解释性内容放 `docs/security-controls/*.md`
   详述文件,个别必要内部词由登记行声明豁免面)。
2. **激活域词表**:该命令域的补充词已在 `human_face_vocab.DOMAIN_TERMS` 预置(init/
   ut-init 共用一池、sra、sast/srr 共用一池),消费方扫描时传 `domains=(<域>,)` 即激活,
   未登记域零副作用。
3. **确定性文案扫一遍**:照 `DeterministicCopyVocabGuardTest`(tests/test_render_sdr_report.py)
   的模式,提取该命令确定性产出的人类面字符串全量扫闭集,先红后绿改写。
4. **`--check` 告警面**:在该命令产出链末步校验里对模型人类面文本字段扫
   `scan_text(text, domains=(...))`,命中仅 stderr 计数告警,退出码不变(与 render 的
   `_vocab_warn` 同形)。
5. **写作纪律**:该命令 fan-out 任务模板加同款紧凑纪律节(读者画像/首句现象/结构字段/
   禁词),字段描述改读者语言;结构字段按表面适用性裁剪(不强制 repro/fix_diff)。
6. **读者评审(可选)**:sdr 的文本束→建议→折叠小节机制是按表面裁剪的;报告类表面建议
   套用(模板 `readability-review.md` 可复用,占位符同形),init 类双受众表面接入期再拍板。

## 词表增长流程(常态机制)

读者评审建议 + 维护者人工发现 → **维护者确认**(评审是 LLM,误报不得直接进闭集)→
`human_face_vocab.py` 加一行(term + plain 人话替身 + note 撞车备注)→ **同步改内容锚**
(tests/test_human_face_vocab.py 的 `CORE_TERMS`/`SDR_TERMS`/域抽查精确集)→ 该词被两面
守卫永久拦截。守则:同形不同义按域收精确词形,NEVER 单词子串禁(红灯样本:「锚点」是
产品概念、「锚定到」是正常动词,只有 sdr 的三个「锚」复合词是算法词;基线/单元/哨兵/
存量/簇/扫描器同此处理)。整表重扫不常规做;新域接入时对该域做一次分域评审即可。

## 未验证 / 遗留(按风险排序)

1. **读者评审子代理的真跑**:确定性半边已实机验证(束写出/建议消费/坏产出省略/退出码
   不变),但「派发真实 LLM 评审 → 建议落盘 → 重渲染出小节」整链要等下一次真实 mgh-sdr
   run 才首次走通。建议下次实机 run 时人为制造一次评审失败,顺带验证壳 step 4.5 的
   NEVER-重试-逾一次纪律。
2. **校准读者人工通读**:文本级检查(闭集零命中、平实句式锚、折叠存在)全过,但「一两年
   经验读者顺读」的最终判断要人来做——建议维护者开一次 smoke 报告(或下次真实报告)通读。
3. **dsh skill 预算余量仅 3 tok**(4997/5000):sdr 壳再改任何内容都要等量对冲裁剪,
   或者考虑 shard-to-fit(抽 lazy fragment)。
4. **存量测试失败一处**:`test_diff_group::test_cg_probe_failure_reason_on_stderr` 经
   stash 对照为 HEAD 存量(环境相关:本机 codegraph 解析路径使 probe 失败原因措辞偏离
   测试预期),与本 change 无关,留待 diff_group 面的后续 change 处理。
5. 词表当前零告警基线:真实 run 的模型文本若开始报告警,按上方增长流程沉淀词条(第一次
   真实告警是词表工作的开始,不是缺陷)。
