## Why

`/mgh-init` 的 scout / T1 fan-out subagent 在 opencode 下偶发向 `C:\Users\<user>\AppData\Local\Temp\opencode\*` 写入并随后 `Read`,触发越权读取提示,中断长跑。根因有二,均为「路径未钉到当前项目树」:

1. **`chunk_sources.py --out` 从未被钉死**。`checkpoint_path`/`rule_path`/`input_path` 经 `list_*` 枚举脚本产绝对路径、编排器逐字透传(R5.3b),但大文件**切片输出**(`--out`)是唯一漏网的 fan-out 邻接路径——契约只说「call `chunk_sources.py` and read the slice」,未规定写哪。subagent 自行发明 `--out`;opencode 下 subagent 进程 cwd = `…\Temp\opencode\`,切片落盘到树外 → 回读触发越权 `Read` 提示。这正是 `harden-mgh-init-fanout-output-paths` 治过的「输出漂到盘符根」同类病,只是那次只覆盖 `checkpoint_path`/`rule_path`,未覆盖切片子路径。
2. **工具脚本路径用相对形式引用**(`.opencode/mgh-core/scripts/chunk_sources.py`)。当父项目也装过本工具(双层 install),subagent 的路径解析可命中**父层那份旧副本**(实测日志:打印 `"node"` 而非当前版的 `"nodes"`,即 7-20 前旧版)。任务因此可能跑陈旧/缺 FD2 自定位的逻辑。

> **明确回应用户 Q1**:写 C 盘**不是**旧版 `chunk_sources.py` 的 bug——新旧版都把 `--out` 写到指定处;写 C 盘是因 `--out` 未钉(根因 1)。旧版被命中是根因 2 的**症状**,换新版不治写 C 盘。**明确回应 Q2**:「全程只用当前项目工具与文件」= 同时钉死切片输出路径(根因 1)+ 钉死工具脚本路径到当前 install(根因 2)。

## What Changes

- **切片输出钉到项目树**:scout / T1 fan-out 的 `chunk_sources.py` 切片输出 SHALL 落入受信子树 `<target>/.mgh-init/slices/<tier>/<unit>/`(绝对)。枚举脚本(`list_scout_batches.py` / `list_clusters.py`)在每个 `pending[]` 项新增 `slice_dir`(绝对、`resolve()`)字段;编排器逐字透传给 subagent,subagent 写 `--out <slice_dir>/<safe-stem>.slice.json` 并回读该确切路径。NEVER 相对 `--out`、NEVER cwd/Temp 派生、NEVER 树外。
- **工具脚本路径钉到当前 install**:编排器 SHALL 在 step 0 经既有 `list_steps.py` stdout 的 `script_abs`(`__file__` 派生 = 当前 install 的脚本目录)取绝对工具基,把绝对 `chunk_sources` 路径透传给 subagent。subagent prompt SHALL 用该绝对路径 verbatim——NEVER 裸 `chunk_sources.py`、NEVER 相对 `.opencode/mgh-core/scripts/…`(多层 install 下可解析到别的副本)。
- **提示词铁律下沉**:`init-scout.md` / `init-induct.md` 增切片输出路径 recipe(写哪、回读哪)+ 工具路径 recipe(用编排器给的绝对路径),沿用 R5.5①「recipe 非 prohibition」、硬边界 `NEVER`(树外写、相对工具名)才用 NEVER。
- **契约 + 测试**:`scout-enumeration.md` / `unit-inputs.md` 记 `slice_dir`;`chunk_sources.py` 本身**保持 cwd 无关、不加树假设**(在 design.md 论证为何不改脚本)。回归测覆盖 `list_*` stdout 含 `slice_dir`(绝对、落 `.mgh-init/slices/…` 子树)。

非目标(披露):mgh-sast 的 s4/deepdive 有同形缺口(`s4-system.md` 同样仅「slice via chunk_sources」未钉路径),本变更**只治 init**;sast 留后续 `harden-mgh-sast-slice-path-pinning` adoption(对标既有 init-first-then-sast-adoption 拆分惯例,保持 apply 上下文有界)。

## Capabilities

### New Capabilities
<!-- 无新能力;均为既有能力的 requirement 增订。 -->

### Modified Capabilities
- `control-discovery`:增「大文件切片输出须钉到项目树 + subagent 用绝对工具路径」requirement(扩展既有「Shard large files for stable LLM analysis」与「Subagent sanctioned-tools allowlist」);scout/T1 枚举 stdout 增 `slice_dir`。
- `request-context-budget`:泛化 fan-out 路径纪律——编排器交给 subagent 的**所有**路径(输入、检查点、**及大文件切片输出**)SHALL 绝对、落受信子树、逐字透传;`slice_dir`/`slice_path` 与 `checkpoint_path`/`input_path` 同纪律。

## Impact

- **确定性脚本**:`list_scout_batches.py`、`list_clusters.py` 增 `slice_dir` 字段(additive,不动 `checkpoint_path`/`input_path` schema);`list_steps.py` 无改(已产 `script_abs`,仅被新消费)。`chunk_sources.py` 不改。
- **提示词/契约**:`core/prompts/stages/init-scout.md`、`init-induct.md`;`core/contracts/init/scout-enumeration.md`、`unit-inputs.md`(及 claude/opencode 镜像 agent 定义)。
- **命令壳**:`releases/{claude-code/commands,opencode/command}/mgh-init.md` 增切片 `--out` 路径 recipe + 工具绝对路径推导步骤(step 0 经 `list_steps.py`)。
- **测试**:`tests/test_init_runtime.py`(或新增)断言 `list_*` stdout `slice_dir` 绝对且落 `.mgh-init/slices/…`。
- **依赖/平台**:零新增运行时依赖(承 R2);纯标准库 + 提示词。双端对等(claude `.claude/mgh-core/` / opencode `.opencode/mgh-core/`),`script_abs` 由 `__file__` 派生天然双端。
- **版本**:`install.sh` 自检 + 受影响 `.md`/脚本 bump 版本号(承 R5.8)。
