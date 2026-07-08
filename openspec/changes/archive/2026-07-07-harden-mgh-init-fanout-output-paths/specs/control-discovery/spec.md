## ADDED Requirements

### Requirement: Fan-out checkpoint paths are deterministic absolute values

scout 与 T1 fan-out 的每个待跑单元的**输出路径** SHALL 是由确定性枚举脚本产出的**单一权威绝对路径值**,
而非占位符模板或相对路径。`list_scout_batches.py` 与 `list_clusters.py` 的 stdout `pending[]` 每项
SHALL 额外包含 `checkpoint_path`(待写产物文件的**绝对路径**)与 `done_marker`(对应 `.done` 标记的
**绝对路径**),二者均由该脚本从其 `--checkpoints` 参数(已 `resolve()`)拼单元 id 得出。编排器 SHALL
把 `list_*` stdout 中的 `checkpoint_path` / `done_marker` **逐字透传**进对应 subagent 的 task 输入,
MUST NOT 自行用 `<target>` / `<batch_id>` / `<cluster_id>` 占位符拼路径,也 MUST NOT 用 `py -c` 算路径。

`init-scout` / `init-induct` subagent 的 stage 提示词 SHALL 把 `checkpoint_path`(与 `done_marker`)
列为**编排器逐字给定**的输入字段,其 Output 段 SHALL 要求「Write 恰好 `checkpoint_path` 给定的绝对路径
并 touch `done_marker`」;且 SHALL 以硬边界 `NEVER` 禁止:自行拼路径、发明文件名(如 `xxxraw.json`)、
写相对路径、写到项目目录之外(含盘符根)。

路径 SHALL 为绝对路径(经 `Path.resolve()`),使其对 subagent 的任意工作目录安全。运行时 hook(在
`MGH_INIT_ACTIVE` 运行域内)SHALL 拦截 `Write`/`Edit` 其 resolved 目标不以 resolved `MGH_TARGET`
为前缀的调用,失败 fail-loud(退出码 2)+ stderr 指向 `list_*` stdout 的 `checkpoint_path` 字段;
`MGH_TARGET` 缺失时该拦截条放行(降级)。`MGH_TARGET` SHALL 由编排器在起步段设置,且其取值 MUST
复用既有确定性脚本的绝对路径 stdout 字段(如 `discover_controls.py` 的 `repo`),MUST NOT 经 `py -c`
现算(守 `harden-mgh-init-orchestration-discipline` 的微脚本明线)。

#### Scenario: Enumeration script emits absolute checkpoint path per pending unit
- **WHEN** `list_scout_batches.py --scout-plan …/scout_plan.json --checkpoints …/checkpoints/scout` 运行
- **THEN** stdout `pending[]` 每项含 `checkpoint_path` 与 `done_marker`,二者均为绝对路径,且分别等于
  `<绝对 checkpoints dir>/<batch_id>.json` 与 `<绝对 checkpoints dir>/<batch_id>.json.done`

#### Scenario: Orchestrator passes path verbatim, never interpolates
- **WHEN** 编排器取得 scout / T1 的 `pending[]` 并起 subagent
- **THEN** subagent task 输入里的输出路径**逐字等于** `list_*` stdout 的 `checkpoint_path`,
  编排器**不**出现 `<target>`/`<batch_id>`/`<cluster_id>` 占位符拼装,也**不** `py -c` 算路径

#### Scenario: Subagent writes exactly the given absolute path
- **WHEN** 一个 init-scout / init-induct subagent 在工作目录 ≠ 项目根(含 Windows 盘符相对 cwd)的隔离上下文运行
- **THEN** 它把产物写到输入字段 `checkpoint_path` 给定的绝对路径(落在 `<target>/.mgh-init/checkpoints/<tier>/` 下),
  **不**写到盘符根或任何项目外目录,**不**发明文件名

#### Scenario: Out-of-tree write is blocked at runtime
- **WHEN** 运行域(`MGH_INIT_ACTIVE=1`)内一个 `Write`/`Edit` 的 resolved 目标不以 resolved `MGH_TARGET` 为前缀
- **THEN** PreToolUse hook 以退出码 2 拒绝,并在 stderr 给出「路径须取自 `list_*` stdout 的 `checkpoint_path`」recipe

#### Scenario: Existing on-disk artifact schema unchanged
- **WHEN** 本变更生效后审阅 `checkpoints/scout/<batch_id>.json` 与 `checkpoints/t1/<cluster_id>.json`
- **THEN** 其磁盘内容 schema 与变更前一致(新增的 `checkpoint_path`/`done_marker` 仅存在于 `list_*` stdout,不写入产物文件)
