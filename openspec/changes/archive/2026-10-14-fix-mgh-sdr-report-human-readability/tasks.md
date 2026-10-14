# tasks — fix-mgh-sdr-report-human-readability

> 第 1 组先写测试并按现状跑出红（证明缺陷存在），第 3、4 组实现后转绿。
> 改了哪面就跑哪面的测试，映射表在仓库 AGENTS.md「改动面 → 测试文件」。

## 1. 红测组（先红后绿）

- [x] 1.1 禁词守卫测（`tests/test_render_sdr_report.py` 增）：提取
  `render_sdr_report.py` 全部人类面字符串常量 + HTML 模板文本节点，全量扫闭集
  （`human_face_vocab` 核心词 + sdr 补充词）——现状报告里有「路由锚/向上锚定/投影/
  hunk/facet」，应跑红
- [x] 1.2 概览/边界新措辞锚测：断言平实句式（「接口单元」「独立文件单元」「挂接到未变更
  接口」）和折叠「分组诊断」明细存在；断言旧措辞不再出现（把
  `test_render_sdr_report.py:385` 的「向上锚定 8」存量锚一并改写）——应跑红
- [x] 1.3 新字段渲染测：draft 带 `repro`/`fix_diff` → 问题卡片出现「复现方式」行和
  「修改前/修改后」代码块（等宽、逐字注入），数据文件 `findings[]` 带这两字段，HTML 与
  JSON 同源——应跑红
- [x] 1.4 `--check` 禁词告警测：draft 的 `risk` 含闭集词 → stderr 至少一条计数告警
  （字段名 + 词），退出码与无该词时相同——应跑红
- [x] 1.5 `tests/test_human_face_vocab.py`：词表内容锚（核心 10 词条按 `vocab-candidates.md`
  §1 定稿；sdr 补充词按 §2 定稿；「锚点/锚定」单词不在任何一层——同形词守则的负向锚）；
  扫描函数行为（命中/不命中/子串边界）；「改词表不改测试 = 红」的锚定方式——模块还不
  存在，应跑红
- [x] 1.6 模板与三面 agent 定义对账测：`sdr-task.md` 含写作纪律节和扩字段 schema 示例，
  输出字段描述文字自身零闭集词；opencode/claude 的 `sdr-review-fanout` 与 dsh 的 `sdr`
  三面 Output schema 行一致——应跑红
- [x] 1.7 文本束与自检小节测：渲染产出 `readability_text_bundle.json`（每条 P-NN 的
  人类面文本）；`readability_advisories.json` 存在时数据文件带 `readability[]`、报告含
  默认折叠「可读性自检」小节；文件缺席时小节与字段省略、退出码不变——应跑红
- [x] 1.8 兼容守护测：旧 draft（无 `repro`/`fix_diff`）→ 无对应展示、渲染不失败、
  `--check` 不报不一致（现状即绿的护栏，防实现期破坏）

## 2. 模式基础设施

- [x] 2.1 落地 `core/scripts/human_face_vocab.py`：词表常量（核心 10 词条 + 按域分组的
  补充词，sdr 激活、其余域预置）+ 扫描函数；每个词条带「人话替身」字段；初始内容按本
  change 的 `vocab-candidates.md` 定稿节落地；零依赖、无 CLI 入口；文件头注释写清维护
  办法（词条只经显式加一行增长，来源 = 评审建议 + 人工发现；同形词只收精确词形、NEVER
  单词子串禁；改词必须同步改 1.5 的内容锚测试）
- [x] 2.2 双端接线：渲染 `--check` 的告警面和回归测试面 import 同一常量（1.5 转绿的
  前提）

## 3. mgh-sdr 实现

- [x] 3.1 `render_sdr_report.py` 确定性文案平实化：分组概览改平实主句 + `<details>`
  折叠「分组诊断」明细（平实标签保留全部数字，数据文件字段不动）；诚实边界 ①–⑦ 与
  排除/失败/截断披露逐条转述（语义保留，去掉「facet」「与 sra/srr 的显式行为分歧」
  这类研发黑话）
- [x] 3.2 `render_sdr_report.py` 问题卡片：复现方式行 + 修改前/修改后 `<pre>` 上下堆叠
  （textContent 注入路线，`_json_embed` 转义覆盖）；数据 `findings[]` 透传新字段
- [x] 3.3 `render_sdr_report.py --check` 加模型文本闭集扫描（`risk`/`suggestion`/
  `repro`/`fix_diff`）：stderr 计数告警，退出码与文本零改动
- [x] 3.4 `render_sdr_report.py` 文本束与建议消费：每次渲染写
  `<run-dir>/readability_text_bundle.json`；发现可解析的
  `<run-dir>/readability_advisories.json` 就把 `readability[]` 并进数据文件、「可读性
  自检」小节并进报告；不可解析 = 省略 + stderr note
- [x] 3.5 `core/prompts/fragments/fanout/sdr-task.md`：Draft schema 示例扩
  `repro`/`fix_diff` + 写作纪律节（画像/首句现象/复现形态示例/前后对比条件/禁词）；
  输出字段描述改读者语言；增量约 15 行
- [x] 3.6 新增 `core/prompts/fragments/fanout/readability-review.md`（读者模拟评审任务
  模板：只读文本束 → 写建议文件 → 单行 ack；建议格式 = 词/句 + 字段 + 一句为什么难懂）
- [x] 3.7 三面 mgh-sdr 壳加「首次渲染后派发一次可读性评审、再重渲染」一步（opencode/
  claude/dsh 逐字镜像；标注尽力而为、失败继续）；三面 agent 定义（opencode/claude
  `sdr-review-fanout`、dsh `sdr`）的 Output schema 行 + 纪律指针同步
- [x] 3.8 `core/contracts/sdr/pipeline.md` draft schema 块同步（可选字段 + 兼容降级
  一句 + 文本束/建议文件两个约定路径）

## 4. 验证

- [x] 4.1 定向回归：`test_render_sdr_report` 全量 + `test_human_face_vocab` + 相邻面
  （`test_sdr_tier`/`test_sdr_failure_chain`/`test_resume_sdr_state`/
  `test_read_roots_config` 照跑）+ `test_zero_deps`/`test_no_compile_warnings`
- [x] 4.2 lint 四件套：`check_contracts`（无 flag 增删，面应不变）/
  `check_distributed_purity`/`check_distributed_prompt_budget`（sdr-task.md 增量受控）/
  `check_plain_language`
- [x] 4.3 实机冒烟：小仓（springBootTemplate 或等价）dry-run 重跑，按「一两年经验读者」
  视角人工通读：概览/边界直读无闭集词、复现方式与前后对比可见、折叠明细可展开、
  「可读性自检」小节出现且正文未被改动；`--check` 告警面观察（应零告警或仅模型抽签
  告警）；评审子代理失败一次（人为）验证尽力而为语义

## 5. 收尾

- [x] 5.1 VERSION bump + CHANGELOG 条目
- [x] 5.2 交接落账：记录扩展路径（mgh-init/ut-init/sast/sra/srr 逐命令接入，双受众取舍
  预案见 design D11，登记表在能力 `human-facing-output-discipline`）和词表增长流程
  （发现 → 确认 → 加一行 → 改锚测试），供后续 change 直接取用
