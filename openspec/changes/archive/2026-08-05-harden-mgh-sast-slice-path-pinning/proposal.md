# Proposal — harden-mgh-sast-slice-path-pinning

> sast 端 adoption,镜像已落地的 `harden-mgh-init-slice-and-tool-pinning`(init 端参考实现)。本变更把
> `/mgh-sast` s4 deep-dive fan-out 的「大文件切片输出 + 工具脚本路径」钉到当前项目树 / 当前 install。
> 非阻塞、不与 init 变更耦合。

## Why

`/mgh-sast` 的 s4 deep-dive fan-out 有与 init 端**同形**的「路径未钉到当前项目树」缺口(init 端已由
`harden-mgh-init-slice-and-tool-pinning` 治愈,其 Non-Goals 显式把 sast s4 留给本 adoption):

1. **`chunk_sources.py --out` 从未被钉死**。`core/prompts/stages/s4-system.md` Sanctioned tools 段仅说
   「only `chunk_sources.py`, when you must slice a large file to read it」——未钉 `--out` 写哪。
   `list_chunks.py` stdout 产 `input_path`/`checkpoint_path`/`done_marker`/`needs_slice`(均绝对)但**无
   `slice_dir`**。sast-deepdive subagent 自行发明 `--out`;opencode 下其进程 cwd = `…\Temp\opencode\` →
   切片落树外 → 回读触发越权 `Read` 提示(与 init 端实测失败形状一致)。两份 `mgh-sast.md` 的示例甚至
   用相对 `--out security-scan/_slice.json`(相对 subagent cwd,非树内绝对)。
2. **工具脚本路径用相对形式引用**(`.claude`/`.opencode/mgh-core/scripts/chunk_sources.py`)。双层 install 下
   subagent 可命中父层旧副本(init 端实测:打印 `"node"` 而非当前版 `"nodes"`)。两份 `mgh-sast.md` s4
   fan-out 仅透传 `input_path`、无绝对工具基;双端 `sast-deepdive` agent 定义亦无绝对工具路径 recipe。

> 跨命令总纲已在 `request-context-budget` 落地(该能力 spec 第 143 行已点名
> `<target>/security-scan/slices/s4/<chunk>/`,由 init 变更同步)。本变更 = sast 端的**执行** adoption,
> 不重改跨命令 spec(承 split-cross-cutting:横切总纲一处落地、per-command adoption 各自闭合 apply 上下文)。

## What Changes

- **切片输出钉到项目树**:`list_chunks.py` stdout `pending[]` 每项**额外**携带 `slice_dir`(绝对、
  `Path.resolve()`、形如 `<target>/security-scan/slices/s4/<safe(chunk_id)>/`;`<命令输出目录>` =
  `--checkpoints` 祖父目录 = `<target>/security-scan`,与 `checkpoint_path` 同根)。编排器逐字透传;
  sast-deepdive 写 `chunk_sources.py --out <slice_dir>/<safe-stem>.slice.json` 并**回读该确切路径**。
  NEVER 相对 `--out`、NEVER cwd/Temp 派生、NEVER 树外。
- **工具脚本路径钉到当前 install**:`list_chunks.py` stdout**额外**携带顶层 `scripts_dir`(`__file__` 派生 =
  当前 install 的 `<mgh-core>/scripts/`)。编排器在 s4 fan-out 取该绝对基,把 `<scripts_dir>/chunk_sources.py`
  逐字透传给 sast-deepdive;subagent 用该绝对路径 verbatim——NEVER 裸名、NEVER 相对
  `.claude`/`.opencode/mgh-core/scripts/…`。
- **提示词 + 契约 + 双端 agent 定义**:`s4-system.md` Sanctioned tools 段把「only `chunk_sources.py`, when
  you must slice」改为 recipe(钉 `--out` 到 `slice_dir` + 绝对工具路径),沿用 R5.5①(recipe 非 prohibition,
  硬边界 `NEVER` 才用 NEVER);双端 `sast-deepdive` agent 镜像;`core/contracts/sast/fanout-enumeration.md`
  `<ChunkLite>` 表 + JSON 样例增 `slice_dir`、stdout 段增顶层 `scripts_dir`。
- **双端命令壳**:s4 fan-out 透传清单增 `slice_dir` + 绝对 `chunk_sources` 路径;`chunk_sources` 调用示例改
  `<scripts_dir>/chunk_sources.py … --out <slice_dir>/<safe-stem>.slice.json`(替原相对路径 +
  `security-scan/_slice.json`)。
- **`chunk_sources.py` 不改**(cwd 无关性保留,承 init D4);`s4-output-schema.md` 不改(其 "slice" 仅指 vvah
  分析切片概念,非切片文件)。
- **测试**:`tests/test_list_chunks.py` 断言 `slice_dir`(绝对、落 `security-scan/slices/s4/` 子树、`_safe_name`
  消毒)+ 顶层 `scripts_dir`(绝对、`__file__` 派生);回归既有字段 additive 不破。

## Capabilities

### Modified Capabilities

- `sast-orchestration-discipline`:MODIFY「s4 deterministic chunk enumeration」pending[] 字段表(+ `slice_dir`)+
  stdout 顶层(+ `scripts_dir`);ADD「s4 大文件切片输出钉到树内绝对路径」+「s4 deep-dive subagent 用钉到当前
  install 的绝对工具路径」两条 requirement(对标 init 端 `control-discovery` 的两条对应 requirement)。

> `request-context-budget` **不动**:其「所有 fan-out 路径绝对+树内+逐字」总纲已含 sast s4(由 init 变更同步,
> 见该 spec 第 143 行)。本变更不重复横切规约。

## Impact

- 确定性脚本:`core/scripts/list_chunks.py`(additive `slice_dir` per pending + 顶层 `scripts_dir`)。
- 提示词/契约:`core/prompts/stages/s4-system.md`;`core/contracts/sast/fanout-enumeration.md`;
  双端 `releases/{claude-code/agents,opencode/agent}/sast-deepdive.md`。
- 命令壳:`releases/{claude-code/commands,opencode/command}/mgh-sast.md`。
- 测试:`tests/test_list_chunks.py`(扩 `slice_dir`/`scripts_dir` 断言)。
- 依赖/平台:零新增运行时依赖(承 R2);双端对等。
- 版本:受影响 `.md` + `list_chunks.py` bump + CHANGELOG(承 R5.8)。

## Non-Goals

- 不改 `chunk_sources.py` / `s4-output-schema.md`。
- 不改 init 端(已覆盖)/ s6(verify job 不切片,已核实)/ s8。
- 不重写全壳相对→绝对(仅钉 subagent 用的 `chunk_sources`;编排器其它相对叶子调用超 scope)。
- 不改 `request-context-budget`(横切总纲已含 sast)。
- 不填充 `.active` 哨兵 `target`(独立 hook 议题;降级子树检查已放行树内写)。
