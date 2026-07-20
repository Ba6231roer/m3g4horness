## Context

`/mgh-sra` 与 `/mgh-srr` 共享一条中间引擎:`prepare_augment.py`(sra a1)/ `ingest_requirements.py`
(srr r1)产同 shape 的 `change_context.json` → 编排器 spawn `sra-clarify`(a2)/ `sra-augment`(a3)
subagent,后者读 `core/prompts/fragments/security-dimensions.md`(**逐维度**扫全 9 类)。9 维度键今天
已是闭集(`prepare_augment.py::DIMENSIONS_BY_CATEGORY` 派生 + 目录维度键),但**没有任何入口收窄
范围**,更无维度内子项(如 sensitive-data 只看身份证/银行卡)的过滤。本设计加一个**默认不动、可
参数化收窄**的「维度聚焦」层,且能下钻 facet。

约束:R2(零运行时依赖)、R5(CLI 契约 = `--help`、`--check` 边界校验、双端壳镜像、确定性脚本闭集)、
R3(文档简练)、R5.10(分发物纯净)。向后兼容是硬要求(R5 稳定性):无 `--focus` 须逐字等价今天。

## Goals / Non-Goals

**Goals:**
- 默认全 9 维度(零回归);`--focus` 可收窄到任意子集 + 维度内 facet 子集。
- focus 解析/校验确定性、闭集、零 token 早停(任何 LLM 之前)。
- sra/srr 共享同一 focus 契约;srr **零新增提示词**复用(sra-clarify/sra-augment 加一段共享覆盖层)。
- 聚焦范围在 manifest/报告明示(诚实边界)。

**Non-Goals:**
- 不改 9 维度本身(focus 只收窄,不扩展)。
- 不引入预设简写(`--focus auth`);MVP = 显式 dimension/facet 列表。
- 不持久化 focus 进 `business_context.json`(单次运行参数)。
- 不动 a4/a5/codegraph(处理 a3 已产出的范围内缺口,天然兼容)。

## Decisions

### D1 — focus 输入形态:单个结构化 flag `--focus <inline-json|path>`,不用扁平 csv
focus 需表达「维度列表 + 嵌套的每维度 facet 白名单」,这是树形,扁平 `--dimensions a,b` + `--facets ...`
要么表达不了嵌套、要么要发明第二套语法。单个 JSON flag 统一表达 + 统一闭集校验。**输入判别(无歧义)**:
值以 `{` 起首 = inline JSON;否则 = JSON 文件路径(裸路径 `config/focus.json` 即可,前导 `@` 可选、会被
剥离;文件缺失/不可读 exit 1)。这让用户能把 focus 存成项目文件反复用。**flag 名保留 `--focus`**:它
同时收窄维度 + facet(不止维度),`--dimensions` 反而误导;且与 sra/srr 既有 flag(`--change`/`--rules`/
`--doc`/`--text`/...) 无冲突。
**替代(否决)**:`--dimensions`/`--facets` 两个扁平 flag——表达不了「sensitive-data 只看 id-card+bank-card
而 injection 全要」这种 per-dimension facet 映射。

### D2 — 新增共享模块 `focus_scope.py`,不内联进两个适配器
两适配器(prepare_augment / ingest_requirements)需**逐字相同**的 parse/validate/render;ingest 已
`import prepare_augment as _sra` 复用其机械抽取器,再加一个 sibling `focus_scope` 同模式(sys.path.insert
自定位,R5.3a)是自然延伸,且闭集 registry 单一真相源、可独立单测。
**替代(否决)**:逻辑抄进两个脚本——闭集 registry 会漂移、双份维护。

### D3 — 校验落在确定性 a1/r1 阶段(任何 LLM 之前),不在编排器壳里
a1/r1 本就是确定性、无 LLM token 的阶段,且是 a2 之前唯一的 choke point。把 `--focus` 解析/校验放
这里 = 复用既有 `--check` 边界校验范式(R5.9)+ 满足「validate BEFORE spending tokens」。编排器只读
`change_context.focus.directive` 逐字透传给 subagent(零重算、零拼装,承 R5.2/R5.3)。

### D4 — focus 指令 = 渲染好的简体中文句子,逐字透传给 subagent(不传原始 JSON)
LLM 对自然语言指令比对嵌套 JSON 更稳。`focus_scope.py` 确定性渲染一条指令(维度 label + facet label
+ 「范围外不产缺口/不发澄清」),编排器逐字塞进 a2/a3 task 输入。同输入 → 字节一致指令(可复现)。
sra-clarify/sra-augment 各加**一小段覆盖层**(「传入 directive 时 SHALL 只扫列出的维度/facet,范围外
SHALL 不产缺口/澄清;无 directive = 全 9 维度」),srr 逐字复用这两份提示词 → 自动获得,零新增提示词。
**替代(否决)**:传原始 JSON 给 subagent 自行解释——LLM 解释嵌套结构更易漂移。

### D5 — facet 只在目录已枚举离散子类的维度上定义(sensitive-data / injection),其余 7 维度整维
facet 词汇严格镜像 `security-dimensions.md` 自己列出的子类(sensitive-data: 身份证/银行卡/手机/邮箱/
密码/token;injection: SQLi/XSS/命令注入/路径穿越/SSRF/反序列化/XXE)。其余维度(横向/纵向越权、认证、
完整性、审计、限流、密钥)目录无离散子类 → 不设 facet(整维收窄)。这把用户示例(「敏感数据只看身份证
和银行卡」)精确覆盖,且避免凭空发明词汇。新增维度/facet = registry + 目录协同改(受控扩展,非自由文本)。

### D6 — `focus: null` = 全 9 维度(向后兼容信号),字段恒在
解析后 focus 要么是 `{dimensions[], facets{}, directive}` 对象、要么是 `null`。`null` 明确表示「不收窄」,
subagent 覆盖层判 `if directive 缺省`。字段恒在 = schema 稳定;无 `--focus` 时 `focus: null`,行为逐字等价
今天(硬性回归门)。

### D7 — 向后兼容是硬要求,非可选
无 `--focus` 路径产出的 `change_context.json`/draft/manifest 在**行为**上须与今天等价(focus=null、无
directive 注入、manifest focus=null 无额外边界)。既有 `test_sra_prepare.py`/`test_srr_ingest.py` 须全绿
不改。这条承 R5(mgh-* 稳定性是产品特性)。

## Risks / Trade-offs

- **[覆盖层可能泄漏范围外缺口]**(提示词护栏非确定性)→ 缓解:指令用规定性措辞(`SHALL 只…;范围外
  SHALL 不产`);承 R5.7 评估驱动:改提示词前 baseline ≥5 次 capture 失败模式,A/B 对比 pass rate;
  测试断言 draft `gaps[].dimension` ⊆ focus 维度。残留非确定性如实披露(同既有纯净性 lint 的诚实边界)。
- **[registry 与目录漂移]** → 缓解:registry 是闭集单一源;目录标注匹配的 facet 键;测试断言 registry
  9 维度键 == 目录维度键列。
- **[focus 过窄漏真缺口]** → 缓解:这是用户显式选择;manifest/报告**显著**披露聚焦范围(诚实边界);
  空维度集(会啥也不查)被闭集校验拒(exit 2)。
- **[闭集拒掉合理新维度需求]** → 缓解:受控扩展(registry+目录协同改)是有意设计,非缺陷。
- **[srr 提示词复用假设]** → 缓解:覆盖层在共享 sra-clarify/sra-augment;srr 零新增提示词;既有
  `test_*_codegraph_parity.py` 同模式的复用断言可参照新增 focus 复用断言。

## Migration Plan

纯增量,无数据迁移。focus 是单次运行参数,**不**写进 `business_context.json`(区别于跨迭代记忆)。
部署:新增 `focus_scope.py` + 改两适配器/两提示词/四壳/目录/两契约文档 + 测试 + 版本号。
回滚:revert 受影响文件即可(无持久状态变更)。install 分发物须过 `check_distributed_md_purity`(R5.10)。

## Open Questions

- **预设简写**(`--focus auth` = 横向+纵向+认证)?MVP 不做;闭集友好,可作后续 registry 扩展(`presets`
  表 + 服务端展开),届时同步四壳 `--help`。
- **项目级默认 focus**(如 `.mgh-sra/focus.json` 作默认)?MVP 不做;但 `--focus @.mgh-sra/focus.json`
  的 `@path` 形态已让用户手动达成,零额外机制。是否要「自动加载项目默认」留后续。
