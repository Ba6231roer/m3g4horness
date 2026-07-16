## Why

`/mgh-sra` 把整套安全需求分析能力**绑死在 openspec 上**:输入靠 `prepare_augment.py`
正则解析变更文件、按 `specs/<cap>/` 拆模块,输出靠 `merge_augment.py` 写回 specs/tasks
受管块。但真实世界大量需求是 **word / txt / md / excel 的原始文字描述**——既没有 openspec
结构,也可能**根本不含具体接口 / 字段**。sra 的备料阶段对这两者做了硬假设,从**全局**把
工具族的能力边界限死:**非 openspec 项目用不了,纯文字需求用不了**。

机会在于:sra 真正值钱的**中间引擎**(9 维度缺口扫描 + 三信号控制复用匹配 + 批量澄清 +
项目级业务记忆 + 诚实边界)是 **openspec 无关**的——它操作的是抽象
`{capabilities, requirements, endpoints, fields, roles, candidate_controls}`。openspec 的耦合
只卡在**两个适配器接缝**:输入解析 + spec 合并。`/mgh-srr`(Security Requirements Review)
做**端口-适配器**:换上「自由文本输入适配器」+「普通报告输出适配器」,中间引擎**原样复用**。
于是无 openspec 的项目、纯文字需求也能做安全需求识别 + 部分安全设计提醒,产物只是一份**普通、
简要的报告**——不碰任何 openspec 内容。

为什么现在:复用比新建便宜得多(只写 2 个确定性适配器脚本 + 1 个薄命令壳,stage 提示词 /
subagent / 维度目录 / 记忆脚本**零新增**),却解锁一个全新使用场景。

## What Changes

- **新增 `/mgh-srr` 命令**(claude + opencode 双壳):自由文本需求 → 复用 sra 中间引擎 →
  普通安全评审报告。编排器仍 = 宿主 agent(承 sra 编排纪律),确定性叶脚本经 `Bash` 调用。
- **新增确定性输入适配器** `core/scripts/ingest_requirements.py`(标准库):text-native
  (`.txt/.md/.csv/.json` 完美)+ stdlib `zipfile`+`xml.etree` 尽力抽 `.docx`/`.xlsx`
  (按段落拼 `<w:t>` 防 token 碎裂;Excel 日期 / 格式降级、列表编号丢失等**显式标注降级**)
  + **永远留 `--text`/stdin 透传口**(抽不好就贴文本,质量顾虑永不卡死)。产出与 sra **同 shape**
  的 `change_context.json`(默认单 capability、接口/字段/角色为可选 hint);`--check`(R5.9)。
- **新增确定性输出适配器** `core/scripts/render_report.py`(标准库):读定稿 draft + 可选记忆
  → 普通的 `security_review_report.md`(简体中文·简要·面向人读)+ `srr_manifest.json`
  (counts + boundaries);**NEVER 写进 openspec**;`--check`。
- **逐字复用 sra 核心**(零复制、零新增):stage 提示词 `sra-clarify.md` / `sra-augment.md` /
  `sra-consistency.md`、`fragments/security-dimensions.md`、`fragments/codegraph-hint.md`、
  `merge_memory.py`、`business_context.json` 契约。SRR 只是把同 shape 的上下文喂给同一批 subagent。
- **新增契约** `core/contracts/srr/intake-report.md`:自由文本 intake 的 `change_context.json`
  shape delta(相对 sra)、report / `srr_manifest.json` shape、`--check` 规则。
- **新增 profile** `core/profiles/srr.yaml`。
- **扩 `block-adhoc-scripts.py`(install 注入目标仓)** 加运行域 `MGH_SRR_ACTIVE` + 子树守卫
  (治 #1 违例 = 微脚本内省 / 越权写;`MGH_TARGET`=项目根,覆盖报告输出 + 项目记忆;双端 parity)。
- **新增单测** `tests/test_srr_ingest.py`(格式抽取 + Word 跨 run 拼接 + 降级标注 + 透传)、
  `tests/test_srr_report.py`(报告渲染 + 不触 openspec + manifest);扩 `check_contracts.py`
  srr flag lint + distributed-purity。
- **新增文档** `docs/mgh-srr-工作流程详解.md`;`AGENTS.md` 命令表加 `/mgh-srr` ✅;`README` 登记。
- **诚实边界**:产物明示「LLM 候选需人工复核 / 覆盖取决于需求文档声明 + 已记业务事实 / 引用控制
  断言存在不断言有效 / 记忆为用户断言非代码真相 / codegraph 为可选 advisory」**+ SRR 专属**:
  「输入抽取对 .docx/.xlsx 有已知降级(日期 / 格式 / 列表);报告质量受输入完整度上界约束——
  含糊的需求文档只能产锚点稀疏的泛化缺口」。

## Capabilities

### New Capabilities

- `freeform-security-review`: 无 openspec 的自由文本需求(word/txt/md/excel/透传)→ 经确定性
  intake 适配器产出 sra 同 shape 上下文 → 复用 sra 中间引擎(澄清 / 增广 / 对账 + 9 维度 + 三信号
  匹配 + 项目记忆)→ 经确定性 report 适配器产普通报告(NEVER 触 openspec)。定义「自由文本 intake →
  复用引擎 → 普通报告」的接缝契约与 sra 的 delta。

### Modified Capabilities
<!-- 无。security-augmentation / business-context-memory 的 requirement 不变,SRR 是其消费者;
     business_context.json 复用同一份(跨 sra/srr 累积,shape 不变),不改契约。 -->

## Impact

- **新增**:2 适配器脚本 + 1 契约 + 1 profile + 1 命令壳(双端)+ 2 单测 + 1 文档。stage 提示词 /
  subagent / 维度目录 / 记忆脚本**零新增**(全复用)。
- **改动**:`block-adhoc-scripts.py` 加 `MGH_SRR_ACTIVE` 运行域 + 子树守卫;`install.sh` 纳入 srr
  资产 + 自检;`AGENTS.md` / `README` 状态表;`tools/check_contracts.py` 加 srr CLI flag lint。
- **依赖**:零新增运行时依赖(R2);`.docx`/`.xlsx` 走标准库 `zipfile`+`xml.etree`,**不** `pip`。
- **无 BREAKING**:新增命令 + 新增能力;现有 `/mgh-sra` / `/mgh-sast` / `/mgh-init` 字节级不变;
  `business_context.json` 被 srr 复用(同文件累积,shape 不变)。
- **产物消费方**:报告 standalone 给人读;`business_context.json` 跨 sra/srr 累积,并为未来 `/mgh-blst`
  预留消费口(据角色 / 越权范式设计业务耦合测试)。
