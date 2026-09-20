# resume-step-discipline Specification

## Purpose

压缩后 same-session **从磁盘恢复「在哪步 + 怎么执行」**的确定性机制——补全 R5.4 disk-truth 的真实 gap
(盘上有进度、**无执行纪律 HOW**)。每个运行域以**姊妹脚本**形态落地同一范式:`/mgh-init` 用
`resume_state.py` / `list_steps.py --step`,`/mgh-sdr` 用 `resume_sdr_state.py` / `list_sdr_steps.py`
(init 侧脚本**零改动**,其 blast radius 隔离)。两域均携带 per-step `discipline_reminders[]`
(当前步的 gate 闸门形状 + 路径配方 + 适用 NEVER 反例),各自双壳的 resume/compaction 恢复路径消费之。
使压缩 head 摘要丢失的纪律配方从**磁盘重派生**,抗任意压缩强度、model-independent。

## Requirements

### Requirement: resume_state.py stdout 携带当前步 discipline_reminders[]

`core/scripts/resume_state.py` 的 stdout(既有 7 字段基座 `{target, format, step, resumable, tiers,
next_action, notes}`)SHALL 增 `discipline_reminders[]` 字段——值 = **当前 step**(stdout `step` 值)的纪律子集,
为**增量字段**(不改变既有字段形状/语义;stdout 仍是单对象 JSON,R5.3b)。`discipline_reminders[]` 每项 SHALL
携带该步的:gate 闸门形状(`--check` 命令 + 退出码 2 fail-loud 语义)、路径配方(fan-out 单元输出路径 =
枚举脚本 stdout 的 `checkpoint_path`/`rule_path`,绝对、逐字透传)、适用 NEVER 反例(该步的硬边界,如
`NEVER 拼 <target>/<id>`、`NEVER py -c` 内省)。该字段是 **resume 衍生量、非持久态**:值纯从
`<target>/.mgh-init/` 产物 + `.done`/`.failed` + `run_config.json` 派生,不写入任何磁盘文件;
`--check`(R5.9)不涉及该字段。

#### Scenario: resume 输出携带当前步纪律子集

- **WHEN** 编排器对处于 t1 步的 run 调用 `resume_state.py --target <t>`
- **THEN** stdout 含 `step: "t1"` 且 `discipline_reminders[]` 非空,覆盖 t1 步的:fan-out 路径配方
  (T1 单元输出路径 = `list_clusters.py` stdout `pending[].checkpoint_path`,绝对、逐字透传)、
  T1→T2 shape-gate(`validate_t1_records --strip-bom`+`--check`,退出码 2 → 外科式重派)、适用 NEVER
  (`NEVER 整份 Read clusters.json`、`NEVER 拼 <target>/<cluster>`)

#### Scenario: discipline_reminders 是衍生量,不写盘

- **WHEN** 审阅 `.mgh-init/` 目录产物清单与 `resume_state.py` 写路径
- **THEN** `discipline_reminders[]` 未持久化到任何磁盘文件;两次 `--resume` 调用的值仍逐字一致
  (同一磁盘状态 → 同一纪律子集)

#### Scenario: 无纪律子集的 step 返回空数组而非缺字段

- **WHEN** 当前步是 `done`(流水线已收尾,无下一步纪律)
- **THEN** stdout 仍含 `discipline_reminders[]`,值为空数组 `[]`(字段恒存在,shape 稳定)

### Requirement: list_steps.py --step 携带同 step 纪律子集

`core/scripts/list_steps.py --step <id>`(现输出 `{step, kind, script_abs, invocation, input, output}`,
§B.1)SHALL 增 `discipline` 子集——与 `resume_state.py` 同一 step 枚举 key、同一纪律单一真相
(两脚本共享静态 per-step 纪律表,不允许各自实现)。`--step` 输出的 `discipline` 与
`resume_state.py` 当前步的 `discipline_reminders[]` SHALL 逐字一致(同一 step)。未知 id 仍退出码 2(闭集,
R5.3b 不变);不增 CLI flag(纪律是 stdout 字段,非 flag;R5.1 契约面不受扰动)。

#### Scenario: list_steps --step 与 resume_state 纪律逐字一致

- **WHEN** 对同一 run 分别调用 `list_steps.py --step t1` 与 `resume_state.py --target <t>`(当前步 t1)
- **THEN** `list_steps.py` stdout 的 `discipline` 与 `resume_state.py` stdout 的 `discipline_reminders[]`
  内容逐字一致(单一真相)

#### Scenario: --step 闭集语义不变

- **WHEN** 调用 `list_steps.py --step bogus`
- **THEN** 退出码 2(stderr recipe),stdout 不产 JSON(既有闭集行为不变)

### Requirement: 双壳 resume/compaction 恢复路径消费 discipline_reminders[]

`releases/claude-code/commands/mgh-init.md` 与 `releases/opencode/command/mgh-init.md` 的
Resume/cache 段 SHALL 更新:`--resume`/压缩后**第一步** SHALL 调 `resume_state.py --target <target>`,
从 stdout 读 `step` + `discipline_reminders[]`,**先按该步纪律执行**(gate/路径配方/NEVER),
再 `list_steps.py --step <step>` 取确切调用行。NEVER 靠对话记忆判步骤、NEVER 跳过 gate、NEVER 在
`discipline_reminders[]` 空时静默继续(空数组仅对 `done` 步合法)。该段措辞是**指令性 recipe**
(承 R5.5①:shaping 用 recipe,硬边界才用 NEVER)。

#### Scenario: 压缩后恢复路径从磁盘拿纪律

- **WHEN** 编排器经历压缩/compact 后 resume,当前步 t1,该步纪律曾被压缩摘要丢弃
- **THEN** 编排器首调 `resume_state.py` 读 `step: "t1"` + `discipline_reminders[]`(T1→T2 gate 配方 +
  fan-out 路径配方),按纪律跑 `validate_t1_records --check` + `list_steps --step t1` 取调用行
  再执行;不依赖任何压缩残留的对话记忆

#### Scenario: done 步后不再加载纪律

- **WHEN** 当前步 `done`(流水线已收尾),编排器 resume
- **THEN** `discipline_reminders[]` 为空,编排器进收尾/停止,不空转

### Requirement: 纪律内容单一真相 + 未来合并路径

per-step 纪律表 SHALL 定义**一次**(两脚本共享),内容与既有 `core/prompts/fragments/init-stage-flow.md`
各 step 的纪律措辞对齐(scout-incomplete-gate、T1→T2 shape-gate、fan-out 路径透传、`.failed` ack、
NEVER 反例——全部覆盖,不删减)。未来与 `split-mgh-init-stage-flow-per-step` 合并时(§B.5),
`discipline_reminders[]` SHALL 改从按步 fragment 的纪律段派生(单一真相),当前静态表成为
fragment 拆分前的过渡来源;合并前两 change 互不阻塞。

#### Scenario: 纪律表覆盖全部承重防御

- **WHEN** 审阅静态 per-step 纪律表
- **THEN** 它覆盖 scout-incomplete-gate(退出码 2)、T1→T2 shape-gate(`--strip-bom`+`--check`)、
  fan-out 输出路径 = 枚举脚本 `checkpoint_path`/`rule_path`(绝对逐字)、`.failed` 终态 ack、
  每步适用 NEVER 反例——任一承重防御不随压缩丢失

#### Scenario: 合并路径以 fragment 为单一真相

- **WHEN** `split-mgh-init-stage-flow-per-step` 落地后两 change 合并
- **THEN** 静态表被移除,`discipline_reminders[]` 从 `init-stage/<step>.md` 纪律段派生;
  两 change 各自独立 apply 阶段互不阻塞

### Requirement: scout 合并凭证丢失子状态的精确恢复指引

当 scout 启用、`scout_plan.json::batches[]` 非空、scout readers 全终态(`.done` + `.failed` ≥ total)但
`scout_candidates.json` **缺失**时,`resume_state.py` SHALL 按 merge marker 与 fold-in 子状态区分输出
note 与恢复配方,不得把「凭证缺」与「merge marker 缺」并成一个含糊状态:
- **merge marker 缺**(`checkpoints/scout/merge.json.done` 不在)→ 合并未跑:note SHALL 载明
  「regen `scout_candidates.json` 后 fold-in 仍待跑」,next_action = spawn `init-scout-merge`。
- **merge marker 在 + fold-in 已跑**(`controls_candidates.json::provenance.scout_merged` 存在)→
  note SHALL 载明:`scout_merged` 的并入证据(值)、`scout_candidates.json` 仅作完成凭证(内容无
  下游消费、LLM 重生成漂移无害)、NEVER 重跑 `merge_scout.py` fold-in、regen 后 `resume_state`
  重派生 `step=t1`。next_action = spawn `init-scout-merge`(诚实重生成)。
- **merge marker 在 + fold-in 未跑**(`scout_merged` 不存在)→ 凭证与 fold-in 均欠:note SHALL 载明
  「regen 凭证后 fold-in 待跑」,next_action = spawn `init-scout-merge`。

所有子状态 next_action 恒为 spawn `init-scout-merge`——**唯一恢复路径**(诚实重生成,宁花 LLM
token 不做占位凭证);重生成内容仅作完成凭证、漂移无害。

#### Scenario: fold-in 已跑但凭证丢失(真实失败形态)

- **WHEN** scout readers 全终态、`merge.json.done` 在、`controls_candidates.json::provenance.scout_merged=760`
  在、但 `scout_candidates.json` 缺失,编排器调用 `resume_state.py`
- **THEN** stdout `step="scout"`、next_action = spawn `init-scout-merge`,note 精确载明「fold-in 已跑
  (scout_merged=760)、regen 仅作完成凭证、NEVER 重跑 merge_scout.py fold-in、regen 后 step=t1」;
  note 不出现「merge marker absent」字样

#### Scenario: merge marker 缺失(合并确未跑)

- **WHEN** scout readers 全终态但 `merge.json.done` 与 `scout_candidates.json` 均缺
- **THEN** note 载明「合并未跑,regen 凭证后 fold-in 待跑」,next_action = spawn `init-scout-merge`

#### Scenario: merge marker 在但 fold-in 未跑

- **WHEN** `merge.json.done` 在但 `controls_candidates.json` 无 `provenance.scout_merged`,且
  `scout_candidates.json` 缺
- **THEN** note 载明「凭证与 fold-in 均欠,regen 后 fold-in 待跑」,next_action = spawn `init-scout-merge`

### Requirement: scout 步纪律表包含「NEVER 重跑 fold-in」反例

`core/scripts/discipline_core.py` scout 步的 `discipline_reminders[].nevers` SHALL 增反例:
「NEVER 重跑 `merge_scout.py` fold-in(`controls_candidates.json::provenance.scout_merged` 已设时;
重跑非幂等——同文件重跑把 `scout_merged` 归零,漂移文件重跑重复追加候选/簇)」。该反例随
`resume_state.py` stdout `discipline_reminders[]` 与 `list_steps.py --step scout` stdout `discipline`
逐字下发(两脚本共享同一纪律表,单一真相)。

#### Scenario: scout 步 resume 收到 fold-in 反例

- **WHEN** 编排器对处于 scout 步的 run 调用 `resume_state.py --target <t>` 或
  `list_steps.py --step scout`
- **THEN** stdout `discipline_reminders[].nevers` / `discipline.nevers` 含「NEVER 重跑 merge_scout.py
  fold-in(scout_merged 已设时)」反例,且两脚本逐字一致

### Requirement: resume-state 契约纠正「fold-in 重跑幂等安全」主张

`core/contracts/init/resume-state.md` SHALL 纠正既有「该键存在 ⟺ fold-in 已跑(再跑幂等、安全)」
的错误主张,改为:`provenance.scout_merged` 存在 ⟺ fold-in 已跑;fold-in **重跑非幂等**(同文件
重跑把 `scout_merged` 覆盖为 0 并触发虚假召回缺口披露,漂移重生成文件重跑重复追加候选/簇);
resume_state 在 `scout_merged` 存在时 MUST NOT 建议或指引重跑 `merge_scout.py` fold-in。契约 SHALL
补记「fold-in 已跑 + 凭证缺」子状态的恢复配方与 `--check` 违例(配方见 `scout-tier-gate`)。

#### Scenario: 契约不再宣称重跑安全

- **WHEN** 维护者读 `core/contracts/init/resume-state.md` 的 fold-in 检测段
- **THEN** 该段明确「scout_merged 在 ⟺ fold-in 已跑;重跑非幂等;resume_state 不得在 scout_merged
  存在时建议重跑 fold-in」,不再出现「再跑幂等、安全」之类主张

### Requirement: resume_state stdout 携带 stale-fanout 检出(stale_fanout)

`resume_state.py` 的 stdout SHALL 增 `stale_fanout` 字段(增量字段,基座 shape 不变):扫
`<init-dir>/fanout_runner.*.pid` liveness 文件,每份残留文件报
`{tier, pid_file, pid_alive, note}`;`pid_alive` = 该 PID 当前存活(OS 进程表查询)。
任一 `pid_alive:true` → `note` SHALL 附 `--kill-stale --dry-run` recipe(编排器 resume
第一步先杀孤儿再继续,防双跑烧 token + checkpoint 竞态)。无 liveness 文件 → `stale_fanout:
[]`(字段恒存在,shape 稳定,承 resume_state 既有空结构约定)。该字段是 resume 衍生量、非
持久态;`--check` 对 stale-fanout SHALL 仅 advisory 披露(notes[]),NEVER 作为 gate(孤儿
单元留 pending 本就是合法可重派态,杀死旧 runner 是优化而非正确性前提)。

#### Scenario: 孤儿 fanout 在 resume 时被点名

- **WHEN** 上次 t1 fanout 被硬杀、宿主子进程树仍在跑,编排器执行 `/mgh-init --resume` 第一步
  `resume_state.py --target <t>`
- **THEN** stdout `stale_fanout` 含该 tier 条目(`pid_alive:true` + kill-stale recipe),
  `notes[]` 含 advisory 披露;step/next_action 派生逻辑不受影响(仍按磁盘 marker 重派 pending)

#### Scenario: 无孤儿时字段空但不缺

- **WHEN** 运行目录无任何 `fanout_runner.*.pid` 残留
- **THEN** stdout 含 `stale_fanout: []`(字段恒存在),无 note,`--check` 无 stale 相关披露

### Requirement: 计数口径披露与自洽校验

`resume_state.py` 的 done 口径 SHALL 为「canonical 单元 id 的正向 marker 存在性」——与
`list_clusters.py`/`list_scout_batches.py` 的判定同源(同一编码函数正向计算 marker 路径),
而非裸 glob 文件计数。`--help`/docstring SHALL 注明各消费方口径:
1. `resume_state.py` 的 tier done = canonical id 集上正向判定 done 的单元数(与枚举脚本
   `pending[]` 语义一致:pending 恒可推导为 `total - done - failed`);
2. `ls checkpoints/<tier>/` 目录条目数 = done marker + `.failed` marker + 记录体 `.json`
   + tier 级 merge/audit marker,含孤儿产物 → 与口径 1 可不等;
3. 两数差非数据丢失(口径不同);**孤儿 marker** (不对应任何 canonical id 的磁盘 marker)
   由枚举脚本 stderr 审计告警、由 `resume_state.py --check` 列出(不计入任何 tier 计数,
   fail-soft 提示,不阻断)。

`--check` 自洽校验 SHALL 覆盖:某 canonical 单元同时携带 `.done` 与 `.failed`(歧义终态,
violation);canonical 单元判 pending 但其 marker 文件已存在(判定不一致 = 枚举脚本与磁盘
真相漂移的确定性信号,violation);孤儿 marker(advisory note,非 violation)。
理由〔口径披露是给「人比对文件数与 stdout 数字」的场景;判定不一致从「静默口径差」升级为
「--check 可检 violation」后,身份漂移类缺陷(mgh-init 实测:超长 id 簇 done 判定漂移致
无限重派)在边界即 fail-loud,不再依赖 fan-out 运行时暴露〕。

#### Scenario: 用户比对 stdout 与目录条目数
- **WHEN** 用户比对 stdout `tiers.t1.done` 与 `checkpoints/t1/` 下文件数
- **THEN** `resume_state.py` docstring/--help 注明口径差异:done = canonical id 正向判定,
  目录条目数含孤儿与记录体;两数差非数据丢失

#### Scenario: 判定不一致是 --check violation
- **WHEN** 某 canonical 单元无 `.done`/`.failed` marker(按正向路径计算判 pending),但其
  checkpoint 目录存在编码后与该单元 marker 路径相同的文件(判定与磁盘真相矛盾)
- **THEN** `resume_state.py --check` 退出码 2,violations 列出该单元 id + 磁盘 marker 路径
  + 修复 recipe;stdout `pending` 语义不变

#### Scenario: 孤儿 marker 是 advisory note
- **WHEN** checkpoint 目录存在不对应任何 canonical id 的 `.done`/`.failed` marker
  (遗留 run 产物)
- **THEN** `resume_state.py --check` 将其列入 notes[](advisory),不 violation、不阻断;
  tier 计数不含孤儿

### Requirement: sdr 运行域的状态重派生(resume_sdr_state.py)

新增确定性叶脚本 `core/scripts/resume_sdr_state.py`(Python ≥3.10 标准库、零运行时依赖、自定位、
任意 cwd 可 `py`,承 R5.3a)SHALL 为 `/mgh-sdr` 恢复面「我现在在哪一步 / 下一步调什么」的唯一出口。
其 `step` 与 `next_action` SHALL 纯从 `<run-dir>/` 磁盘产物重派生——`context.json` / `grouping.json` /
单元 marker(`<run-dir>/markers/<unit_id>.done|.failed`)/ `sdr_manifest.json`——SHALL NOT 读对话记忆,
SHALL NOT 读取 `<run-dir>/run_config.json`(该文件在本 change 只承载 codegraph 信号,不含起始态;
见 `security-design-review`)。起始态一律来自 `context.json` / `grouping.json`。

init 域既有脚本 `core/scripts/resume_state.py` SHALL 保持**零改动**(其 blast radius 隔离);sdr 域以
**姊妹脚本**形态落地,与既有 ut-init 域 `resume_ut_init_state.py` 同范式。

sdr 的 run 目录有两种产生路径(launcher 的 `<repo>/.mgh-sdr/runs/<ts>-<branch>/` 与命令壳的
`--run-dir`),该脚本 SHALL 对两者一视同仁——**只吃一个 run 目录**,不对目录命名做任何假设。

CLI 契约(`--help` 即契约面,R5.1):
`py resume_sdr_state.py --run-dir <abs> [--repo <abs>] [--check] [--rearm-sentinel]`

- `--run-dir` 为**必填**(sdr 无唯一缺省 run 目录,`runs/<ts>` 每次不同);缺该 flag → argparse 退出码 2。
- `--run-dir` 指向不存在的目录 → 退出码 1(路径错/误用,stderr 给可操作 recipe)。
- `--check` 自洽校验失败 → 退出码 2;`--rearm-sentinel` 成功 → 退出码 0;其余 → 退出码 0。
- `--repo` 可省:按 `<run-dir>` 路径布局(`<repo>/.mgh-sdr/runs/<…>`)推导;推不出时相关字段降级并在
  `notes[]` 披露(见「起始态不可重派生时的显式退化披露」)。

stdout SHALL 为单对象 JSON(R5.3b:stdout = 结构化 JSON,stderr = 诊断/进度严格分流),至少含:

| 字段 | 语义 |
|---|---|
| `repo` / `run_dir` | 绝对路径(Windows 原生,Python `Path.resolve()` 产出,NEVER shell 的 MSYS 形态) |
| `base` / `branch` | 从 `context.json`(缺则 `grouping.json`)重派生;两者冲突以 `context.json` 为准并在 `notes[]` 披露 |
| `step` | 闭集枚举,**当前待办步** |
| `resumable` | 布尔;`step == "done"` → `false` |
| `tiers` | `{done, failed, total}`(口径见下) |
| `next_action` | `{kind: "bash"\|"subagent"\|"done", desc, absolute_paths[]}` |
| `notes[]` | 披露与 advisory(退化、缺口、失败单元、孤儿 marker 等) |
| `discipline_reminders` | 当前步纪律子集 `{gates[], path_recipes[], nevers[]}`(字段恒存在) |
| `stale_fanout[]` | `<run-dir>/fanout_runner.*.pid` 残留扫描 `{tier, pid_file, pid, pid_alive, note}`(字段恒存在) |

`tiers` 的 `done`/`failed` SHALL 为「canonical 单元 id 的正向 marker 路径存在性」判定(与 `diff_group.py`
的枚举口径**同源**),SHALL NOT 由 glob 文件数或文件名 stem 反推(身份漂移类缺陷的确定性防线)。

#### Scenario: 中断的 run 返回磁盘一致的步骤与下一步

- **WHEN** 一个 fan-out 中途被打断的 sdr run(部分单元 `.done`、部分 pending)被 `resume_sdr_state.py --run-dir <abs>` 查询
- **THEN** stdout `step="fanout"`,`next_action.kind="bash"` 且 `desc` 载明 `fanout_runner.py --tier sdr` 的确切调用,
  `next_action.absolute_paths[]` 为逐字取自磁盘的 repo / checkpoints / slices 绝对路径(无占位符、无相对路径);
  `notes[]` 披露未终态单元计数

#### Scenario: 同一磁盘状态重复查询输出稳定

- **WHEN** 磁盘状态不变时对同一 run 目录连续调用两次
- **THEN** 两次 stdout 逐字一致(纯函数于磁盘状态,幂等)

#### Scenario: 重派生不读任何「起始态」文件

- **WHEN** 对一个**含**历史遗留 `run_config.json` 的旧 run 目录查询
- **THEN** 该文件既不被读取也不影响输出(base/branch 全部来自 `context.json`/`grouping.json`)

### Requirement: sdr 步骤图、终止凭证与 marker 谓词单一真相

`resume_sdr_state.py` SHALL 按下列确定性规则派生 `step`(按序短路;判据全部是 `<run-dir>/` 下的磁盘存在性,
无任何对话态输入),`next_action` 为该步的确切调用。`step` 名 = **当前待办步**(与 init 域 `t1`/`t2` 语义一致:
`step` 说「下一步要做什么」,而非「上一步做完了什么」):

| `step` | 判据 | `next_action` 指向 |
|---|---|---|
| `not-started` | `context.json` 不存在 | `sdr_context.py --repo <abs> --run-dir <abs>`(该步同时完成运行域激活:哨兵由 `sdr_context` 确定性 co-write) |
| `group` | `context.json` 存在、`grouping.json` 不存在 | `diff_group.py --repo <abs> --base <ref> --branch <ref> --checkpoints <run-dir>/markers --materialize <run-dir>/slices` |
| `fanout` | `grouping.json` 存在、且未全部单元终态 | `fanout_runner.py --tier sdr --repo <abs> --base <ref> --branch <ref> --checkpoints <run-dir>/markers --inputs-dir <run-dir>/slices`(带四级超时三参数) |
| `render` | 全部单元终态(`done + failed ≥ total`)且 `sdr_manifest.json` 不存在 | `render_sdr_report.py --run-dir <abs> --repo <abs>` |
| `done` | `sdr_manifest.json` 存在 | 无(run 已收尾,`resumable=false`) |

- **终止凭证**:整条 run 的终态凭证 SHALL 为 `<run-dir>/sdr_manifest.json`(与 init 域 `init_manifest.json`
  同角色);该文件不存在 ⇒ run 未收尾。
- **零 diff / 全排除**:`grouping.json::empty == true`,或 `total == 0` 但 `excluded.count > 0`(diff 全被
  排除集吃掉)⇒ fan-out 步空跑即完成(`0 ≥ 0`),`step` 直接推进到 `render`,SHALL NOT 停在 fan-out 空转。
- **单元终态判据**:SHALL 只看 marker 文件(`done_marker` / `failed_marker`)是否存在,
  SHALL NOT 采信 `grouping.json::units[].status`(该字段在**枚举时点**算出,fan-out 之后即陈旧)。
- **marker 谓词单一真相**:单元 marker 路径的拼接规则 SHALL 定义**一次**,由写入方 `diff_group.py`
  与读取方 `resume_sdr_state.py` **共享导入**(新共享模块,与 init 域 `init_tier.py` 承载
  `forward_marker_paths`/`forward_done_ids` 同范式),SHALL NOT 各写一份拼接
  (口径分叉 = 「枚举说 pending、磁盘说有 marker」的无限重派缺陷类)。

#### Scenario: 全终态的 run 推进到渲染步

- **WHEN** 某 run 的全部单元都已终态(`.done` + `.failed` ≥ `total`),但 `sdr_manifest.json` 不存在
- **THEN** stdout `step="render"`,`next_action` 为 `render_sdr_report.py --run-dir <abs> --repo <abs>` 的调用

#### Scenario: 零 diff 的 run 不停在 fan-out 空转

- **WHEN** `git diff` 为空(`grouping.json::empty == true`,`total == 0`)
- **THEN** stdout `step="render"`(fan-out 步因 `0 ≥ 0` 视为已完成),`notes[]` 载明零变更

#### Scenario: 陈旧 status 字段不参与判定

- **WHEN** `grouping.json::units[].status` 全部写 `pending`(枚举时点快照),但磁盘 marker 显示多数单元已终态
- **THEN** stdout `tiers` 的 `done`/`failed` 反映**磁盘 marker 真相**(不采信 `status` 字段),`step` 相应推进到 `render`

### Requirement: 起始态不可重派生时的显式退化披露

在 `not-started` 步,`context.json` 尚未存在,起始态(尤其 `--base` / `--branch`)在磁盘上**无可判定产物**。
该脚本 SHALL 在此情形**显式披露**退化,SHALL NOT 静默猜测步骤或参数:`notes[]` SHALL 载明「起始态未落盘,
需重新给定」,`next_action.desc` SHALL 给出可执行的重新给参调用(含默认值提示 — `--base master`、
`--branch` 为当前分支),`repo` SHALL 在可由 run 目录路径推出时给出,推不出则要求 `--repo` 显式传入。

该退化 SHALL NOT 被描述为数据丢失:这一步恰是**零已完成工作**的步(run 目录刚建立),重新给参重跑即完整恢复。
`run_config.json` 之所以可以退场,正是由这一条支撑——唯一「磁盘上没有起始态」的步,也正是唯一「没有工作可丢」的步。

#### Scenario: 空 run 目录查询披露退化并重新给参

- **WHEN** 对刚建立、尚无任何产物的 `<repo>/.mgh-sdr/runs/<ts>/` 查询
- **THEN** stdout `step="not-started"`、`resumable=true`;`notes[]` 载明起始态未落盘;
  `next_action.desc` 给出 `sdr_context.py --repo <abs> --run-dir <abs> --base master --branch <当前分支>` 形态的可执行调用

#### Scenario: 推不出 repo 时不猜

- **WHEN** `--run-dir` 指向的路径不符合 `<repo>/.mgh-sdr/runs/<…>` 布局、且未传 `--repo`
- **THEN** `repo` 为空且 `notes[]` 指明需显式传 `--repo`;SHALL NOT 编造一个仓库根

### Requirement: sdr 纪律表与 per-step 纪律携带

`core/scripts/discipline_core.py` SHALL 从「init 单域静态表」扩展为**按域分表**:
`get_discipline(step, domain="init")` 默认域 `init`(既有两处调用零改动),新增 `domain="sdr"` 表,
其 key 与 `resume_sdr_state.py` 的 step 闭集一致(`not-started|group|fanout|render|done`)。

sdr 各步的纪律子集 SHALL 携带:

- **gate 闸门形状**:该步产出者的 `--check` 命令 + 退出码 2 fail-loud 语义
  (`sdr_context.py --check` / `diff_group.py --check` / `render_sdr_report.py --check`);
- **路径配方**:fan-out 单元的输入切片 / 草稿 / 完成标记 / 失败标记 = `diff_group.py` stdout
  `pending[].input_path|draft_path|done_marker|failed_marker`(**绝对、逐字透传**);
  `baseline_path` / `external_dir` 同源;
- **适用 NEVER 硬边界**(该步的硬边界,如 `NEVER 自拼路径`、`NEVER py -c 内算路径`、`NEVER Read 叶子源码`)。

纪律表内容 SHALL 与 `mgh-sdr.md` 双壳的 Orchestration flow 承重防线保持一致(同一步两处 MUST 输出同构内容):
fan-out 刚性三元组、四级超时不变式(`--stall-timeout-s < --call-timeout-s < --time-budget-ms × 0.8`)、
每步 `--check`、快败冷却形态与 `--retry-failed` 配方、非 ok 单元的 `run.log` 证据路径。

该纪律子集是 **resume 衍生量、非持久态**:不写入任何磁盘文件,`--check` 不涉及该字段;
无纪律的步(`done` / `not-started`)与未知步 SHALL 返回**空结构**(三键恒存在,shape 稳定)。

#### Scenario: fan-out 步的 resume 携带路径配方与硬边界

- **WHEN** 编排器对处于 fan-out 步的 run 调用 `resume_sdr_state.py`
- **THEN** stdout `discipline_reminders.path_recipes[]` 含「单元路径取自 `diff_group.py` stdout `pending[]` 字段、绝对逐字透传」配方,
  `discipline_reminders.gates[]` 含 `diff_group.py --check`(失败退出码 2),
  `discipline_reminders.nevers[]` 含该步硬边界;三者与 `mgh-sdr.md` 双壳同一步的措辞同构

#### Scenario: 无纪律的步返回空数组而非缺字段

- **WHEN** 当前步是 `done`(run 已收尾)
- **THEN** stdout 仍含 `discipline_reminders` 且三键均为空数组(字段恒存在,shape 稳定)

### Requirement: list_sdr_steps.py --step 携带同 step 纪律子集

新增 `core/scripts/list_sdr_steps.py` SHALL 输出 sdr 步清单
`{steps:[{step, kind, script, script_abs, invocation, input, output, discipline}]}`:
`invocation` 为可复制粘贴的调用行,`script_abs` 由 `__file__` 自定位派生,`discipline` 与
`resume_sdr_state.py` 当前步的 `discipline_reminders[]` **逐字一致**(同一 step,同一纪律单一真相)。

`--step <id>` SHALL 只接受**命名 id**(闭集);未知 id → 退出码 2 + stderr 可操作提示;
不新增 CLI flag(纪律是 stdout 字段,非 flag,R5.1 契约面不受扰动)。

#### Scenario: list_sdr_steps 与 resume_sdr_state 纪律逐字一致

- **WHEN** 对同一 run 分别调用 `list_sdr_steps.py --step group` 与 `resume_sdr_state.py --run-dir <abs>`(当前步 group)
- **THEN** 前者的 `discipline` 与后者的 `discipline_reminders[]` 逐字一致

#### Scenario: 未知 step id 闭集拒收

- **WHEN** 调用 `list_sdr_steps.py --step bogus`
- **THEN** 退出码 2 + stderr 列出已知 id;stdout 不产 JSON
