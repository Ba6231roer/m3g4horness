# Proposal: add-mgh-init-scout-fanout-runner

> **人话序**
> **现象**:大仓库跑 `/mgh-init`,scout 层可能切出几千个批;现状每个波次之间都要经过编排器
> (宿主 LLM)一个回合——看 ack、重跑 `list_scout_batches`、决定下一批、亲手撰写 5 个 subagent 的
> 任务消息。**根因**:「派发循环」是纯机械逻辑(取 pending → 派 5 个 → 收 ack → 翻页),却由
> LLM 回合执行;且每个 subagent 的任务输入由弱模型**逐次手写**(自由文本 + 路径靠概率复现),
> 已实证的失败形态包括:各 fanout 任务描述格式不一、`checkpoint_path` 漂到盘符根、下划线目录名被
> 概率性拼成分隔符对(`acme_wing` → `acme\wing`)。**改什么**:把波次循环下沉为产品自带的确定性
> dispatcher 叶脚本(`fanout_runner.py`,stdlib),编排器一次 `Bash` 调用 + `--resume` 重派跑完
> 整个 scout 层;每个 scout 的任务消息由脚本以**固定模板 + 从 `list_scout_batches` stdout 逐字
> 填充**生成,spawn 宿主 CLI(`claude -p` / `opencode run --agent init-scout`)并发执行,波次
> 边界零 LLM。**怎么验证**:`py tests/test_fanout_runner.py` 状态机/模板/守卫单测 +
> `tools/check_contracts.py`(新 flag lint)+ 双壳 token lint + 真机大仓冒烟
> (scout 批全 `.done`、编排器 scout 段 token 消耗对比)。

## Why

`/mgh-init` 的 scout 层在大仓下批量可达数千(`docs/opencode-subagent-fanout-analysis.md` §1:
波次边界必经编排器 LLM 回合,~1–3K token/波,是「大仓 token 浪费 + 弱模型漂移的根源」)。现状
两条既有防线只治了输入的**有界性**(`request-context-budget`:pending 壳 slim + per-unit
`input_path` 物化)与输入的**树内性**(`harden-mgh-init-scout-path-binding`:producer 物化绝对
路径 + reader 毒输入拒识),都没治「任务消息本身由弱模型逐次撰写」——格式不一、路径拼写错误
(盘符根漂移 / 下划线幻觉)是**概率性复现失败**,provenance recipe 只是提示词护栏,拦不住首次
生成错。分析文档 §3/§4 已论证目标形态(脚本化波次派发、编排器零介入)可行:subagent 的创建
本就不需要 LLM 参与,prompt 可由外部确定性输入完全决定。

## What Changes

- **新增确定性 dispatcher 叶脚本 `core/scripts/fanout_runner.py`**(stdlib,零运行时依赖承 R2):
  输入 = `list_scout_batches.py` 的 stdout JSON(逐字透传 `pending[]` 路径字段,承 R5.3b 扇出
  路径契约),内部做波次循环(取下 N 个 pending → 并发 spawn 宿主 CLI → 解析 ack → 更新
  pending)——**纯代码,零 LLM 回合**;支持 `--resume`(重派直至 `partial:false`)、
  `--time-budget-ms` 软时限干净早退(R5.4 长跑契约)、per-call `timeout`、stdout 结构化摘要
  `{total, done, failed, pending, partial}`(R5.3b I/O 契约)。
- **subagent 任务消息由脚本确定性构造**:固定模板(`core/prompts/fragments/fanout/scout-task.md`)
  + 从 `pending[]` 逐字填充(`input_path`/`checkpoint_path`/`done_marker`/`failed_marker`/
  `slice_dir`/`chunk_sources` 绝对路径/codegraph 信号)——「同一系统提示 + 同格式任务内容」
  由**构造**保证,不再依赖编排器逐次手写,路径拼写错误类失败从根上消失。
- **宿主 CLI spawn 适配层**:`fanout_runner.py` 探测宿主(`claude`/`opencode` 在 PATH)并映射到
  各自的 headless 调用(`claude -p --agents <init-scout 定义> --allowedTools ...` /
  `opencode run --agent init-scout`);CLI 不可用 → fail-loud 退出码 2 + recipe(回退 = 现状
  波次式编排器手派,行为不变)。
- **命令壳/fragment 改造**:`init-stage/scout.md` 派发段改为「先跑 `fanout_runner.py`(Bash,
  per-call timeout),`partial:true` → 重派同一命令;CLI 不可用回退手派」;scout 步入
  `list_steps.py` 契约面增 dispatcher 调用行。
- **回退语义不变**:`.failed` 终态 / crash 无 ack → 留 pending → resume 重派 / `.done` 磁盘
  真相源 / 哨兵 hook 守卫激活(子进程经磁盘哨兵 `<target>/.mgh-init/.active`,R5.7)全部原样承接。
- **回归**:dispatcher 状态机/模板填充/守卫交互单测、契约 lint、双壳 token lint、install 自检
  清单增 `fanout_runner`、版本号 bump。

## Capabilities

### New Capabilities

- `fanout-dispatch`:确定性 fan-out 派发基座——产品自带 dispatcher 叶脚本消费枚举脚本 stdout
  `pending[]`,以固定模板构造 subagent 任务消息、spawn 宿主 CLI 并发执行波次,零 LLM 回合;
  覆盖 resume/partial/timeout/ack 状态机与宿主 CLI 探测回退。mgh-init scout 是首个消费方,
  T1/T3/sra-augment 同构可复制(不在本 change 范围)。

### Modified Capabilities

- `request-context-budget`:「Orchestrator context is bounded by a slim paged work-list」
  requirement 增量——编排器取待办、驱动 fan-out 的方式新增确定性 dispatcher 路径:scout 步
  编排器 SHALL 一次 `Bash` 调用 `fanout_runner.py`(其内部按 `--orch-budget-bytes` 同源预算
  分页消费 pending),`partial:true` 重派;该路径下编排器 NEVER 手动翻页、NEVER 逐次撰写
  subagent 任务消息(由模板 + 逐字字段填充构造)。

## Impact

- **代码**:新增 `core/scripts/fanout_runner.py`、`core/prompts/fragments/fanout/scout-task.md`;
  改 `core/prompts/fragments/init-stage/scout.md`、`core/scripts/list_steps.py`(scout 步契约
  面)、`releases/{claude-code,opencode}/` 双壳 mgh-init(如需)、`releases/claude-code/agents/`
  init-scout agent 定义装载方式(headless spawn 需可寻址)、`install.sh` 自检清单、
  `tests/test_fanout_runner.py` 新增、版本号 bump。
- **既有安装项目**:重跑 `install.sh` 获新脚本 + fragment;无磁盘 schema 变更
  (`run_config.json`/`init_manifest.json` 不动)。
- **风险**:① 宿主 CLI headless spawn 是新执行面(`claude -p` / `opencode run` 的 flags/行为
  需 spike 实证,分析文档 §6 开放问题 1/2:并发 SQLite、`--agent` 显式指定);② claude 侧
  agent 定义须可被 headless 寻址(`--agents` 内联 JSON 或 install 落位);③ 并发子进程与
  hook 哨兵交互(磁盘哨兵本为跨进程边界设计,预期兼容,需真机冒烟)。spike 失败 → 回退路径
  = 现状波次式手派,行为不变(fail-loud + recipe)。
- **非目标**:不治 T1/T3/sra-augment 的 dispatcher 采纳(同构可复制,后续 change);不改
  `.done`/`.failed` marker 契约与 resume 磁盘真相源语义;不引入任何 pip 依赖(spawn 用
  stdlib `subprocess` + `concurrent.futures`)。
