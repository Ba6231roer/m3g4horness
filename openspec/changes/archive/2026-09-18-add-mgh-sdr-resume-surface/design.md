## Context

动机见 `proposal.md`。设计只需知道五条现状(全部经实读核实):

1. **init 域已有完整恢复面**:`core/scripts/resume_state.py`(976 行)从 `<target>/.mgh-init/` 产物
   + `.done`/`.failed` + `run_config.json` 重派生 `step`/`next_action`/`tiers`,并携带当前步的
   `discipline_reminders[]`(纪律表在 `core/scripts/discipline_core.py`);`list_steps.py --step`
   输出同一步的同一纪律。ut-init 域**已用姊妹脚本落地**(`resume_ut_init_state.py`),其 docstring
   自陈「Copied from init's `resume_state.py` and adapted to the ut step graph …; init's
   `resume_state.py` is ZERO-changed (its blast radius stays isolated)」。**sdr 域什么都没有**。

2. **sdr 运行目录的磁盘真相足够重派生步骤**,不需要任何新文件:
   `context.json`(`sdr_context.py` 写,含 `repo`/`base`/`branch`/`baseline_path`/`external_repos[]`)、
   `grouping.json`(`diff_group.py` 写,含 `repo`/`base`/`branch`/`empty`/`total`/`units[]`/`excluded`/
   `pending[]`)、`markers/<unit_id>.done|.failed`、`drafts/<unit_id>.json`、`sdr_manifest.json`
   (`render_sdr_report.py` 写,终态凭证)。

3. **共享谓词范式在本仓已存在**:`core/scripts/init_tier.py` 承载 `forward_marker_paths`/
   `forward_done_ids`/`forward_failed_ids`,被 `resume_state.py`、`list_clusters.py`、
   `list_scout_batches.py` **共享导入**(不各自复制),正是为了关掉「枚举说 pending、磁盘有 marker」
   的无限重派缺陷类。sdr 侧缺同一层:`diff_group.py:1514-1531` 用裸拼接
   `f"{u.unit_id}.done"` 写 marker,读取侧目前不存在。

4. **`run_config.json` 的双重身份里,只有一半是死的**(本条经实读修订过一次,修订原因见 D2 的
   「与并存 change 的冲突」):文件里被命令壳写进去的字段只有 `no_codegraph` 一个,而它**现在有
   消费者**——`fanout_runner.py::_codegraph_signal()` 对全部 tier 读 `<plan-dir>/run_config.json`
   的该字段(sdr 的 plan 锚点 = `<run-dir>/grouping.json`,父目录即运行目录)。**没有**消费者的是
   本 change 原以为它承载的另一半:**起始态意图**(repo/base/branch),即「`--resume` 免重输参数」
   的那条用途——sdr 侧既无读取方,也无 `--resume` 入口。故本 change 退场的是**起始态用途**,
   不是文件本身;文件保留为 codegraph 信号载体,写入者从「编排器手执行 `printf`」换成脚本
   (D2/D3)。

5. **两处入口行为不对称**:`mgh_sdr_launch.py:330-332` 每次调用按当前时刻**新建**
   `<repo>/.mgh-sdr/runs/<ts>-<branch>/`,无 `--resume`/`--run-dir`;而命令壳有 `--run-dir`。
   现有 `security-design-review` 规格的「重跑 launcher 同参数即复用 run 目录」场景**与实现对不上**。
   哨兵写入同样不对称:launcher 在进程内确定性写(`_write_sentinel`),壳则要编排器 `Bash printf` 手执行。

## Goals / Non-Goals

**Goals:**

- sdr 恢复面与 init/ut-init **同形**:磁盘重派生 `step`/`next_action`,per-step 纪律随恢复重新注入,
  使压缩 / 崩溃 / 新会话坍缩成同一条路径(读磁盘 → 继续)。
- 让「守卫该开着的窗口」有确定性判据:哨兵写入脚本化、缺失 fail-loud、可确定性重写。
- 清掉 sdr 侧的不可执行指引与不可靠写入(壳里指向 init 域脚本的恢复命令、编排器手执行的
  `printf` 配方——含哨兵与 `run_config.json` 两处)。

**Non-Goals**(设计层边界,不重复 `proposal.md` 的范围声明):

- 不合并三份 resume 脚本进一个通用引擎(见 D1 否定案)。
- 不改 `mgh_sdr_launch.py` 的 run 目录复用(launcher 无 `--resume`,缺口如实披露,见 D2/D4)。
- 不下发 `--dimensions` 收窄与 codegraph 信号到 subagent task(现状是真断线,本 change 只如实披露,见 D8)。
- 不改分组算法、报告结构、派发器机制、外部仓授权闸门。

## Decisions

### D1 — 姊妹脚本,不扩 `resume_state.py`

新增 `core/scripts/resume_sdr_state.py` + `core/scripts/list_sdr_steps.py`,与 ut-init 同范式。
`resume_state.py` **零改动**。

| 替代案 | 否定理由 |
|---|---|
| 给 `resume_state.py` 加 `--domain {init,sdr}` 开关 | 两个步骤图、两套 tier 语义挤进同一个 976 行文件;它 import `init_tier`/`list_clusters`,sdr 与这些零关系;init 的每次改动都要背上 sdr 回归面——**扩的正是最承重脚本的 blast radius** |
| 抽通用引擎 + 三份 domain config | 要重写一个已上线且承重的脚本;收益只是省一份 ~300 行样板,代价是三条命令的恢复面同时暴露在新抽象下 |
| 整份复制 `resume_state.py`(含 scout/t1/t2/t3 语义) | sdr 步骤图用不上那些分支;副本越大越容易被后来者误以为「两边要同步」 |

### D2 — 起始态退场、信号载体保留;写入者从编排器换成脚本

**决定性判据(起始态用途)**:唯一「磁盘上没有起始态可派生」的步是 `not-started`(`context.json`
尚未写出),而它**恰是唯一没有已完成工作的步**——重新给参(`--base`/`--branch`)重跑即完整恢复,
没有任何东西可丢。于是「起始态意图文件」的收益为零,而它带来的成本是实打实的(一个只被 resume
读、且只在那一刻被读的文件;外加壳里一段手执行的写配方)。故**起始态**这一半退场。

**与并存 change 的冲突(本节经修订过一次,勿回退)**:本 change 初稿断言该文件「无人读」并主张
整份退场,该断言建立在 `fanout_runner.py::_codegraph_signal()` 对 `tier_key == "sdr"` 早返回
`"off"` 的旧代码上。并存 change `fix-mgh-sdr-fanout-callface-contract` 已删除该早返回(其代码先于
本 change 落入工作区),使 `no_codegraph` 成为**有消费者**的字段,并在其规格里写死「信号载体唯一:
sdr 的 codegraph 信号 SHALL 只经 `run_config.json` 承载」「该占位符 SHALL NOT 对 sdr tier 恒为
`off`」。两份 change 因此对同一文件断言相反。**裁决(维护者拍板)**:保留文件,把写入者换成脚本。

于是本 change 真正治的缺陷——「编排器读懂并手执行一段 `printf` 配方」——被消除,而并存 change 的
契约(载体唯一、占位符不恒 off)原样保住,`fanout_runner` 零改动。

| 替代案 | 否定理由 |
|---|---|
| 整份退场(初稿方案) | 直接回滚并存 change 的核心成果:sdr 的 `{{codegraph}}` 占位符回到恒 `off`,违反其规格「SHALL NOT 恒为 off」 |
| 载体迁到 `grouping.json::codegraph`(由 `diff_group` 自己写出) | 语义上更强(事实与产出它的那一步同源),但要改 `fanout_runner._codegraph_signal()`(并存 change 刚重写的函数)、给 `diff_group` 补一个它目前没有的 `--no-codegraph` flag、并修订并存 change 的规格——越界到另一份 change |
| 保留为「起始态意图」(补确定性写 + resume 面读) | 收益为零(见上判据);resume 侧改从 `context.json`/`grouping.json` 重派生即可,不需要第四个真相 |

**载荷收敛**:文件内**只**承载 codegraph 信号(`{"no_codegraph": <bool>}`);起始态字段
(repo/base/branch/维度)SHALL NOT 写入该文件。resume 侧**不读**该文件(其派生只依赖
`context.json`/`grouping.json`/marker/`sdr_manifest.json`)。

**兼容**:历史 run 目录里的遗留 `run_config.json` 若含起始态字段,被**忽略**——不读、不影响派生;
不做删除动作。写入为原子 + 幂等(同一磁盘态 → 逐字相同内容)。

### D3 — 哨兵写入脚本化(`sdr_context.py` co-write),launcher 保留幂等刷新

init 域早已在这条上吃过教训:`write_runconfig.py` 把哨兵变成**脚本副作用**(「脚本一跑哨兵必在」,
不依赖编排器读懂并执行 `printf` 配方)。sdr 侧的自然落点是 `sdr_context.py`——它是 **launcher 与命令壳
两条入口都必经的第一步**,且它自己就知道**实际检索过哪些根**,而那正是 `read_roots[]` 该放的集合
(最小化原则,不新增信息流)。

- `sdr_context.py` 完成检索后 co-write **两样**:`<repo>/.mgh-sdr/.active`(`target` = 其 stdout 的
  Windows 原生 `repo`;`read_roots[]` = `external_repos[].path` 中存在且为目录者),以及
  `<run-dir>/run_config.json`(`{"no_codegraph": <bool>}`,取自其新增的 `--no-codegraph` flag)。
  两处均为原子写、幂等,失败 fail-loud 不静默。**同一个副作用位置写两样文件**,是因为两者的写入
  时机、内容来源与失败语义完全一致——都由「这一步实际发生了什么」决定。
- `mgh_sdr_launch.py` 的 `_write_sentinel` **保留为幂等刷新**:它在 spawn 宿主 CLI 之前对已确认根
  再做一次项目配置复核(版本错配的第二道闸门)并并入操作者 `--read-root`。同语义、同内容来源,
  不是第二个真相。launcher 经 `_run_context` 调用 `sdr_context.py` 时透传 `--no-codegraph`。
- 命令壳 step 0 的哨兵 `printf` 配方、step 1 的「有 external_repos → 重写哨兵」步骤、以及
  step 2 的 `run_config.json` `printf` 配方**全部删除**(改由 `sdr_context.py` 写出;壳只传
  `--no-codegraph`,壳同时瘦身,R5.6 token 预算受益)。

| 替代案 | 否定理由 |
|---|---|
| 只让 launcher 写 | 壳入口(非 launcher 路径)仍靠编排器手执行 `printf`,正是要治的形态 |
| 维持壳 `printf` | 手执行配方 = 编排器读错/漏执行即守卫休眠,且哨兵内容与 `sdr_context` 的实际检索面可能漂移 |

### D4 — step 闭集、终止凭证与「step = 当前待办步」

闭集 `not-started|group|fanout|render|done`,对应 4 件工作 ↔ 4 个产出物:

| `step` | 判据(磁盘) | 下一步 |
|---|---|---|
| `not-started` | `context.json` 不存在 | `sdr_context.py`(同时完成哨兵 co-write) |
| `group` | `context.json` 在、`grouping.json` 缺 | `diff_group.py` |
| `fanout` | `grouping.json` 在、单元未全终态 | `fanout_runner.py --tier sdr` |
| `render` | 单元全终态、`sdr_manifest.json` 缺 | `render_sdr_report.py` |
| `done` | `sdr_manifest.json` 在 | 无 |

- **命名取「当前待办步」**,与 init 域 `t1`/`t2` 一致(`t1` 意思是「该跑 T1 了」,不是「T0 跑完了」)。
  替代案「已完成步」会让恢复时容易 off-by-one。
- **不设 `context` 独立 id**:它与 `not-started` 的磁盘判据完全相同,是两个名字一件事。
- **终止凭证 = `sdr_manifest.json`**(对位 init 的 `init_manifest.json`)。`render_sdr_report.py`
  先写报告再写 manifest,故 manifest 存在 ⟹ 报告已产出。
- **单元终态只看 marker**,不采信 `grouping.json::units[].status`——该字段在**枚举时点**算出,
  fan-out 之后即陈旧,采信它会把已完成的 run 判成未完成。
- **零 diff / 全排除**:`empty == true` 或 `total == 0 && excluded.count > 0` ⇒ `0 ≥ 0` 视为
  fan-out 完成,直接进 `render`,不空转。

### D5 — marker 谓词单一真相(新共享模块,同 `init_tier.py` 范式)

新增共享模块承载「单元 marker 的正向路径计算」与「canonical 单元 id 集上的 done/failed 集合计算」,
由**写入侧 `diff_group.py`** 与**读取侧 `resume_sdr_state.py`** 共享导入。

理由:今天的写入是裸拼接 `f"{u.unit_id}.done"`(`diff_group.py:1515-1519`)。读取侧若各自复制这条拼接,
就重现 init 域**实测过**的缺陷类——枚举判 pending、磁盘却有 marker,于是同一个单元被无限重派。
共享一个函数是这条缺陷类的结构性关闭;复制一行代码看起来便宜,保护为零。

替代案:读取侧复制拼接。否定理由:单行代码的诱惑 vs 已经付过学费的失效形态。

> 残余(本 change 不修,如实记录):marker 文件名由 `unit_id` 裸拼接,无字符净化;若未来引入净化,
> 写入侧与读取侧必须同时改——共享模块正是为了让这件事只发生在一个地方。

### D6 — 纪律表按域分表,不新开平行文件

`discipline_core.get_discipline(step, domain="init")`:默认域保持既有两处调用**零改动**;新增
`domain="sdr"` 表,key 与 sdr step 闭集一致。

sdr 各步纪律内容来自命令壳的承重防线(同一步、两处 MUST 同构):每步 `--check`(退出码 2)、
fan-out 路径配方(`diff_group` stdout `pending[].input_path|draft_path|done_marker|failed_marker`
绝对逐字透传)、四级超时不变式、快败冷却形态与 `--retry-failed` 配方、`run.log` 证据路径、
该步适用的 `NEVER` 硬边界。

| 替代案 | 否定理由 |
|---|---|
| 新开 `discipline_sdr_core.py` | 两份文件必须保持结构一致的子集契约;且「sdr 与 init 的承重防线相邻可见」这个好处消失——本仓对 `discipline_core` 的价值定位恰恰是「单一真相、便于发现漂移」 |
| 把 sdr 的 key 直接平铺进现有 dict | 两域共用同一命名空间,未来任一侧改名会**静默碰撞**(`done` 是两边都有的 key) |
| 不给 sdr 纪律(只做步骤重派生) | 恢复只回答了「在哪步」,没回答「这步怎么走」——正是 R5.4 disk-truth 要补齐的那一半 |

### D7 — 哨兵存在性校验的适用步:与「守卫该开着的窗口」重合

`--check` 只在 `step ∈ {group, fanout, render}`(已有工作产物)时把「哨兵缺失」判为违例(退出码 2 + re-arm recipe);
`not-started` 仅 advisory(哨兵按设计还没被 `sdr_context` 写出);`done` 不违例(run 已收尾,守卫本就应休眠——与 init 域同款判断)。

理由:gate 的判据必须与守卫真正该生效的窗口重合。把正常状态判成违例会制造噪声,噪声会被忽略,
被忽略的 gate 等于没有 gate。

### D8 — `--dimensions` 断线:如实披露,不在本 change 修

**核实事实**:`sdr_context.py` 校验 `--dimensions` 闭集后不再向下传递;任务模板 `sdr-task.md` 第 85 行
写着「The orchestrator's `--dimensions` narrowing rides this message's **检查面** line」,但该模板里
**没有** `检查面` 这一行,`dimensions` 既不在 `diff_group` 的 `pending[]` 字段里,也不在 sdr tier 的
`placeholders` 里。即:**该收窄开关今天只做闭集校验,不影响任何一次评审**。

处置:本 change 只在 `security-design-review` 的诚实边界与本节记录该事实,不下发。下发会改变评审行为面
(检查面真的收窄),且要同时动 `pending[]` 契约、tier `placeholders`、任务模板三处,应独立成 change。

## Risks / Trade-offs

- **起始态在 `not-started` 不可重派生** → 显式披露 + `next_action` 载重新给参的可执行调用(含默认值提示);
  该步零已完成工作,重跑即完整恢复,**不构成恢复面缺口**(D2 的判据即建立在此)。
  残余:`--branch` 的默认值是「当前分支」,若中断期间用户切了分支,默认值会与实际 run 的分支不符——
  脚本 SHALL NOT 用 git 猜,只给提示(冒用他人分支做 diff 的代价高于多打一个参数)。
- **`sdr_context.py` 新增写副作用(哨兵)** → 写失败 SHALL fail-loud(不静默),launcher 的幂等刷新是兜底;
  该副作用与此前的「壳 printf」是同一份内容、同一处落点,只是把执行者从模型换成脚本。
- **壳删除 `printf` 后,`MGH_SDR_ACTIVE=1` 之前的那一小段窗口守卫不激活** → 该窗口内没有任何受保护的
  工作产物(运行域标记正是 `sdr_context` 自己要写的);如实披露,不做补偿。
- **`resume_sdr_state.py` 与 `diff_group.py` 的单元判定漂移** → D5 的共享谓词 + 单测(构造
  「marker 在、`status` 陈旧」等中间态断言两侧口径一致)。
- **旧 run 目录兼容** → 遗留 `run_config.json` 里若含起始态字段,被忽略(不读、不影响派生);
  无 schema 变更,旧目录仍可被新脚本查询。
- **launcher 的 run 目录复用缺口** → 本 change 在 `security-design-review` 里把既有场景改写为
  「重跑 launcher 会新建目录」的**可断言事实**并披露。这是刻意的:让规格停止断言一个实现不成立的行为,
  比留着一个永远测不过的承诺好。
- **给旧 run 重写哨兵时,`read_roots[]` 的来源只有 `context.json`** → 该集合正是「实际检索过的根 +
  操作者显式确认的根」,与当时的哨兵内容同源;不存在的路径被剔除(fail-closed 方向,不会放宽授权)。

## Migration Plan

无数据迁移。改动是**行为等价替换 + 死契约退场**:

1. 新增 `resume_sdr_state.py` / `list_sdr_steps.py` / 共享 marker 谓词模块;`discipline_core` 加域参数
   (默认域不变)。
2. `diff_group.py` 改为导入共享谓词(写入侧行为不变,marker 路径逐字相同)。
3. `sdr_context.py` 加哨兵 + `run_config.json` 的 co-write 副作用与 `--no-codegraph` flag;
   `mgh_sdr_launch.py` 保留哨兵幂等刷新并透传 `--no-codegraph`(内容来源不变)。
4. 双壳:删三处 `printf` 配方(哨兵两处 + `run_config.json` 一处),改传 `--no-codegraph`;
   恢复段改指 `resume_sdr_state.py`。
5. 契约 lint / 安装自检 / 零依赖扫描 / 分发纯净性 lint 同步登记新脚本;版本号 bump。

**回滚**:还原脚本与壳文本即可。已产出的 run 目录不含任何新 schema,旧流程仍可消费;
回滚后壳重新手写 `run_config.json` 与哨兵(即回到本次优化前的形态),两条路径都仍被消费方接受。

## Open Questions

- **ut-init 域是否也补 `discipline_reminders`**:`resume_ut_init_state.py` 目前无纪律字段,ut-init 的
  `list_ut_steps.py` 也无 `discipline`。本 change 不动它(范围外),但 `discipline_core` 加了域参数后,
  补 ut-init 只是一个域表的增量。
- **launcher 侧 run 目录复用的形态**:`--resume --run-dir <abs>` 与「按 branch 自动取最近一次 run 目录」
  是两种语义(前者精确、后者方便但可能认错 run)。留待专门 change,本 change 只披露缺口。
- **`--dimensions` 收窄的下发路径**:需要同时决定「谁把收窄后的维度写进 `pending[]`」与「收窄后报告如何披露
  未覆盖的维度」。本 change 只记录断线事实。
