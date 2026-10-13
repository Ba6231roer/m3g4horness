# findings — `/mgh-sdr --multi-branch` 真仓复测(2026-10-13)

> **受众**:维护者。
> **背景**:2026-10-12 首轮真仓验证(`archive/2026-10-12-test-mgh-sdr-multibranch-realrepo/`,产出 P1–P6)之后,上轮 findings 的修复已随 `a6dc963 fix-mgh-sdr-multibranch-findings`(0.1.59)落地(其任务 7.2「真仓回归待维护者执行」即本轮),另有 0.1.63–0.1.68 五批 sdr review 修复(diff 解析 / 报告渲染 / fanout 派发器 / 外部仓检索 / 文档-壳-契约对齐)。本轮 = 用同一测试床、同一分支夹具、同一失败探针复测,验收「修复批次的真机行为」并观察上次 findings 是否复现;**本轮同时是 `fix-mgh-sdr-multibranch-findings` change 任务 7.2 的欠账回归,已通过**。
> **测试床**:`C:/DEV/springBootTemplate`(master 仍 `5e8ac26`;分支夹具与上轮逐字节相同:`sdr-dryrun` 16f/+595−39、`sdr-mb-authz` 8f/+340、`sdr-mb-sql-sensitive` 8f/+244)。
> **被测**:`install.sh --opencode` 重装后的副本(与开发态 `core/scripts/` 五个关键脚本 `cmp` 逐字节一致)。
> **环境**:opencode 1.18.31、py 3.13.2;测试床项目级 model 覆盖 `deepseek/deepseek-flash` 仍在(上轮 E2 绕开,未动用户全局配置)。

---

## 0. TL;DR(人话)

1. **本轮全程无阻塞缺陷**。两轮真跑:run1 从测试床 cwd 起跑 4 分支串行(3 个真实分支各自完整收敛、报告与分支形状一一对应;探针分支被 launcher 预检**零 spawn 确定性早败**;退出码 1 + FAILED BRANCHES 汇总);run2 从**开发仓 cwd** 起跑单分支完整收敛(P3 行为级验收通过)。哨兵随分支生灭、工作树零改动、扇出 8/5/4(+run2 的 8)全收敛、零冷却零限流、零 traceback、零 "database is locked"。
2. **上次 P1–P6 全部不复现**:P1/P2/P4/P6 为 `a6dc963`(0.1.59)已修并通过本轮验收(分支预检 / 报告认领走渲染器 stdout / `--print-logs` 接线 / dry-run 同走预检),P5(守卫误拦)本轮零误拦且收获一次**真阳性**拦截(宿主试图列用户家目录,守卫正确阻断)。
3. **一个新问题(F1,可诊断性)**:launcher 给 opencode 加的 `--print-logs --log-level ERROR` 在 1.18.31 上对「扇出子会话内的 provider 错误」**行为级无效**——run1 sql-sensitive 扇出期间真实发生 2 次 ERROR 级 stream error(deepseek socket 中断),launcher stderr 零浮出;对照实验证明该 flag 组合本身零输出(DEBUG 打 32 行、ERROR 打 0 行),子会话错误只落 opencode 全局日志文件。失败自愈未受影响(该分支仍 4/4 收敛),但「失败可诊断」的承诺在目标失败形态上不成立。
4. 轻微摩擦 N1:opencode 宿主 Glob 工具对 `.opencode` 隐藏目录下的 `**/scripts/*.py` 返回 0 匹配,宿主多花 1–2 个定位轮次自行绕行——不影响正确性,属宿主工具行为。

---

## 1. 执行轮次与每分支关键指标

### 1.1 轮次总览

| 轮 | 启动 cwd | 时刻(本地) | 结果 |
| --- | --- | --- | --- |
| dry-run 冒烟 | 测试床 | 17:26:26→17:26:27(~2s) | 3 run 目录 + 探针 `FAILED pre-check`,退出 **1** + FAILED BRANCHES(1);哨兵按设计保留供真跑复用 |
| run1 真跑(4 分支) | 测试床 | 17:27:51→17:43:30(~15m40s) | 3 ok + 探针早败,退出 **1** + FAILED BRANCHES(1) |
| run2 真跑(单分支,验 P3) | **开发仓** | 17:50:37→17:56:12(~5m35s) | sdr-dryrun ok → `mgh-sdr-sdr-dryrun-20261013_175612.html`,退出 **0**;8 单元全收敛 |

### 1.2 真跑每分支指标

| # | 分支 | run 目录 | 耗时 | 单元(接口+standalone) | findings(高/中/低) | 扇出 | 报告 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | sdr-dryrun | `20261013_172751-sdr-dryrun` | ~6m09s | 8(6+2) | 24(7/13/4) | waves_run=8,p50=104s/max=145s | `mgh-sdr-sdr-dryrun-20261013_173400.html` |
| 2 | sdr-mb-nonexistent(探针) | **无(零产物)** | ~0s | — | — | **零 spawn** | **无(未认领他人报告)** |
| 3 | sdr-mb-authz | `20261013_173412-sdr-mb-authz` | ~4m19s | 5(3+2) | 26(10/9/7) | waves_run=5,p50=97s/max=150s | `mgh-sdr-sdr-mb-authz-20261013_173831.html` |
| 4 | sdr-mb-sql-sensitive | `20261013_173843-sdr-mb-sql-sensitive` | ~4m26s | 4(2+2) | 17(9/8/0) | waves_run=4,p50=108s/max=133s | `mgh-sdr-sdr-mb-sql-sensitive-20261013_174309.html` |

三分支 fanout 汇总行一致:`done=total`、`failed=0`、`pending=0`、`partial=false`、`stalled=false`、`stall_killed=[]`、`cooldowns=0`、`retried_failed=0`、`rate_limited=false`。

---

## 2. 断言逐项结论

| 断言 | 结论 | 证据 |
| --- | --- | --- |
| 串行性(逐分支起止、任一时刻至多一个宿主) | ✅ | 单 launcher 进程 4 段 `=== branch <名> ===`;`spawning opencode` 恰 3 次 |
| 探针确定性早败(零 spawn / 零产物 / 零 LLM) | ✅ | `FAILED pre-check (ref does not resolve) — zero spawn, zero artifacts`;runs/ 下无探针 run 目录 |
| 失败记录后继续 + 退出码 1 + stderr FAILED 汇总 | ✅ | 探针 FAILED 后两分支照常完整执行;`exit=1` + `FAILED BRANCHES (1)` |
| 每分支独立产物(HTML + data.json + manifest) | ✅ | 3 run 目录均含 `grouping.json`/`slices`/`drafts`/`markers`/`fanout_progress.sdr.json`/`sdr_manifest.json`/`sdr_report_data.json` |
| 报告对应性(内容可溯分支形状) | ✅ | authz:越权×25/横向×14/垂直×10/输入校验×9;sql-sensitive:SQL 注入×5/敏感信息×8/手机号×3/证件号×4/硬编码;dryrun:Controller×73/Service×49/Mapper×39/调用链×4 |
| 历史残留不误认 | ✅ | 3 份新报告 mtime 17:34:00/17:38:31/17:43:09 均落各自分支窗口内;上轮 5 份残留未被动过 |
| 哨兵生命周期(run 中在 / 结束移除) | ✅ | run 中 `.active` 在;末分支 step5 `rm` 后 `No such file` |
| 工作树不动 | ✅ | 全程检出 `sdr-dryrun`;`git status` 零 tracked 修改 |
| 降级披露(manifest + 报告) | ✅ | 3 manifest `sensitive_catalog_source: "default-template"`;报告 `boundaries`=6 条(LLM 候选声明/注解启发式/控制存在≠有效/外部仓快照/字节预算投影/默认模板回退),每报告附「发现是 LLM 生成的待复核候选,不是已确认漏洞」 |
| 守卫行为 | ✅ | 零误拦;1 次**真阳性**(宿主 `ls C:\Users\megah\.claude…` 树外列举被拦,消息含 recipe) |
| P3 行为级(异仓 cwd 启动,会话落测试床) | ✅ | run2 从开发仓 cwd 启动,宿主会话全程在测试床干活(diff_group/report 路径全测试床)、单分支完整收敛 exit 0——若 P3 未修,按上轮 E1 形态应在 ~10s 内全灭 |
| opencode 并行子会话稳定性 | ✅ | 全程零 "database is locked"、零 traceback |

---

## 3. 上轮 findings(P1–P6)复现状态

| 上轮问题 | 本轮状态 | 依据 |
| --- | --- | --- |
| P1(高)探针被宿主「干净停」洗成 ok | **已修复,不复现** | launcher spawn 前 `rev-parse --verify` 预检(`mgh_sdr_launch.py` 头注 BRANCH PRE-CHECK 段);真跑探针零 spawn 记 FAILED |
| P2(高)报告认领 = 仓根最新 `mgh-sdr-*.html` | **不复现** | 报告路径取渲染器 stdout(`report` 字段),`mgh-sdr-*.html` glob 已弃用(源码头注明示);探针未认领任何报告,三分支报告名与分支一一对应 |
| P3(高)spawn 不清 `PWD` → 会话落错项目 | **代码已修;本轮无直接行为样本** | `_spawn_host` 子进程 env 显式剥 `PWD`(源码头注 + L383);本轮按上轮 E1 教训仍从测试床 cwd 启动,未刻意从异仓 cwd 验证 |
| P4(中)失败不可诊断 | **已接线,但行为级无效 → 见新问题 F1** | flag 确实传给 opencode(`_spawn_host`);但对照实验证明 `--log-level ERROR` 在 1.18.31 上零输出,子会话错误不经此面浮出 |
| P5(中)守卫误拦仓根报告发现命令 | **不复现** | 全程零误拦;step5 已不要求仓根 glob 找报告(报告路径走 stdout),且守卫通配前缀判定已修 |
| P6(低)dry-run 对探针报 ok | **已修复,不复现** | dry-run 同走预检:探针 `FAILED pre-check` + dry-run 退出码 1 |

> 维护者此前认为「上次的 findings 应该都还没修」——实际 P1–P6 已随 `a6dc963 fix-mgh-sdr-multibranch-findings`(0.1.59)落地并通过本轮真机验收;P3 本轮补上了行为级样本。

---

## 4. 本轮新问题

### F1(中)`--print-logs --log-level ERROR` 对扇出子会话的 provider 错误行为级无效

- **现象**:run1 最后分支(sql-sensitive)扇出期间,opencode 全局日志记录了 2 条 ERROR 级 stream error(17:40:53/58,`sdr-review-fanout` 子会话,`AI_APICallError: Cannot connect to API: socket connection closed`,provider=deepseek/model=deepseek-flash,各带 session id);launcher 捕获的 stderr 里**零** `timestamp=` 日志行——失败原因对 launcher 消费者不可见。
- **对照实验**(本机 1.18.31,同环境):`echo "reply with exactly: ok" | opencode run --print-logs --log-level ERROR` → stdout/stderr **零**日志行;同命令换 `--log-level DEBUG` → stderr 打出 **32 行** `timestamp=…` 日志(全部 `run=` 本进程 id)。即 flag 机制本身活着,但 (a) ERROR 级在本进程无错时什么都不打,(b) 扇出子会话的日志属**其它 run id**,不经父 `run` 进程的 `--print-logs` 面输出。
- **复现**:任一分支扇出期间人为断网/限流致子会话 provider 错误 → launcher stderr 只有失败信封,无根因;唯一可见处 = `~/.local/share/opencode/log/opencode.log`。
- **影响**:P4 想治的「失败不可诊断」在其目标失败形态(扇出子会话 provider 错误)上依旧成立;故障定位仍要脱离 run 目录去翻用户级全局日志。本轮未扩大为单元失败纯因自愈(opencode 内部重试吸收了 2 次断连,该分支仍 4/4 done、0 failed)。
- **定位线索**:`mgh_sdr_launch.py` `_spawn_host` 的 cmd 构造(`["opencode","run","--print-logs","--log-level","ERROR"]`)——flag 写法与上游文档一致,失效点在 opencode 的日志路由(子会话 run 的日志只进全局文件)。
- **建议方向**:①失败 recipe / 报告缺口披露里直接指认全局日志文件绝对路径(`~/.local/share/opencode/log/opencode.log`,grep `level=ERROR` + 时间窗),成本最低;②或 fanout 单元失败时由 launcher 从该文件抽取对应时间窗 ERROR 行落 `<run-dir>/host.run.log`(改动集中在 launcher 收尾段);③上游行为(子会话日志路由)不属本仓可修面。

---

## 5. 本轮新观察(非缺陷)

- **N1(轻微,宿主工具行为)**:opencode 会话内 Glob `**/scripts/diff_group.py`、`**/scripts/fanout_runner.py` 均 0 匹配(Glob 不索引 `.opencode` 隐藏目录),宿主转经 `ls` 定位脚本,每分支多花 1–2 个定位轮次。mgh-sdr 不受正确性影响;若想省这轮次,编排提示词已含脚本绝对路径,宿主无视直接自寻是模型行为,不改产品。
- **N2(真阳性样本,正面)**:dryrun 分支宿主定位阶段尝试 `ls C:\Users\megah\.claude{,/commands,/plugins}`(树外)被守卫拦截,消息含越权列举 recipe;宿主随即回到 run 目录正常推进——读侧越树拦截的真机首样本(上轮仅 P5 误拦样本)。
- **N3(新行为确认)**:`sensitive_catalog.json` 已物化到每个 run 目录(含 dry-run 目录),manifest 记 `sensitive_catalog_source`——M6(敏感目录物化+路径透传)真机行为符合预期。
- **N4(正面,韧性样本)**:run1 扇出期间 2 次瞬时 provider 断连(见 F1)被 opencode 内部重试自愈,分支仍 4/4 done、0 failed——「瞬时网络抖动不丢单元」的首个真机样本。
- **N5(卫生,无害)**:`.opencode/mgh-core/scripts/` 下存在 `.pyc` 伴生文件(本仓某检查流程 py_compile 所留),对运行无影响。
- **N6(检查手段注记,非产物问题)**:用 `tail -c <N>` 按**字节**截 tail 会劈开 UTF-8 多字节字符、显示成 GBK 形乱码;落盘日志文件本身 UTF-8 完好(按行 grep 中文正常)。

---

## 6. 局限披露

- 探针仅覆盖「分支不存在」早败形态(本轮按设计早败成功);「单元级扇出失败」「快败冷却」「限流截断」「零进展熔断」「stall 杀树」仍**零真实样本**(各分支全收敛、零冷却)——本轮仅新增「瞬时 provider 断连自愈」样本(N4),单元失败形态依旧只有单测信心。
- 复核仍走「无存量基线 + 默认敏感目录模板」降级路径(与上轮同,设计拍板不补基线);基线在场、外部前端仓受控检索(external=0)两面未获真机样本。
- 报告候选质量(是否真漏洞)不在范围;单元数/严重度分布仅作机制证据。
- 被测副本为 opencode 端;claude/dsh 端未在本轮覆盖。
- F1 的对照实验仅覆盖「本进程无 ERROR」形态;「父 run 进程自身发生 ERROR 时 `--log-level ERROR` 是否浮出」未测(该形态上轮 P4 手工复现时 DEBUG 下可见,ERROR 下未验)。

## 7. 证据索引

| 证据 | 落点 |
| --- | --- |
| dry-run 全输出 | 本目录 `evidence/run0-dryrun.log` |
| run1(测试床 cwd,4 分支)stdout / stderr / 退出码 | 本目录 `evidence/run1-stdout.log` / `run1-stderr.log` / `run1-exit.txt`(`exit=1`) |
| run2(开发仓 cwd,单分支 P3 验证)stdout / stderr / 退出码 | 本目录 `evidence/run2-stdout.log` / `run2-stderr.log` / `run2-exit.txt`(`exit=0`) |
| F1 对照实验(ERROR 零行 / DEBUG 32 行) | 本机 `/tmp/oc-printlogs-test.{out,err}`、`/tmp/oc-debug-test.{out,err}`(临时,关键计数已录于 §4) |
| run1 扇出 2 次 stream error 原始记录 | `~/.local/share/opencode/log/opencode.log` 内 `2026-10-13T09:40:5x` 两条 `level=ERROR` |
| 分支清单 | 本目录 `branch-list.txt`(4 分支含探针)、`branch-list-p3.txt`(单分支) |
| 测试床产物 | `C:/DEV/springBootTemplate` 根 4 份新 HTML(`20261013_173400/173831/174309/175612`)+ `.mgh-sdr/runs/20261013_*` 四个真跑 run 目录 |
