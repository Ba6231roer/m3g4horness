## Why

`/mgh-init` 的发现调用图是**纯文本/AST**(`discover_controls.build_call_graph`:name→files 两遍正则),
**解不动框架路由 / DI / AOP / interface→impl / 反射**——这些被 scout 明文丢进 `unresolved[]`
(`init-scout.md` 硬规则:「DI / AOP / reflection-only wiring … append the file to `unresolved[]`」)。
同时 scout 靠 **Read/Glob/Grep 逐文件爬**找自研控制,token/轮次随仓线性涨——恰在 mgh-init 自己
建议 `--scope`+`--merge` 的**大仓**上最痛。

当**目标项目已建了 codegraph 索引**(`<target>/.codegraph/`)时,那张预计算知识图谱(符号+调用边+
**17 框架路由**+interface→impl,单次 `codegraph_explore` 返回源码+调用路径+blast radius)能两路补:

1. **外科式上下文**:给 scout/induct/survey subagent 一次调用替代 Read 爬(benchmark:大仓 file-reads→~0);
2. **`unresolved[]` 解析器**:codegraph 的框架路由/跨文件解析,正是 mgh-init 文本图结构性漏掉的。

关键:**codegraph 是宿主能力(MCP 工具 / `codegraph` CLI),在 LLM 层消费,从不被任何 `.py` import**——
故零新增运行时依赖(R2)、确定性 `.py` 契约零改动(R5.3)、codegraph 缺席即 fail-soft 回退现状。

## What Changes

- **检测闸(编排器侧,Bash)**:起步 `test -d <target>/.codegraph && command -v codegraph`;默认 `auto`,
  `--no-codegraph` opt-out(对齐既有 `--no-scout` 模式)。信号透传给 subagent task。
- **共享提示词片段** `core/prompts/fragments/codegraph-hint.md`:codegraph 在场时,scout/induct/survey
  subagent **优先** `codegraph_explore`(MCP)/ `codegraph explore`(CLI Bash)取「符号源码 + 调用路径 +
  blast radius」,仅对 codegraph 未覆盖(非索引语言/超 `--big-file-bytes`)回退 Read。**主谓非「可」**
  ——规避 codegraph 官方警示的「subagent 仍去 Read,codegraph 成纯开销」陷阱(见 design D6)。
- **★ 新增可选 stage `init-resolve`**(插在 scout-merge 与 T1 之间):用 codegraph `callers`/`explore`
  + 框架路由解析排空 `unresolved[]` → `resolved.json`(每条带 `source:"codegraph"`、`file:line`、解析出的
  调用路径),**additive 并入候选集**(复用 `form_clusters`,不 mutate regex/scout 候选)。
  fail-soft:codegraph off → 整 stage 跳过,流程不变。
- **T1 induct advisory**:codegraph 在场时,cluster 控制的 blast radius(谁依赖它 / 是否接入请求路径 vs
  死代码)作 **advisory 证据**进 induct,强化「existence ≠ effectiveness」(承 CVE-2025-41248)。
- **覆盖披露(R5.4)**:`init_manifest.json` 增 `codegraph:{available,used,resolved_count,
  unresolved_residual}`;`report.md` 写明「codegraph 是否辅助 + 残留盲区」,**不声称全解析**。

## Capabilities

### New Capabilities
<!-- 无新能力。全部落在既有 control-discovery 内。 -->

### Modified Capabilities
- `control-discovery`: 增「可选 codegraph 富化」需求(检测闸 + subagent 外科式上下文 + T1 advisory +
  披露)与「`unresolved[]` 解析」需求(新 `init-resolve` stage,`source:codegraph` additive,fail-soft)。
  下游 `form_clusters` → T1 → T2 → T3 → T4 主链**不变**(resolve 只往候选集加料,如 scout)。
  `rules-emission` 不受影响。

## Impact

- **新增提示词**:`core/prompts/fragments/codegraph-hint.md`(共享,claude/opencode 同用);
  `core/prompts/stages/init-resolve.md`(排空 unresolved[])。
- **新增 subagent**:`init-resolve`(claude `agents/` + opencode `agent/` 双 shell 镜像)。
- **改动提示词**:`init-scout.md` / `init-induct.md` / `init-survey.md` 在 codegraph 在场时引用片段。
- **改动命令壳**:两份 `mgh-init.md`(claude/opencode)——起步检测段 + flow 插入 `init-resolve` 段 +
  `--no-codegraph` 参数 + stage→component 表 + 编排器声明。
- **改动契约/产物**:`core/contracts/init/candidates.md` 增 `source:"codegraph"` 说明;
  新增 `resolved` 契约;`init_manifest.json` 增 `codegraph:` 块。
- **确定性脚本**:**零改动**(`discover_controls.py` / `plan_scout.py` / `merge_scout.py` 契约不动,R5.3)。
- **依赖**:**零新增运行时依赖**(R2)。codegraph 是外部 MCP/CLI,从不 `import`;内网无 codegraph 的项目
  完全不受影响(fail-soft)。
- **hook(R5.7)**:**无需新增/改动**——`codegraph explore`(Bash)与 `codegraph_explore`(MCP)均**不**命中
  `block_adhoc_scripts` 的 `py -c` / ad-hoc `.py` / 子树外写任一拦截面;双端(claude + opencode)MCP 对等。
- **无 BREAKING**:codegraph off = 现状;产物全 additive;`controls_inventory.json` schema 不变
  (`source` 字段既有,新增一枚枚举值)。
