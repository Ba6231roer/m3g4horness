# Tasks — harden-mgh-init-slice-and-tool-pinning

> 实现顺序(承 design.md Migration):确定性脚本加字段 → 契约 md → 提示词 + 双端 agent 定义 → 双端命令壳 → 测试 → 版本/lint/CHANGELOG。每条可证伪。

## 1. 确定性枚举脚本:additive `slice_dir`

- [x] 1.1 `core/scripts/list_scout_batches.py`:`pending[]` 每项(materialize 与 lite 两分支)增 `slice_dir` = `(<init-dir>/slices/scout/<safe(batch_id)>/).resolve()`;`<init-dir>` 由 `--checkpoints` 的祖父目录派生(与 `checkpoint_path` 同根,即 `<scout-plan>/..` = `<target>/.mgh-init`)。stderr/`--help` 文档同步。零新增依赖、utf-8、`resolve()` 绝对。
- [x] 1.2 `core/scripts/list_clusters.py`:`pending[]` 每项增 `slice_dir` = `(<init-dir>/slices/t1/<safe(cluster_id)>/).resolve()`(注意 `cluster_id` 含 `::`,经既有 `_safe_name` 消毒,与 checkpoint 文件名分量消毒同源,承 NTFS ADS 规约)。
- [x] 1.3 两脚本 `--help` docstring 增 `slice_dir` 字段说明(R5.1:`--help` 即契约面);契约 lint `tools/check_contracts.py` 跑过(无新 flag,仅 stdout 字段;若 lint 断言 stdout 字段则同步)。

## 2. 契约 md

- [x] 2.1 `core/contracts/init/scout-enumeration.md`:`<BatchLite>` 表 + JSON 样例增 `slice_dir`(绝对、`<init-dir>/slices/scout/<batch_id>/`);说明 subagent 写 `chunk_sources --out <slice_dir>/<safe-stem>.slice.json` 并回读该确切路径。
- [x] 2.2 `core/contracts/init/cluster-enumeration.md`:T1 pending 项增 `slice_dir`(同形,`slices/t1/<safe(cluster_id)>/`)。
- [x] 2.3 `core/contracts/init/unit-inputs.md`:Path convention 表增 `slices/<tier>/<unit>/` 行(ephemeral、随 `.mgh-init/` gitignore);记 `slice_dir` 由 `list_*` 产出、编排器逐字透传、subagent 写 + 回读。

## 3. 提示词 + 双端 agent 定义(切片输出 recipe + 绝对工具路径 recipe)

- [x] 3.1 `core/prompts/stages/init-scout.md`:Input 段增 `slice_dir`(编排器逐字透传);Task/Sanctioned tools 段把「call `chunk_sources.py` and read the slice」改为 recipe——`chunk_sources.py --out <slice_dir>/<safe-stem>.slice.json` + 回读该确切绝对路径;硬边界 `NEVER`(相对 `--out`、cwd/Temp 派生、树外)。增「用编排器透传的绝对工具路径 verbatim,NEVER 裸名/相对 `.opencode\|\.claude/mgh-core/scripts/…`」。
- [x] 3.2 `core/prompts/stages/init-induct.md`:同 3.1(T1 大证据文件运行时发现,用 `slice_dir` + stem 规则;绝对工具路径同)。
- [x] 3.3 `releases/claude-code/agents/init-scout.md` 与 `releases/opencode/agent/init-scout.md`:镜像 3.1 的提示词改动(分发态 agent 定义 = 实际载入 subagent 的 prompt)。
- [x] 3.4 `releases/claude-code/agents/init-induct.md` 与 `releases/opencode/agent/init-induct.md`:镜像 3.2。
- [x] 3.5 分发纯净性 `tools/check_distributed_purity.py` 跑过(R5.10:agent 定义里新增的 `slice_dir`/`<safe-stem>` 等不得引入 dev-only 溯源/R5.x/FDn 悬空引用)。

## 4. 双端命令壳(step 0 工具基 + 切片 `--out` recipe)

- [x] 4.1 `releases/opencode/command/mgh-init.md` 与 `releases/claude-code/commands/mgh-init.md`:step 0 增「经 `list_steps.py` stdout `script_abs` 取绝对工具基 → 透传给 scout/induct subagent」recipe(implementation-intention 段加一条「subagent 用的绝对脚本路径 → `list_steps.py` stdout `script_abs`」)。
- [x] 4.2 同两壳:步骤 3b(scout)/ 步骤 4(T1)fan-out 透传清单增 `slice_dir`;deterministic invocation 示例的 `chunk_sources.py --out` 改为 `<slice_dir>/<safe-stem>.slice.json`(原 `./.mgh-init/_slice.json` 示例更新为树内 `slice_dir` 形)。
- [x] 4.3 同两壳:`chunk_sources.py` 调用示例的脚本路径从相对 `.opencode|.claude/mgh-core/scripts/chunk_sources.py` 改为占位 `<list_steps script_abs 派生的绝对路径>`(或明确「编排器据 `list_steps` stdout 透传绝对路径」),消除相对路径歧义说明。
- [x] 4.4 契约 lint `tools/check_contracts.py` 跑过(双壳 MD 里 `chunk_sources.py --flag` 对 `--help` 存在断言不变;新增 recipe 不引未声明 flag)。

## 5. 测试

- [x] 5.1 `tests/test_init_runtime.py`(或新增 `tests/test_init_slice_dir.py`):断言 `list_scout_batches.py --materialize` 与 `list_clusters.py --materialize` stdout `pending[]` 每项 `slice_dir` 存在、`Path.is_absolute()`、且 `slice_dir` 落 `<init-dir>/slices/<tier>/` 子树;`resolve()` 一致(无 `..` 残留)。
- [x] 5.2 断言 `slice_dir` 文件名分量对含 `::` 的 `cluster_id` 经 `_safe_name` 消毒(无 NTFS ADS 分隔符 `:`/`\`/`/`)。
- [x] 5.3 回归:既有 `list_*` stdout 字段(`checkpoint_path`/`input_path`/`done_marker`/`failed_marker`/`oversize`)与退出码语义不变(additive 不破);`py tests/test_init_runtime.py` 全过。

## 6. 版本 / 自检 / CHANGELOG(R5.8)

- [x] 6.1 受影响 `.md`(双端命令壳 + 双端 agent 定义)+ `core/scripts/list_scout_batches.py`/`list_clusters.py` bump 版本号(按既有版本标记位)。
- [x] 6.2 `install.sh` 镜像后自检(fail-soft:校验 `list_*` 同目录共存)不阻断;CI 测 `tests/` 必过(含新增 5.x)。
- [x] 6.3 `CHANGELOG.md` 记本变更(承既有条目风格:一句话 + 受影响文件类)。

## 7. 边界披露(非阻塞)

- [x] 7.1 在 `design.md` Open Questions 记录的「sast 同形缺口」:本变更 apply 后,另立 stub change `harden-mgh-sast-slice-path-pinning`(覆盖 `s4-system.md`/`sast-deepdive.md` 的切片 `--out` 未钉),非本变更阻塞项。
- [x] 7.2 「从目标项目根调 `/mgh-init`」的 launch-cwd 前置条件写入命令壳「Always disclose」或 step 0(recipe:`list_steps.py` 首调相对路径解析于编排器 Bash cwd)。
