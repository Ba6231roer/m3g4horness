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
[]`(字段恒存在,shape 稳定,承 resume_state 既有空结构约定)。**字段恒存在承诺 SHALL 覆盖
全部 step 分支,含 `run_config.mode=merge` 的短路分支**(修复前 merge 分支缺该字段,违背
「field always present」承诺,消费方下标访问即 KeyError)。该字段是 resume 衍生量、非
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

#### Scenario: merge 模式分支同样携带字段

- **WHEN** `run_config.mode=merge` 的 run 被查询(merge 短路分支)
- **THEN** stdout 含 `stale_fanout`(无残留时为 `[]`),字段集与常规分支一致

### Requirement: 计数口径披露与自洽校验

`resume_state.py` 的 done 口径 SHALL 为「canonical 单元 id 的正向 marker 存在性」——与
`list_clusters.py`/`list_scout_batches.py` 的判定同源(同一编码函数正向计算 marker 路径),
而非裸 glob 文件计数。**canonical id 集本身 SHALL 与枚举器口径合一**(单一真相,禁止第二份
退化实现):

1. **t1 的 id 集 SHALL 经 `list_clusters.py` 生产者侧共享函数复算**:读 `clusters.json` +
   `controls_candidates.json` 真实候选,按**共享默认单元预算**(与枚举器 `--max-unit-bytes`
   缺省值同一常量、共享导入,NEVER 各持一份)派生整簇 id + 真超预算簇的 `::shard-<n>` 分片
   id。SHALL NOT 以空候选集/零预算的退化入参调收集器——该入参下分片簇永判未完,step 永卡
   t1(2026-10-13 评审唯一 Critical 的根因);
2. **t3 的 id 集 SHALL 由「`controls_inventory.json` 的 categories × run format」派生**
   `<category>.<fmt>` 单元 id(id 公式与 `list_rule_jobs.py` 单一来源共享导入),done/failed
   按正向 marker 判定;SHALL NOT 裸 glob 计数(孤儿 marker 不得抬高 done 静默跳过 pending
   category);
3. scout 的 id 集维持 `scout_plan.json::batches[].batch_id`(既有口径不变)。

`--help`/docstring SHALL 注明各消费方口径:
1. `resume_state.py` 的 tier done = canonical id 集上正向判定 done 的单元数(与枚举脚本
   `pending[]` 语义一致:pending 恒可推导为 `total - done - failed`);
2. `ls checkpoints/<tier>/` 目录条目数 = done marker + `.failed` marker + 记录体 `.json`
   + tier 级 merge/audit marker,含孤儿产物 → 与口径 1 可不等;
3. 两数差非数据丢失(口径不同);**孤儿 marker** (不对应任何 canonical id 的磁盘 marker)
   由枚举脚本 stderr 审计告警、由 `resume_state.py --check` 列出(不计入任何 tier 计数,
   fail-soft 提示,不阻断)。

`--check` 自洽校验 SHALL 覆盖:某 canonical 单元同时携带 `.done` 与 `.failed`(歧义终态,
violation);canonical 单元判 pending 但其 marker 文件已存在(判定不一致 = 枚举脚本与磁盘
真相漂移的确定性信号,violation);孤儿 marker(advisory note,非 violation)。**孤儿审计与
判定一致性审计 SHALL 覆盖 scout/t1/t3 三个 checkpoint 目录**(此前 t3 不在审计面内)。
理由〔口径披露是给「人比对文件数与 stdout 数字」的场景;判定不一致从「静默口径差」升级为
「--check 可检 violation」后,身份漂移类缺陷(mgh-init 实测:超长 id 簇 done 判定漂移致
无限重派)在边界即 fail-loud,不再依赖 fan-out 运行时暴露;id 集合一是同一教训的收口——
「枚举说完成、状态机说未完」的分片簇死锁与「状态机说完成、磁盘说有失败」的吞失同属口径
分裂缺陷类〕。

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

#### Scenario: 合法分片 marker 不再误报孤儿

- **WHEN** 某超预算簇已物化为 2 个 `::shard-<n>` 单元且 marker 在盘,运行 `--check`
- **THEN** 该分片 marker 对应复算 id 集中的 canonical id,不出现在孤儿 advisory(修复前
  退化 id 集把全部合法分片 marker 误报为孤儿)

#### Scenario: t3 孤儿 marker 不抬高 done

- **WHEN** `checkpoints/t3/` 存在一个文件名不对应任何 inventory category × format 单元 id 的
  `.json.done` marker,`resume_state.py` 查询该 run
- **THEN** `tiers.t3.done` 不计该 marker;`--check` notes[] 以孤儿披露(t3 审计面与 scout/t1
  对齐)
### Requirement: T1 终态闸门按单元口径收敛(分片簇不死锁)

step 派生的 t1 闸门 SHALL 以「全部 canonical 单元(整簇 + 真超预算簇的 `::shard-<n>` 分片)
终态」为完成判据:`tiers.t1` SHALL 为单元口径 `{done, failed, total = canonical 单元数(含
分片)}`,`step` 停留 t1 当且仅当 `done + failed < total`。分片簇的收敛 = 其全部分片单元终态
(整簇 marker 存在 OR 簇被切分时全部分片 marker 终态,均计入)。pack 模式(`--pack-bytes > 0`)
下成员级 marker 仍是唯一真相源,单元口径复算对 pack run 同样成立(pack 级 `.failed` marker 经
孤儿审计豁免披露、不进计数)。

**t1 复算预算与派发侧恒同源(run_config 锁步)**:t1 canonical 单元集复算
(`canonical_unit_ids_for_run`)的单元预算 SHALL 与派发侧同值——`run_config.json` 的
`budgets.max_unit_bytes` 存在且为正整数时,复算 MUST 用该值(经收集器的显式预算参数传入);
缺 run_config 或字段缺失时回退共享默认常量(与枚举器缺省一致)。理由〔派发侧透传 run_config
预算后,若复算仍锚共享默认,自定义预算的 run 会出现「物化按 64KB 切片、复算按 192KB 只见整簇
id」的口径分叉——已终态分片 marker 对复算不可见,step 永卡 t1,即 CR-1 死锁形态复活;两侧
同值是同一 change 内的强制锁步(`list_clusters.py::canonical_unit_ids_for_run` 的 COUPLING
LOCKSTEP 注释所锚契约)〕。

`init_manifest.json` 存在(整条 run 的终态凭证)时,step 派生 SHALL **短路为 done,先于任何
tier 闸门探针**——完成态 run 不因下游计数的历史漂移被拉回执行态重派;tier 计数照实披露,但
不再驱动 step。

#### Scenario: 分片簇全 done → step 越过 t1(回归锚)

- **WHEN** 单簇被物化为 3 个 shard 单元、3 个 `.done` marker 全部在盘、t2 产物尚未生成,
  编排器查询 `resume_state.py`
- **THEN** stdout `step` 推进到 t2,`tiers.t1 = {done:3, failed:0, total:3}`;修复前同一磁盘
  状态实测输出 `{done:0, total:1}` + `step:"t1"`(枚举器报 pending=0 与状态机死锁并存)

#### Scenario: 自定义预算 run 的复算与物化同口径

- **WHEN** `run_config.json` 记录 `budgets.max_unit_bytes: 65536`,某簇按 64KB 预算被物化为
  2 个 shard 单元且两 marker 均终态,查询 `resume_state.py`
- **THEN** t1 复算用 65536 复算分片计划,`tiers.t1 = {total:2(该簇), …}` 且两分片计入终态,
  step 越过 t1;修复前复算锚共享默认 192KB → 该簇只见整簇 id、无 marker → step 永卡 t1
  (锁步缺失的 CR-1 复活形态);缺 run_config 的 run 回退共享默认,行为不变

#### Scenario: 分片部分完成仍留 t1

- **WHEN** 3 个 shard 仅 2 个终态(2 `.done` + 0 `.failed`)
- **THEN** `step` 停留 t1;重派清单只含未终态分片(经枚举器 `pending[]`,不重派已完分片)

#### Scenario: 分片含失败计入收敛但不吞失

- **WHEN** 3 个 shard 中 2 `.done` + 1 `.failed`
- **THEN** `tiers.t1 = {done:2, failed:1, total:3}`,step 越过 t1(`.failed` 终态承既有语义),
  `notes[]` 披露失败计数(终局需人评)

#### Scenario: manifest 在则 done 短路

- **WHEN** `init_manifest.json` 存在,但某 tier 的磁盘计数呈现「未完」形态(如历史口径漂移
  遗留的分片 marker)
- **THEN** stdout `step = "done"`、`resumable = false`;tier 计数字段照实输出但不驱动 step
### Requirement: done 步收尾纪律可达与完成态哨兵残留违例

step=done 时 `stage_flow_files[]` SHALL 返回 `init-stage/done.md` 的绝对路径——manifest 收尾、
fan-out 失败落账、**收尾移除哨兵 `<init-dir>/.active`** 的纪律经既有「Read stage_flow_files[0]」
壳配方恢复可达(长跑压缩后恢复到收尾态不再失联;not-started 维持空数组,bootstrap 仍由壳
fresh-run recipe fixed-path Read)。survey/resolve 等 step 派生**从不路由**的可选步,其 fragment
头注 SHALL 如实陈述可达性(编排器决定执行该 optional 阶段时按固定路径 Read 本文件),NEVER
声称「经 resume_state per-step 加载」;`assemble.md` 尾部 SHALL 携带「进入 T4 前 Read
`init-stage/t4.md`」的固定路径配方(T4 纪律不依赖 step 派生路由)。

`--check` SHALL 新增完成态哨兵残留违例:`init_manifest.json` 存在(run 已完成)但
`<init-dir>/.active` 仍存在 → 退出码 2 + violations 载移除 recipe(残留哨兵在守卫激活语义下
会把目标项目日常开发会话整体写锁定);进行中 run 缺哨兵的既有违例语义不变。

#### Scenario: 压缩后恢复到收尾态加载 done.md

- **WHEN** 长跑压缩后 resume,全部 stage 完成但 manifest 尚未写(finalize 分支,step=done)
- **THEN** `stage_flow_files[]` 含 done.md 绝对路径;编排器按其完成 manifest 收尾并执行
  `rm <init-dir>/.active`

#### Scenario: 完成态哨兵残留是 --check 违例

- **WHEN** `init_manifest.json` 与 `<init-dir>/.active` 同时存在,运行 `resume_state.py --check`
- **THEN** 退出码 2,violations 含「run 完成但哨兵残留」+ 移除 recipe

#### Scenario: 可选步 fragment 头注不虚假声明

- **WHEN** 审阅 `init-stage/survey.md`/`resolve.md`/`t4.md` 的头注
- **THEN** 头注如实陈述可达性(编排器选择执行时固定路径 Read / 经 assemble.md 尾部配方),
  不出现「Loaded per-step via resume_state.py」类与机制不符的声明

### Requirement: --invalidate-stale 前置判定、删除失败与组合互斥

`--invalidate-stale` SHALL 复用「scout 启用(`run_config.no_scout` falsy)**且** scout 未完成」
作为前置判定(与 `--check` 的 stale-credential 违例同判据):

- 前置不满足(no_scout / scout 已完成)→ SHALL 输出诚实空结果(stdout `removed:[]` /
  `markers:[]`)+ stderr 提示「前置不满足,无过期凭证可清」,删除零文件,退出码 0——
  NEVER 对有效下游凭证执行删除(迫使 T2-T4 全量重跑);
- 真实删除路径中任一 marker unlink 失败 → 退出码 2 fail-loud(stderr 列失败路径 + 可操作
  recipe),SHALL NOT 以 exit 0 静默吞删除失败;
- `--invalidate-stale` 与 `--check`/`--rearm-sentinel` SHALL 互斥:同时传入 → argparse 误用
  退出码 2 + 可操作提示(消除「组合时后到 flag 被静默短路」的歧义语义)。

#### Scenario: no_scout run 上空转不删

- **WHEN** 对 `no_scout=true` 的 run 执行 `--invalidate-stale`(不带 --dry-run)
- **THEN** stdout `removed: []`、退出码 0、下游 t2/t3/t4 marker 零删除,stderr 提示前置不满足

#### Scenario: unlink 失败 fail-loud

- **WHEN** 前置满足且某 stale marker 因文件系统错误 unlink 失败
- **THEN** 退出码 2,stderr 列失败路径;stdout 如实区分已删/未删

#### Scenario: 与 --check 组合是误用

- **WHEN** 同时传 `--invalidate-stale --check`
- **THEN** 退出码 2 + stderr 可操作提示(二者互斥,分开调用),不执行任何删除或校验

### Requirement: sdr 运行域的状态重派生(resume_sdr_state.py)

新增确定性叶脚本 `core/scripts/resume_sdr_state.py`(Python ≥3.10 标准库、零运行时依赖、自定位、
任意 cwd 可 `py`)SHALL 为 `/mgh-sdr` 恢复面「我现在在哪一步 / 下一步调什么」的唯一出口。
其 `step` 与 `next_action` SHALL 纯从 `<run-dir>/` 磁盘产物重派生——`context.json` / `grouping.json` /
单元 marker(`<run-dir>/markers/<unit_id>.done|.failed`)/ `sdr_manifest.json`——SHALL NOT 读对话记忆,
SHALL NOT 读取 `<run-dir>/run_config.json`(该文件只承载 codegraph 信号,不含起始态;见
`security-design-review`)。起始态一律来自 `context.json` / `grouping.json`。

init 域既有脚本 `core/scripts/resume_state.py` SHALL 保持**零改动**(其 blast radius 隔离);sdr 域以
**姊妹脚本**形态落地,与既有 ut-init 域 `resume_ut_init_state.py` 同范式。

sdr 的 run 目录有两种产生路径(launcher 的 `<repo>/.mgh-sdr/runs/<ts>-<branch>/` 与命令壳的
`--run-dir`),该脚本 SHALL 对两者一视同仁——**只吃一个 run 目录**,不对目录命名做任何假设。

CLI 契约(`--help` 即契约面):
`py resume_sdr_state.py --run-dir <abs> [--repo <abs>] [--check] [--rearm-sentinel] [--arm-sentinel]`

- `--run-dir` 为**必填**(sdr 无唯一缺省 run 目录,`runs/<ts>` 每次不同);缺该 flag → argparse 退出码 2。
- `--run-dir` 指向不存在的目录 → 退出码 1(路径错/误用,stderr 给可操作 recipe)。
- `--check` 自洽校验失败 → 退出码 2;`--rearm-sentinel` 成功 → 退出码 0;其余 → 退出码 0。
- `--repo` 可省:按 `<run-dir>` 路径布局(`<repo>/.mgh-sdr/runs/<…>`)推导;推不出时相关字段降级并在
  `notes[]` 披露(见「起始态不可重派生时的显式退化披露」)。
- `--arm-sentinel`(step 0 预武装,与 `--rearm-sentinel` 互斥):**写**最小哨兵
  `<repo>/.mgh-sdr/.active`(`target` 取 `--repo`,缺失且布局推不出 → 退出码 2 + recipe),
  幂等与 target 冲突语义按 `runtime-hook-enforcement` 的 sdr 哨兵要求执行;成功 → 退出码 0,
  stdout 单对象 JSON 含 `sentinel_path`(绝对)/`armed`(本次新写为 `true`、已存在同 target 为
  `false`)/`target`。该 flag 是**写侧**动作,SHALL NOT 改变本脚本其余字段的只读派生语义。

stdout SHALL 为单对象 JSON(stdout = 结构化 JSON、stderr = 诊断/进度严格分流),至少含:

| 字段 | 语义 |
|---|---|
| `repo` / `run_dir` | 绝对路径(Windows 原生,Python `Path.resolve()` 产出,NEVER shell 的 MSYS 形态) |
| `base` / `branch` | 从 `context.json`(缺则 `grouping.json`)重派生;两者冲突以 `context.json` 为准并在 `notes[]` 披露 |
| `step` | 闭集枚举,**当前待办步** |
| `resumable` | 布尔;`step == "done"` → `false` |
| `tiers` | `{done, failed, total}`(口径见「计数口径披露与自洽校验」) |
| `next_action` | `{kind: "bash"\|"subagent"\|"done", desc, absolute_paths[]}` |
| `notes[]` | 披露与 advisory(退化、缺口、失败单元、孤儿 marker 等) |
| `discipline_reminders` | 当前步纪律子集 `{gates[], path_recipes[], nevers[]}`(字段恒存在) |
| `stale_fanout[]` | `<run-dir>/fanout_runner.*.pid` 残留扫描 `{tier, pid_file, pid, pid_alive, note}`(字段恒存在) |

`tiers` 的 `done`/`failed` SHALL 为「canonical 单元 id 的正向 marker 路径存在性」判定(与 `diff_group.py`
的枚举口径**同源**),SHALL NOT 由 glob 文件数或文件名 stem 反推(身份漂移类缺陷的确定性防线)。

`step == "not-started"` 时 `next_action` SHALL 同时携带 step 0 预武装的确切命令
(`resume_sdr_state.py --run-dir <abs> --repo <abs> --arm-sentinel`)作为该步 recipe 的前置行,使恢复
路径与首发路径给出同一条上膛指令。

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

#### Scenario: arm-sentinel 写最小哨兵且回报绝对路径

- **WHEN** 对尚未起步的 run 目录执行 `resume_sdr_state.py --run-dir <abs> --repo <abs> --arm-sentinel`
- **THEN** `<repo>/.mgh-sdr/.active` 存在(`read_roots:[]`),stdout `armed=true`、`sentinel_path` 为
  Windows 原生绝对路径;再次执行同命令 → `armed=false` 且哨兵文件逐字不变

#### Scenario: not-started 的 next_action 携带上膛配方

- **WHEN** `context.json` 不存在的 run 目录被查询
- **THEN** `step="not-started"`,`next_action` 的确切命令文本含 `--arm-sentinel` 前置行,恢复的编排器
  无需翻壳即可知道先武装再跑 step 1
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

### Requirement: get_discipline 返回防御性深拷贝(共享纪律表不可被消费方污染)

`core/scripts/discipline_core.py` 的 `get_discipline(step, domain)` SHALL 返回纪律子集的**深拷贝**
(`{gates[], path_recipes[], nevers[]}` 全层复制),SHALL NOT 返回模块级共享表的内部引用(含
`dict(_EMPTY)` 浅拷贝形态——嵌套列表仍是共享引用)。消费方(`resume_state.py` 的
`discipline_reminders`、`list_steps.py` 的 `discipline`)对返回值做任何 append/修改 SHALL NOT
影响后续任何调用、任何域的输出——一次消费方污染(如对 `gates` append 一项)在修复前会**永久**
变更跨域共享表,污染此后所有 run 的 stdout 纪律面。两脚本同 step 输出逐字一致的单源不变量不受
影响(深拷贝保持值相等);调用频次(每 resume/list_steps 调用一次)下的拷贝成本可忽略。

#### Scenario: 消费方修改返回值不污染共享表

- **WHEN** 调用 `get_discipline("t1")` 得到子集,对其 `gates` 执行 `append(...)` 后再次调用
  `get_discipline("t1")`(以及 `get_discipline("t1", domain="sdr")` 等其它域/步)
- **THEN** 后续调用返回的子集与首次调用值相等(共享表未被污染);模块级表常量逐字不变

#### Scenario: 双脚本输出一致性不受深拷贝影响

- **WHEN** 对同一磁盘状态分别调用 `resume_state.py` 与 `list_steps.py --step t1`
- **THEN** `discipline_reminders[]` 与 `discipline` 仍逐字一致(既有单源不变量保持)
