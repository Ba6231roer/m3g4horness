## ADDED Requirements

### Requirement: Big-file slice outputs are confined to an absolute in-tree path

`chunk_sources.py` 的切片输出(`--out`)是 fan-out 邻接路径,SHALL 与 `checkpoint_path`/`input_path` 同纪律——绝对、落受信子树、由枚举脚本产出 + 编排器逐字透传。`list_scout_batches.py` 与 `list_clusters.py` 的 stdout `pending[]` 每项 SHALL **额外**携带 `slice_dir`(绝对、`Path.resolve()`、形如 `<init-dir>/slices/<tier>/<safe(unit_id)>/`,其中 `<init-dir>` = `<target>/.mgh-init`、`<tier>` ∈ `scout`/`t1`)。scout/induct subagent 处理大文件(`needs_slice[]` 或运行时发现 > `--big-file-bytes` 的证据文件)SHALL 调 `chunk_sources.py --out <slice_dir>/<safe-stem>.slice.json` 并**回读该确切绝对路径**。subagent NEVER 写相对 `--out`、NEVER 写 cwd/Temp 派生路径、NEVER 写 `<target>/.mgh-init/` 子树之外。`chunk_sources.py` 本身保持 cwd 无关、不假设项目树(承 R5.3a);路径钉死在契约 + 提示词层,非脚本层。

#### Scenario: Slice output lands inside the project tree, not the opencode temp dir
- **WHEN** opencode 下 scout subagent 处理一个含 250KB `LegacyGuard.java`(`needs_slice[]`)的 batch,且 subagent 进程 cwd 为 `C:\Users\<u>\AppData\Local\Temp\opencode\`
- **THEN** subagent 调 `chunk_sources.py --out <slice_dir>/LegacyGuard.slice.json`,其中 `<slice_dir>` = 编排器透传的 `pending[].slice_dir`(绝对、落 `<target>/.mgh-init/slices/scout/<batch_id>/`);切片落该树内路径,subagent 回读该确切路径,**不**向 `…\Temp\opencode\*` 发起 `Read`、**不**触发越权读取提示

#### Scenario: Enumeration stdout carries an absolute slice_dir per pending unit
- **WHEN** 编排器运行 `list_scout_batches.py --materialize <init-dir>/inputs/scout`(或 `list_clusters.py --materialize <init-dir>/inputs/t1`)
- **THEN** stdout `pending[]` 每项含 `slice_dir` 字段,值为 `resolve()` 后的绝对路径且以 `<target>/.mgh-init/slices/<tier>/` 为前缀;编排器将其与 `input_path`/`checkpoint_path` 一同逐字透传给 subagent

#### Scenario: T1 induct slices a runtime-discovered big evidence file in-tree
- **WHEN** `init-induct` subagent 在读某 `evidence_file` 时发现其 > `--big-file-bytes`(该文件未预先列入任何 `needs_slice[]`,系运行时发现)
- **THEN** subagent 用编排器透传的 `slice_dir` + 确定性 stem 规则(`<safe-stem>.slice.json`,`_safe_name` 消毒 `/ \ :`)写切片,回读该确切路径;NEVER 自发明 cwd 相对路径或树外路径

#### Scenario: chunk_sources.py itself stays cwd-agnostic
- **WHEN** 人类或编排器按 `list_steps.py` 示例以 `py chunk_sources.py --in <f> --out <any>` 直接执行(ad-hoc,非 fan-out 切片)
- **THEN** 脚本仍按 `--out` 指定处写出,不强制树内、不假设项目树(cwd 无关性不破);fan-out 树内约束由枚举脚本的 `slice_dir` + subagent prompt 兜,非由 `chunk_sources.py` 兜

### Requirement: Fan-out subagents use absolute tool-script paths pinned to the current install

编排器 SHALL 在 step 0 经 `list_steps.py` stdout 的 `script_abs`(`__file__` 派生 = 当前运行 install 的 `<mgh-core>/scripts/` 目录)取绝对工具基,把绝对 `chunk_sources` 脚本路径逐字透传给 scout/induct subagent task 输入。subagent SHALL 用该绝对路径 verbatim 调用,**NEVER** 用裸名 `chunk_sources.py`、**NEVER** 用相对 `.opencode/mgh-core/scripts/…` / `.claude/mgh-core/scripts/…`(多层 install 下相对路径可经 `.opencode/`/`.claude/` 上溯解析到**别的** install 的副本,实测会命中父层旧版本)。此约束使整 run 只用当前项目(命令壳加载处)的工具副本,与 `<target>` 可独立(允许 install 在 A、分析 B)。

#### Scenario: Subagent uses the orchestrator-broadcast absolute tool path, not a bare name
- **WHEN** 父项目与叶项目均装过本工具(叶项目 `D:\repo\leaf\.opencode\mgh-core\scripts\chunk_sources.py` 为当前版,父项目 `D:\repo\parent\.opencode\mgh-core\scripts\chunk_sources.py` 为 7-20 前旧版),编排器从叶项目调 `/mgh-init`
- **THEN** 编排器经 `list_steps.py`(其 `__file__` 落叶项目 install)取 `script_abs` = `D:\repo\leaf\.opencode\mgh-core\scripts\chunk_sources.py`,逐字透传给 scout subagent;subagent 调该绝对路径,**不**命中父层旧版(不出现旧版 stdout `"node"` 这类版本错位)

#### Scenario: Tool base derived from list_steps script_abs, not from --target
- **WHEN** 编排器需要给 subagent `chunk_sources` 的绝对路径
- **THEN** 它读 `list_steps.py --step discover`(或任一 step)stdout 的 `script_abs`,取其目录作为工具基;NEVER 从 `--target` 拼 `<target>/.opencode/mgh-core/scripts`(install-dir 可与 target 不同)、NEVER 从 mid-session bash env 读工具基(opencode 插件进程不继承,承 R5.7)
