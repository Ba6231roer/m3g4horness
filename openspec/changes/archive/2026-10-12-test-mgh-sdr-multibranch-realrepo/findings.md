# findings — `/mgh-sdr --multi-branch` 首次真仓验证(2026-10-12)

> **受众**:维护者(后续 fix/improve change 的立项输入,结论自足、无需回访测试现场)。
> **测试床**:`C:/DEV/springBootTemplate`(真实 Spring Boot 仓,基线缺失、敏感目录仅模板);**被测** = 开发态 `install.sh --opencode` 装入的副本;**宿主**显式钉死 opencode 1.18.31。
> **分支清单**(本目录 `branch-list.txt`):`sdr-dryrun`(既有形状分支)→ `sdr-mb-nonexistent`(**故意不存在的失败探针**)→ `sdr-mb-authz`(新建,越权+输入校验形状,commit `685f91a`)→ `sdr-mb-sql-sensitive`(新建,SQL 注入+敏感信息形状,commit `cc3322f`)。
> **原始证据**:本目录 `evidence/`(run0=dry-run、run1/run2=失败轮、run3=有效轮的 stdout/stderr 全量落盘 + 退出码)。

---

## 0. TL;DR(人话)

1. **机制面基本成立**:单条命令串行跑 4 分支、每分支独立 run 目录与报告、报告内容与各自分支 diff 对应、哨兵随分支生灭、全程不动工作树、降级披露齐全、opencode 并行扇出三轮全收敛。
2. **失败语义与规格相反(最重要的发现)**:规格承诺「不存在的分支 = 确定性早败:不 spawn 宿主、不耗 LLM、记 FAILED、最终退出码 1」。实测:launcher 照常 spawn 宿主(真实消耗 LLM 轮次),宿主自查分支不存在后按提示词「干净停」退出 0,launcher 把探针标成 **ok**,还**把第 1 个分支的报告认领为探针的产物**,最终退出码 **0**。「失败记录后继续」只在「宿主非零退出」一种形态下成立。
3. **环境面踩了两个 opencode 的坑**(与 mgh-sdr 无关,但被 launcher 的 spawn 方式放大):opencode 用 `PWD` 环境变量而非实际工作目录决定项目归属;维护者全局默认模型 ID 已失效。两者叠加 = 所有分支 FAILED,报错只有一句「Unexpected server error」,定位花了三轮(诊断开关 `--print-logs` 不在产品路径上)。

---

## 1. 执行轮次与每分支关键指标

### 1.1 轮次总览

| 轮 | 起止(本地) | 墙钟 | 结果 | 根因 |
| --- | --- | --- | --- | --- |
| run0 dry-run | 16:37:12→16:37:13 | ~2s | 4/4 分支产 run 目录,退出 0 | —(零 LLM,符合预期) |
| run1 | 16:38:12→16:39:03 | 51s | **4/4 FAILED**,退出 1 | 环境双因:E1(PWD→会话落错项目)+ E2(模型 ID 失效) |
| run2 | 16:49:05→16:49:14 | 9s | **4/4 FAILED**,退出 1 | 环境单因:E2(E1 已绕开:改从测试床 cwd 启动) |
| run3(有效轮) | 16:53:55→17:10:20 | 16m25s | 4/4「ok」(**探针为假 ok**),退出 **0** | 环境修复后完整跑通 |

环境修复方式(均为测试床/启动方式层面,未改产品代码、未动用户全局配置):E1 → 从测试床 cwd 启动 launcher;E2 → 测试床项目级 `.opencode/opencode.json` 写 `{"model": "deepseek/deepseek-flash"}` 覆盖失效的默认模型。

### 1.2 run3 每分支指标

| # | 分支 | 起止 | 耗时 | 单元数(接口+standalone) | findings(高/中/低) | 失败单元 | 报告产物 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | sdr-dryrun | 16:53:55→17:00:17 | 6m22s | 8(6+2) | 22(6/12/4) | 0 | `mgh-sdr-sdr-dryrun-20261012_170017.html` |
| 2 | sdr-mb-nonexistent(探针) | 17:00:32→17:02:59 | 2m27s | —(早停,无分组产物) | — | — | **误认 #1 的报告**(问题 P1/P2) |
| 3 | sdr-mb-authz | 17:02:59→17:06:46 | 3m47s | 5(3+2) | 22(8/11/3) | 0 | `mgh-sdr-sdr-mb-authz-20261012_170646.html` |
| 4 | sdr-mb-sql-sensitive | 17:06:59→17:10:20 | 3m21s | 4(2+2) | 13(7/6/0) | 0 | `mgh-sdr-sdr-mb-sql-sensitive-20261012_171020.html` |

扇出全收敛:三分支均 wave=5、waves_run=8/5/4、cooldowns=0、rate_limited=false、partial=false;每分支独立 run 目录 `.mgh-sdr/runs/<时间戳>-<分支名>/`,内含 `sdr_manifest.json` + `sdr_report_data.json`(与 HTML 同源)。

---

## 2. 规格场景逐条结论

| 规格场景 | 结论 | 一句证据 |
| --- | --- | --- |
| 三分支就绪(master 零新提交、各分支 diff 非空) | ✅ 符合 | `git diff --stat` 16f/+595−39、8f/+340、8f/+244;master 仍 `5e8ac26` |
| sweep 不动工作树(不 checkout) | ✅ 符合 | 全程检出 `sdr-dryrun`;`git status` 零 tracked 修改 |
| dry-run 冒烟(4 run 目录、零 spawn、哨兵行为记录) | ⚠️ 部分符合 | 4 目录 + `orchestrator_prompt.md` 齐、零宿主 spawn;哨兵保留 + 残哨复用文案已记录;**但探针分支在 dry-run 也报 ok**(P6) |
| 单条命令串行真跑(逐分支可辨、任一时刻至多一个宿主) | ✅ 符合 | run3 单进程 4 段 `[launch] === branch <名> ===`;opencode 日志显示会话严格顺序创建 |
| 探针分支确定性早败 | ❌ **偏差** | 探针 spawn 了宿主并消耗 LLM 轮次,宿主「clean stop」退出 0(P1) |
| 最终退出码 1 + stderr FAILED 汇总 | ❌ **偏差** | 退出码 0、无 FAILED 汇总(探针被标 ok;run1/run2 反而因环境失败演示了该形态:退出 1 + FAILED BRANCHES(4) 汇总正常) |
| 报告独立性与对应性 | ✅ 符合 | 3 份报告文件名各含分支名;authz 报告命中越权×26/输入校验×9 及全部夹具文件;sql-sensitive 命中 SQL 注入×7/敏感信息×5/硬编码×2 及 Mapper `${}`、手机号/证件号;dryrun 报告 6 接口链可溯源 |
| 历史残留报告不被误认 | ⚠️ 部分符合 | 3 份新报告 mtime(17:00:17/17:06:46/17:10:20)均晚于各自 run 起始、晚于全部 5 个残留文件(最新残留 15:32:25)——旧残留无误认;**但探针把最新报告(第 1 分支的)认领为自己的产物**——跨分支误认成立(P2) |
| 哨兵随分支生灭、run 后无残留 | ✅ 符合 | 每分支 run 中 `.active` 在、转场重写;run3 结束后不存在 |
| 降级披露(manifest + 报告) | ✅ 符合 | 3 份 manifest `sensitive_catalog_source: "default-template"`;`boundaries[]` 含「LLM 候选非已确认漏洞」「默认模板回退」「基线字节预算投影」三条;外部仓 external=0 → `frontend_is: 未知` 如实呈现 |

---

## 3. 问题清单(后续 change 立项输入)

### P1(高)失败探针语义反转:宿主「干净停」退出 0 → launcher 标 ok

- **现象**:清单第 2 位的不存在分支没有按规格「确定性早败」,而是完整走了一次宿主 spawn:宿主会话内 `resume_state` 正常给出 step=group 配方,agent 跑 `diff_group` 才发现分支不存在,随即按提示词 step 5 的「clean stop(分支不存在)」语义删除哨兵并**退出 0**;launcher 据此把探针标 **ok**。
- **复现**:清单中放一个不存在的分支名,真跑(证据 `evidence/run3-stderr.log` 探针段:`[✓] step 5: clean stop (branch not found) + remove sentinel` + `[launch] branch sdr-mb-nonexistent: ok`)。
- **影响**:①探针白烧一次宿主 spawn 与真实 LLM 轮次(约 2m27s);②失败不被记录,「FAILED BRANCHES 汇总 + 退出码 1」的合同整体失效;③连锁触发 P2 的报告误认;④任何依赖失败汇总的自动化断言(含本规格场景)全部失效。
- **定位线索**:`core/scripts/mgh_sdr_launch.py` 的 `_run_branch`——以**宿主退出码**为唯一 ok/FAILED 判据,spawn 前无分支存在性预检(全文件仅 `rev-parse --git-dir` 与 `--abbrev-ref HEAD` 两处 git 调用);编排提示词 step 5 把「分支不存在」并入 clean-stop 语义,宿主遵嘱退出 0。
- **建议方向**:launcher 在 spawn 前 `git -C <repo> rev-parse --verify --quiet <branch>` 预检,失败即记 FAILED(reason=branch-not-found)并跳过该分支——这才是规格说的「确定性早败」。(宿主侧改退出码语义是另一条路,但要动编排提示词且仍烧 spawn,劣于预检。)

### P2(高)报告认领 = 仓根最新 `mgh-sdr-*.html`,不按分支名过滤

- **现象**:探针分支没有产任何报告(其 run 目录只有 baseline/context/prompt/run_config 四个文件),但 launcher 给它记的产物是 `mgh-sdr-sdr-dryrun-20261012_170017.html`——**第 1 个分支的报告**。
- **复现**:任一「宿主退出 0 但未渲染报告」的分支 + 仓根已有任意更新的 `mgh-sdr-*.html`(今日=探针;未来=任何在渲染前早退的分支)。
- **影响**:launcher stdout 的 `reports[]` 与 `--open` 打开的报告不可信;跨分支产物污染,「每分支报告与分支 diff 对应」在失败相邻场景被破坏。
- **定位线索**:`core/scripts/mgh_sdr_launch.py` `_run_branch` 末尾:`sorted(repo.glob("mgh-sdr-*.html"), key=mtime)[-1]`——纯「仓根最新」。
- **建议方向**:按 `mgh-sdr-<branch-safe>-*.html` 前缀过滤 + 「mtime 晚于本分支 run 起始」双条件;两者不满足 → 记「该分支未产报告」,NEVER 认领他人产物。

### P3(高,环境触发器)launcher spawn 不清理 `PWD`,opencode 会话落错项目

- **现象**:从开发仓 cwd 启动 launcher(run1)时,4 个 opencode 会话全部创建在**开发仓**的项目下(opencode 日志:`created session … directory="C:\DEV\m3g4horness"`,而 spawn 声明的 cwd 是测试床),随后宿主报「Unexpected server error」全灭。从测试床 cwd 启动(run2/3)则会话归属正确。
- **复现**:`cd <任意非目标仓目录> && py <目标仓>/.opencode/mgh-core/scripts/mgh_sdr_launch.py --repo <目标仓> --host opencode …`(证据 `evidence/run1-stderr.log` + opencode 日志 16:38 时段)。
- **影响**:opencode 宿主的 sweep 从任何非目标仓 cwd 启动都全灭;更广地,所有经 launcher 的 opencode 会话的项目归属( hence 配置/插件/权限)取错项目。claude 宿主不受影响(`-p` 按真实 cwd)。
- **定位线索**:launcher `_spawn_host` 用 `subprocess.run(cmd, input=prompt, cwd=str(repo))`——只改子进程工作目录,**不改继承的环境变量**;而 opencode v1.18.31 `run` 命令按 **`process.env.PWD ?? process.cwd()`** 解析项目目录(PWD 优先)。Git Bash 启动的 Python 进程带着 `PWD=<launcher 父目录>`,子进程原样继承。
- **建议方向**:spawn 时传 `env={**os.environ, "PWD": str(repo)}`(或剥掉 `PWD`);更稳的是对 opencode 加 `--dir <repo>` 参数(该 flag 走显式 chdir)。任一皆可,后者语义最正。

### P4(中)失败呈现不可诊断:「Unexpected server error」一句话,server 日志无 ERROR

- **现象**:run1/run2 共 8 次宿主失败,launcher stderr 只有 4 行错误信封(name=UnknownError + ref);opencode 自己的日志文件在对应时段**零 ERROR 记录**;真实根因(E2 模型 ID 失效 → `ProviderModelNotFoundError`)只能手工 `opencode run --print-logs --log-level DEBUG` 复现才可见。
- **复现**:默认模型指向不存在的 model id,跑任意不带 `--print-logs` 的 `opencode run`。
- **影响**:真机故障的定位成本从「看一眼日志」变成「三轮排查 + 读上游源码」;「Check server logs for details.」的提示指向的日志里并没有 details。
- **定位线索**:上游 opencode 客户端错误信封设计 + 服务端未把 handler 异常落盘;launcher `_spawn_host` 的 cmd 仅 `[opencode, run]`,未透传任何日志开关。
- **建议方向**:launcher 对 opencode 加 `--print-logs --log-level ERROR`(stderr 已严格分流,并入不影响契约),或落 run 目录 `<run>/host.run.log`;`docs` 类排查手册补一句该手段(非分发的研发手册即可)。

### P5(中)运行域守卫误拦「仓根报告发现」命令(编排提示词要求的动作)

- **现象**:run3 探针会话中,宿主执行 `ls -la "C:\DEV\springBootTemplate" | grep -i "mgh-sdr" ; ls "C:\DEV\springBootTemplate"/*.html` 被守卫拦下,理由是「out-of-tree file search」——但目标路径就在 target 子树内。
- **复现**:mgh-sdr 运行域内(哨兵在)执行同命令(证据 `evidence/run3-stderr.log` 行 533)。
- **影响**:step 5「在仓根找报告」是提示词明确要求的动作,合法命令被拦 → 宿主每轮都要额外试错绕行(本轮最终完成,但烧轮次);所有「目录 + 通配符」形态的仓根列举大概率复现。
- **定位线索**:`core/scripts/block_adhoc_scripts.py` Bash 路径净网对 `*.html` glob token 的 resolve 失败 → 判为树外。对照:同 run 行 341 拦截「temp 目录写读回」是**真阳性**且 recipe 清晰——守卫主路径正常,这是 glob 形态的误伤。
- **建议方向**:净网对「target 前缀 + 通配」的 token 先按前缀判属;更釜底抽薪:step 5 提示词已让宿主用渲染器 stdout 的报告绝对路径(`report` 字段),把「仓根 glob 找报告」的指引删掉,命令自然不再出现。

### P6(低)dry-run 对不存在分支报 ok(绿灯冒烟 ≠ 真跑能过)

- **现象/复现**:3.3 dry-run 中探针分支 ok(带 baseline/prompt 全套产物);真跑中该分支实际失败。
- **影响**:冒烟对「分支清单有效性」零校验,绿色冒烟给出虚假信心;若清单批量打错分支名,dry-run 不会发现。
- **定位线索**:dry-run 复用 `_run_branch` 但不 spawn,现有闸门只覆盖上下文准备,分支存在性不在任何闸门内(与 P1 同根:缺预检)。
- **建议方向**:与 P1 同一修复点覆盖(预检放 step 0,真跑/dry-run 都过)。

### E 类:环境因素(非产品缺陷,如实记录)

- **E1** opencode 项目目录解析优先吃 `PWD` 环境变量(上游行为,P3 的放大器;opencode 1.18.31 实测)。
- **E2** 用户级 `~/.config/opencode/opencode.json` 默认模型 `deepseek/deepseek-v4-flash` 已不在 provider 目录(报错建议 `deepseek-flash`/`deepseek-v4-pro`)→ 任何会话必败。已用测试床项目级 model 覆盖绕开;**用户全局配置未动**,是否更新由维护者自行决定。

---

## 4. 观感与优化建议(非缺陷类)

- dry-run「哨兵保留」+ 真跑首分支「残哨复用」行为与设计预期完全一致,复用文案清楚(resume semantics)。
- 宿主 agent 曾把 `render_sdr_report.py --check` 带上多余的 `--repo`(报错即自纠,多一轮试错);`--check takes only <run-dir>` 报错足够清晰,属可接受摩擦。
- 分支转场处,若上一分支未产报告,launcher 可加显式警告行(当前只有 `reports[]` 里的字符串能看出)。
- 建议 launcher 增加透传参数:`--model`、`--print-logs`(多 provider 与故障诊断友好)。

## 5. 局限披露

- 探针只覆盖「分支不存在」形态,且因 P1 实际未按规格早败;「扇出中途失败」「限流冷却」「零进展熔断」本轮**零真实样本**,这些路径仍只有单测信心。
- 复核走「无存量基线 + 默认敏感目录模板」降级路径(设计拍板不补基线);基线在场时的行为未验证。
- 外部前端仓受控检索未触发(external=0),该面未获真机样本。
- 报告候选质量(是否真漏洞)不在本次范围;单元数/严重度分布仅作机制证据。
- run1/run2 的失败 run 目录保留在测试床 `.mgh-sdr/runs/` 未清理,可作 P3/P4 现场。

## 6. opencode 宿主特有形态结论

- **并行子会话数据库锁:未出现**。opencode 1.18.31、默认 wave=5、三分支 waves_run 8/5/4 全收敛,opencode 日志全程零 "database is locked"——已知前科在当前版本 + 本负载下未复现。
- **快败冷却 / 限流截断 / 零进展熔断:全部未触发**(cooldowns=0、rate_limited=false、partial=false),未获得真实触发样本。
- **串行性成立**:每分支恰好一个宿主会话,前一会话终止后才创建下一个;run1 期间每分支 spawn 后 ~3-4s 即死,launcher 不重试直接 FAILED、继续下一分支——「宿主立刻死」形态的失败隔离成立。

## 7. 证据索引

| 证据 | 落点 |
| --- | --- |
| run0 dry-run 全输出 | `evidence/run0-dryrun.log` |
| run1(环境双因失败) | `evidence/run1-stdout.log`、`evidence/run1-stderr.log` |
| run2(单因失败) | `evidence/run2-stdout.log`、`evidence/run2-stderr.log` |
| run3(有效轮全输出) | `evidence/run3-stdout.log`、`evidence/run3-stderr.log` |
| 三轮退出码 | `evidence/exits.txt`(1 / 1 / 0) |
| 分支清单 | `branch-list.txt` |
| 测试床产物 | `C:/DEV/springBootTemplate` 根 3 份 HTML + `.mgh-sdr/runs/<ts>-<branch>/`(含 `sdr_manifest.json`、`sdr_report_data.json`) |
| 夹具提交 | `sdr-mb-authz`=`685f91a`、`sdr-mb-sql-sensitive`=`cc3322f`(均只留本地) |
| 环境修复记录 | 测试床 `.opencode/opencode.json`(项目级 model 覆盖,E2) |
