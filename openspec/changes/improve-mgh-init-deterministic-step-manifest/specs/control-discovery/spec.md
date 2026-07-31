## ADDED Requirements

### Requirement: Canonical per-step invocation manifest (zero prompt-token, host-prefix derived from install location)

`/mgh-init` SHALL 提供确定性叶脚本 `core/scripts/list_steps.py`(对标 `list_clusters.py`/
`list_scout_batches.py`/`list_rule_jobs.py` 同族;R5.2 零运行时依赖、R5.3 自包含、`--help` 即 CLI 契约 R5.1),
作为编排器「每步确切脚本调用行 + 输入/产物 shape」反射的**规范化出口**——专治上下文压力下模型
**猜脚本路径**的失败形状(实测:opencode 下猜 `scripts/merge_scout.py`,实际为
`.opencode/mgh-core/scripts/merge_scout.py`)。其 stdout SHALL 输出结构化 JSON:一个 `steps[]` 数组,
每项 `{step, kind∈bash|subagent, script_abs, invocation, input{artifact, shape}, output{artifact, shape, path_pattern}}`;
退出码 `0/1/2`;stderr 仅诊断/进度(R5.3b)。脚本 SHALL 支持 `--step <id>`(打印单步确切调用行);
默认打印全量紧凑清单(不静默截断,承 R5.3b)。

每步的 `script_abs` / `invocation` 中的**脚本路径 SHALL 是经 `Path(__file__).resolve().parent` 派生的
绝对路径**(本脚本所在 `scripts/` 目录的同族文件),MUST NOT 硬编码宿主前缀、MUST NOT 经提示词传递、
MUST NOT 是相对路径。这使得脚本在 claude install(`<target>/.claude/mgh-core/scripts/`)与 opencode
install(`<target>/.opencode/mgh-core/scripts/`)下分别 emit **正确宿主的同族绝对路径**——**「宿主前缀」
不存在可猜空间**(哪个宿主装的就 emit 哪个宿主的路径,双壳 `.claude/` vs `.opencode/` 手镜像漂移失效)。
模型 SHALL 逐字直抄该绝对路径(任意 cwd 安全),NEVER 自拼 `scripts/` / `mgh-core/scripts/`、
NEVER 漏宿主前缀。

脚本 SHALL **零磁盘前置**:不读 `run_config.json`、不扫 `.mgh-init/`、不依赖任何 run 态产物(step→IO 表
是静态契约)。故其**任意时刻可查**——包括 run 起步前、`--resume`/压缩后、纯文档审阅。这与 `resume_state.py`
(磁盘派生、要求 `run_config.json`)形成互补分工:`resume_state` 答「我在哪 / 下一步干啥」(磁盘真相),
`list_steps` 答「这一步的确切调用行 / 全量 step→IO map」(静态契约);二者**配套**用——`--resume` 或
任何压缩事件后,编排器调 `resume_state.py` 得 `step`/`next_action`,据 `step` 调
`list_steps.py --step <id>` 得确切调用行。

两份命令壳(claude-code / opencode,**逐字镜像**)SHALL 在 Orchestrator discipline 段以**一行 recipe**
声明:需任一步确切脚本路径 / 调用行 / IO shape → `list_steps.py` stdout(宿主前缀自动派生,NEVER 猜);
MUST NOT 把全量 `steps[]` 表内联进提示词正文(护 R5.6 token 预算,正是 D6 列明的冲突点);既有
`Deterministic invocation` 示例块与 inline flow **保留**(示例可直抄,manifest 是「确认/兜底」互补层)。
该 manifest 是 `control-discovery` 编排纪律的一个 aspect,NEVER 替代 `resume_state.py` 的磁盘派生进度。

#### Scenario: list_steps emits host-correct absolute script paths per step

- **WHEN** 在一个 claude install 的目标项目(`<target>/.claude/mgh-core/scripts/list_steps.py`)运行
  `py <target>/.claude/mgh-core/scripts/list_steps.py`
- **THEN** stdout `steps[]` 每项的 `script_abs` 是 `<target>/.claude/mgh-core/scripts/<name>.py` 形态的
  **绝对路径**(经 `Path(__file__).resolve().parent` 派生,非硬编码、非相对),且每条 `invocation` 可
  逐字 `py <abs> <args>` 执行;不出现裸 `scripts/<name>.py` 或漏 `mgh-core/` 前缀

#### Scenario: opencode install emits the opencode prefix (no drift from claude)

- **WHEN** 在一个 opencode install 的目标项目(`<target>/.opencode/mgh-core/scripts/list_steps.py`)运行
  `list_steps.py`,与 claude install 下对比
- **THEN** opencode 下 `script_abs` 落 `<target>/.opencode/mgh-core/scripts/<name>.py`,与 claude 下各自
  指向**自身实际所在** scripts 目录的同族文件;两份 install 各自正确,**NEVER** 出现「claude 壳 emit
  opencode 路径」或反过来的手镜像漂移

#### Scenario: Manifest is queryable pre-run with no disk precondition

- **WHEN** 对一个**尚未跑过** `/mgh-init` 的目标项目(无 `<target>/.mgh-init/`、无 `run_config.json`)
  运行 `py <install>/list_steps.py`
- **THEN** 脚本成功退出(退出码 0)、emit 完整 `steps[]` manifest;**不**因缺 `run_config.json` 或
  `.mgh-init/` 报错或 exit 2(与 `resume_state.py` 要求 run_config 形成互补分工)

#### Scenario: Shell routes path confirmation through list_steps, never guesses prefix

- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-init.md` 的 Orchestrator discipline 段
- **THEN** 两壳均含一行 recipe 指向 `list_steps.py` 作为「确切每步脚本路径/调用行/IO shape」的确认出口,
  且明示「宿主前缀自动派生,NEVER 猜 `scripts/` vs `mgh-core/scripts`、NEVER 漏宿主前缀」;
  全量 `steps[]` 表**不**内联进提示词正文

#### Scenario: Step-id set is consistent with resume_state (drift guard)

- **WHEN** 对比 `list_steps.py` stdout 的 `steps[].step` 集合 与 `resume_state.py` 的 step 枚举
  (`not-started|discover|survey|scout|resolve|t1|t2|t3|assemble|t4|merge|done`)
- **THEN** 两者 step id 集合一致(或 `list_steps` 为 documented 超集);每 step 的 `script_abs` 指向的
  脚本名在 `core/scripts/` **实际存在**(回归测断言,防双真相源漂移 + 防指向幽灵脚本)

#### Scenario: list_steps is self-contained and offline

- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/list_steps.py` 或 `py <path>/list_steps.py --step t1` 执行
- **THEN** 脚本成功(自定位 `sys.path`、utf-8、零第三方依赖),stdout 为合法 JSON,退出码 0;`--help`
  暴露 `--step` 且 `--help` 即其 CLI 契约(承 R5.1)
