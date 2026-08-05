# Tasks — harden-mgh-sast-slice-path-pinning

> 实现顺序(承 design.md Migration):确定性脚本加字段 → 契约 md → 提示词 + 双端 agent 定义 → 双端命令壳 →
> 测试 → 版本/lint/CHANGELOG。每条可证伪。镜像 `harden-mgh-init-slice-and-tool-pinning` 的任务结构(sast 端 adoption)。

## 1. 确定性枚举脚本:additive `slice_dir` + 顶层 `scripts_dir`

- [x] 1.1 `core/scripts/list_chunks.py`:`pending[]` 每项(materialize 分支)增 `slice_dir` =
      `(<命令输出目录>/slices/s4/<safe(chunk_id)>/).resolve()`(`<命令输出目录>` = `checkpoints_dir.parent.parent` =
      `<target>/security-scan`,与 `checkpoint_path` 同根;`_safe_name` 消毒 `/ \ :`,对干净 `chunk-NN` 为 no-op)。
      lite 分支(无 `--materialize`)不加(lite 为 backward-compat、不进 fan-out)。
- [x] 1.2 `core/scripts/list_chunks.py`:顶层 result 增 `scripts_dir` = `str(Path(__file__).resolve().parent)`
      (当前 install 脚本目录,绝对、host-agnostic)。
- [x] 1.3 `--help` docstring 同步:`pending[]` 字段表 + stdout 顶层字段表各增 `slice_dir`/`scripts_dir` 说明(R5.1:
      `--help` 即契约面);零新增依赖、utf-8、`resolve()` 绝对。

## 2. 契约 md

- [x] 2.1 `core/contracts/sast/fanout-enumeration.md`:`<ChunkLite>` 表 + JSON 样例增 `slice_dir`(绝对、
      `<命令输出目录>/slices/s4/<safe(chunk_id)>/`);stdout 段(顶部 JSON 样例 + 字段说明)增顶层 `scripts_dir`;
      说明 subagent 写 `chunk_sources --out <slice_dir>/<safe-stem>.slice.json` 并回读该确切路径 + 用
      `<scripts_dir>/chunk_sources.py` 绝对路径。
- [x] 2.2 `core/contracts/init/unit-inputs.md`:「大文件切片输出」小节的产出者清单 + sast 行核对——产出者增
      `list_chunks.py`(sast s4)、`<命令输出目录>` sast 行已有 `<target>/security-scan/`(slice 子节示例已含
      `security-scan/slices/s4/<chunk>/`,确认一致即可,仅在该小节显式点名 sast 产出者 = `list_chunks.py`)。

## 3. 提示词 + 双端 agent 定义(s4 切片输出 recipe + 绝对工具路径 recipe)

- [x] 3.1 `core/prompts/stages/s4-system.md`:Sanctioned tools 段把「only `chunk_sources.py`, when you must slice a
      large file to read it」改为 recipe——`<绝对 chunk_sources> --in <big_file> --big-file-bytes .. --line <L>
      --out <slice_dir>/<safe-stem>.slice.json`,再回读该确切绝对路径(`<safe-stem>` 取源文件 stem);硬边界
      (`NEVER`):裸名 `chunk_sources.py`、相对 `.claude`/`.opencode/mgh-core/scripts/…`(多层 install 下可解析到
      **别的**旧副本)、相对 `--out`、cwd/Temp 派生路径、树外写。**不**改 vvah 移植正文 + `Source:` 溯源注释(R1)。
- [x] 3.2 `releases/claude-code/agents/sast-deepdive.md` 与 `releases/opencode/agent/sast-deepdive.md`:镜像 3.1——
      Input 段增「编排器透传 `slice_dir` + 绝对 `chunk_sources` 路径」;`needs_slice[]` 文件写
      `<绝对 chunk_sources> --out <slice_dir>/<safe-stem>.slice.json` 并回读该确切路径,NEVER 裸名/相对
      `.claude`/`.opencode/mgh-core/scripts/…`、NEVER 相对 `--out`、NEVER cwd/Temp/树外。分发态 agent 定义 = 实际
      载入 subagent 的 prompt(R5.10)。
- [x] 3.3 分发纯净性 `tools/check_distributed_purity.py` 跑过(R5.10:agent定义/壳里新增的 `slice_dir`/`<safe-stem>`/
      `scripts_dir` 等不得引入 dev-only 溯源/R5.x/FDn 悬空引用)。

## 4. 双端命令壳(s4 fan-out 切片 `--out` recipe + 绝对工具基)

- [x] 4.1 `releases/{claude-code/commands,opencode/command}/mgh-sast.md`:s4 fan-out 段增「经 `list_chunks.py`
      stdout `scripts_dir`(`__file__` 派生 = 当前 install 脚本目录)取绝对工具基 → 把 `<scripts_dir>/chunk_sources.py`
      透传给 sast-deepdive」recipe(implementation-intention 段加一条「subagent 用的绝对 `chunk_sources` 路径 →
      `list_chunks.py` stdout `scripts_dir`」,对标 init 壳的 `list_steps script_abs` 条但锚点为 `list_chunks`)。
- [x] 4.2 同两壳:s4 fan-out `spawn sast-deepdive` 透传清单(原仅 `input_path`)增 `slice_dir` + `<scripts_dir>/
      chunk_sources.py 绝对路径`;subagent needs_slice 文件写 `<绝对 chunk_sources> --out <slice_dir>/<safe-stem>.slice.json`
      并回读该确切路径。
- [x] 4.3 同两壳:Deterministic invocation 的 `chunk_sources.py` 调用示例从相对 `py .claude|.opencode/mgh-core/
      scripts/chunk_sources.py … --out security-scan/_slice.json` 改为绝对工具基 + 树内 `--out`:
      `py <list_chunks stdout scripts_dir 派生的绝对路径>/chunk_sources.py --in <big_file> --big-file-bytes 204800
      --line <L> --out <slice_dir>/<safe-stem>.slice.json`(替原相对路径 + `security-scan/_slice.json`)。
- [x] 4.4 契约 lint `tools/check_contracts.py` 跑过(双壳 MD 里 `chunk_sources.py --flag` 对 `--help` 存在断言不变;
      新增 recipe 不引未声明 flag;`list_chunks` stdout 新字段非 CLI flag 不涉 lint)。

## 5. 测试

- [x] 5.1 `tests/test_list_chunks.py`(扩 `TestListChunksMaterialize`):断言 `--materialize` stdout `pending[]`
      每项 `slice_dir` 存在、`Path.is_absolute()`、落 `<命令输出目录>/slices/s4/` 子树、`resolve()` 一致(无 `..`
      残留);与 `checkpoint_path` 同根(共享 `<target>/security-scan/` 前缀)。
- [x] 5.2 同测试:断言 stdout 顶层 `scripts_dir` 存在、`Path.is_absolute()`、等于
      `Path(list_chunks.py 源码).resolve().parent`(`__file__` 派生)。
- [x] 5.3 断言 `slice_dir` 文件名分量对含 `/`/`\`/`:` 的 chunk_id 经 `_safe_name` 消毒(用一含分隔符的合成 chunk_id
      验证;现实 `chunk-NN` 为 no-op,此处防御性 parity)。
- [x] 5.4 回归:既有 `list_chunks` stdout 字段(`input_path`/`checkpoint_path`/`done_marker`/`bytes`/`oversize`/
      `needs_slice`/`files_count`/`threat_id`)+ 退出码语义不变(additive 不破);lite 分支不带 `slice_dir`;
      `py tests/test_list_chunks.py` 全过。

## 6. 版本 / 自检 / CHANGELOG(R5.8)

- [x] 6.1 受影响 `.md`(双端命令壳 + 双端 `sast-deepdive` agent)+ `core/scripts/list_chunks.py` bump 版本号(按
      既有版本标记位;契约 md 视既有规约)。〔核实:受影响 `.md`/`list_chunks.py` **无** per-file 版本标记位;
      全局 `VERSION` 文件为 release-time 产物(init 参考实现亦未 mid-stream bump);本变更版本信号 = CHANGELOG
      `[Unreleased]` 条目(见 6.3),与既有规约一致。〕
- [x] 6.2 `install.sh` 镜像后自检(fail-soft:校验 `list_chunks` 同目录共存)不阻断;CI 测 `tests/` 必过(含新增 5.x)。
      〔`install.sh` 自检清单扩入 sast 管线脚本(`list_chunks`/`list_verify_jobs`/`prefilter`/`dedup`/`emit_sarif`);
      镜像后自检 ✓ 全 co-located + purity ✓;`py -m unittest discover` 582 tests OK。〕
- [x] 6.3 `CHANGELOG.md` 记本变更(承既有条目风格:一句话 + 受影响文件类)。
