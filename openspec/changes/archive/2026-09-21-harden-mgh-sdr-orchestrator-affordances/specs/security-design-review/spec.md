## ADDED Requirements

### Requirement: 外部仓审批单命令闭环与未知参数报错出口

`sdr_context.py` SHALL 新增 `--approve-external <abs>`(可重复):在检索开始前,对每个传入路径执行
与 `read_roots_config.py --add` **同源**的校验与原子写(存在且为目录,违者退出码 2 + 可操作 stderr,
幂等:已配置条目为 no-op),登记成功后该仓**当次运行即被检索**并随既有 co-write 进入哨兵
`read_roots[]`。审批语义不破:该 flag SHALL 仅由编排器在宿主会话获用户明示同意后传入,脚本与编排器
SHALL NOT 自行批准;`read_roots_config.py --add` + 重跑的既有路径保持逐字可用(两条入口同 schema、
同原子写逻辑,NEVER 各维护一份写实现)。

`sdr_context.py` SHALL 对未识别参数做审批语义的模糊识别:当未知 flag 名(去 `--`、小写、分词后)
命中 `approve` / `read` / `external` 任一词根时,stderr SHALL 在 argparse 原生报错之后追加一段
可照抄执行的配方——经 `read_roots_config.py --target <repo> --add <abs>` 批准(或同脚本
`--approve-external` 形态重跑本命令)——配方中的脚本绝对路径与 `<repo>` 由脚本自身拼接产出;
未命中词根的未知 flag 维持 argparse 原报错(退出码 2 不变)。

#### Scenario: 同意后单命令完成审批与检索

- **WHEN** 首轮运行报出 `pending_approval:["D:/xxx/front"]`,用户同意,编排器按壳配方重跑
  `sdr_context.py --repo <abs> --run-dir <abs> --approve-external D:/xxx/front`
- **THEN** `D:/xxx/front` 写入 `<repo>/.mgh/read-roots.json`(与 `read_roots_config.py --add` 产物
  逐字段同形),当次 stdout `external_repos[]` 含该仓记录、`pending_approval` 为空,哨兵
  `read_roots[]` 含该根

#### Scenario: 非法审批目标 fail-loud

- **WHEN** `--approve-external D:/gone`(不存在或不是目录)
- **THEN** 退出码 2,配置零写入,stderr 指明条目无效(与 `read_roots_config.py --add` 同判据)

#### Scenario: 发明的审批参数得到出口配方

- **WHEN** 编排器对 `sdr_context.py` 传入其未声明的 `--approve-external-repos`(或任何命中
  `approve`/`read`/`external` 词根的未知 flag;实现侧对「已声明的 `--approve-external`」不误伤)
- **THEN** 退出码 2,stderr 除 argparse 原生报错外追加可照抄的批准+重跑配方(含脚本绝对路径与
  `--target <repo>`),编排器无需再探索即可走对路径

#### Scenario: 已配置仓重复批准为 no-op

- **WHEN** 对已写入配置的仓再次传 `--approve-external <同一路径>`
- **THEN** 配置不变(`added:[]` 语义),当次照常检索该仓,退出码 0

### Requirement: 产出者 stdout 摘要视图与审批滞留提醒

`sdr_context.py` 与 `diff_group.py` SHALL 各支持 `--summary`:与完整调用同参数运行(含幂等重跑的
副作用语义不变),但 stdout 只输出**定长的关键量视图——不改动任何已落盘产物**:

- `sdr_context.py --summary` 的 stdout SHALL 含 `repo`/`run_dir`/`base`/`branch`/`baseline_path`/
  `baseline_bytes`/`baseline_truncated`/`sensitive_catalog_source`/`external_repos[]`(每项仅
  `path`/`slug`/`summary_path`/`diff_files`/`bytes`/`truncated`,**不含** `route_hits[]` 明细)/
  `external_skipped[]`/`pending_approval[]`;完整记录仍在 `<run-dir>/context.json`。
- `diff_group.py --summary` 的 stdout SHALL 含单元计数与分布(`pending_total`/`done`/`failed`、
  interface/standalone/partN 计数)、`excluded{count}` 与 `empty` 谓词,以及分页字段
  (`effective_limit`/`offset`);`pending[]` 各项的路径字段在摘要形态下 SHALL 以
  `slices_dir` + 单元相对后缀给出**或**保持绝对逐字(二选一在契约文档落定,选后不得漂移);
  完整 `pending[]` 仍在非摘要调用与 `grouping.json`。

`--summary` 缺省时两脚本 stdout SHALL 与现状逐字一致(纯附加,零回归面)。

`sdr_context.py --check <run-dir>` SHALL 在产物自洽之外追加 advisory:读 `<run-dir>/context.json`,
`pending_approval[]` 非空 → stderr 打印「外部仓声明未批、零读取降级」并列出条目(不改退出码——
未批是合法降级态,不是破损态)。

#### Scenario: 摘要视图免文件中介

- **WHEN** 编排器跑 step 1 只想知道「基线多大、外部仓检索了几何、有无待批」
- **THEN** `sdr_context.py --summary`(同参)的 stdout 为上述关键量,单屏可读;编排器 NEVER 需要
  `| tail`、重定向到文件、或 `describe_artifact.py` 之外再内联解析

#### Scenario: 非摘要调用逐字不变

- **WHEN** 同一参数下分别以缺省形态与 `--summary` 形态运行,再比对缺省形态与改动前基线
- **THEN** 缺省形态 stdout 与基线逐字一致;`--summary` 不落任何新文件、不改动 `context.json`

#### Scenario: check 对未批外部仓出声

- **WHEN** 某 run 的 `context.json` 含 `pending_approval:["D:/xxx/front"]`,编排器跑
  `sdr_context.py --check <run-dir>`
- **THEN** 退出码仍为 0(产物完好),stderr 出现含该路径的未批提醒行;若 `pending_approval` 为空则
  无该行

### Requirement: sdr 命令壳暴露产物内省与 stdout 直消费配方

`/mgh-sdr` 双端命令壳 SHALL 在步骤级配方中就近暴露以下合法出口(先于任何拦截发生):

- step 1 与 step 2 段各含一条「需检查产物结构/字段 →
  `py <mgh-core>/scripts/describe_artifact.py --in <abs-json> --keys|--field a.b.c|--shape|--sample N`」
  配方(确切脚本名与 flag 形态逐字镜像其 `--help` 契约);
- step 1/2 各含一句「stdout = 单个 JSON 对象、stderr = 进度与提醒;正常路径从 Bash 工具返回值直接
  消费,NEVER 重定向到文件再回读;输出过大时用 `--summary`(step 1/2 均支持),需 narrowing 用
  `describe_artifact.py --field`」;
- 硬边界 (b) 的措辞 SHALL 覆盖解释器内联代码的**全部**喂入形态:`-c`、解释器后跟独占 `-`(heredoc
  经 stdin)、here-string(如 `- <<<`),而非仅 `-c`;
- 审批闸门的「同意」分支 SHALL 以 `sdr_context.py --approve-external <abs>` 为推荐路径,
  `read_roots_config.py --add` + 重跑保留为等价路径(两条文案都给出,语义一致)。

双壳(宿主路径)在上述各点的措辞 SHALL 同构(宿主差异只留在工具名/路径前缀层)。

#### Scenario: describe_artifact 配方在壳内可见

- **WHEN** 审阅两份 `mgh-sdr.md` 的 step 1 与 step 2 段
- **THEN** 每份都含 `describe_artifact.py` 的确切调用形态(与守卫 recipe 的推荐一致),且含
  「stdout 直消费 + `--summary`」声明;编排器在**首次**需要内省前即知道合法出口

#### Scenario: 双壳措辞同构

- **WHEN** 比对 claude 壳与 opencode 壳的新增配方段
- **THEN** 除路径前缀(`.claude/mgh-core` vs `.opencode/mgh-core`)外逐句一致

## MODIFIED Requirements

### Requirement: sdr 运行域守卫激活与幂等 resume

`/mgh-sdr` SHALL 为第 6 个运行域:env `MGH_SDR_ACTIVE=1` 或磁盘哨兵 `<repo>/.mgh-sdr/.active`
(向上 walk 发现,承既有激活契约)激活守卫;哨兵 `read_roots[]` 声明的外部只读根按 `runtime-hook-enforcement`
的 read_roots 扩展要求生效。

哨兵的写入 SHALL 为**确定性脚本副作用**且分**两级时序**:

- **step 0 预武装**:编排器在**首次调用 `sdr_context.py` 之前**执行
  `py <mgh-core>/scripts/resume_sdr_state.py --run-dir <abs-run-dir> --repo <abs> --arm-sentinel`,
  确定性写最小哨兵(`domain:"mgh-sdr"`、`target`= `--repo` 的 Windows 原生绝对路径、
  `out_roots:[]`、`read_roots:[]`)。目的:闭合「step 1 在参数解析/前置校验阶段即失败 → 哨兵未写 →
  守卫整个试错期休眠」的窗口。`--arm-sentinel` SHALL 幂等(同 target 重复执行为 no-op;不覆盖已存在
  哨兵的 `read_roots[]`)。SHALL NOT 以 `Bash printf` 手执行配方实现。
- **step 1 细化覆盖**:`sdr_context.py` 完成基线投影与外部检索后的 co-write 语义不变(把哨兵刷新为
  含实际检索根 `read_roots[]` 的完整版);launcher 路径的 spawn 前写入亦不变。

流程 SHALL 幂等可恢复,分**产物层**与**入口层**两件事:

- **产物层**(既有语义不变):`diff_group.py --materialize` 对已存在 `.done` marker 的单元跳过物化重复工作;
  `fanout_runner.py --resume` 按磁盘 marker 重派 pending;`render_sdr_report.py` 对 draft 齐备的 run 目录
  可重复执行(重跑覆盖同名报告)。
- **入口层**(既有语义):`resume_sdr_state.py`(见 `resume-step-discipline`)SHALL 从 `<run-dir>/`
  磁盘产物重派生 `step` / `next_action` / `discipline_reminders[]`,使压缩 / 崩溃 / 新会话三态坍缩为同一条
  恢复路径(**读磁盘 → 继续**)。恢复 SHALL 复用**既有 run 目录**(同一 `<run-dir>`),SHALL NOT 另起一个新的
  时间戳 run 目录——新建目录 = 已完成单元的 marker 不在新目录里 = 全部重做(零复用即全损)。

编排器每步完成后 SHALL 跑对应产出者 `--check`,失败(退出码 2)回退重跑,不带着破损产物继续。
step 1 **之前**的失败(含 argparse 退出码 2)SHALL 由编排器按命令壳收尾段的「干净停止」路径移除预武装
哨兵(`rm <repo>/.mgh-sdr/.active`),NEVER 留残哨进入日常开发;残留(宿主硬杀)由下次 launcher 启动时
检测并复用/清理的既有路径兜底。

**恢复指引 MUST 域内可执行**:命令壳给出的恢复、排障与"磁盘状态是否正常"判定指引,SHALL 只引用
在 sdr 运行目录下可实际执行的脚本——即接受 `--run-dir <sdr run dir>`(或等价的 `<run-dir>` 位置参数)
且不依赖其它运行域目录布局的产出者(如 `diff_group.py --check <run-dir>`)。命令壳 SHALL NOT 让
编排器调用以 `<target>/.mgh-init` 为默认状态根、在 sdr 运行目录下必然以"目录不存在"失败的脚本
(如 `resume_state.py`,其运行目录解析为 `--init-dir > <target>/<run-root=默认 .mgh-init>`);此类
跨域引用 SHALL 在 sdr 场景视为坏指引,因为它百分之百失败并使编排器在真实拥塞形态下失去判据。
该约束 SHALL NOT 被读成"指引只能有一个":`resume_sdr_state.py`(入口层状态重派生,域内可执行)与
`diff_group.py --check <run-dir>`(产物层完整性)是**两件不同的事**,SHALL 并存——前者回答"我做到哪一步、
下一步跑什么",后者回答"分组产物有没有坏"。二者语义不同,SHALL NOT 互相替代:产物完好而以产物检查
代替状态查询会丢失"下一步";状态可派生而产物已坏时,状态查询本身不校验产物。

**已披露的入口层缺口(既有披露,本 change 不修)**:`mgh_sdr_launch.py` 每次调用按当前时刻**新建**
`<repo>/.mgh-sdr/runs/<ts>-<branch>/`,且无 `--resume` / `--run-dir` 参数;故「经 launcher 同样参数重跑即续跑」
**目前不成立**(会落到新目录、从头再跑)。续跑入口为:由调用方已知 run 目录时,经命令壳的显式
`--run-dir` + `resume_sdr_state.py --run-dir <abs>` 继续。launcher 侧的 run 目录复用 SHALL 由后续 change 补齐。

#### Scenario: step 1 失败窗口守卫仍武装

- **WHEN** 编排器 step 0 已跑 `--arm-sentinel`,随后对 `sdr_context.py` 传入不存在的 flag argparse
  退出码 2,再接续尝试 `py -c` 内联或 heredoc 形态解析产物
- **THEN** 因 `<repo>/.mgh-sdr/.active` 已在,守卫对后续违规动作照常 fail-loud(退出码 2 + recipe),
  不再存在「试错期整段放行」的窗口

#### Scenario: 预武装哨兵幂等且不被 step 0 重复破坏

- **WHEN** 预武装之后,编排器因压缩/重入再次执行同一 `--arm-sentinel` 命令
- **THEN** 已存在且 `target` 相同的哨兵逐字不变(no-op,`read_roots[]` 即使已被 step 1 细化也 NEVER
  被清空);`target` 不同则退出码 2 + 报错(拒绝把守卫锚到第二个树)

#### Scenario: step 1 成功后的完整哨兵覆盖预武装

- **WHEN** `--arm-sentinel` 预武装(read_roots 空)后 `sdr_context.py` 完整跑成并检索了两个外部根
- **THEN** co-write 把同一哨兵刷新为 `read_roots[]` = 实际检索根;守卫的读允许集随之扩展

#### Scenario: step 1 前干净停止移除预武装哨兵

- **WHEN** step 1 因参数错误终止、用户选择干净停止,编排器走壳的移除步
- **THEN** `<repo>/.mgh-sdr/.active` 被移除,守卫恢复休眠,日常开发零误伤

#### Scenario: 崩溃后 resume 零全损推进

- **WHEN** fan-out 中途宿主中断(部分单元 `.done`、部分 pending),调用方带着**同一个** run 目录路径回来
- **THEN** `resume_sdr_state.py --run-dir <abs>` 报 `step="fanout"` 与确切重派命令;`diff_group.py --materialize`
  复用既有 run 目录(按 resume 语义),dispatcher 仅重派未 `.done` 单元,已完成单元零重复消耗;最终报告覆盖全部单元

#### Scenario: launcher 重跑会新建 run 目录(缺口如实成立)

- **WHEN** 对同一 branch 再次运行 `mgh_sdr_launch.py`(同参数)
- **THEN** 产生一个新的 `<repo>/.mgh-sdr/runs/<ts>-<branch>/` 目录,上一次 run 的 marker 不被复用;
  该行为 SHALL 在命令壳的恢复指引与 `/mgh-sdr` 的诚实边界中披露(不得宣称「重跑 launcher 即续跑」)

#### Scenario: 完成/干净停止后哨兵移除

- **WHEN** 流程跑完(报告渲染完成)或用户干净停止(含 `--dry-run` 早退之外的正常退出路径)
- **THEN** `<repo>/.mgh-sdr/.active` 被移除;残留哨兵的 run(宿主被硬杀)由下次 launcher 启动时
  检测并复用/清理,不静默锁死日常开发

#### Scenario: 壳内恢复指引在真实 sdr 运行目录可执行

- **WHEN** 审阅命令壳的恢复/排障段并按其中逐字给出的命令实跑(工作目录为任意 sdr 运行目录)
- **THEN** 每条被引用的检查命令以退出码 0(状态正常)或 2(状态异常,fail-loud)返回,NEVER 因
  "状态根目录不存在"以退出码 1 失败;命令中出现的脚本参数与 sdr 运行目录的实际布局一致
  (`--check <run-dir>` 形态在册)

#### Scenario: 拥塞形态的产物自检是域内命令

- **WHEN** 编排器遇到 `stalled:true` 需要先判定"磁盘上分组产物有没有坏"再同参重派
- **THEN** 它跑 `diff_group.py --check <run-dir>`(域内可执行,退出码 0/2),NEVER 跑在 sdr 运行目录下
  必然以退出码 1 失败的跨域脚本;该命令的语义边界(校验产物完整性、非运行进度自洽性)SHALL 在该指引
  处就近披露,使编排器不会把它读成完整的恢复面
