# Contract: per-unit materialized inputs (`inputs/<tier>/<unit>.input.json`)

Producer: the deterministic enumeration leaf scripts (`list_clusters.py` /
`list_scout_batches.py` / `list_rule_jobs.py`) when invoked with `--materialize <dir>`.
Consumer: the corresponding stage subagent (`init-induct` / `init-scout` / `init-rulewriter`),
which **reads its own `input_path`**; the orchestrator only passes the path verbatim.

> 闭合「编排器整份读多单元聚合」的契约缺口(见 `request-context-budget` 能力):每个 fan-out
> 单元的**完整输入记录**由枚举脚本物化成**一个有界文件**,subagent 自读;编排器只装 slim 分页
> 待办壳,NEVER 整份读 `clusters.json`/`controls_candidates.json`/`scout_plan.json`/
> `controls_inventory.json`。预算单位 = 字节(标准库可测,零运行时依赖)。

## Path convention

`<命令输出目录>/inputs/<tier>/<unit>.input.json`(绝对路径,落运行域树内,幂等覆盖,`--resume`
复用)。**文件名为存储编码,非身份**:含 `::`(NTFS Alternate-Data-Stream 分隔符,写即 errno 22)
的 unit id —— 即 T1 `cluster_id` 与 `<cid>::shard-<n>` —— 其 input 文件名 + `checkpoint_path`/
`done_marker` 文件名分量经 `_safe_name`(`/`、`\`、`:` → `_`)消毒;canonical unit id(含 `::`)
原样保留为 envelope `cluster_id` 字段 + 物化记录 + 检查点记录 `unit` 字段(done 检测读 `unit` 字段、
不依赖文件名 → resume 不受影响)。`batch_id`(`scout-NNN`)/ `category` 为纯标识、不含 `::`,消毒为
no-op。各命令的 `<命令输出目录>` + `<tier>`:

| 命令 | 输出目录 | tier / unit | 物化者 |
|---|---|---|---|
| `/mgh-init` **← 本 contract 实例化** | `<target>/.mgh-init/` | `t1/<safe(cluster_id)>` · `scout/<batch_id>` · `t3/<category>` | `list_clusters.py` / `list_scout_batches.py` / `list_rule_jobs.py` |
| `/mgh-sast`(后续 adoption) | `<target>/security-scan/` | `s4/<chunk>` · `s6/<verify-job>` | `list_chunks.py` / `list_verify_jobs.py` |
| `/mgh-sra`(后续 adoption) | `<change-root>/.mgh-sra/` | `augment/<capability>` | `prepare_augment.py` |
| `/mgh-srr`(后续 adoption) | `<out-dir>/` | `augment/<capability>` | `ingest_requirements.py`(复用 sra 引擎) |

> sast/sra/srr 的路径约定供后续 `harden-mgh-{sast,sra,srr}-context-budget` adoption 引用;本 contract
> 只在 init 端落地参考实现。

### 大文件切片输出(`slices/<tier>/<unit>/`)— 邻接 fan-out 路径,与 `input_path`/`checkpoint_path` 同纪律

`<命令输出目录>/slices/<tier>/<safe(unit)>/<safe-stem>.slice.json`(绝对路径,ephemeral、随运行域
目录 gitignore、整 run 结束随之清理)。`chunk_sources.py` 的大文件切片(`--out`)是 fan-out 邻接路径,
SHALL 与 `checkpoint_path`/`input_path` 同纪律——**绝对、落受信子树、由枚举脚本产出 + 编排器逐字透传**:

- **产出者**:`list_scout_batches.py` / `list_clusters.py`(init scout/T1)/ `list_chunks.py`(sast s4)
  stdout `pending[]` 每项**额外**携带 `slice_dir`(绝对、`Path.resolve()`、形如
  `<命令输出目录>/slices/<tier>/<safe(unit_id)>/`;`<命令输出目录>` = `--checkpoints` 祖父目录:init =
  `<target>/.mgh-init`(`<tier>` ∈ `scout`/`t1`)、sast = `<target>/security-scan`(`<tier>` = `s4`))。
  绝对工具基:init 经 `list_steps.py` stdout `script_abs`、sast 经 `list_chunks.py` stdout 顶层 `scripts_dir`。
- **编排器**:把 `slice_dir` 与 `input_path`/`checkpoint_path` 一同**逐字透传**给 scout/induct subagent。
- **subagent**:处理大文件(scout 的 `needs_slice[]`,或 T1 运行时发现 > `--big-file-bytes` 的证据文件)
  写 `chunk_sources.py --out <slice_dir>/<safe-stem>.slice.json`(`<safe-stem>` 取源文件 stem 经 `_safe_name`
  消毒)并**回读该确切绝对路径**。NEVER 写相对 `--out`、NEVER 写 cwd/系统临时目录(如 opencode 的
  `…\AppData\Local\Temp\opencode\`)派生路径、NEVER 写运行域受信子树之外(含盘符根)。
- **`chunk_sources.py` 本身**保持 cwd 无关、不假设项目树(`--out` 默认相对 cwd 的人类 ad-hoc 用法不变);
  树内约束由枚举脚本的 `slice_dir` + subagent prompt 兜,非由 `chunk_sources.py` 兜。

## Schema

每个 `pending[]` 项携带该单元的 `input_path`(绝对)+ `bytes`(该 input 文件字节数)+ `oversize`(bool,
是否超 `--max-unit-bytes`)。input 文件正文 = 该单元的**完整记录**(slim 待办壳剔除的可变长负载下沉于此):

| tier | `<unit>.input.json` 正文 |
|---|---|
| `t1` | 簇记录(`cluster_id`/`category`/`kind`/`shape`/`evidence_files`/`usage_sites`)+ 本簇候选命中(回查 `controls_candidates.json` 的完整 `Candidate` 记录) |
| `scout` | 该批完整 `targets[]`(每行 skeleton:`file`/`pkg`/`classes`/`imports`/`method_sigs`/`fan_in`/`bytes`)+ `needs_slice[]` |
| `t3` | 该 category 的全部 `Control` 记录(自 `controls_inventory.json::controls[]`) |

## 语义

- **幂等 / `--resume`**:同单元再次枚举时,`<unit>.input.json` 按单元覆盖(不重复膨胀);`pending[]`
  据各自 `done_marker` **与** `failed_marker` 跳过已终态单元(`.done` = 成功、`.failed` = 确认失败,
  均终态、均不重派)。
- **`.failed` marker**(终态失败,与 `.done` sibling):`<checkpoint_path>.failed`,body
  `{unit,reason,tier}`(advisory;**编排器**在收到 subagent `failed <reason>` ack 后写,路径取 `list_*`
  stdout 的 `failed_marker` 逐字透传、NEVER 自拼)。subagent 失败路径 **touch nothing**(不 touch
  `done_marker`)。crash 无 ack → 无 marker → 单元仍 `pending` → resume 重派(crash ≠ 确认失败)。
  escape hatch:人工 `rm` 该 `.failed` 后 `--resume` 即重派该单元。
- **`bytes` ≤ `--max-unit-bytes`**(默认 192KB):超阈值单元被确定性处置(见下),NEVER 以原始整份
  形态进任何 subagent 请求。
- **子单元派生 `::shard-<n>`**(仅 init T1):某簇物化输入超 `--max-unit-bytes` 时,按 evidence/usage-site
  组切分为 `<cluster_id>::shard-<n>`,每子单元 `bytes` ≤ 预算且有独立 `input_path`/`checkpoint_path`/
  `done_marker`;T2 仍见全部子单元记录(additive,dedup 在 candidate 层不受影响)。
- **scout 批**:不切分批(批已是 plan 单元);超 `--max-unit-bytes` 的批标 `oversize`,批内超
  `--big-file-bytes` 的单文件入 `needs_slice[]` 由 `init-scout` 经 `chunk_sources.py` 切片。
- **T3 category**:不切分(rulewriter 需整 category 视图);超 `--max-unit-bytes` 标 `oversize:true` +
  recipe(建议 `--scope`+`--merge`)。

> 编排器 NEVER `Read`/`cat`/`py -c` 整份多单元聚合;需某单元完整记录 → 读 `pending[].input_path`。

## `run_config.json`(起始态意图文件,非 per-unit 输入)

`<命令输出目录>/run_config.json`(`<target>/.mgh-init/run_config.json`)由 `write_runconfig.py` 在
step 0 **原子写出**(`.tmp`+`os.replace`),记录**决定步骤图的本次调用 flag**:`target`(绝对)/`format`/
`scope`/`scope_mode`/`no_scout`/`no_codegraph`/`skip_consistency`/`merge`+`merge_partials_dir`/
`include_dotfiles`/`include_tests`/预算(`max_unit_bytes`/`orch_budget_bytes`/`max_aggregate_bytes`)/`scout.*`。

- **起始态,非终态**:与 `init_manifest.json`(step 8 写,版本/计数/出处)边界清晰、互不替代——
  `run_config` = 本次 run 的**意图**,`init_manifest` = 本次 run 的**结果**。
- **stateless resume 意图源**:`resume_state.py` 消费它解析 optional/codepath 分支,使 `/mgh-init --resume`
  无需重输 flag。缺失/破损 → `resume_state.py` fail-loud(退出码 2)+ recipe(重跑 `/mgh-init --<flags>`
  重建),NEVER 静默猜步骤图(见 [`resume-state.md`](resume-state.md))。
- 随 `.mgh-init/` gitignore。
