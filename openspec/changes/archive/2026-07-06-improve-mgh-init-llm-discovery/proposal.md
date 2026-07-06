## Why

当前 `/mgh-init` 的发现是一个**硬编码正则闸门**:`discover_controls.py` 的 `_QUICK_RX`
预过滤(`discover_controls.py:118` + `:296`)对每个文件做「是否命中 ~120 个规范
token 之一」的判断,**不命中的文件整文件丢弃,永不进入任何 LLM**。其后果是:对
**非 Spring / 大量自研封装安全组件**的项目,凡命名不撞规范词(authentication/
authorization 几乎 100% Spring 类名,csrf 全 Spring)的自研控制——`PermGuard`/
`TokenInterceptor`/`FlowControl`/`TraceLogger` 等——在 i1 即被结构性丢弃,后续
T1/T2/T3 的 LLM 理解力再强也看不到它们(且 `init-survey` 提示词明令「NOT to re-scan
from scratch」,其产出还「非 T1 输入」)。

init 一般是**每项目一次性**任务,token 消费可接受。因此正解不是「省 token 的规则
闸门」,而是把 **LLM 上移到「选择之前」**:让它在全仓廉价元数据(包路径/类名/签名/
导入/扇入)上自己决定读谁,而非让一道规则替它筛掉。规则的角色从**有损语义闸门**
降级为**无损机械抽取 + 噪声剪枝**,所有「这是不是控制」的语义判断交给 LLM。

## What Changes

- **regex 从闸门降级为 fast-path hint**:i1 正则仍产出高置信的规范 token 命中(作
  为稳定锚点 + T1 grounding),但**不再是「LLM 能看到什么」的过滤器**。发现候选集
  改为 **regex ∪ scout 双源并集**,每条候选带 `source: regex|scout`。
- **新增无损骨架抽取**:搭 i1 已有的单遍 I/O 顺风车(`walk_sources`/`CLASS_RX`/
  `JAVA_DEF`/reverse graph 已算),为**每个**源文件产出 `{pkg, classes[], imports[],
  method_sigs[], fan_in, bytes}` 骨架 → `skeleton.json`。纯机械抽取,**不判断「是不是
  控制」**;新增 imports 正则即可(其余原语已存在)。
- **新增 LLM scout 发现层**(插在 i1 与 T1 之间):scout 读 `skeleton.json` + repo,
  自适应地 Glob/Grep/Read,找出 regex 漏掉的自研控制,按 Candidate schema 子集吐
  锚点 → `scout_candidates.json`,merge 进候选集后走既有 `form_clusters`。
- **scout 并行 fan-out 策略**(本变更核心):确定性**按字节预算 + 包内聚**把 scout
  目标切成批次(批数 = `ceil(目标总字节 / --scout-batch-bytes)` 涌现而出,非拍脑袋),
  每批一个**隔离 subagent** 深读、最多 `max_concurrent`(默认 8)并行;再由单个
  subagent 在**仅结构化记录、无原始码**上做 merge(复刻既有 T1→T2 隔离模式 D12)。
  单个超批文件经既有 `chunk_sources.py` 切片。
- **新增自检采样(false-negative hunt)**:随机抽取一批 scout **拒绝的**骨架,由一个
  怀疑论 subagent 复核——拿 token 预算买「防漏」,而非买「省」。
- **覆盖披露**:`init_manifest.json`/`report.md` 写明「LLM 审视了 X/Y 个骨架、深度
  Read 了 Z 个、自检复核了 K 个」+ 残留盲区,**不声称全仓覆盖**(R5.4 无静默截断)。
- **新增产物 / 契约字段**:`skeleton.json`、`scout_plan.json`、`scout_candidates.json`、
  `checkpoints/scout/**`;`Candidate`/`Cluster` 增**可选** `source` 字段(additive,向后
  兼容)。新增参数 `--no-scout`/`--scout-budget`/`--scout-batch-bytes`/`--scout-audit-pct`
  + `init.yaml` 的 `scout:` 块。

## Capabilities

### New Capabilities
<!-- 无新能力。全部落在既有 control-discovery 内。 -->

### Modified Capabilities
- `control-discovery`: 发现机制由「正则闸门」改为「正则 fast-path ∪ LLM scout 双源」;
  新增无损骨架抽取、scout 并行 fan-out、自检采样、`source` 溯源、覆盖与残留盲区披露。
  下游 `form_clusters` → T1 → T2 → T3 → T4 流水线**不变**(scout 只往候选集里加料)。
  `rules-emission` 不受影响。

## Impact

- **新增脚本**:`core/scripts/plan_scout.py`(确定性批次规划器,枚举 pending 批次供
  编排器 fan-out,对标 `list_clusters.py`)。骨架抽取**并入** `discover_controls.py`
  的既有单遍(保 FD3 单遍 I/O;见 design D2 的替代方案讨论)。
- **改动脚本**:`discover_controls.py` 增 `skeleton.json` 输出 + 候选标 `source`;
  `_QUICK_RX` 预过滤的语义从「丢弃」降级为「仅 regex fast-path 跳过(文件仍 scout 可见)」。
- **新增提示词**:`core/prompts/stages/init-scout.md`(per-batch 深读)、
  `init-scout-merge.md`(结构化 merge)、`init-scout-audit.md`(自检采样)。
- **新增 subagent**:`init-scout` / `init-scout-merge` / `init-scout-audit`(claude +
  opencode 双 shell 镜像)。
- **改动命令壳**:两份 `mgh-init.md`(claude/opencode)在 i1 与 T1 之间插入 scout
  fan-out 段 + 新参数表 + 编排器声明。
- **改动 profile**:`core/profiles/init.yaml` 增 `scout: {enabled, model, budget_files,
  batch_bytes, audit_pct, max_concurrent}`。
- **改动契约**:`core/contracts/init/candidates.md`、`clusters.md` 增 `source` 字段
  说明;新增 `skeleton`/`scout_plan`/`scout_candidates` 契约(并入既有 init/ 目录)。
- **新增单测**:`tests/test_scout_plan.py`(字节预算+包内聚分批、超批走切片、resume)、
  `tests/test_skeleton.py`(imports 抽取、复用既有原语无回归)。
- **依赖**:**零新增运行时依赖**(R2)。`plan_scout.py`/骨架抽取仅标准库;不 import
  `vvaharness`,不引入 Semgrep/CodeQL/tree-sitter。
- **无 BREAKING**:scout 默认开启,但 `--no-scout` 完整保留旧行为(纯 regex 闸门);
  产物全部 additive;下游 `mgh-sra`/`mgh-blst`/未来 mgh-sast 控制入口消费的
  `controls_inventory.json` schema 不变。
