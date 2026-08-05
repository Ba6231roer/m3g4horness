## Context

`/mgh-sast` s4 deep-dive fan-out 与 init scout/T1 共用大文件切片工具 `chunk_sources.py`,但漏装了 init 端
已落地的两条路径纪律。`harden-mgh-init-slice-and-tool-pinning`(2026-08-05 archive)的 Non-Goals 显式把 sast
留作后续 adoption;本变更即该 adoption。

**当前 sast 端的具体缺口(读码确认)**:

- `core/prompts/stages/s4-system.md` Sanctioned tools(`:168`):「only `chunk_sources.py`, when you must slice
  a large file to read it」——**未钉 `--out` 写哪**。sast-deepdive subagent 自发明 `--out`;opencode 下 subagent
  进程 cwd = `…\Temp\opencode\` → 切片落树外 → 回读触发越权 `Read` 提示(与 init 端实测失败同形)。
- `core/scripts/list_chunks.py`:stdout `pending[]` 产 `input_path`/`checkpoint_path`/`done_marker`/`needs_slice`
  (均 `resolve()` 绝对)但**无 `slice_dir`**;顶层无工具基字段。
- 两份 `mgh-sast.md`:s4 fan-out(`:92`/`:89`)仅透传 `input_path`;`chunk_sources` 示例(`:150`/`:147`)用相对
  脚本路径 + `--out security-scan/_slice.json`(相对 subagent cwd,非树内绝对);无 step-0/枚举时工具基获取。
- 双端 `sast-deepdive` agent(`:25`/`:30`):「slice any file in `needs_slice[]` via `chunk_sources.py`」——无
  `slice_dir` recipe、无绝对工具路径。

**跨命令总纲已就位**:`request-context-budget` spec 第 143 行(由 init 变更同步)已要求「所有 fan-out 路径
绝对+树内+逐字」并点名 `<target>/security-scan/slices/s4/<chunk>/`。本变更不重改横切 spec,只在 sast 端闭合
执行 + 在 `sast-orchestration-discipline` 落 sast 专属 requirement。

约束:R2(零运行时依赖)、R5.3a(脚本 cwd 无关)、R5.5①(recipe 非 prohibition,硬边界才 NEVER)、R5.7(opencode
插件进程不继承 mid-session bash env → 路径经 stdout/磁盘传递,不经 env)、R5.10(分发纯净)。`list_chunks.py`
经 `--checkpoints`/`--materialize` 接收绝对或相对路径、`resolve()` 输出;`chunk_sources.py --out` 默认相对 cwd
(`shards.json`)、保持 cwd 无关。

## Goals / Non-Goals

**Goals:**

- 切片输出钉到受信子树 `<target>/security-scan/slices/s4/<safe(chunk_id)>/`,sast-deepdive 树内写 + 树内回读
  (消除越权 `Read` 提示 + 落 hook 受信子树自动放行)。
- 工具脚本路径钉到**当前 install**(经 `list_chunks.py` stdout `scripts_dir`),消除双层 install 下命中父层旧副本。
- 双端对等(claude/opencode),零新增依赖,`chunk_sources.py` cwd 无关性不破。

**Non-Goals:**

- 不改 `chunk_sources.py`(保持 cwd 无关 + 人类 ad-hoc 可用)。
- 不改 `s4-output-schema.md`(其 "slice" 是 vvah 分析切片概念,非切片文件)。
- 不覆盖 s6/s8(s6 = verify-job fan-out,不切片;已 grep 核实。s8 = chain subagent,不切片)。
- 不改 init 端(已覆盖)/ 不改 `request-context-budget`(横切总纲已含 sast)。
- 不重写全壳相对→绝对(仅钉 subagent 用的 `chunk_sources`;编排器其它相对叶子调用超 scope)。
- 不填充 `.active` 哨兵 `target`(独立 hook 议题;降级子树检查已放行树内写)。

## Decisions

### D1 — 切片输出由 `list_chunks.py` stdout 新增 `slice_dir` 钉死(非改脚本默认)

`list_chunks.py` 在每个 `pending[]` 项新增 `slice_dir`(绝对、`Path.resolve()`、落
`<命令输出目录>/slices/s4/<safe(chunk_id)>/`)。`<命令输出目录>` = `--checkpoints` 的祖父目录
(`checkpoints/s4` → `checkpoints` → `security-scan`)= `<target>/security-scan`,与 `checkpoint_path` 同根。
编排器逐字透传;subagent 写 `chunk_sources.py --out <slice_dir>/<safe-stem>.slice.json` 并回读该确切路径。

| 选择 | 理由 |
|---|---|
| 契约层钉路径(`list_chunks` 产 `slice_dir`) | 与 `checkpoint_path`/`input_path` 钉法同构(同由枚举脚本产、编排器透传),单一范式;additive 字段不破既有 schema |
| 否决:改 `chunk_sources.py --out` 默认/校验 | 脚本须 cwd 无关(R5.3a)、人类 ad-hoc 可用;让脚本假设项目树破此特性(承 init D1) |

### D2 — `slice_dir` + 确定性 stem 规则(非 per-file 全预算 `slice_path`)

统一用 `slice_dir`(每 chunk 一个)+ subagent 命名 `<safe-stem>.slice.json`(`_safe_name`: `/ \ :`→`_`)。s4 的
`needs_slice[]` 由 `list_chunks.py` 据 `--repo` + `--big-file-bytes` **预算期就知道**并写入 input 文件,理论上可
per-file 预算 `slice_path`;但选 `slice_dir`+stem 以与 init 端**同机制**(scout/T1 已落地),减少提示词/测试面。

| 选择 | 理由 |
|---|---|
| `slice_dir` + stem 规则(与 init 同形) | 全产品单一切片机制;dir=逐字绝对字段 + stem=纯文件名,「拼装」此处有界,不触发 R5.3b「`<target>/<id>` 占位符漂移」(dir 非空绝对) |
| 否决:s4 走 per-file `slice_path` | 虽可行(needs_slice 预算期已知),但与 init 两套机制;统一性胜过 per-file 精确 |

> 边界:`<safe-stem>` 取源文件 stem(去扩展名),collision 罕见(同 chunk 内同 stem 不同扩展极少);若发生,subagent
> 后写覆盖前写(切片为一次性读后即弃,可接受)。披露于 risks。

### D3 — 工具基经 `list_chunks.py` stdout `scripts_dir` 钉到当前 install(**非** `list_steps.py`)

`list_chunks.py` 顶层新增 `scripts_dir` = `Path(__file__).resolve().parent` = **当前运行 install** 的
`<mgh-core>/scripts/` 目录。编排器在 s4 fan-out(已调 `list_chunks`)读 stdout `scripts_dir`,把绝对
`<scripts_dir>/chunk_sources.py` 透传进 sast-deepdive task;prompt SHALL 用该绝对路径 verbatim。

| 选择 | 理由 |
|---|---|
| `list_chunks.py` stdout `scripts_dir`(`__file__` 派生) | s4 fan-out **已调** `list_chunks`,零额外调用;`__file__` 指当前项目副本 → 广播绝对路径给 subagent,消除 `.opencode/`/`.claude/` 上溯歧义;经 stdout 传递绕开 opencode「插件进程不继承 mid-session env」边界(R5.7) |
| 否决:`list_steps.py` `script_abs`(init 用法) | `list_steps.py` 是 **`/mgh-init` 专属**(docstring「for /mgh-init」、step 表 = discover/scout/t1/t2/t3);从 sast 调它会副作用打印 init 步骤 = 范畴错误 |
| 否决:`<target>/.claude\|.opencode/mgh-core/scripts` 派生 | 假设 install-dir == target(可 install 在 A、分析 B) |
| 否决:env `MGH_TOOL_BASE` | opencode 插件进程不继承 mid-session bash env(同 R5.7 哨兵动机) |

> 与 init 的差异:init 在 step 0 经 `list_steps.py` 取 `script_abs`;sast 在 s4 fan-out 经 `list_chunks.py` 取
> `scripts_dir`——因 sast 无 `list_steps` 等价物,而 `list_chunks` 本就在该步被调。机制等价(`__file__` 派生 +
> stdout 传递),锚点不同。

### D4 — `chunk_sources.py` 不改(cwd 无关性保留)

切片「写哪」由契约钉(D1),脚本保持「slice 文件、写 `--out`」的 cwd 无关契约。符合 R5.5①:recipe(「写
`--out <slice_dir>/<stem>.slice.json`」)在 prompt,非把 prohibition 打进脚本。

### D5 — 切片 Write 落既有受信子树,无需改 hook

`<target>/security-scan/` 是 sast 运行域;`block-adhoc-scripts` 正向允许运行域内 `Write`/`Edit`;
`slices/s4/<chunk>/` 在其内 → 切片 Write 自动放行,且切片 JSON 非脚本扩展名 → 不触脚本写入拦截。`.active` 哨兵
`target` 当前为空 → 子树检查降级放行(不误伤树内写)。D1 把「树外 Write」(guard 主机上事后拦 / 非 guard 主机上
弹越权提示)转为「树内 Write」(放行 + 无提示 + 有界)。`runtime-hook-enforcement` 能力**无改**(承 init D5)。

### D6 — 仅 s4 切片;s6/s8 不涉(grep 核实)

`chunk_sources` 在 sast 全部 stage 提示词中**仅**出现在 `s4-system.md` + `s4-output-schema.md`(后者 "slice" 是
vvah 分析概念);s6(`s6-verify.md`)走 `list_verify_jobs.py` 的 finding 级 fan-out(无大文件切片)、s8(`s8-chain.md`)
为 chain subagent(无切片)。故 scope = s4 only。

### D7 — chunk_id 干净(`chunk-NN`),`_safe_name` 防御性 parity

vvah s3 发 `chunks[].id` = `"chunk-NN"`(filename-safe,**无** init `cluster_id` 的 `::`)。`_safe_name` 对当前值
为 no-op,但仍施加(与 init T1 同源消毒),防御未来 chunk_id 形态变化(承 NTFS ADS 规约,见
`core/contracts/init/unit-inputs.md`)。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| `slices/` 在 `security-scan/` 内累积 | `security-scan/` 已 gitignore + 整 run 清理;slices 随之而去。每 chunk ≤ 数个切片(超 `--big-file-bytes` 的文件数有界)。无需清理脚本(R3)。若某 chunk 大文件多,记 `boundaries[]` |
| subagent 仍发明路径违 recipe | recipe 是正引导;硬边界 `NEVER`(相对/Temp/树外 `--out`)兜底;hook 子树守卫是确定性 backstop(guard 主机上树外 `security-scan` 邻接写被拦)。belt-and-suspenders |
| `list_chunks.py` 首调命中错副本(bootstrap) | 编排器首调用相对 `.claude\|.opencode/mgh-core/scripts/list_chunks.py`,解析于编排器 Bash cwd(`/mgh-sast` 被调项目,命令壳加载处)。若用户从歧义 cwd 调 `/mgh-sast`,是 launch-cwd 问题,本修不涉;披露:从目标项目根调 `/mgh-sast`。下游经 `scripts_dir` 全钉死 |
| orchestrator 其它相对叶子调用仍相对 | D3 仅钉 subagent 用的 `chunk_sources`;`prefilter`/`dedup`/`emit_sarif` 等仍相对。本变更不扩到全壳相对→绝对重写(超 scope);若再现,另起 `harden-mgh-sast-absolute-tool-base` |
| 同 chunk 内 stem collision | 见 D2 边界;切片一次性读后弃,后写覆盖可接受 |

## Migration Plan

- additive:`pending[]` 增 `slice_dir`;顶层增 `scripts_dir`;旧消费者忽略未知字段不受影响。
- 无 on-disk schema 迁移(slices 为 `security-scan/` 内 ephemeral)。
- 回退:删 `slice_dir`/`scripts_dir` 字段 + 还原 prompt/agent/壳 → 退回旧行为(subagent 又得自发明 `--out`——即
  回退到本变更前的不安全态,非静默)。
- 版本:受影响 `.md`/脚本 bump(承 R5.8),`install.sh` 自检 fail-soft + CI 必过(承 R5.8)。
- apply 顺序:`list_chunks.py` 加字段 → 契约 md → prompt(双端 agent 定义)→ 双端命令壳 → 测试 → 版本/lint/CHANGELOG。

## Open Questions

propose 时已全部解决,记录于 Decisions:

- s6/s8 是否切片?→ 否,仅 s4(D6,grep 核实)。
- s4 chunk_id 是否需 NTFS 消毒?→ 干净(`chunk-NN`),`_safe_name` 防御性 parity(D7)。
- 工具基是否经 `list_steps.py`?→ 否,经 `list_chunks.py` stdout `scripts_dir`(D3,`list_steps` 为 init 专属)。
