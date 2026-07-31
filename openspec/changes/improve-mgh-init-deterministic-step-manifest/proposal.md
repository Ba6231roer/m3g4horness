## Why

`/mgh-init` 真机跑里出现过 **#1 路径漂移**:opencode 下模型把脚本调用路径猜成 `scripts/merge_scout.py`
(实际是 `.opencode/mgh-core/scripts/merge_scout.py`),靠自探索重试才找到。根因不是「信息缺失」——
两份命令壳(claude/opencode)正文里**已有** stage→组件表 + `Deterministic invocation` 示例块 +
implementation-intention recipe,路径/IO/格式事实**全在**,但**散落**在五处(inline flow / 组件表 /
调用示例 / recipe / Output 节),上下文压力下模型没能正确合成,转而猜前缀。用户「衍生想法」要求把
每步的 {输入格式 / 脚本绝对路径 / 产物路径 / 产物格式} 以**每次执行都能准确确认**的形式落地。

D6(`harden-mgh-opencode-hook-enforcement` design)显式把「统一声明式 step manifest」列为**残量**并指出
它与 R5.6 token 预算**直接冲突**(把全量表塞进每份提示词 = 扩 token)。本变更的目标就是**用零提示词
token 的方式补上这块残量**——把 manifest 做成**运行时可查的确定性叶脚本输出**(对标既有 `list_*` 族 +
`describe_artifact` + `resume_state` 的「`--help`/stdout 即契约面」模式),而非塞进提示词正文。

> **Scope(本变更 = 残量补全,非重写既有覆盖)**:manifest 的多数子项**已被既有机制覆盖**(D6 已核实):
> step/next_action → `resume_state.py`;磁盘态 → `run_config.json`/`init_manifest.json`;fan-out 单元
> 绝对路径 → `list_*` stdout `checkpoint_path`/`rule_path`/`done_marker`/`failed_marker`(R5.3b);
> stage→组件表 + recipe → 命令壳。本变更**只补未被覆盖的那一块**:每步**确切脚本调用行 + 输入/产物
> shape**,且**宿主前缀(`.claude/mgh-core/` vs `.opencode/mgh-core/`)由脚本自身安装位置派生**,
> 从根上消除「猜前缀 / 双壳手镜像漂移」。

## What Changes

- **新增确定性叶脚本 `core/scripts/list_steps.py`**(对标 `list_clusters`/`list_scout_batches`/
  `list_rule_jobs` 同族,R5.2 零依赖、R5.3 自包含、`--help` 即 CLI 契约):stdout 输出**规范化
  step→{确定性脚本调用行(宿主正确前缀)、输入产物 + shape、产物产物路径 + shape}** 清单 JSON。
  宿主前缀**经 `Path(__file__)` 自动派生**(脚本知道自己在 `.claude/mgh-core/scripts/` 还是
  `.opencode/mgh-core/scripts/`),**NEVER** 硬编码、**NEVER** 靠提示词传递。**无磁盘前置**(不读
  `run_config.json`、不要求 `.mgh-init/` 存在)→ **pre-run 也可查**(治 #1 多发于 run 起步/中途)。
  可选 `--step <id>` 打单步确切调用行;退出码 `0/1/2`;stderr 仅诊断。
- **新增契约 `core/contracts/init/step-manifest.md`**:step→IO 表的**人读单一真相源**,与 `list_steps.py`
  stdout 镜像;与既有 `clusters.md`/`scout-enumeration.md`/`rule-jobs.md`/`resume-state.md` 并列。
- **双壳编排器 recipe**(`releases/{claude-code/commands,opencode/command}/mgh-init.md`,**逐字镜像**):
  Orchestrator discipline 段增一行**确认 recipe**——「确切每步脚本路径 + 调用行 + IO shape →
  `list_steps.py` stdout(前缀自动派生,NEVER 猜 `scripts/` vs `mgh-core/scripts`、NEVER 漏宿主前缀);
  `--resume`/压缩后与 `resume_state.py` 配合(后者给当前 step,前者给全量 manifest)」。**NEVER** 把
  全量 manifest 表内联进提示词(护 R5.6)。既有 `Deterministic invocation` 示例块 + inline flow **保留**
  (示例仍可直抄;manifest 是「确认 / 兜底」互补层,非替代)。
- **stage 提示词零改动**(manifest 是编排器侧确认工具,subagent 不直接消费;既有 sanctioned-tools
  allowlist 不变)。
- **回归测试**:`tests/test_list_steps.py`——① 宿主前缀 = `Path(__file__).parent.parent`(脚本所在
  `mgh-core/scripts` → `mgh-core` 根的同族前缀),claude/opencode 两份 install 镜像下均正确;
  ② step id 集与 `resume_state.py` 的 step 枚举**一致**(跨脚本一致性,防双真相源漂移);③ pre-run
  (无 `.mgh-init/`)可查;④ `--help` 暴露 `--step`;⑤ 契约与 stdout parity。

## Capabilities

### New Capabilities
<!-- none — manifest 是既有 control-discovery 编排纪律的一个 aspect,非新能力 -->

### Modified Capabilities
- `control-discovery`:新增要求「Canonical per-step invocation manifest」——`/mgh-init` SHALL 提供确定性
  叶脚本 `list_steps.py`,emit 每步确切脚本调用行(宿主前缀**经脚本安装位置派生**、NEVER 硬编码 /
  提示词传递)+ 输入/产物 shape;**无磁盘前置、pre-run 可查**;双壳 SHALL 以一行 recipe 把「每步确切
  路径/调用行的确认」路由到该脚本(NEVER 猜前缀、NEVER 内联全量表进提示词)。今日失败形状 = 模型在
  上下文压力下猜 `scripts/` vs `.opencode/mgh-core/scripts/`。

## Impact

- **新增确定性脚本**:`core/scripts/list_steps.py`(纯 stdlib、自定位 `sys.path`、utf-8、任意 cwd 可 `py`;
  承 R5.3a)。`install.sh` 镜像到 `.claude/mgh-core/scripts/` 与 `.opencode/mgh-core/scripts/`。
- **新增契约**:`core/contracts/init/step-manifest.md`(分发态;受 R5.10 纯净性——仅操作性内容,无
  研发铁律编号 / FDn / 内部 issue 指针)。
- **改命令壳**:两份 `mgh-init.md`(Orchestrator discipline 段 +1 行确认 recipe;既有示例块/flow 保留)。
  **净 token ≈ 中性或略降**(manifest 不内联;既有散落路径硬编码可酌情去重,但不强求)。
- **改 `tools/check_contracts.py` 面**:无新 CLI flag 之外,`list_steps.py --step` 是新脚本的新 flag →
  双壳若引用 `list_steps.py --step` 须镜像(`check_contracts.py` 按既有机制断言 `--help` 存在)。
- **改单测**:新增 `tests/test_list_steps.py`;`tests/test_deterministic.py` 等不退化。
- **依赖**:零新增运行时依赖(R2)。`list_steps.py` 不 import codegraph / vvaharness;不读磁盘 run 态。
- **BREAKING / 风险**:无磁盘 schema 变更、无既有 CLI flag 变更(纯 additive 新脚本 + 新契约 + 壳 +1 行)。
  主要风险 = 双真相源(step id 在 `list_steps.py` 与 `resume_state.py` 各一份)→ 缓解:跨脚本一致性单测
  断言二者 step 枚举一致(design 评估是否共享一个 step-definition 模块)。
