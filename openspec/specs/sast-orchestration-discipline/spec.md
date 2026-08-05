# Spec: sast-orchestration-discipline

## Purpose

为 `/mgh-sast` 命令建立编排纪律的硬性规约:编排器即宿主 agent(非物化脚本)、扇出经确定性
枚举脚本、阶段边界有 `--check`、运行域有 hook 拦截、subagent 工具受白名单约束、CLI 契约与回归
测试覆盖到位。本能力 spec 由 change `harden-mgh-sast-orchestration-discipline` 同步建立。
## Requirements
### Requirement: Orchestrator is host agent with three never boundaries

`/mgh-sast` 的编排器 SHALL 是宿主 agent 本身(按 `mgh-sast.md` 用自身工具跑流水线,非写代码)。
两份 `mgh-sast.md` SHALL 在正文最前列声明此点,并把编排纪律明线扩展到一次性微脚本(承
`harden-mgh-init-orchestration-discipline` FD1)。agent **MUST NOT**(硬边界,`NEVER`):

- (a) `Write` 任何 `.py`——含大编排器(`mgh_sast.py`)与一次性微脚本(`py -c` 产物、`_prep_chunks.py`、
  `_aggregate_verify.py`、`<run>_helper.py`);
- (b) 经 `Bash` 运行 `py -c`/`python -c` 去内省或重派生产物(`import json`/`open(`/`load(` 读
  `checkpoints/**`/`scope_manifest.json` 之类);
- (c) `Read` 叶子脚本 `.py` 源码进编排上下文(报错看 stderr)。

当 agent 需要「工作清单 / 瞄一眼结构 / 派生量」时,SHALL 走 implementation-intention 句式声明的
合法出口(见下列各 Requirement)。命令壳 SHALL 以刚性三元组表述每个 fan-out 步骤。

#### Scenario: No orchestrator or helper script is created
- **WHEN** 宿主 agent 执行 `/mgh-sast`,需取得 s4 待跑 chunk 清单
- **THEN** agent 调用 `list_chunks.py`,**不** `Write` `_prep_chunks.py` 之类一次性 `.py`,也**不**
  `py -c "import json…"` 挖 `checkpoints/s4_candidates.json`

#### Scenario: Leaf scripts invoked, not read
- **WHEN** 编排器执行确定性阶段
- **THEN** `prefilter.py`/`dedup.py`/`emit_sarif.py` 经 Bash 执行,其源码不被 `Read` 进编排上下文

#### Scenario: Shell declares the discipline in both formats
- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-sast.md` 顶部
- **THEN** 两壳均显式声明「编排器 = 宿主 agent,非写成代码」+ 三条 `NEVER` 明线

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

### Requirement: Deterministic verify-job enumeration for s6 fan-out

`/mgh-sast` 的编排器 MUST 经确定性叶脚本 `core/scripts/list_verify_jobs.py` 取得 s6 工作清单(闭合 s6 扇出
不对称),MUST NOT 手挖 `s5_filtered.json`、MUST NOT **整份读**之进编排器上下文。`list_verify_jobs.py` SHALL
读 s5 产物 `findings[]` 并扫 `<repo>/security-scan/checkpoints/s6/*.json.done`,stdout
`{repo,total,done,pending[],truncated,offset,limit,effective_limit,shrunk}`,`pending[]` 每项(slim 壳)含
`{finding_id,file,line,vuln_class,input_path,checkpoint_path,done_marker,bytes,oversize}`(完整 `source_ref`/
`sink_ref` 下沉进 `input_path` 文件);stderr 仅诊断;退出码 `0/1/2`;`--help` 即 CLI 契约。脚本 SHALL 支持
`--materialize <dir>`(每 finding 完整输入写到 `<dir>/<finding_id>.input.json` + 报 `input_path`/`bytes`/
`oversize`)、`--offset`/`--limit`(分页)、`--max-unit-bytes`(超阈值 → 标 `oversize` + recipe,s6 单 finding
通常不切分)。当某页字节 > `--orch-budget-bytes` 时 SHALL 自动收紧 `--limit`、报 `effective_limit`+
`shrunk:true`。`sast-verify` SHALL 读自己的 `input_path`(该 finding 的 source/sink 锚点 + 上下文)。自定位、
utf-8、零依赖、任意 cwd(承 R5.3a)。

#### Scenario: Orchestrator enumerates verify jobs via the leaf script
- **WHEN** 编排器进入 s6 fan-out
- **THEN** 它调用 `list_verify_jobs.py --materialize <inputs/s6>` 取 `pending[]`,据此逐 finding 扇出
  `sast-verify`,向 subagent **透传 `input_path`**;不手挖 `s5_filtered.json`、不 `py -c`、不整份读之

#### Scenario: list_verify_jobs is resume-aware
- **WHEN** 部分 finding 已 done 后再次运行
- **THEN** `pending[]` 仅含未完成,`total = done + len(pending)`

#### Scenario: list_verify_jobs is self-contained and offline
- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/list_verify_jobs.py --findings <dir>/s5_filtered.json --checkpoints <dir>/checkpoints/s6 --materialize <dir>/inputs/s6` 执行
- **THEN** 脚本成功(自定位、utf-8、零依赖),stdout 为合法 JSON,per-finding input 文件落 `<dir>/inputs/s6/`

#### Scenario: Work-list page shrinks to the orchestrator budget
- **WHEN** 一页 `pending[]` 序列化字节 > `--orch-budget-bytes`
- **THEN** `list_verify_jobs.py` 自动收紧 `--limit`,stdout 报 `effective_limit` + `shrunk:true`,编排器翻页

### Requirement: Sanctioned structure-inspection primitive reused

`/mgh-sast` 的编排器与 subagent「瞄一眼产物结构」MUST 复用既有 `core/scripts/describe_artifact.py`
(`--keys/--count/--sample/--shape/--field`,harden-mgh-init 已交付),MUST NOT 用 `py -c`/`python -c`
或 `Read` 整份大 JSON 去内省产物结构(承 mgh-init FD5,不重造)。

#### Scenario: Structure reflex routes to sanctioned primitive
- **WHEN** 编排器想确认 `scope_manifest.json` / `s3_chunks.json` 的结构再动手
- **THEN** 它调用 `describe_artifact.py --keys/--sample/--shape`,**不** `py -c` 读 `[0]` 或 list keys

### Requirement: Stage-boundary contract checks for deterministic stages

`prefilter.py` / `dedup.py` / `emit_sarif.py` 各 SHALL 暴露 `--check <artifact>`;编排器跑完每个确定性
阶段、进下一步前 MUST 运行之;失败 MUST fail-loud(退出码 2)并回退重跑(泛化 mgh-init
`assemble_rules.py --check` 范式,承 R5.9)。校验项:`prefilter.py --check <s5_filtered.json>`(每条
finding 有 `file`/`line`/`vuln_class`/`source_ref`/`sink_ref`)、`dedup.py --check <s7_findings.json>`
(去重后无明显近重复簇)、`emit_sarif.py --check <report.sarif>`(SARIF 2.1.0 合法 + 每条
`run.invocation`)。

#### Scenario: Check passes on a well-formed artifact
- **WHEN** 编排器对刚产出的 `s5_filtered.json` 运行 `prefilter.py --check`
- **THEN** 退出码 0,编排器进入下一步

#### Scenario: Check fails loud on a corrupted artifact
- **WHEN** `s7_findings.json` 的某条 finding 缺 `file`/`line`
- **THEN** `dedup.py --check` 退出码 2,编排器回退重跑,不带着破损产物继续

### Requirement: Runtime enforcement hook for the sast run-domain

`/mgh-sast` SHALL 复用既有 `releases/claude-code/hooks/block_adhoc_scripts.py`。守卫的**激活模型 + 运行域
写入纪律**由共享契约 [`runtime-hook-enforcement`](../runtime-hook-enforcement/spec.md) 单一规定:激活 =
`MGH_SAST_ACTIVE=1`(或 init 域 `MGH_INIT_ACTIVE=1`)env **或** `<cwd>/security-scan/.active` 哨兵(编排器
step 0 经 `Bash` 写、run 完成/干净停止移除;哨兵绕开 opencode 插件不继承 mid-session env 的可靠性边界)。
运行域内一切脚本扩展名(`.py`/`.ps1`/`.sh`/`.ts`/…)写入均 fail-loud——**取消**既有
`core/scripts`/`tests`/`tools`/`releases/*/hooks` 白名单豁免(叶脚本 read-only)。既有 `py -c`/`python -c`
内省拦截 + recipe(指向 `list_chunks`/`list_verify_jobs`/`describe_artifact`/脚本 stdout 字段)+ 多单元聚合
(`s3_chunks.json`/`s5_filtered.json`/`scope_manifest.json`)整读拦截 **不变**。sast 域保留**树外**写入拦截
(`MGH_TARGET` 取值优先级 env > 哨兵.`target` > cwd),不加正向受信子表。命中 SHALL fail-loud(退出码 2)+
stderr recipe。非运行域 SHALL 直接放行(零日常噪声)。`install.sh` 的 hook 注入与 `--no-enforce-hook`
opt-out 行为不变(hook 已由 mgh-init 注入、幂等)。

#### Scenario: Hook blocks introspection py -c during a sast run
- **WHEN** `MGH_SAST_ACTIVE=1` 下编排器运行 `py -c "import json; json.load(open('security-scan/checkpoints/s5_filtered.json'))"`
- **THEN** hook 以退出码 2 拦截,stderr 给出「用 list_verify_jobs.py / describe_artifact.py」recipe

#### Scenario: Hook passes legitimate leaf-script invocation
- **WHEN** `MGH_SAST_ACTIVE=1` 下运行 `py .claude/mgh-core/scripts/prefilter.py --in … --out …`
- **THEN** hook 放行,不误伤合法叶子调用

#### Scenario: Hook blocks editing a leaf script during a sast run
- **WHEN** `MGH_SAST_ACTIVE=1` 下编排器 `Edit`/`Write` `.claude/mgh-core/scripts/prefilter.py`
- **THEN** hook 以退出码 2 拦截(叶脚本 read-only,取消 `core/scripts` 白名单豁免)

#### Scenario: opencode activates the sast guard via the disk sentinel
- **WHEN** opencode 下 `MGH_SAST_ACTIVE` env 未设,但 step 0 已写 `<cwd>/security-scan/.active` 哨兵
- **THEN** 守卫经哨兵激活,等效 env 已设;内省/越权脚本写/越树写均 fail-loud

#### Scenario: Non-run-domain is silent
- **WHEN** 既无 `MGH_INIT_ACTIVE` 也无 `MGH_SAST_ACTIVE`、且哨兵不存在时运行任意 Bash
- **THEN** hook 退出码 0 放行,零噪声

#### Scenario: Shell sets the run-domain flag and writes the sentinel
- **WHEN** 审阅两份 `mgh-sast.md` 编排流起步与完成态
- **THEN** 两壳均含 `export MGH_SAST_ACTIVE=1` + 写 `<target>/security-scan/.active` 哨兵步骤 + hook 存在/opt-out 声明;完成态移除哨兵

### Requirement: Subagent sanctioned-tools allowlist

每个 LLM 阶段提示词 MUST 追加一段 Sanctioned tools 白名单(覆盖 `core/prompts/stages/` 下的
`s1-survey.md`、`s2-threat-model.md`、`s3-decompose.md`、`s4-system.md`、`s6-verify.md`、`s8-chain.md`,
以及双壳 `agents/sast-*.md`)。白名单规定:读侧 `Read`(仅 input 给定文件/slice)/ `Glob` / `Grep`
自由;脚本侧仅 `chunk_sources.py`(若需切片);`Write`/`Edit` 仅限该 stage 产物。subagent MUST NOT
`Write` 任何 `.py`、MUST NOT 经 `py -c`/`python -c` 内省或重派生。stage 输入产物 SHALL 视为终态。
该 overlay 为追加纪律段,MUST NOT 改动 vvah 移植正文与 `Source: vvaharness/...` 溯源注释(R1)。

#### Scenario: deep-dive subagent does not write helper scripts
- **WHEN** `sast-deepdive` subagent 处理一个 chunk
- **THEN** 它仅用 Read/Glob/Grep + `chunk_sources.py`(若需),不 `Write .py`、不 `py -c`

#### Scenario: Stage prompt carries the allowlist without editing ported body
- **WHEN** 审阅 `core/prompts/stages/s4-system.md` / `s6-verify.md` 等
- **THEN** 每份含一个可识别的 Sanctioned-tools 段,且 vvah 移植正文 + `Source:` 溯源注释未被修改

#### Scenario: Shell agent mirrors the allowlist
- **WHEN** 审阅 claude-code 与 opencode 两份 `agents/sast-*.md` 的 Hard constraints 段
- **THEN** 两壳均显式声明 subagent NEVER `Write .py` / `py -c`

### Requirement: Rigid fan-out triplets and terminal-state declarations

两份 `mgh-sast.md` 的编排流 SHALL 以刚性三元组 `[输入产物::字段] → script/subagent →
[输出产物::字段]` 表述每个 fan-out 步骤(s3 chunks→s4、s5 findings→s6),并在 doubt 时刻内联 1 行
shape。`s5_filtered.json` / `s7_findings.json` SHALL 被声明为**终态**——不再二次聚合/重切(不出现
`_aggregate_verify.py` 之类重实现)。

#### Scenario: Fan-out steps expressed as rigid triplets
- **WHEN** 审阅两份 `mgh-sast.md` 的 s4 / s6 fan-out 段
- **THEN** 它们以 `[产物::字段] → script/subagent → [产物::字段]` 表述,且指向 `list_chunks.py` /
  `list_verify_jobs.py` 取 pending

#### Scenario: Merged artifacts declared terminal
- **WHEN** 审阅编排流的 s5/s7 步骤
- **THEN** `s5_filtered.json` / `s7_findings.json` 被显式声明为终态,禁止二次聚合

### Requirement: Deterministic-script CLI contract compliance

`prefilter.py`/`dedup.py`/`emit_sarif.py`/`list_chunks.py`/`list_verify_jobs.py` SHALL 遵守 R5.3(b)
CLI I/O 契约:`stdout`=结构化 JSON、`stderr`=诊断/进度**严格分流**;退出码 `0/1/2`(成功/通用错/误用);
闭集参数拒歧义输入 + 可操作报错;`--help` 即 CLI 契约面。命令壳调用示例 SHALL 与脚本 `--help`
逐字镜像(承 R5.1,经 `tools/check_contracts.py` 断言)。

#### Scenario: stdout/stderr are strictly separated
- **WHEN** 任一确定性脚本运行
- **THEN** stdout 仅含结构化 JSON 摘要,诊断/进度仅在 stderr

#### Scenario: Exit codes follow 0/1/2
- **WHEN** 脚本成功 / 遇通用错 / 误用 flag
- **THEN** 退出码分别为 0 / 1 / 2

#### Scenario: Contract lint covers new scripts and flags
- **WHEN** 运行 `tools/check_contracts.py`
- **THEN** 双壳 `mgh-sast.md` 里每个 `*.py --flag`(含 `--controls`、`list_chunks`/`list_verify_jobs`
  及各 `--check`)在对应脚本 `--help` 中存在

### Requirement: Regression test coverage and zero dependencies

本变更新增脚本 MUST 有回归单测:`tests/test_list_chunks.py`(resume-aware pending、空/截断不静默)、
`tests/test_list_verify_jobs.py`;既有 `tests/test_stage_check.py` SHALL 扩到 `prefilter`/`dedup`/
`emit_sarif` `--check`;`tests/test_block_adhoc_scripts.py` SHALL 扩到 `MGH_SAST_ACTIVE` 路径(放行
合法叶子、拦截内省/越权 Write)。全部新增脚本 MUST 仅用 Python ≥3.10 标准库,MUST NOT `import
vvaharness`、MUST NOT 要求 `pip install`(承 R2)。

#### Scenario: New enumeration scripts have resume-aware tests
- **WHEN** 运行 `py tests/test_list_chunks.py` / `test_list_verify_jobs.py`
- **THEN** 部分 `.done` 时 `pending[]` 仅含未完成;空/截断显式告警

#### Scenario: Hook test covers the sast run-domain
- **WHEN** 运行 `py tests/test_block_adhoc_scripts.py`
- **THEN** 断言在 `MGH_SAST_ACTIVE=1` 下放行合法叶子调用、拦截 `py -c` 内省与越权 `Write *.py`

#### Scenario: AST scan finds no third-party imports
- **WHEN** 对新增脚本做 AST 扫描
- **THEN** 不存在非标准库 import,且无 `import vvaharness` / `from vvaharness import`

### Requirement: Long-running deterministic Bash calls carry a per-call timeout

`/mgh-sast` 命令壳的编排器 SHALL 给**长跑确定性 Bash 调用**——尤其 `prefilter`/`dedup`/`emit_sarif`
(s5/s7/s9 确定性阶段)——传一个慷慨的 per-call `timeout`(claude Bash 工具与 opencode shell 工具均接受
毫秒级 `timeout` 参数),使其在大仓上不被宿主默认超时(opencode 实测 60s / 官方 120s;claude 120s)强杀。
命令壳 SHALL 在边界/披露段说明:opencode 用户**可**经环境变量
`OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS`(默认 120000)提升全局默认,但该变量**须在 opencode
启动前就绪**(mid-session `export` 不被 opencode 插件进程继承,与 R5.7 `MGH_*_ACTIVE` 可靠性边界同根因);
per-call `timeout` 是跨宿主公共杠杆,可在会话中即时生效。本要求与 `control-discovery` 的同名横切 recipe
同形(承 `harden-mgh-init-shell-timeout`)。

#### Scenario: Shell recipe tells the orchestrator to pass a per-call timeout
- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-sast.md`
- **THEN** 两壳均显式要求 `prefilter`/`dedup`/`emit_sarif` 等长跑确定性 Bash 调用携带 per-call `timeout`

#### Scenario: opencode env-var boundary disclosed
- **WHEN** 审阅 `mgh-sast.md` 边界段
- **THEN** 其中明示 `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS` 须 opencode 启动前设置、mid-session
  `export` 不生效,并指 per-call `timeout` 为会话内即时生效的替代

