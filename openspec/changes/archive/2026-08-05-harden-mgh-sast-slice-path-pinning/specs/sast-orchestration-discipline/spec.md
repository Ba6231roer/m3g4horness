## MODIFIED Requirements

### Requirement: Deterministic chunk enumeration for s4 fan-out

`/mgh-sast` 的编排器 MUST 经确定性叶脚本 `core/scripts/list_chunks.py` 取得 s4 工作清单(对标
mgh-init `list_clusters.py`,闭合 s4 扇出不对称),MUST NOT **整份读** `s3_chunks.json` 进编排器上下文。
`list_chunks.py` SHALL 读 s3 产物的 `chunks[]` 并扫 `<repo>/security-scan/checkpoints/s4/*.json.done`,stdout
输出结构化 JSON `{repo,total,done,pending[],truncated,offset,limit,effective_limit,shrunk,scripts_dir}`,
`pending[]` 每项(slim 壳)含 `{chunk_id,files_count,threat_id,needs_slice,input_path,checkpoint_path,
done_marker,bytes,oversize,slice_dir}`(完整 `files[]`/`hypothesis` 下沉进 `input_path` 文件);stderr 仅诊断/进度;
退出码 `0/1/2`;`--help` 即其 CLI 契约(承 R5.1)。`total = len(chunks[])`,`done = #已 .done`,
`pending = total − done`。脚本 SHALL 支持 `--materialize <dir>`(把每 chunk 完整输入写到
`<dir>/<chunk_id>.input.json` + 报 `input_path`/`bytes`/`oversize`)、`--offset`/`--limit`(分页)、
`--max-unit-bytes`(超阈值且含 > `--big-file-bytes` 文件 → 强制 `needs_slice` 走 `chunk_sources` 切片,NEVER 整文件
喂 LLM)。当某页字节 > `--orch-budget-bytes` 时 SHALL 自动收紧 `--limit`、报 `effective_limit`+`shrunk:true`。
`sast-deepdive` SHALL 读自己的 `input_path`(一个 chunk 的 files + threat + hypothesis)而非编排器内联传记录。
脚本 MUST 自定位 `sys.path`、utf-8 读入、零第三方依赖、任意 cwd 可 `py`(承 R5.3a)。顶层 `scripts_dir` =
`Path(__file__).resolve().parent`(当前运行 install 的 `<mgh-core>/scripts/` 目录,绝对、host-agnostic);`pending[]`
每项 `slice_dir` = `(<命令输出目录>/slices/s4/<safe(chunk_id)>/).resolve()`(`<命令输出目录>` = `--checkpoints`
祖父目录 = `<target>/security-scan`,与 `checkpoint_path` 同根;`_safe_name` 消毒 `/ \ :`)。`chunk_sources.py` 本身
不改(cwd 无关);切片树内约束由 `slice_dir` + subagent prompt 兜(见下两条 ADDED requirement)。

#### Scenario: Orchestrator enumerates chunks via the leaf script
- **WHEN** 编排器进入 s4 fan-out
- **THEN** 它调用 `list_chunks.py --materialize <inputs/s4>` 取 `pending[]`,据此逐 chunk 扇出
  `sast-deepdive`,向 subagent **透传 `input_path`**;不出现手搓 JSON 内省、`Write _prep_chunks.py` 或整份读 `s3_chunks.json`

#### Scenario: list_chunks reports total vs done for resume
- **WHEN** 部分 chunk 已 done(`checkpoints/s4/<chunk_id>.json.done` 存在)后再次运行
- **THEN** stdout 的 `done` 反映已完成数,`pending[]` 仅含未完成,`total = done + len(pending)`

#### Scenario: list_chunks is self-contained and offline
- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/list_chunks.py --chunks <dir>/s3_chunks.json --checkpoints <dir>/checkpoints/s4 --materialize <dir>/inputs/s4` 执行
- **THEN** 脚本成功(自定位 `sys.path`、utf-8、零第三方依赖),stdout 为合法 JSON,per-unit input 文件落 `<dir>/inputs/s4/`

#### Scenario: Empty or truncated chunks handled without silent truncation
- **WHEN** `chunks[]` 为空,或 `truncated: true`
- **THEN** `list_chunks.py` 输出 `total:0`(空)或保留 `truncated: true`(显式告警),退出码仍 `0`,不静默丢信息

#### Scenario: Oversize chunk respects the unit budget via slicing
- **WHEN** 某 chunk input `bytes` > `--max-unit-bytes`(或含 > `--big-file-bytes` 文件)
- **THEN** 该文件入 `needs_slice[]`,`sast-deepdive` 经 `chunk_sources.py` 切片后读 slice,NEVER 整文件喂 LLM

#### Scenario: Work-list page shrinks to the orchestrator budget
- **WHEN** 一页 `pending[]` 序列化字节 > `--orch-budget-bytes`
- **THEN** `list_chunks.py` 自动收紧 `--limit`,stdout 报 `effective_limit` + `shrunk:true`,编排器翻页

#### Scenario: stdout carries absolute slice_dir per pending chunk and a top-level scripts_dir
- **WHEN** 编排器运行 `list_chunks.py --materialize <inputs/s4> --checkpoints <repo>/security-scan/checkpoints/s4`
- **THEN** stdout 顶层含 `scripts_dir`(绝对、`Path(__file__).resolve().parent`、host-agnostic);`pending[]` 每项含
  `slice_dir` 字段,值为 `resolve()` 后的绝对路径、以 `<repo>/security-scan/slices/s4/` 为前缀、文件名分量经
  `_safe_name` 消毒(无 `:`/`\`/`/`);编排器将 `slice_dir` 与 `input_path`/`checkpoint_path` 一同逐字透传给
  sast-deepdive,并把 `<scripts_dir>/chunk_sources.py` 作为绝对工具路径透传

## ADDED Requirements

### Requirement: Big-file slice outputs are confined to an absolute in-tree path (sast s4)

`chunk_sources.py` 的切片输出(`--out`)是 s4 fan-out 邻接路径,SHALL 与 `checkpoint_path`/`input_path` 同纪律——
绝对、落受信子树、由枚举脚本产出 + 编排器逐字透传。`list_chunks.py` 的 stdout `pending[]` 每项 SHALL **额外**携带
`slice_dir`(绝对、`Path.resolve()`、形如 `<target>/security-scan/slices/s4/<safe(chunk_id)>/`,其中 `<safe()>` 经
`_safe_name` 消毒 `/ \ :`)。`sast-deepdive` subagent 处理 `needs_slice[]` 文件(> `--big-file-bytes`)SHALL 调
`chunk_sources.py --out <slice_dir>/<safe-stem>.slice.json`(`<safe-stem>` 取源文件 stem)并**回读该确切绝对路径**。
subagent NEVER 写相对 `--out`、NEVER 写 cwd/系统临时目录(如 `…\AppData\Local\Temp\opencode\`、`/tmp/`)派生路径、
NEVER 写 `<target>/security-scan/` 子树之外(含盘符根)。`chunk_sources.py` 本身保持 cwd 无关、不假设项目树(承
R5.3a);路径钉死在契约 + 提示词层,非脚本层。本要求是 `request-context-budget`「所有 fan-out 路径绝对+树内+逐字」
总纲在 sast s4 的执行落地(该总纲已含 `<target>/security-scan/slices/s4/<chunk>/`)。

#### Scenario: Slice output lands inside the project tree, not the opencode temp dir
- **WHEN** opencode 下 sast-deepdive subagent 处理一个含 250KB `LegacyGuard.java`(`needs_slice[]`)的 chunk,且
  subagent 进程 cwd 为 `C:\Users\<u>\AppData\Local\Temp\opencode\`
- **THEN** subagent 调 `chunk_sources.py --out <slice_dir>/LegacyGuard.slice.json`,其中 `<slice_dir>` = 编排器透传的
  `pending[].slice_dir`(绝对、落 `<target>/security-scan/slices/s4/<chunk_id>/`);切片落该树内路径,subagent 回读
  该确切路径,**不**向 `…\Temp\opencode\*` 发起 `Read`、**不**触发越权读取提示

#### Scenario: chunk_sources.py itself stays cwd-agnostic
- **WHEN** 人类或编排器以 `py <scripts_dir>/chunk_sources.py --in <f> --out <any>` 直接执行(ad-hoc,非 fan-out 切片)
- **THEN** 脚本仍按 `--out` 指定处写出,不强制树内、不假设项目树(cwd 无关性不破);fan-out 树内约束由 `list_chunks`
  的 `slice_dir` + subagent prompt 兜,非由 `chunk_sources.py` 兜

### Requirement: s4 deep-dive subagent uses absolute tool-script paths pinned to the current install

`list_chunks.py` stdout SHALL 额外携带顶层 `scripts_dir` = `Path(__file__).resolve().parent`(`__file__` 派生 = 当前
运行 install 的 `<mgh-core>/scripts/` 目录)。编排器 SHALL 在 s4 fan-out 读该 `scripts_dir`,把绝对
`<scripts_dir>/chunk_sources.py` 脚本路径逐字透传进 `sast-deepdive` task 输入。subagent SHALL 用该绝对路径 verbatim
调用,**NEVER** 用裸名 `chunk_sources.py`、**NEVER** 用相对 `.claude/mgh-core/scripts/…` / `.opencode/mgh-core/
scripts/…`(多层 install 下相对路径可经 `.claude/`/`.opencode/` 上溯解析到**别的** install 的副本,实测会命中父层
旧版本)。此约束使整 run 只用当前项目(命令壳加载处)的工具副本,与 `<target>` 可独立(允许 install 在 A、分析 B)。
工具基取自 `list_chunks.py`(`__file__` 落当前项目 install)而非 init 专属的 `list_steps.py`(其 step 表为 init 步骤)。

#### Scenario: Subagent uses the orchestrator-broadcast absolute tool path, not a bare name
- **WHEN** 父项目与叶项目均装过本工具(叶项目 `D:\repo\leaf\.opencode\mgh-core\scripts\chunk_sources.py` 为当前版,
  父项目 `D:\repo\parent\.opencode\mgh-core\scripts\chunk_sources.py` 为旧版),编排器从叶项目调 `/mgh-sast`
- **THEN** 编排器在 s4 fan-out 读 `list_chunks.py`(其 `__file__` 落叶项目 install)stdout 的 `scripts_dir` =
  `D:\repo\leaf\.opencode\mgh-core\scripts`,逐字透传 `<scripts_dir>/chunk_sources.py` 给 sast-deepdive;subagent 调
  该绝对路径,**不**命中父层旧版(不出现旧版 stdout `"node"` 这类版本错位)

#### Scenario: Tool base derived from list_chunks scripts_dir, not from --target or list_steps
- **WHEN** 编排器需要给 sast-deepdive `chunk_sources` 的绝对路径
- **THEN** 它读 s4 fan-out 的 `list_chunks.py` stdout 顶层 `scripts_dir`,取其作为工具基;NEVER 从 `--target`/`--repo`
  拼 `<target>/.claude|.opencode/mgh-core/scripts`(install-dir 可与 target 不同)、NEVER 调 init 专属的
  `list_steps.py`(其 step 表为 init 步骤,副作用打印 init 步骤)、NEVER 从 mid-session bash env 读工具基
  (opencode 插件进程不继承,承 R5.7)
