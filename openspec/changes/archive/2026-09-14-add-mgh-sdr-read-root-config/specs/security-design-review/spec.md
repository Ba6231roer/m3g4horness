## MODIFIED Requirements

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
接口路由与否;**前端仓中新增接口路由字符串出现处计数**——正则 SHALL 与 diff_group 的路由注解
族对齐(含 `@RequestMapping` 及组合注解),并拼接类级 base route(平凡可判定时)),结果落盘
为 `<run-dir>/external/<repo-slug>/` 下的小体积结论文件(逐仓字节预算,默认 ≤64KB,超限截断
披露),**并 SHALL 将逐路由计数落盘进 context.json `external_repos[].route_hits[]`**
(`{route, count}` 列表;此前仅存在于 hits.md 文本、render 不可确定性消费),并输出该仓**根绝
对路径**供编排器写入运行域哨兵 `read_roots[]`。检索前 SHALL 先对项目配置
`<repo>/.mgh/read-roots.json` 核对授权:**已配置**(条目存在且为目录)的外部仓照常检索;**未配置**
的外部仓 SHALL NOT 被检索(该仓零读取),降级为 `external_skipped:"unapproved: <path>"` 并在
stdout 输出 `pending_approval:[<abs>…]`,流程继续不失败。外部声明不存在、路径不可达、非 git
目录、未获配置授权四者任一 SHALL 降级为 `external_repos: []` + stdout `external_skipped:<原因>`,
流程继续不失败。subagent task 消息 SHALL 仅携带结论文件的路径(逐字透传),NEVER 携带外部仓原始
路径供 subagent 自行读取。`--check <run-dir>` 校验两类产物自洽(新增校验:`route_hits[]` 存在时
SHALL 为 `{route, count}` 列表形态)。

#### Scenario: 前端路由计数进入 context.json 可被 render 消费

- **WHEN** 存量设计声明前端仓 `D:/xxx/front`(存在、git 可达、**已配置**),本分支新增路由
  `/order/submit` 与 `/cache/user/direct`,前端仓文本文件分别命中 2 处与 0 处
- **THEN** context.json `external_repos[0].route_hits` 含 `{route:"/order/submit", count:2}`
  与 `{route:"/cache/user/direct", count:0}`,render 简报表该路由行前端两列为「是 / 2 处」与
  「否 / —」;`@RequestMapping` 族路由(非组合注解)同样被计数

#### Scenario: 存量设计声明前端仓时检索结论被物化

- **WHEN** `AGENTS.md` 安全章节含「本地前端项目地址 D:/xxx/front,前端分支名与本项目一致;
  垂直越权以 buttonAuth.properties 配置为准」,该目录存在且 `D:/xxx/front` 已在
  `.mgh/read-roots.json` 配置中
- **THEN** `sdr_context.py` 产出基线 slice + `external/<slug>/` 结论文件(含本分支新增接口路由在
  `buttonAuth.properties` 的命中清单 + 前端出现计数),stdout 声明 `external_repos: [{path:"D:/xxx/front",...}]`;
  后续接口单元 subagent 读到的 task 消息含该结论文件路径而非 `D:/xxx/front`

#### Scenario: 未配置的外部仓跳过检索并进入待批清单

- **WHEN** 存量设计声明 `D:/xxx/front`(目录存在)但 `.mgh/read-roots.json` 不含该路径
- **THEN** `sdr_context.py` 对该仓零读取,stdout `external_skipped: "unapproved: D:/xxx/front"`
  且 `pending_approval` 含 `D:/xxx/front`,`external_repos: []`,流程以纯后端 diff 继续

#### Scenario: 声明路径不可达时降级继续

- **WHEN** 存量设计声明 `D:/xxx/front` 但该目录不存在
- **THEN** stdout `external_skipped: "not-found: D:/xxx/front"`,`external_repos: []`,流程以纯
  后端 diff 继续跑完并渲染报告;报告边界声明「外部仓声明不可达,前端相关检查面未覆盖」,简报表
  前端两列为「未知 / —」

#### Scenario: 基线超预算按优先级截断

- **WHEN** 存量设计安全章节 + security-controls 合计远超 32KB 预算
- **THEN** 基线 slice 按维度优先级保留「接口授权」相关段落、截断尾部,stdout
  `baseline_truncated: true` + 截断字节数;manifest `boundaries[]` 披露「基线经截断,低优先级
  维度的存量设计细节未全量投影」

### Requirement: launcher 单命令外壳与运行域激活

新增 launcher 脚本 `core/scripts/mgh_sdr_launch.py`(**随 install 分发**;人/cron 入口,NEVER 被
宿主 subagent 调用;标准库)SHALL 支持一条命令拉起全流程:`py mgh_sdr_launch.py --repo
<abs-target> [--branch <ref>] [--base <ref>] [--host opencode|claude] [--dimensions <json>]
[--multi-branch <file>]`。launcher
SHALL:① 校验目标仓可达 + 宿主 CLI 在 PATH(`--host` 显式 > opencode > claude;均缺退出码 2 +
recipe);② 于**自身进程内**(编排提示词发往宿主 CLI **之前**)执行编排流程中需要项目外读权限的
部分——调用 `sdr_context.py` 完成外部仓受控检索与结论落盘,使跨树读取只发生在 launcher 进程
(已获用户明示授权的 shell 会话),宿主 CLI subagent 会话零权限打断;跨树读取以项目配置
`<repo>/.mgh/read-roots.json` 为前提——未配置的外部声明仓 SHALL 被跳过(零读取),经 stderr warn
+ stdout `pending_approval[]` 披露,不阻断流程;③ 准备运行域:写 `<repo>/
.mgh-sdr/.active` 磁盘哨兵(JSON `{domain:"mgh-sdr", target, out_roots:[], read_roots:[<已配置
且本次参与检索的外部仓>], v:1}`)+ 组装编排提示词文件(逐字含 launcher 已产出的绝对路径:run 目录 /
基线 slice /外部结论文件 / `sensitive_catalog_source` 判定结果 / `pending_approval[]` 若非空),
spawn `opencode run`(任务经 stdin)或 `claude -p`(任务经 stdin)执行编排;④ 宿主 CLI 退出后移除
哨兵。`--multi-branch <file>` SHALL
对清单分支**串行**逐个执行完整流程(每分支独立 run 目录 + 独立报告;单分支失败记录后继续)。
launcher 自身退出码:0 全部分支成功 · 1 运行时失败 · 2 误用(参数/宿主缺失/目标不可达)。

#### Scenario: launcher 一条命令拉起 opencode 全流程

- **WHEN** 用户在任意 cwd 运行 `py mgh_sdr_launch.py --repo D:/work/svc --host opencode`
- **THEN** launcher 校验宿主、完成外部仓检索与运行域准备(哨兵 + 提示词文件)、spawn
  `opencode run`(stdin 传编排提示词);流程跑完后项目根出现报告文件、哨兵被移除;全程 subagent
  零权限确认打断

#### Scenario: 外部仓读取权限只发生在外壳

- **WHEN** 存量设计声明的外部前端仓已配置于 `.mgh/read-roots.json` 并需被检索
- **THEN** 检索由 launcher 进程(用户显式运行的 `py` 命令)完成,宿主 CLI 内 subagent 仅读结论
  文件——运行域守卫对未授权根的跨树读拦截语义不变,宿主会话 NEVER 弹外部目录权限确认

#### Scenario: 未配置仓不检索、不进哨兵、待批披露

- **WHEN** 存量设计声明 `D:/xxx/front` 但配置中无该路径,launcher 同参数启动
- **THEN** launcher 对该仓零读取,哨兵 `read_roots[]` 不含该路径,stdout/stderr 披露
  `pending_approval` 与 `unapproved` 原因,编排提示词携带该清单,流程继续(纯后端 diff)

#### Scenario: 多分支串行

- **WHEN** `--multi-branch branches.txt`(每行一个分支名)含 3 个分支
- **THEN** launcher 串行跑 3 轮完整流程,产出 3 份独立报告 + 各自 run 目录;第 2 分支失败不阻断
  第 3 分支,launcher 最终退出码 1 且 stderr 列出失败分支

## ADDED Requirements

### Requirement: 外部仓读取授权经用户确认并持久化到项目配置

`/mgh-sdr` 编排流 SHALL 在 launcher/sdr_context 报告非空 `pending_approval[]` 后、继续消费外部
结论前,于宿主会话向用户呈现待批外部仓清单(绝对路径 + 用途说明)并请求决策:**同意** → 编排器经
`py <mgh-core>/scripts/read_roots_config.py --target <repo> --add <abs>` 将仓写入项目配置
(支持一次多仓逐个 `--add`),随后**重跑 launcher 同参数**完成检索(配置即时生效,launcher 幂等可
续);**拒绝** → NEVER 写配置,按降级继续,报告边界声明「外部仓未授权,相关检查面未覆盖」。编排器
NEVER 在未获用户同意时写配置。确定性叶脚本 `read_roots_config.py`(标准库、自定位)SHALL:支持
`--target <abs>` 与 `--add <abs>`(可重复)/`--remove <abs>`/`--list`/`--check`;对
`<target>/.mgh/read-roots.json` 原子写(schema `{"v":1,"read_roots":[…]}`,未知字段保留、顺序
稳定);幂等(已存在的 `--add` 为 no-op);`--add` 校验目标存在且为目录(违者退出码 2 + 可操作
stderr);每次实际变更打印 stderr(变更前后条目);stdout 结构化 JSON(`configured[]`/`added[]`/
`removed[]`),退出码 0/1/2;`--check` 校验配置文件自洽(schema 合法 ∧ 条目均存在且为目录,违者
退出码 2)。

#### Scenario: 首次运行问询、同意后写配置并重跑放行

- **WHEN** 首次在某项目运行 `/mgh-sdr`,存量设计声明前端仓 `D:/xxx/front`(未配置),编排器向
  用户呈现待批清单,用户同意
- **THEN** 编排器执行 `py …/read_roots_config.py --target <repo> --add D:/xxx/front`(stderr
  打印变更),重跑 launcher 同参数;第二轮 launcher 检索该仓、哨兵 `read_roots[]` 含该路径,
  subagent 工具面/Bash 面对该仓的读按 `runtime-hook-enforcement` 的统一读允许集放行

#### Scenario: 拒绝后降级继续并如实披露

- **WHEN** 用户对待批仓 `D:/xxx/front` 拒绝
- **THEN** 配置不变,流程按 `external_skipped:"unapproved"` 降级继续跑完并渲染报告;报告边界
  声明「外部仓未授权,前端相关检查面未覆盖」,简报表前端两列为「未知 / —」

#### Scenario: 二次运行不再问询

- **WHEN** 上一 run 中用户已批准 `D:/xxx/front` 并写入配置,再次运行 `/mgh-sdr`
- **THEN** launcher 检索照常、`pending_approval` 为空,编排器不再问询(每仓仅首次决策)

#### Scenario: read_roots_config.py 幂等与非法输入

- **WHEN** 对同一已配置仓重复 `--add`;或 `--add D:/gone`(不存在);或 `--check` 遇到含失效条目
  的配置文件
- **THEN** 重复 `--add` 为 no-op(stdout `added:[]`,退出码 0);`--add D:/gone` 退出码 2 +
  stderr 指明目录不存在;`--check` 对失效条目退出码 2 并列出条目(fail-closed:失效条目在守卫
  侧本就零授权,`--check` 使其显式可见)
