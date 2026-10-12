## MODIFIED Requirements

### Requirement: launcher 单命令外壳与运行域激活

新增 launcher 脚本 `core/scripts/mgh_sdr_launch.py`(**随 install 分发**;人/cron 入口,NEVER 被
宿主 subagent 调用;标准库)SHALL 支持一条命令拉起全流程:`py mgh_sdr_launch.py --repo
<abs-target> [--branch <ref>] [--base <ref>] [--host opencode|claude] [--dimensions <json>]
[--multi-branch <file>] [--read-root <abs>]... [--model <provider/model>] [--open] [--dry-run]`。
launcher
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
哨兵;⑤ **分支存在性预检**:对每个待跑分支(单分支与 `--multi-branch` 同一预检、真跑与
`--dry-run` 同一预检),在任何产物写入(run 目录 / 哨兵 / 提示词文件)与任何宿主 spawn 之前
先以 `git rev-parse --verify` 校验分支 ref 在目标仓可解析;不可解析 → 该分支**确定性早败**
(记 FAILED,原因 = branch-not-found;零宿主 spawn、零 LLM 消耗、零 run 目录与哨兵副作用),
其后的分支照常执行——`--dry-run` 因此对清单有效性有真实校验力(含无效分支的 dry-run 退出 1,
NEVER 报 ok);⑥ **报告认领以本分支 run 目录为唯一来源**:宿主 CLI 退出 0 后,launcher SHALL
读该分支 run 目录内 `sdr_manifest.json` 的 `report` 字段(绝对路径)认领报告;manifest 缺失
或其 `report` 指向的文件不存在 → 该分支记 FAILED(原因 = no-report);launcher NEVER 以
「仓根最新 / 任意 `mgh-sdr-*.html` glob」认领任何分支的报告——跨分支产物认领在结构上不可能;
⑦ **spawn 环境卫生**:spawn 宿主 CLI 时 SHALL 保证子进程的项目目录解析落在目标仓——剥离
子进程环境中的 `PWD` 变量(宿主按 `PWD ?? cwd` 解析项目归属时回落到 launcher 显式传入的
cwd = 目标仓;claude 宿主同路径处理、无害);⑧ **可诊断性与模型透传**:opencode spawn SHALL
追加 `--print-logs --log-level ERROR`(provider 形失败在 launcher stderr 可定位,NEVER 只有
一句错误信封);`--model <provider/model>` SHALL 透传给宿主 CLI 的同名 flag(opencode 与
claude 同形),未传时不附加。
`--multi-branch <file>` SHALL
对清单分支**串行**逐个执行完整流程(每分支独立 run 目录 + 独立报告;单分支失败记录后继续)。
launcher 自身退出码:0 全部分支成功 · 1 运行时失败(任一分支 FAILED:分支不存在 / sdr_context
失败 / 宿主 CLI 非零退出 / 宿主退出 0 但未产报告)· 2 误用(参数/宿主缺失/目标不可达)。

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

#### Scenario: 不存在分支确定性早败

- **WHEN** `--multi-branch` 清单含一个目标仓不存在的分支名(如失败探针),launcher 真跑
- **THEN** 该分支在创建 run 目录、写哨兵、spawn 宿主之前即被记 FAILED(原因 branch-not-found),
  零宿主 spawn、零 LLM 消耗、零 run 目录;其后的分支照常完整执行并各出报告;launcher 最终退出码 1
  且 stderr 失败汇总列出该分支及原因

#### Scenario: dry-run 对无效清单如实报败

- **WHEN** 以 `--dry-run` 跑同一含不存在分支的清单
- **THEN** 不存在分支同样被记 FAILED(与真跑同一预检),launcher 退出码 1——绿色冒烟不再对
  无效分支清单给出虚假信心;有效分支照常产 dry-run 产物(run 目录 + 提示词,零 spawn)

#### Scenario: 报告认领以本分支 run 目录为准

- **WHEN** 某分支宿主 CLI 退出 0 但该分支 run 目录内无 `sdr_manifest.json`(如宿主中途干净停),
  且仓根存在其他分支已渲染的 `mgh-sdr-*.html` 报告
- **THEN** 该分支被记 FAILED(原因 no-report),launcher NEVER 把仓根任何既有报告记为该分支
  产物;`--open` 不触发;stdout `reports[]` 不含跨分支认领的路径

#### Scenario: 非 target cwd 启动宿主归属正确

- **WHEN** 用户在开发仓(或任意非目标仓)cwd 运行 launcher 指向目标仓,宿主为 opencode
- **THEN** spawn 的子进程环境中无 `PWD`,opencode 按 launcher 传入的真实 cwd(目标仓)解析项目
  归属——会话创建在目标仓项目下,项目级配置/插件按目标仓生效(修复「从开发仓启动全灭」)

#### Scenario: 模型透传

- **WHEN** launcher 以 `--model deepseek/deepseek-flash` 启动
- **THEN** 宿主 CLI 以该模型 id 启动(opencode `run --model …` / claude `-p --model …`);
  未传 `--model` 时 launcher 不附加任何模型参数(沿用宿主自身默认)
