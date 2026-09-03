# security-design-review Specification

## Purpose

`/mgh-sdr`(security design review)——需求分支代码变更的存量安全设计符合性复核:以
`git diff <base>..<branch>` 为输入,按接口维度 + 独立变更单元分组 fan-out,对照 mgh-init 产出的
存量安全设计与可配置检查维度(垂直/横向越权、其他权限、SQL 注入、敏感信息屏蔽、输入校验默认开)
逐单元查设计遗漏,确定性汇总渲染一份 md 报告到项目根。覆盖:diff 采集与分组、外部仓受控检索、
fan-out 评审、统一问题记录、报告渲染、launcher 外壳、幂等 resume 与边界校验。

## Requirements

### Requirement: 确定性 diff 采集与接口维度分组

新增确定性叶脚本 `diff_group.py`(Python ≥3.10 标准库、零运行时依赖、自定位、任意 cwd 可 `py`,
承 R5.3a)SHALL 作为 `/mgh-sdr` 的枚举与切分唯一入口:以 `--repo <abs-root>` + `--base <ref>`
(默认 `master`)+ `--branch <ref>`(默认当前分支,经 `git rev-parse --abbrev-ref HEAD` 确定性
解析)运行 `git diff --no-color <base>..<branch>`,取得变更文件清单与 hunk。脚本 SHALL 先提取
**变更符号集**(diff hunk 锚到首个 added 行的宿主方法/接口:注解 + 方法声明 brace 域
确定性本地扫描作单一边界源——codegraph `node --file --symbols-only` 为 markdown 符号
表、无机器 endLine,不作边界源;无法映射的 hunk 归文件级变更),随后按以下
闭集规则分组:

- **调用链分组(codegraph 可用时)**:当 `<repo>/.codegraph/` 存在 ∧ PATH 有 `codegraph` 时,对
  每个变更符号 SHALL 跑 `codegraph callers --json` / `callees --json` 取调用边,在变更符号集上
  建图(仅保留两端均在变更集内的边)并并查集求连通分量;含 ≥1 路由注解符号的分量 → **`interface`
  单元**(= 该接口的完整下游链:路由方法 + 被调的变更 service/dao 的 hunk 合并进一个 slice),
  `route` 取该路由注解方法的 route 串;无路由分量 → **`standalone` 单元**。
- **退化分组(codegraph 不可用)**:当 codegraph 不可用时 SHALL 退化为注解启发式接口单元 + 目录簇
  standalone 归并(接口文件内按接口方法切、剩余文件按目录聚类,`--max-standalone-bytes` 控制单
  单元 slice 上限),行为与无 codegraph 时逐字等价。

两种模式下,分组 SHALL 是**启发式非承诺**:接口识别失败(无注解、非 java web)或调用边判不穿
(反射/DI/AOP 残差)SHALL 退化为 standalone 单元,流程不失败。**共享下游** SHALL 按接口拆:一个
变更符号被多个 interface 分量引用时不合并成一个分量,该符号 hunk 在每个引用它的 interface 单元
slice 内重复(受 `unit_bytes` 预算),跨单元重复 finding 交渲染侧三元组去重。每单元 SHALL 物化
一份**只读 slice 文件**(diff hunk + 有限邻近上下文,含文件相对路径、变更类型 A/M/D/R 标注),落
`<repo>/.mgh-sdr/runs/<ts>/slices/`。`--materialize <dir>` SHALL 枚举 `pending[]`:每项含
`unit_id`(文件系统安全命名,`/ \ :` 一律 `_`,承 NTFS ADS 教训)、`input_path`(slice 绝对路径,
`Path.resolve()` 绝对且在 repo 子树内)、`draft_path`/`done_marker`/`failed_marker`(同形绝对)、
`kind`(`interface`|`standalone`)、`route`(interface 单元的路由串,standalone 为空串)、
`unit_bytes`;stdout 另携带 `repo` 锚、`branch`/`base`、`total`/`done`/`failed`、
`counts{interface,standalone}`、`codegraph`(bool:本次是否走调用链分组)。退出码 `0/1/2`;
stdout=结构化 JSON、stderr=诊断严格分流;`--check <run-dir>` 校验 run 产物自洽(slice 齐备、
pending 路径绝对且在 repo 子树、manifest 字段一致),失败退出 2(承 R5.9)。零变更 diff(两 ref
无差异)SHALL 退出码 0 且 `pending: []` + stdout `empty:true`,不进入 fan-out。

#### Scenario: 同链变更合并为接口调用链单元

- **WHEN** 某 diff 触及 `OrderController.java` 的 `@PostMapping("/order/create")` 方法、
  `OrderService.java` 的 `createOrder` 方法、`OrderDao.java` 的 `insertOrder` 方法,且 codegraph
  调用边表明 `OrderController.createOrder` → `OrderService.createOrder` → `OrderDao.insertOrder`
- **THEN** `diff_group.py --materialize` 产出 1 个 `kind=interface` 单元(route=`/order/create`,
  slice 含三者 hunk 与类级注解上下文),而非 1 个接口单元 + 2 个 standalone 单元

#### Scenario: 反射/DI 判不穿的变更落独立单元

- **WHEN** 某 diff 触及 `PayService.java` 的 `pay` 方法(经反射/DI 注入被调用,codegraph 无其
  调用边)与 `AuditService.java` 的 `log` 方法(彼此无调用边)
- **THEN** 两方法各落一个 `kind=standalone` 单元(拆多个、不硬塞),流程退出码 0、pending 非空、
  不失败

#### Scenario: 共享下游按接口拆、不并成一个分量

- **WHEN** 某 diff 触及 `UserController.java` 的 `/user/detail` 与 `/user/list` 两个接口,两者都
  调变更的 `UserService.queryUser`
- **THEN** 产出 2 个 `kind=interface` 单元(`/user/detail`、`/user/list`),`UserService.queryUser`
  的 hunk 在两单元 slice 内各出现一次;两单元若产相同 finding 由渲染侧三元组去重

#### Scenario: 无 codegraph 退化为注解+目录分组

- **WHEN** `<repo>/.codegraph/` 不存在或 PATH 无 `codegraph`
- **THEN** 分组退化为注解启发式接口单元 + 目录簇 standalone,stdout `codegraph:false`;行为与无
  codegraph 时逐字等价

#### Scenario: 零变更 diff 空转

- **WHEN** `--base master --branch X` 且 X 与 master 无任何差异
- **THEN** 退出码 0,stdout `{"empty": true, "pending": [], ...}`,编排器不 spawn 任何 subagent,
  仍渲染一份「无变更」报告

### Requirement: fan-out 评审单元与 6 维度默认检查面

编排器 SHALL 经 `fanout_runner.py --tier sdr` 波次派发评审:每个 pending 单元一个 subagent
(`sdr-review-fanout` agent 定义;claude 侧经 `--agents` inline JSON,opencode 侧 `mode: primary`
克隆),任务消息由固定模板 `core/prompts/fragments/fanout/sdr-task.md` + 该单元 `pending[]` 字段
逐字填充。subagent SHALL **恰好读** `input_path`(slice 文件)、**恰好写** `draft_path`(统一
JSON 问题记录)+ touch `done_marker`,NEVER 读其他单元的 slice 或其他分支产物。默认检查维度 SHALL
为闭集 6 项:`vertical-authz`(垂直越权)、`horizontal-authz`(横向越权)、`other-authz`(其他
权限问题)、`sql-injection`(SQL 注入)、`sensitive-data`(敏感信息屏蔽)、`input-validation`(输入
校验);检查面 SHALL 经 `--dimensions <inline-json|@path>` 参数化收窄或扩展(闭集校验,维度键
闭集 + 扩展维度仅作自由文本检查项透传;非法键退出码 2 早停,任何 LLM token 之前)。每条问题
记录(draft `findings[]` 项)SHALL 统一 schema:`{dimension, severity(high|medium|low|info),
route, file, line_hint, risk(简体中文风险描述), suggestion(简体中文整改建议), control_ref
(命中的存量安全设计名或 null)}`。`sensitive-data` 维度 SHALL 依编排器透传的敏感目录执行(见
「敏感目录复用与回退」要求);6 维度各自的判定锚点是**存量安全设计**(AGENTS.md 安全章节 +
`docs/security-controls/*.md` + 项目记忆),subagent task 消息 SHALL 逐字携带编排器从存量设计
投影出的**检查基线摘要**(确定性由 `sdr_context.py` 产出,≤ 预算字节),NEVER 要求 subagent 自行
读全部 rules 文件。

#### Scenario: 接口单元产出统一 schema 问题记录

- **WHEN** 某 `kind=interface` 单元(路由 `/user/detail`)的 slice 显示新增接口按入参 `brch_no`
  查询但调用链无 `UserContext.get()` 校验,而存量设计声明「横向越权须 brch_no + UserInfo 校验」
- **THEN** 该单元 draft 含一条 `{dimension:"horizontal-authz", severity:"high", route:"/user/detail",
  file:"UserController.java", risk:<未按存量设计校验的中文描述>, control_ref:<存量设计名>}` 的
  finding,且该 finding 可被渲染器与其他单元的去重合并

#### Scenario: 检查面参数化收窄

- **WHEN** 编排器传 `--dimensions '{"dimensions":["sql-injection","input-validation"]}'`
- **THEN** subagent 仅对这两个维度产出 findings(sensitive-data 目录不透传),其余维度不检查;
  manifest 记录实际检查面

#### Scenario: 非法维度键早停

- **WHEN** 编排器传 `--dimensions '{"dimensions":["crypto-audit"]}'`(非闭集且非自由文本扩展形态)
- **THEN** 编排器在任何 subagent spawn 之前以退出码 2 fail-loud,stderr 给出合法维度清单

### Requirement: 存量安全设计基线投影与外部仓受控检索

新增确定性叶脚本 `sdr_context.py`(标准库、自定位、退出码 0/1/2,stdout/stderr 分流)SHALL 产出
两类输入供 fan-out 消费:**(a) 检查基线摘要**——从 `<repo>` 的存量安全设计来源(`AGENTS.md`
安全相关章节、`docs/security-controls/*.md`、`<repo>/.mgh-sra/business_context.json`(若存在))
确定性抽取与 6 维度相关的段落,按字节预算(默认 ≤32KB,`--baseline-budget-bytes` 可调)投影为
单文件基线 slice,预算超限按「接口授权 > SQL > 输入校验 > 敏感数据」优先级截断并在 stdout 显式
披露 `baseline_truncated:true`;**(b) 外部仓受控检索**——解析存量设计中的**外部仓声明**
(约定形态:正则匹配「前端/外部项目本地绝对路径 + 同名分支约定」类描述;命中即产出 `external_repos[]`
声明对象 `{path, branch_sync_note}`),对每个可达的外部仓在本流程**主进程内**(launcher 外壳
/编排器 step 1,NEVER 在 subagent 内)执行受控检索:外部仓同名分支的 `git diff`(同 base)变更
文件清单 + 定向内容命中(配置权限文件——如声明中点名的 `buttonAuth.properties`——中含本分支新增
接口路由与否;前端仓中新增接口路由字符串出现处计数),结果物化为 `<run-dir>/external/<repo-slug>/`
下的小体积结论文件(逐仓字节预算,默认 ≤64KB,超限截断披露),并输出该仓**根绝对路径**供编排器
写入运行域哨兵 `read_roots[]`。外部声明不存在、路径不可达、非 git 目录三者任一 SHALL 降级为
`external_repos: []` + stdout `external_skipped:<原因>`,流程继续不失败。subagent task 消息 SHALL
仅携带物化结论文件的路径(逐字透传),NEVER 携带外部仓原始路径供 subagent 自行读取。`--check
<run-dir>` 校验两类产物自洽。

#### Scenario: 存量设计声明前端仓时检索结论被物化

- **WHEN** `AGENTS.md` 安全章节含「本地前端项目地址 D:/xxx/front,前端分支名与本项目一致;
  垂直越权以 buttonAuth.properties 配置为准」,且该目录存在
- **THEN** `sdr_context.py` 产出基线 slice + `external/<slug>/` 结论文件(含本分支新增接口路由在
  `buttonAuth.properties` 的命中清单 + 前端出现计数),stdout 声明 `external_repos: [{path:"D:/xxx/front",...}]`;
  后续接口单元 subagent 读到的 task 消息含该结论文件路径而非 `D:/xxx/front`

#### Scenario: 声明路径不可达时降级继续

- **WHEN** 存量设计声明 `D:/xxx/front` 但该目录不存在
- **THEN** stdout `external_skipped: "not-found: D:/xxx/front"`,`external_repos: []`,流程以纯
  后端 diff 继续跑完并渲染报告;报告边界声明「外部仓声明不可达,前端相关检查面未覆盖」

#### Scenario: 基线超预算按优先级截断

- **WHEN** 存量设计安全章节 + security-controls 合计远超 32KB 预算
- **THEN** 基线 slice 按维度优先级保留「接口授权」相关段落、截断尾部,stdout
  `baseline_truncated: true` + 截断字节数;manifest `boundaries[]` 披露「基线经截断,低优先级
  维度的存量设计细节未全量投影」

### Requirement: 统一问题记录汇总与确定性报告渲染

新增确定性叶脚本 `render_sdr_report.py`(标准库、退出码 0/1/2、`--check` 承 R5.9)SHALL 收
run 目录下全部 fan-out 单元 draft(`.done` 且 JSON 可解析者;`.failed` 单元以 stderr 汇总 +
manifest `failed_units[]` 计入,不阻断渲染),按 `{dimension, route, file}` 三元组去重合并,
渲染 `<repo>/<工具名>-<分支名>-<YYYYMMDD_HHMMSS>.md`(工具名固定 `mgh-sdr`;分支名取文件系统
安全命名;时间戳到秒、本地时区)。报告 SHALL 为简体中文、面向人读,结构:头部(分支/base/
时间/检查面/敏感目录来源/外部仓结论摘要)+ 按维度分组的问题清单(每条含 severity/route/file/
line_hint/风险/建议/control_ref)+ 「无问题单元」清单(通过复核的接口,供 merge 前放行参考)+
诚实边界节。同名报告文件已存在 SHALL 原子覆盖(时间戳到秒内重跑)。`sdr_manifest.json`(落
run 目录)SHALL 记 `{branch, base, dimensions, sensitive_catalog_source, external_repos[],
counts{units, interfaces, standalone, findings_by_severity, failed_units}, boundaries[]}`。
诚实边界 SHALL 至少含 6 条:① 发现是 LLM 候选需人工复核,非确认漏洞;② 接口分组是注解启发式,
漏分组接口退入独立单元(分析粒度粗但覆盖不丢);③ 引用存量控制断言存在、不断言有效;④ 外部仓
结论是检索时点快照(不保证前端分支已同步);⑤ 基线经字节预算投影,低优先级细节可能未全量投影;
⑥ 敏感目录来源与覆盖范围(目录外字段仅按回退规则识别)。渲染器 NEVER 写 `openspec/`、NEVER 写
run 目录与报告文件之外的目标仓文件。

#### Scenario: 报告文件名与内容可追溯

- **WHEN** 对分支 `feature-pay` 于 2026-09-03 14:30:22 完成评审
- **THEN** 项目根出现 `mgh-sdr-feature_pay-20260903_143022.md`,头部含 branch/base/时间戳,正文
  按 6 维度分组列 findings,每条可溯源到 file + line_hint

#### Scenario: 部分单元 failed 不阻断渲染

- **WHEN** 10 个单元 9 个 `.done`、1 个 `.failed`
- **THEN** 渲染器汇总 9 份 draft 出报告,manifest `counts.failed_units = 1` + `failed_units[]`
  列出该单元 id 与 reason,报告诚实边界披露「1 个评审单元失败,该单元覆盖范围未复核」

#### Scenario: 重复 finding 跨单元去重

- **WHEN** 同一接口路由的两个 hunk 被拆入同组或相邻单元,各产一条 `{dimension,route,file}` 相同
  的 finding
- **THEN** 渲染器按三元组去重合并为一条(line_hint 取并集),报告不再重复列出

### Requirement: 敏感目录复用与默认模板回退(与 sra/srr 的显式分歧)

`sensitive-data` 维度的检查清单 SHALL 按以下优先级解析:① `<repo>/.mgh-sra/sensitive_catalog.json`
存在 → 经 sibling import 复用 `sensitive_catalog` 模块解析 + 闭集校验(非法 → 退出码 2 早停,
任何 LLM token 之前);② 不存在 → **回退加载随 install 落地的默认模板**
(`.mgh-core` 内 `sensitive_catalog.json.example`,即 PIPL/GB-T 35273 37 项)作为生效目录。解析后
对象(`{version, source, categories[], items[], counts{}, directive}`)SHALL 逐字透传进 subagent
task 消息,manifest `sensitive_catalog_source` SHALL 记 `project|default-template`。该回退是
sdr 与 sra/srr(`null` → 6-facet 兜底)的**有意行为分歧**:sdr 复核的是代码 diff,收窄到 6 facet
会让公司目录缺位时的敏感数据检查显著弱于默认模板;此分歧 SHALL 在本 spec、命令壳 `--help` 文案与
报告诚实边界三处显式披露。

#### Scenario: 项目目录存在则复用

- **WHEN** `<repo>/.mgh-sra/sensitive_catalog.json` 存在且合法
- **THEN** 编排器以 `sensitive_catalog_source: "project"` 解析并透传该目录,subagent 逐项查脱敏缺口
  并标 `catalog_key`

#### Scenario: 项目目录缺失回退默认模板

- **WHEN** `<repo>/.mgh-sra/sensitive_catalog.json` 不存在
- **THEN** 编排器以 `sensitive_catalog_source: "default-template"` 加载 `.example` 默认模板并透传,
  检查面为 PIPL/GB-T 35273 37 项;manifest 与报告披露该来源

#### Scenario: 项目目录非法早停

- **WHEN** `<repo>/.mgh-sra/sensitive_catalog.json` 存在但含未知 category
- **THEN** 编排器退出码 2 + 可操作 stderr(指向该文件的违规项),不 spawn 任何 subagent

### Requirement: launcher 单命令外壳与运行域激活

新增 launcher 脚本 `core/scripts/mgh_sdr_launch.py`(**随 install 分发**;人/cron 入口,NEVER 被
宿主 subagent 调用;标准库)SHALL 支持一条命令拉起全流程:`py mgh_sdr_launch.py --repo
<abs-target> [--branch <ref>] [--base <ref>] [--host opencode|claude] [--dimensions <json>]
[--multi-branch <file>]`。launcher
SHALL:① 校验目标仓可达 + 宿主 CLI 在 PATH(`--host` 显式 > opencode > claude;均缺退出码 2 +
recipe);② 于**自身进程内**(编排提示词发往宿主 CLI **之前**)执行编排流程中需要项目外读权限的
部分——调用 `sdr_context.py` 完成外部仓受控检索与结论物化,使跨树读取只发生在 launcher 进程
(已获用户明示授权的 shell 会话),宿主 CLI subagent 会话零权限打断;③ 准备运行域:写 `<repo>/
.mgh-sdr/.active` 磁盘哨兵(JSON `{domain:"mgh-sdr", target, out_roots:[], read_roots:[<已确认
外部仓>], v:1}`)+ 组装编排提示词文件(逐字含 launcher 已产出的绝对路径:run 目录 / 基线 slice /
外部结论文件 / `sensitive_catalog_source` 判定结果),spawn `opencode run`(任务经 stdin)或
`claude -p`(任务经 stdin)执行编排;④ 宿主 CLI 退出后移除哨兵。`--multi-branch <file>` SHALL
对清单分支**串行**逐个执行完整流程(每分支独立 run 目录 + 独立报告;单分支失败记录后继续)。
launcher 自身退出码:0 全部分支成功 · 1 运行时失败 · 2 误用(参数/宿主缺失/目标不可达)。

#### Scenario: launcher 一条命令拉起 opencode 全流程

- **WHEN** 用户在任意 cwd 运行 `py mgh_sdr_launch.py --repo D:/work/svc --host opencode`
- **THEN** launcher 校验宿主、完成外部仓检索与运行域准备(哨兵 + 提示词文件)、spawn
  `opencode run`(stdin 传编排提示词);流程跑完后项目根出现报告文件、哨兵被移除;全程 subagent
  零权限确认打断

#### Scenario: 外部仓读取权限只发生在外壳

- **WHEN** 存量设计声明的外部前端仓需被检索
- **THEN** 检索由 launcher 进程(用户显式运行的 `py` 命令)完成,宿主 CLI 内 subagent 仅读物化
  结论文件——运行域守卫对未声明根的跨树读拦截语义不变,宿主会话 NEVER 弹外部目录权限确认

#### Scenario: 多分支串行

- **WHEN** `--multi-branch branches.txt`(每行一个分支名)含 3 个分支
- **THEN** launcher 串行跑 3 轮完整流程,产出 3 份独立报告 + 各自 run 目录;第 2 分支失败不阻断
  第 3 分支,launcher 最终退出码 1 且 stderr 列出失败分支

### Requirement: sdr 运行域守卫激活与幂等 resume

`/mgh-sdr` SHALL 为第 6 个运行域:env `MGH_SDR_ACTIVE=1` 或磁盘哨兵 `<repo>/.mgh-sdr/.active`
(向上 walk 发现,承既有激活契约)激活守卫;哨兵 `read_roots[]` 声明的外部只读根按 `runtime-hook-enforcement`
的 read_roots 扩展要求生效。流程 SHALL 幂等可恢复:`diff_group.py --materialize` 对已存在 `.done`
marker 的单元跳过物化重复工作;`fanout_runner.py --resume` 按磁盘 marker 重派 pending(既有语义);
`render_sdr_report.py` 对 draft 齐备的 run 目录可重复执行(重跑覆盖同名报告)。编排器每步完成后
SHALL 跑对应产出者 `--check`,失败(退出码 2)回退重跑,不带着破损产物继续(承 R5.9)。

#### Scenario: 崩溃后 resume 零全损推进

- **WHEN** fan-out 中途宿主中断(部分单元 `.done`、部分 pending)后重新运行 launcher 同参数
- **THEN** `diff_group.py` 复用既有 run 目录(按 resume 语义),dispatcher 仅重派未 `.done` 单元,
  已完成单元零重复消耗;最终报告覆盖全部单元

#### Scenario: 完成/干净停止后哨兵移除

- **WHEN** 流程跑完(报告渲染完成)或用户干净停止(含 `--dry-run` 早退之外的正常退出路径)
- **THEN** `<repo>/.mgh-sdr/.active` 被移除;残留哨兵的 run(宿主被硬杀)由下次 launcher 启动时
  检测并复用/清理,不静默锁死日常开发
