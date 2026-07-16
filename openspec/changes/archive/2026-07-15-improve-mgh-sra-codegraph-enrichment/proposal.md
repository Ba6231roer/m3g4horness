## Why

`/mgh-sra` 的三信号匹配里,**信号-2「业务域相似」是语义判定**——靠接口路径文本相似 +
`file_overlap`(文本相交)推断「这条存量控制守护的是同业务域类似接口」。这条信号回答不了**结构性**
问题:**该控制到底接没接到这条缺口的接口的请求路径上?**——而它恰恰由 `@PreAuthorize`/AOP pointcut/
DI 织入的拦截器/Feign 路由表等**框架路由**决定,文本/AST 解不动(与 mgh-init 文本调用图同样的盲点,
落到 mgh-init 就是 `unresolved[]`)。结果:一份「文件重叠」的存量控制可能被语义误推为「可复用」,
而它其实根本不在该接口的请求链上(对这条缺口而言近乎死代码)——这正是 SRA 自己写的诚实边界
「维度匹配为语义判定,可能误接或漏接」+「引用控制断言存在不断言有效」。

同时 a3 augment subagent 靠 **Read/Glob/Grep 逐文件爬**核验锚点真实(`sra-augment.md` 明示
「可读目标项目源码以核验锚点真实」),token/轮次随仓线性涨;而 `prepare_augment.py` 的业务面抽取器
(`_ENDPOINT_RX`/`_ROLE_HAS_RX`/`_SENS_SUBSTR`)也**全是文本正则**,抓不到框架注解/路由表里的真实端点与角色。

当**目标项目已建了 codegraph 索引**(`<target>/.codegraph/`)时,那张预计算知识图谱(符号+调用边+
**17 框架路由**+interface→impl,单次 `codegraph_explore` 返回源码+调用路径+blast radius)能两路补:

1. **外科式上下文**:给 sra-clarify/sra-augment subagent 一次调用替代 Read 爬;
2. **★ 请求路径结构确认**:codegraph 的框架路由/跨文件解析,把「该控制是否接在缺口接口的请求路径上」
   从语义判定升级为**结构证据**,直击 SRA 的「误接/漏接」盲区——**这是本变更与 mgh-init codegraph
   富化最独特、最高价值的契合点**(对标 mgh-init 的 `unresolved[]` 解析)。

关键:**codegraph 是宿主能力(MCP 工具 / `codegraph` CLI),在 LLM 层消费,从不被任何 `.py` import**——
故零新增运行时依赖(R2)、确定性 `.py` 契约零改动(R5.3)、codegraph 缺席即 fail-soft 回退现状。

## What Changes

- **检测闸(编排器侧,Bash)**:起步 `test -d <target>/.codegraph && command -v codegraph`;默认 `auto`,
  `--no-codegraph` opt-out(对齐既有 `--no-scout`/`--rules` 可选模式)。信号透传给 a2/a3 subagent task。
- **复用共享提示词片段** `core/prompts/fragments/codegraph-hint.md`(由姊妹变更 `improve-mgh-init-
  codegraph-enrichment` 引入;本变更复用同一通用片段,若该片段尚未存在则创建之,与该变更字节级一致):
  codegraph 在场时,a2/a3 subagent **优先** `codegraph_explore`(MCP)/ `codegraph explore`(CLI Bash)
  取「符号源码 + 调用路径 + blast radius」,仅对 codegraph 未覆盖项回退 Read。**主谓非「可」**——规避
  codegraph 官方警示的「subagent 仍去 Read,codegraph 成纯开销」陷阱。
- **★ a3 augment 的「codegraph 结构证据确认」(inline,非新 stage)**:codegraph 在场时,a3 用它把三信号
  语义判定里**文本/AST 解不动**的结构性问题补成**结构证据**(advisory)。四个 facet 共用同一机制
  (`codegraph_explore` 调用路径 / `callers` / `callees` + 框架路由),bounded/fail-soft:
  (1) **call-path(首要,唯一入 draft 结构字段)**——已 `recommended_control` 的控制是否接在该缺口接口的
  **请求路径上**(入口 → 受保护资源)→ draft `recommended_control.call_path:{confirmed, path[], source:"codegraph", note}`;
  确认 → 强化「复用」措辞,不在路径 → 降级置信 + 注「控制存在但未确认接入此接口」;
  (2) **data-flow 可达性**(callees)——缺口的敏感字段是否真被该接口**流向/返回/落日志**(治 sensitive-data/
  injection 维度的伪缺口,改善 `risk`/锚点质量,非新字段);
  (3) **控制存活 liveness**(blast radius)——推荐控制是否有 caller、还是近乎死代码(强化「存在≠有效」,入 `note`);
  (4) **domain-sibling 聚类**——枚举该接口**同业务域兄弟接口及其守卫控制**,把信号-2「业务域相似」从文本路径
  相似升级为结构聚类(改善 `reason`,非新字段)。**bounded + fail-soft**:每 capability 的 a3 隔离上下文内,只对该
  上下文**已推荐控制 / 已锚定缺口**做(非全部候选);(缺口×控制×facet)过多超单上下文预算 → 解析每缺口 top-1 控制
  的**首要 facet(call-path)**、其余 `confirmed:null` + 摘要披露,流程不阻断。**确定性脚本零改动**
  (`prepare_augment.py`/`merge_augment.py`/`merge_memory.py` 契约不动,R5.3)——`call_path` 是 a3 subagent 在
  draft(自由 JSON)里写的 advisory 字段,不入确定性契约;facet 2–4 以改善既有 `evidence`/`risk`/`reason` 的 advisory
  形式体现,不新增 schema。
- **a2 clarify 次要 advisory**:codegraph 可预解析「谁调用该接口」(`callers`→角色)、「该字段是否敏感且可达」
  (data-flow)、「同域既有鉴权范式」(domain-sibling)→ 减少部分角色/归属/敏感字段/范式澄清问(codegraph-sourced
  事实,优先级低于用户断言/代码声明,不覆盖 `business_context.json`)。
- **覆盖披露(R5.4)**:`sra_manifest.json` 的 `counts` 增 `call_path_confirmed`/`call_path_residual`;
  `boundaries[]` 新增「codegraph 是否辅助、确认了 N 条推荐、残留 M 条未确认;语义匹配仍近似」。**既有四条
  诚实边界不动**(语义匹配仍真;codegraph 是其上的可选结构确认)。

## Capabilities

### New Capabilities
<!-- 无新能力。全部落在既有 security-augmentation 内。 -->

### Modified Capabilities
- `security-augmentation`: 增「可选 codegraph 富化」需求(检测闸 + subagent 外科式上下文 + a2 clarify
  advisory + 披露)与「请求路径结构确认」需求(a3 augment inline 的 call_path advisory 信号,refine 信号-2,
  bounded/fail-soft)。下游 a4 一致性、a5 合并主链**不变**(call_path 是 draft advisory 字段,合并渲染时
  作为推荐置信/措辞,不改受管块契约)。同时「Parse arguments」需求增 `--no-codegraph` flag。
  `business-context-memory` 不受影响(clarify 仍幂等累积,codegraph 仅减问不增问)。
  **明确不做**:用 codegraph 自动**播种** `business_context.json`(自动产 `interface_authz[]`/
  `sensitive_fields[]` 初始条目)——这是真实可优化点,但触记忆 schema + `merge_memory.py` 语义 + 下游
  `/mgh-blst` 消费口,属 Tier C,本变更(Tier B,与 mgh-init codegraph 富化对称)显式**拆后续变更**(见 design Non-Goals)。

## Impact

- **复用提示词**:`core/prompts/fragments/codegraph-hint.md`(共享,与 `improve-mgh-init-codegraph-
  enrichment` 同一片段;若该变更尚未 apply,本变更新建之,内容一致)。
- **改动提示词**:`core/prompts/stages/sra-augment.md`(增 `codegraph=on` stanza:外科式上下文 +
  call_path 确认信号)、`core/prompts/stages/sra-clarify.md`(增 `codegraph=on` stanza:callers 预解析
  advisory)、`core/prompts/stages/sra-consistency.md`(a4 透传 call_path 字段,去重时归一其措辞)。
- **改动命令壳**:两份 `mgh-sra.md`(claude/opencode)——起步检测段 + `--no-codegraph` 参数 + step 1(a1)
  后置 `codegraph=on|off` 信号透传 + a2/a3 task 输入含信号 + Stage→component 表脚注 + 编排器声明。
- **改动契约/产物**:`core/contracts/sra/augmentation.md` 增 draft `recommended_control.call_path`
  optional 字段说明 + `sra_manifest.json::counts` 增 `call_path_confirmed`/`call_path_residual` +
  `boundaries[]` 增 codegraph 披露条。`change_context.json` schema **不变**(candidate_controls 仍文本抽取)。
- **确定性脚本**:**零改动**(`prepare_augment.py`/`merge_augment.py`/`merge_memory.py` 契约不动,R5.3)。
- **依赖**:**零新增运行时依赖**(R2)。codegraph 是外部 MCP/CLI,从不 `import`;内网无 codegraph 的项目
  完全不受影响(fail-soft)。
- **hook(R5.7)**:**无需新增/改动**——`codegraph explore`(Bash)与 `codegraph_explore`(MCP)均**不**命中
  `block_adhoc_scripts` 的 `py -c` / ad-hoc `.py` / 子树外写任一拦截面;双端(claude + opencode)MCP 对等。
- **跨变更依赖**:复用 `improve-mgh-init-codegraph-enrichment` 引入的 `codegraph-hint.md` 片段。两变更可任意
  顺序 apply;若 SRA 先 apply 且片段缺失,本变更新建之(同内容),init 变更 apply 时幂等跳过。
- **无 BREAKING**:codegraph off = 现状;产物全 additive(draft 增 optional 字段,manifest 增计数字段);
  `change_context.json`/`business_context.json` schema 不变;a4/a5 主链不变。
