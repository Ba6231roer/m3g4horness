# mgh-sdr 全流程深度代码评审明细(2026-10-13)

> **受众**:人类 · 仅研发仓(开发者资料,不随 install 分发;本文件是 [`mgh-sdr-review.md`](../mgh-sdr-review.md) 的逐条明细与修复工作清单)。
> **评审基线**:main 分支 HEAD `6e6ac63`,干净树,只评审未改码。
> 标注【已二次验证】的发现,均有独立验证 subagent 的复现实验背书(复现在仓库外临时目录完成、已清理)。

## 1. 评审方法与覆盖

- **评审面确定**:以任务给定清单为起点,与 opencode 命令壳、`core/contracts/sdr/`、`fanout_runner.py` 的 sdr tier 定义交叉核对,确认权威面 = 下表 24 文件。交叉核对结论:`diff_seed.py` 是 mgh-sast scope-resolver 组件(sdr 管线不引用),仍全量评审并单独标注归属。
- **流程**(open-code-review-delegate 模式,OCR 侧零 LLM):`ocr delegate rule` 分两批拿规则组(12 个 `.py` 命中 Python 规则组、12 个 md/json 命中 default 组)→ 6 批 general-purpose subagent 批内逐文件全读、按规则组 + 业务不变量核查 → 汇总去重与严重度校准 → critical/high 逐条派独立二次验证 subagent 复现。
- **辅助机器检查(全过)**:`tools/check_contracts.py`(459 flag / 17 壳)、`tools/check_distributed_purity.py`(0 违例)、`tools/check_distributed_prompt_budget.py`(17 壳全在限内;mgh-sdr dsh SKILL 4994/5000 mid_tokens 贴顶)。

| # | 文件 | 行数 | 批次 | 覆盖 |
| --- | --- | --- | --- | --- |
| 1 | `core/scripts/diff_group.py` | 2192 | B | reviewed |
| 2 | `core/scripts/sdr_tier.py` | 129 | B | reviewed |
| 3 | `core/scripts/sdr_context.py` | 940 | C | reviewed |
| 4 | `core/scripts/read_roots_config.py` | 275 | C | reviewed |
| 5 | `core/scripts/sensitive_catalog.py` | 418 | C | reviewed |
| 6 | `core/scripts/sensitive_catalog.json.example` | 191 | C | reviewed |
| 7 | `core/scripts/render_sdr_report.py` | 1382 | D | reviewed |
| 8 | `core/scripts/resume_sdr_state.py` | 633 | E | reviewed |
| 9 | `core/scripts/list_sdr_steps.py` | 210 | E | reviewed |
| 10 | `core/scripts/mgh_sdr_launch.py` | 553 | E | reviewed |
| 11 | `core/scripts/describe_artifact.py` | 205 | E | reviewed |
| 12 | `core/scripts/diff_seed.py`【sast 侧】 | 95 | E | reviewed |
| 13 | `core/scripts/fanout_runner.py` | 2792 | A | reviewed |
| 14 | `core/prompts/fragments/fanout/sdr-task.md` | 102 | A | reviewed |
| 15 | `core/contracts/sdr/pipeline.md` | 127 | F | reviewed |
| 16 | `core/contracts/sdr/resume-state.md` | 139 | F | reviewed |
| 17 | `core/contracts/fanout/runtime.md` | 73 | A+F | reviewed |
| 18 | `core/contracts/hooks/runtime-enforcement.md` | 320 | F | reviewed |
| 19 | `releases/opencode/command/mgh-sdr.md` | 233 | F | reviewed |
| 20 | `releases/claude-code/commands/mgh-sdr.md` | 233 | F | reviewed |
| 21 | `releases/dsh/skills/mgh-sdr/SKILL.md` | 250 | F | reviewed |
| 22 | `releases/opencode/agent/sdr-review-fanout.md` | 62 | F | reviewed |
| 23 | `releases/claude-code/agents/sdr-review-fanout.md` | 54 | F | reviewed |
| 24 | `releases/dsh/agents/sdr.md` | 55 | F | reviewed |

**覆盖率 100%(24/24,0 skipped)。**

## 2. 发现总表

| 编号 | 严重度 | 位置 | 一句话 |
| --- | --- | --- | --- |
| C1 | critical | diff_group.py:352,1722 | quotePath 引号路径整文件静默丢失 |
| C2 | critical | diff_group.py:1165-1171 | 超预算贪心拆分丢「开启 part 的成员」hunk |
| C3 | critical | render_sdr_report.py:227-256 | `javascript:` href 注入 |
| H1 | high | render_sdr_report.py:170 | severity 错型 TypeError 双路径崩 |
| H2 | high | render_sdr_report.py:476-481 | failed 单元致前端两列 zip 错位 |
| H3 | high | render_sdr_report.py:552-556 | `<!--`+`<script` 双转义吞页 JS,--check 盲 |
| H4 | high | diff_group.py:244-247 | NTFS 非法字符未清,Windows 写盘崩 |
| H5 | high | fanout_runner.py:1371-1377 | wmic 已移除,kill-stale 全盲且销毁证据 |
| H6 | high | sdr_context.py:307-308 | 同名外部仓结论互相覆盖、证据错配 |
| M1 | medium | fanout_runner.py:2684-2689,2191 | 退出摘要 failed 双计 |
| M2 | medium | fanout_runner.py:2388-2394,2630-2638 | 心跳 idle 读死 sink |
| M3 | medium | fanout_runner.py:1883-1895 | kill-stale 对 sdr 扫错目录 |
| M4 | medium | fanout_runner.py:2478-2500 | 限流截断竞态,回归测试确定性红【已二次验证】 |
| M5 | medium | fanout_runner.py:1628-1633 | kill-stale 仓内配方不可运行 |
| M6 | medium | sdr-task.md:56-58 | 敏感目录下发机制主路径不可达且无披露 |
| M7 | medium | diff_group.py:1211-1218 | A 文件 hunk 归属按符号数错位 |
| M8 | medium | sdr_context.py:471-476 | skip_dirs 按绝对组件误判,路由计数假零 |
| M9 | medium | sdr_context.py:710-711 | --check 基线尺寸硬编码 4× 预算误报 |
| M10 | medium | sdr_context.py:446-447 | 外部仓最多 6 遍未剪枝全树扫描 |
| M11 | medium | render_sdr_report.py:396-401 | 前端两列子串 join 计数错配 |
| M12 | medium | describe_artifact.py:64-69 | --field 索引守卫与 int() 错配即崩 |
| M13 | medium | describe_artifact.py:95-105 | 全族唯一缺 utf-8 reconfigure |
| M14 | medium | diff_seed.py:47-66【sast 侧】 | quotepath 未关,非 ASCII 漏 seed |
| M15 | medium | releases/dsh/skills/mgh-sdr/SKILL.md:17-19 | dsh 面推荐不支持的宿主 |
| M16 | medium | opencode 壳:131-134;dsh SKILL:148-151 | 超时不变式段三面措辞漂移 |
| M17 | medium | opencode agent:29-30 | `{{ }}` 字面占位符永不替换,三面漂移 |
| M18 | medium | core/contracts/sdr/pipeline.md:108-111 | --dimensions「透传」与壳披露矛盾 |
| M19 | medium | core/contracts/sdr/pipeline.md:48,69 | 字段清单欠载 |
| M20 | medium | core/contracts/hooks/runtime-enforcement.md:3-14,81 | 漏 sdr 哨兵生命周期 + 过时表述 |
| L1–L12 | low | 见第 6 节 | 有明确价值者 12 条 |

## 3. Critical 明细(C1–C3,均【已二次验证】)

### C1 — quotePath 引号路径整文件静默丢失

- **位置**:`core/scripts/diff_group.py:352`(`_FILE_HDR_RX = re.compile(r'^diff --git a/(.+?) b/(.+)$')`);`:1722`(`_git(repo, "diff", "--no-color", f"{base}..{branch}")`,无 quotePath 配置)。
- **问题**:git 默认 `core.quotePath=true`,路径含非 ASCII(中文文件名——目标环境正是中文企业仓)时 diff 头输出带引号的 C 风格八进制转义形 `"a/src/\345\246\207..."`;正则要求字面 ` a/`,遇 ` "a/` 不匹配,解析循环对该行落到 `i += 1` 静默跳过,后续 `---`/`+++`/`@@` 同样无锚点丢弃。
- **影响**:该文件不进 `all_diffs`、不进 units、**也不进 excluded 计数**;若它是唯一变更文件,stdout 报 `empty:true / total:0 / excluded:0`,exit 0——变更被完整吞掉且与真零 diff 不可区分,直接违反「任何 diff 文件都不得静默丢失」核心不变量。
- **复现**:临时 git 仓(git 2.54.0.windows.1)+ 中文名 `.java` 单文件 diff → `parse_diff` 返回 0 文件;同输出加 `-c core.quotePath=false` 后 1 文件 1 hunk;整脚本端到端 `exit 0 + empty:true`。
- **修复**:git diff 调用加 `-c core.quotePath=false`(`errors="replace"` 解码已兜底非 UTF-8 字节);补中文路径回归测试。**同一修法适用于 M14(diff_seed.py,sast 侧同族问题)。**

### C2 — 超预算贪心拆分丢「开启 part 的成员」

- **位置**:`core/scripts/diff_group.py:1165-1171`(`_split_interface_budget` 贪心装包);对照正确实现:`:1145-1164`(单成员超上限分支在 `_new_part` 后手动 `acc.files.append(fd)`)。
- **问题**:`acc = _new_part(host, c["route"], c["ann"])` 只携带 route/ann、files 为空,`_fill(acc, c)` 被放在 `else:` 分支——仅当 acc 已存在且装得下才执行。于是**每个「开启新 part 的成员」的 files/hunk 从不进入任何 part**;且步骤 4 的 `_absorb` 已把这些 hunk 写入 claimed,步骤 5 残差兜底(按 claimed 跳过)不会再接住——双重绕过,彻底静默。附带症状:part 挂着成员 a 的路由标签却装着成员 b 的文件。
- **影响**:触发条件 = codegraph 模式 + 多成员 host(共享链合并/上游锚定)+ 合并切片超 `--max-interface-bytes`(默认 256KB)而各成员单独不超——数百万行大仓的大 controller 正是目标场景。覆盖丢失,hunk locator 不在任何单元。
- **复现**:①直接调用:双成员各 1880B、合并 2648B、cap=2264 → 1 个 part,成员 a 的 `('src/SController.java', 0)` 不在任何 part;②端到端(真实 git 仓 + codegraph stub,双路由共享 service):cap 收紧复跑后 locator 集合缺失一个 hunk。
- **测试盲区**:`tests/test_diff_group.py::test_interface_budget_splits_parts` 的 fixture 两个成员单独就超 cap(各 ~2600B > 2048),都走了「单成员超上限」分支,贪心分支零覆盖。
- **修复**:去掉 `else`,在 `_new_part` 后无条件 `_fill(acc, c)`;补「各成员单独 ≤ cap、合并 > cap」的 hunk locator 无损回归测试。

### C3 — `javascript:` href 注入

- **位置**:`core/scripts/render_sdr_report.py:227-256`(`_href_of` 相对路径分支只拦 `..`/空格/圆括号,不查冒号);消费点 `:696-701`(页面 JS `setAttribute("href", href)`)、`:1084`(`_href_of(f["file"], ...)`,file 字段来自 LLM 草稿)。
- **问题**:findings 的 file/chain 字段是 LLM 输出、引述受审仓库与外部前端仓源码(文件头 docstring 自认注入面)。`javascript:location=\`https:/evil/${...}\``(无空格无圆括号)原样通过全部检查;normpath 把 `//` 折叠为 `/` 但 WHATWG URL 解析对特殊 scheme 容忍单斜杠,payload 存活。
- **影响**:复核人在 file:// 报告页点击「位置」链接即于页面 origin 执行脚本(bookmarklet 语义)。对本产品(评审可能含攻击者影响的分支代码,提示注入是现实威胁面)是报告主交付物的注入缺陷。`C:foo` 盘符相对路径同样漏网成坏链接。
- **复现**:仓库外 import 实测该字符串经 `_href_of` 返回原样非 None;端到端渲染后 payload 原样进入 `sdr_report_data.json` 的 `findings[0].loc.href`。现有 `HrefTest` 无冒号/scheme 用例。
- **修复**:相对分支(及最终 rel)首段 `rel.split('/')[0]` 含 `:` 即 return None 降级纯文本。

## 4. High 明细(H1–H6,均【已二次验证】)

### H1 — severity 错型 TypeError 双路径崩

- **位置**:`core/scripts/render_sdr_report.py:170`(`f.get("severity") in _SEVERITY_ORDER`,severity 为 list/dict 时不可哈希);调用链 `:1245`(`_run`)与 `:1285`(`_check`)均裸调 `_merge_findings`。
- **影响**:草稿含 `"severity": ["high"]`(LLM 完全可信会产出的形态)→ 渲染与 `--check` 双路径裸 traceback、退出码 1(非契约的 2),打破「draft 质量永不使渲染器崩溃、坏单元走 failed_units」的设计意图。hashable 错值(如 `"High"`/`5`)已安全降级 medium,唯独非字符串类型漏防。
- **复现**:最小 run-dir + `"severity": []` 草稿,渲染与 `--check` 均在 :170 崩溃,退出码 1。
- **修复**:`sev = f.get("severity"); "severity": sev if isinstance(sev, str) and sev in _SEVERITY_ORDER else "medium"`。

### H2 — failed 单元致前端两列 zip 错位

- **位置**:`core/scripts/render_sdr_report.py:439-441`(第一趟建 rows 跳过 `status=="failed"`)+ `:477`(第二趟 `zip(rows, _sorted_units(g_units))` 对全量单元 zip,rows 短、zip 截断)。
- **影响**:有 failed 单元时从首处起整体错一位:配到 failed 的 row 残留占位「—」(`_frontend_pair` 永不返回「—」= 未填痕迹),其后的 row 拿到**前一个**单元的前端值——错误数据同步写进 manifest/data/HTML;`--check` 两边同错检不出。降级运行(最需诚实呈现的场景)下数据损坏。
- **复现**:1 failed + 2 ok 单元、route_hits 命中其中一条 ok 路由 → 有命中的单元显示「—」、无命中的显示「是/2 处」。三个相关测试恰好都缺 failed+external_repos 组合。
- **修复**:前端两列并入第一趟循环(route 与 external 届时已在手),或 `zip(rows, [u for u in _sorted_units(g_units) if u.get("status") != "failed"])`;补组合回归用例。

### H3 — `<!--`+`<script` 双转义吞页 JS

- **位置**:`core/scripts/render_sdr_report.py:552-556`(`_json_embed` 仅 `.replace("</", "<\\/")`);模板 `:673-674`(数据块真终止符同行,紧随注释 `<!-- section: page js ... -->` 提供 `-->`)。
- **问题**:HTML 规范 script-data-double-escaped 状态:数据内先 `<!--` 再 `<script` 后,真正的 `</script>` 被忽略,解析器向后扫 `-->` 才退出 → 页面自身全部渲染 JS 被当作 JSON 数据块文本吞掉,报告六章节空白(结构破坏 DoS,非 XSS)。findings 引述外部前端仓 .vue/.html 片段天然可能携带该序列。
- **盲区**:`--check` 用 regex `(.*?)</script>` 取块,恰好停在浏览器忽略的那个 `</script>` 上,嵌入 JSON 与 data 文件逐字节等价——实测对 hostile run-dir `--check` exit 0 通过。
- **复现**:真渲染(draft risk 含 `<!--<script>`)+ WHATWG 规范状态机推演:数据块元素直到页 JS 自己的 `</script>`(:440)才闭合。
- **修复**:`_json_embed` 追加 `.replace("<!--", "<\\u0021--")`(parse-identical,一行)。

### H4 — NTFS 非法字符未清,Windows 写盘崩

- **位置**:`core/scripts/diff_group.py:244-247`(`_safe_name` 仅替换 `/ \ :`);消费点 `:1812`(`slices_dir / f"{u.unit_id}.slice.md"`)、`:1820`(`spath.write_text`,无 try 包裹);route 可达性:`:219-226` 注解正则允许 `*` 进入 route 值(`@GetMapping("/**")` 是 catch-all 控制器常见写法)。
- **影响**:unit_id 含 `*` → Windows 写盘抛 `OSError [Errno 22]` → **traceback + exit 1 + stdout 零字节**(破坏退出码契约),且已写一半 slice 而 grouping.json 未写。Linux 上这些是合法文件名,故为 Windows 专属(本工具族以 Windows/NTFS 为一等目标)。
- **复现**:`Path("x*y.slice.md").write_text` 逐字符实测(`* ? < > |`)全抛;端到端 `@GetMapping("/**")` 崩于 `ZZController___api_**.slice.md`。
- **修复**:替换集扩为 `[/:\\*?<>|"]`;可在 `--check` 加 unit_id 合法性断言。

### H5 — wmic 已移除,kill-stale 全盲且销毁证据

- **位置**:`core/scripts/fanout_runner.py:1371-1377`(`_pid_cmdline` Windows 分支 `wmic process where ... get commandline`;`FileNotFoundError` 被 `except OSError` 静默吞、返回 `''`);判定链 `:1449-1485`(两种 kill 形态都要求 cmdline 匹配);`:1544-1549`(非 dry-run 零 targets 仍无条件 unlink liveness 文件)。
- **影响**:Windows 11 24H2+ 已移除 wmic(本机 build 26200 实测不存在)→ cmdline 恒空 → `--kill-stale` **永远零 targets、孤儿进程 100% 存活、证据文件被销毁、退出码 0 假成功**——「看起来成功」方向的静默失效,孤儿宿主 CLI 继续烧 token 且后续无从发现。影响面:仅 `--kill-stale` 恢复路径;运行期 stall/timeout 树杀(进程内记账)不受影响。
- **复现**:端到端伪造真实孤儿进程(活进程 cmdline 含 `fanout_runner.py` / `claude`):非 dry-run 报 `killed: []` 但 removed 两个 liveness 文件,tasklist 确认孤儿存活;对照实验:仅把 `_pid_cmdline` 换成 PowerShell `Get-CimInstance Win32_Process -Filter 'ProcessId=<pid>'`,同一批结构立即正确分类出 runner+child 两个目标(每次约 731ms,恢复路径可接受,powershell.exe 5.1 是 Win11 核心组件,零 pip 依赖不破)。
- **修复**:wmic 先试 + PowerShell CIM 回退;或「PID 活着但 cmdline 探测不可用」时 fail-loud(stderr 披露 + 不删 liveness 文件),绝不静默降级。微小更正:发现原文称报 `none:true`——有 pid 文件被删时 `none` 实为 false(`removed` 非空),核心主张不变。

### H6 — 同名外部仓结论互相覆盖、证据错配

- **位置**:`core/scripts/sdr_context.py:307-308`(`_external_slug = _safe_slug(Path(decl["path"]).name)`,仅 basename);`:418-420`(out_dir = run_dir/external/<slug>,mkdir `exist_ok=True` 容忍冲突);`:501`(hits.md 全量覆盖写)、`:509`(两条 record 的 summary_path 指向同一文件)、`:516-517`(summary.json 同);声明去重键 `:296` 是字面路径串不 resolve。
- **影响**:两个已批准外部仓 basename 同名(如 `projA/front` 与 `projB/front`)→ 共享同一 out_dir,后检索者覆盖前者:**前仓的人读证据(配置命中 file:line、出现位置清单)不可恢复丢失,record A 的 summary_path 指向 B 仓内容**——下游渲染/复核若信之即采信错配证据;`--check` 仅存在性检查,exit 0 放行。附加:同一仓以含 `..` 的两种写法声明也撞同一 slug(双倍检索 + 同样错配)。
- **边界澄清**:route_hits 计数在 record 内物化未丢;损害集中在 hits.md/summary.json 证据链。
- **复现**:端到端(两个外部仓各含不同标记的 buttonAuth.properties)→ external/ 下只有一个 `front` 目录,hits.md 只含 projB 内容,record[0] 的 summary_path 所指文件内容是 projB 的;`--check` exit 0。测试无同名冲突用例。
- **修复**:out_dir 键改为消歧形式(resolved 全路径短哈希后缀,或撞名追加序号);声明去重键改 resolved 字符串。

## 5. Medium 明细(M1–M20)

> 本节未做二次验证,均为单批 agent 的代码证据 + 局部实验;修复时以实际代码为准。M4 除外(已独立复现)。

### M1 — 退出摘要 failed 双计(fanout_runner.py:2684-2689;同形 :2191)

`failed_now = int(snap.get("failed", failed0)) + len(failed_written)` 把同一批 marker 计两次:枚举器按磁盘 marker 计数(re-list 已含本 run 写入的 `.failed`),`failed_written` 记的正是这批 → 真实 1 个失败报 2;全败 10 单元 run 报 `failed=20 > total=10`。`--retry-failed` 决策与报告缺口披露都消费该字段。测试全走 `--pending-file`(host=test,快照冻结)未覆盖。修:`max(int(snap.get("failed", failed0)), failed0 + len(failed_written))`;`_sidecar_payload` 同改。

### M2 — 心跳 idle 读死 sink(fanout_runner.py:2388-2394;消费 :2630-2638)

`_hb_inflight` 的 `idle` 读的是 `_dispatch` 创建的 out/err sink,但**没有任何 reader 线程更新它们**——`_run_unit` 自建内部 sink(:1056-1057),签名不接收 dispatch 侧 sink。idle 恒等于距派发时刻的流逝时间:持续正常输出的健康单元也显示 `idle=1500s stall_window=900s`(看似将判死,实则不会),与 docstring「seconds since its child's last output」直接矛盾。git 考古确认自引入起未接线(未完成特性)。修:把 dispatch 侧 sink 传入 `_run_unit`,或暴露活跃 sink 引用。

### M3 — kill-stale 扫错目录(fanout_runner.py:1883-1895)

kill-stale 分支 `init_dirs = [Path(plan_flag).parent]` 假设 plan 参数是文件(scout/t1/t3 成立);sdr 的 plan 参数是 `--repo`(目录)→ 扫**仓库父目录**;t2/scout-merge 的 plan 参数是 init_dir → 扫目标仓根;而 liveness 实际住在 run 目录(dispatch 侧 plan_path 再锚定在 :1967-1980,位于 kill-stale 分支之后未复用)。双侧对照实验证实:liveness 放 run 目录时规范 sdr 调用形报 `none:true`。修:把 plan_path 再锚定逻辑挪到 kill-stale 分支之前,kill-stale 扫 `plan_path.parent`。

### M4 — 限流截断竞态,回归测试确定性红【已二次验证】(fanout_runner.py:2478-2500;对侧 :2443-2455)

截断旗标(worker 线程在 storm_lock 下置 `rate_limited`)与主线程 backfill(`_fill` 先查再 pop+submit)之间无同步:第一个 crash future 收割后、第 wave 个记账落地前,主线程可向已限流网关补派新单元。**本机(Python 3.14.6/Win11 26200)实跑 `TestRateLimitStorm::test_all_rate_limit_storm_truncates_fast` 连跑 5/5 失败(`AssertionError: 3 != 2`,断言在 tests/test_fanout_runner.py:2667),每次约 30s(补派单元卡在已 reset 的 Barrier 上等 30s 超时)。clean HEAD 回归套件确定性红,CI 必挂。**生产影响有界(截断落地前最多多派一个单元,marker 不损)。修:`_next_unit` pop 后、`pool.submit` 前再查一次 `_rate_limited()`,或派发决策纳入 storm_lock;若接受有界过冲为语义,则放宽测试断言并注明——当前「测试红 + 文档称立即停止」的状态不可留。

### M5 — kill-stale 仓内配方不可运行(fanout_runner.py:1628-1633)

`--checkpoints/--inputs-dir` 无条件 `required=True`,而 kill-stale 恢复模式的功能性输入只是扫描提示:仓内全部 sanctioned 配方(resume_sdr_state.py 的 note、init stage fragments、三面 mgh-init 壳)按原样调用都会 argparse 退出 2,根本到不了 kill-stale 分支(:1881 docstring 已承认此疣)。恢复路径恰是最坏状态下的调用场景,配方首跑必失败。修:两 flag 改可选(默认 None),kill-stale 分支容忍缺失;或同步修全部配方文本。

### M6 — 敏感目录下发机制主路径不可达且无披露(sdr-task.md:56-58)

sensitive-data 维度声明「目录对象随编排器任务消息下发」——但主路径任务消息只由 fanout_runner 从固定模板 + 固定占位符集构造(占位符集无 catalog 槽),目录无搭载通道;launcher `_build_prompt`(mgh_sdr_launch.py:287-288)声称「逐字透传」并内嵌目录,但截断 4000 字符(「逐字」在 launcher 层已不成立)且其 step 3 只给规范 fanout_runner 调用、无下发机制;agent 定义重复同一预期。净效果:**主路径下 sensitive-data 维度永远拿不到项目敏感目录**(目录落盘在 context.json,但刚性三元组禁止读它),该维度只能依赖基线投影 + 通用掩码预期,**无任何披露**(与 `--dimensions` 的明示披露形成对比)。对银行项目目标用户是六维之一的实质弱化。修(二选一):(a) 模板加 `{{sensitive_catalog}}` 占位符(sdr_context 物化目录文件后经 run 目录喂给占位符集);(b) 改为指认物化路径——sdr_context 把目录单独落 `<run-dir>/sensitive_catalog.json`,模板三元组加该只读路径。任一方向同步修 launcher 措辞与 agent 定义。

### M7 — A 文件 hunk 归属按符号数错位(diff_group.py:1211-1218)

A 文件(新增)`owner = list(range(len(syms)))` 产出**每符号**列表,消费方 :1229 把它当**每 hunk** 映射(j 为 hunk 下标)→ hunk j 武断归给符号 j;最常见场景(新增 controller 整文件 1 hunk)所有方法里只有第 1 个符号拿到 hunk,其余路由方法不进 changed/anchors,**路由分簇对新增控制器坍缩为单单元**,与注释宣称意图相反。覆盖由残差/class-level 兜底维持(不丢,实证 :1457-1459),但新增 controller 恰是安全评审最关键产物,分簇质量退化。修:A 文件时每 hunk 归属全部符号(`[list(range(len(syms)))] * len(fd.hunks)` 语义),写入时过滤越界下标。

### M8 — skip_dirs 按绝对组件误判(sdr_context.py:471-476)

`any(part in skip_dirs for part in p.parts)` 判的是**绝对路径全组件**:外部仓祖先目录名叫 build/dist(如 `D:\ci\build\front`)时整个仓被误跳过 → 每条路由出现计数恒 0,**hits.md 与 route_hits 静默给假零值、无任何披露**——「前端是否引用新路由」信号被静默否定。相邻的 `rel = str(p.relative_to(ext))` 已算出相对路径却未用于判定。修:判定改用 `p.relative_to(ext).parts`。

### M9 — --check 基线尺寸硬编码 4× 预算误报(sdr_context.py:710-711)

`--check` 的 baseline 尺寸断言硬编码 `DEFAULT_BASELINE_BUDGET*4`(131072B),无视运行时实际 `--baseline-budget-bytes`:合法调大预算(如 400000 → 产出 162KB、truncated=false)被 exit 2「unexpectedly huge」否决完全合法的 run——边界校验对合法状态误报,编排器会中止有效流水线(实验证实)。修:生效预算写进 context.json(新增字段向后兼容,旧文件按默认值),`--check` 按记录值判定;或删除该启发式(存在性校验已够,截断腐败由 JSON parse 失败兜住)。

### M10 — 外部仓最多 6 遍未剪枝全树扫描(sdr_context.py:446-447)

每个声明配置文件名各一次 `ext.rglob(root_name)`(≤5 次,这路**完全没有** skip_dirs 过滤,连 .git 与 node_modules 都全量下钻),再加一次 `ext.rglob("*")` 做出现计数(过滤在产出之后)。真实前端仓每仓多付出秒到分钟级 I/O。修:单遍 os.walk,dirs 原位删除 skip_dirs 实现真剪枝,一趟同时收集配置命中与文本文件,一次读双用。**与 H6 的 out_dir 重构同批做。**

### M11 — 前端两列子串 join(render_sdr_report.py:396-401)

`_frontend_pair` 用 `rt in main` 子串包含匹配,而 route_hits 按精确路由串计量:REST 嵌套路由(`/api/user` 与 `/api/user/list`)时短路由的计数算到长路由头上——**把无前端使用的接口标成有**(方向性错误),误导复核人。修:改 `rt == main`(或分号段集合内精确命中)。

### M12 — --field 索引守卫与 int() 错配(describe_artifact.py:64-69)

`seg.lstrip("-").isdigit()` 接受 `int()` 拒收的形态:`--field a.--5`(lstrip 后 `5` 过守卫,`int('--5')` 抛 ValueError)与 `--field a.²`(`'²'.isdigit()` 为 True,`int('²')` 抛 ValueError)均未捕获 ValueError traceback 崩——agent 传畸形 field 路径是本工具的目标使用面。修:守卫改 `try: idx = int(seg) except ValueError: return None, False`。

### M13 — 全族唯一缺 utf-8 reconfigure(describe_artifact.py:95-105)

core/scripts 全族 28 个产 JSON 脚本在 parse_args 前都有 `stream.reconfigure(encoding='utf-8', errors='replace')` 块(防 cp936/gbk 控制台),本脚本是唯一例外;它以 `ensure_ascii=False` dump 工件值(中文发现、特殊符号),在 cp936 控制台/管道 print 抛 UnicodeEncodeError 崩——维护者本机即中文 Windows,真实崩溃路径。修:补与兄弟脚本相同的 reconfigure 块。

### M14 — quotepath 未关【sast 侧】(diff_seed.py:47-66)

与 C1 同族:`git diff --name-status` 对非 ASCII 路径输出引号转义形,解析出的 token 带引号尾 → suffix 变 `.java"` ∉ SOURCE_EXT → **该文件静默从 seed[] 消失**,安全扫描的静默覆盖缺口且零披露;中文 Windows 仓的非 ASCII 源文件路径是现实场景。修:`-c core.quotepath=false`(或 `--name-status -z` + NUL 分割)。注:本文件属 mgh-sast scope-resolver,修复应记入 sast 面。

### M15 — dsh 面推荐不支持的宿主(releases/dsh/skills/mgh-sdr/SKILL.md:17-19)

「零打断优选入口」把 launcher「首选」建议逐字镜像自 opencode 面,但 `mgh_sdr_launch.py` 的 `--host` choices 仅 `[opencode|claude]`(argparse :468),探测序 opencode>claude、全缺 exit 2——**launcher 不支持 dsh 作为 spawn 宿主**。dsh-only 部署按「首选」走会在 host gate 处 fail-loud 早退;有共存宿主的机器上跑的是别的宿主而非 dsh。修:dsh 面补一句披露(launcher 仅 spawn opencode/claude,dsh-only 部署直接走壳内路径),或给 launcher 增加 dsh host。

### M16 — 超时不变式段三面措辞漂移(opencode 壳 :131-134;dsh SKILL :148-151)

opencode/dsh 两面写作压缩括号注形,不复述「call < budget×0.8」层;claude 面为完整规范形(`--call-timeout-s` MUST 显式传且 < budget×0.8,`--stall-timeout-s`(≥60) MUST < `--call-timeout-s`),与 fanout_runner 实现(:1917-1945,三层强制)一致。语义两版等价但压缩形括号绑定有歧义、**非白名单五类文本漂移**,弱模型可能漏 budget 层约束。修:opencode/dsh 对齐 claude 规范形(宿主具体数值留在调用占位符)。

### M17 — `{{ }}` 字面占位符永不替换 + 三面漂移(releases/opencode/agent/sdr-review-fanout.md:29-30)

opencode agent 判定纪律首条写 `the baseline projection ({{ baseline path from the task message }})`——agent 定义是静态文件,dispatcher 只对任务模板做占位符替换,**该 `{{ }}` 运行时永不替换、以字面 mustache 形态进入提示词**;claude 面(:21-22)为精确散文形,dsh 面(:22-23)第三种措辞——同一指令三种写法,无一处落入白名单五类。修:三面统一为 claude 精确形,本面删 `{{ }}` 形态。

### M18 — --dimensions「透传」与壳披露矛盾(core/contracts/sdr/pipeline.md:108-111)

契约称「--dimensions 可收窄,闭集键外按自由文本扩展检查项**透传**」,与三面壳的诚实披露(「收窄当前不下发:不进入评审单元的任务消息」)直接矛盾:sdr-task.md 无 dimensions 占位符,fanout_runner 占位符集亦无。现状 = 仅闭集校验 + manifest 记录,评审恒全 6 维。契约读者会误以为收窄已生效。修:改写为与壳披露一致;真正接线后恢复现文。

### M19 — 契约字段清单欠载(core/contracts/sdr/pipeline.md:48、:69、:90)

① :48 pending[] 字段清单漏 `baseline_path/external_dir`(壳刚性三元组明确列二者;diff_group.py:1842-1843 实际产出)及 slimmed/chain;② :69 sdr_context 默认 stdout 行漏 `base/branch/pending_approval[]/baseline_truncated_bytes`(壳明言编排器要消费),external_repos[] item shape 漏 slug/diff_files/route_hits/bytes/truncated(route_hits 是渲染三态 join 的数据源);③ :90 manifest counts 漏 findings/excluded_files。修:补全三处清单。

### M20 — hooks 契约漏 sdr 哨兵生命周期 + 过时表述(core/contracts/hooks/runtime-enforcement.md:3-14、:81、:123-145)

① Producer/Lifecycle 段完全遗漏 sdr 域哨兵生命周期:实现事实是 resume_sdr_state `--arm-sentinel` 预武装(最小形)→ sdr_context `_write_run_state` co-write(含实际检索根)→ `--rearm-sentinel` 确定性重写 → `--check` 中途存在性校验;契约却把 sdr 归入「other domains … orchestrator shell step 0 (Bash)」——只读本契约会得出「sdr 哨兵由编排器 printf 写入」的**相反结论**(:57 target 来源清单也未列 sdr_context stdout repo);② :81「确定性写入器是 follow-up change and not required」已过时——`read_roots_config.py --add` 与 `sdr_context.py --approve-external` 已落地且共享同一原子写实现。修:补 sdr 生命周期段落;Authoring 行改为两个确定性写入器。

## 6. Low 明细(保留有明确价值者)

| 编号 | 位置 | 问题与修法 |
| --- | --- | --- |
| L1 | mgh_sdr_launch.py:431-434 | 空 `try/finally` 死代码:异常路径(含 Ctrl-C)跳过哨兵移除,残留 `.mgh-sdr/.active` 使守卫常驻后续开发会话;「用户放弃 run」时无任何工具提示哨兵已陈旧。修:删 try 外壳,或真正做成 finally 清理并在注释写明 Ctrl-C 保留是有意行为 |
| L2 | mgh_sdr_launch.py:260-264 | sdr_context stdout 消费(json.loads/下标访问)全无防护:sibling 输出错形 → launcher traceback 崩溃而非 per-branch FAILED,且 sdr_context 已 co-write 哨兵、崩溃留下残留哨兵。修:包 try/except (ValueError/KeyError/TypeError) 转 per-branch FAILED |
| L3 | mgh_sdr_launch.py:288 | `_build_prompt` 对敏感目录对象 `[:4000]` 静默截断无标记,大项目 catalog 被切在 JSON 结构中间。修:截断时追加显式标记并指路 context.json(与 M6 同族,修 M6 时一并处理) |
| L4 | sdr_context.py:425-427 | 「同名分支缺失,回退默认分支」实际取的是外部仓**当前检出分支**(`rev-parse --abbrev-ref HEAD`),不是默认分支——结论文件错误归因。修:改文案为「回退当前检出分支」,或探测 origin/HEAD 拿真默认分支 |
| L5 | sdr_context.py:104-105 | `_EXT_PATH_RX` 把 URL 当盘符路径提取,external_skipped 出现伪造的 `not-found: s://github.com/...` 噪声条目。修:候选提取处排除含 `://` 的 token(守卫的路径 regex 已有此先例) |
| L6 | diff_group.py:2128-2163 | `--limit` 负值不校验(`max(0, req_limit)` 静默空页,与 0 不可区分);`--check` 与 `--base/--branch/--offset/--limit/--summary/--include-excluded` 同传时被静默忽略。修:负值 exit 2;--check 互斥集扩大或在 stderr 提示 |
| L7 | render_sdr_report.py:684-688 | 页面 JS `escapeHtml` 是死代码且上方注释失实(实际全程 textContent/setAttribute,无字符串级拼装)——失实注释反而削弱对真实安全性质的表述。修:删除函数,注释改为如实陈述 |
| L8 | render_sdr_report.py:1333-1336 | `--check` 的「manifest 须在 run 目录」守卫恒假(构造方式决定 str 必然包含该文件名),零效检查给人已设防假象。修:删除或改为校验 manifest['report'] 落在 repo 根 |
| L9 | agent 定义三面(sdr-review-fanout.md:33-35 等) | persona 含「task message 的检查面 note 会收窄维度」句,描述永不触发的机制(与 `--dimensions` 不下发现状矛盾,三面同病)。修:删句或标注「机制接线后生效」(与 M18 同批) |
| L10 | releases/opencode/command/mgh-sdr.md:25-36 | 参数表声明的 `--max-standalone-bytes/--max-interface-bytes/--include-excluded` 在 step 2 调用行与示例块均无转发槽位(编排器只能靠推断)。修:加括号槽位,三面同步 |
| L11 | read_roots_config.py:154-166 | `mkdir(parents=True)` 在 try 之外:`.mgh` 已作为文件存在时裸 traceback(方向无害、零写入,但违反 stderr=人类诊断契约;异常会穿透 --approve-external 路径)。修:挪进现有 try 块 |
| L12 | fanout_runner.py:2235-2236 | liveness 写失败(契约称仅警告不打断)后立刻读回,目录只读场景 FileNotFoundError 未捕获 → 整 run traceback 崩,违反同文件声明的非致命契约。修:读回包 try/except,失败时就地重建 body |
| 卫生类(一句话) | 多文件 | diff_group 死 import os/shutil + `raw_text` 死参数链(:126-133);sdr_tier probe 失败原因统一报 "no binary" 掩盖 env 指向陈旧路径(:44-65);resume_sdr_state STEPS 死常量(:90)+ `_resolve_repo` grp 死参(:194-209);mgh_sdr_launch 函数内重复 import os(:169);diff_seed SOURCE_EXT 重复 `.ts` + deleted[] 未按源码扩展过滤(:24-28、:61) |

## 7. 未入 findings 的有价值观察(修复时可参考)

- **sdr_context**:baseline/context/hits 非原子写(幂等重跑 + --check JSON parse 失败自愈);授权门是 resolved 精确匹配而守卫是包含匹配——已批准根的子目录声明会进 pending_approval 自愈(fail-closed 方向);POSIX 形态路径在 Windows 上被静默忽略(MSYS 形态本就在契约外);`--check` 携 `--approve-external` 时批准静默跳过(不发生授权,自愈);坏目录浪费一次全量检索(敏感目录校验排在外部检索之后)。
- **fanout_runner / sdr-task.md**:sdr tier `path_fields` 未含 baseline_path/external_dir 的越树预检——与 draft_path 同根派生,今日无独立漂移风险;`_parse_ack` 的 `startswith("ok")` 前缀过宽(散文末行 "okay" 误判,磁盘 marker 是跨 run 真相,有界);diff_group docstring 的 unit 形状漏列 baseline_path/external_dir(枚举器侧文档滞后);sdr-task.md 头部 HTML 注释随每份任务消息发给 subagent(约 150 token/单元,可剥离,纯优化)。
- **render_sdr_report**:报告 tmp 写在 out_dir 再 replace 到 repo 根,跨卷会 OSError(注释已自认 same-volume 前提);同一 unit 同时有 .done 与 .failed 时 units_total 双计;`if f.get("line"):` 使 line=0 丢锚(行号 1 起,实际不可达);--check 读非 UTF-8 报告裸 traceback(仅外部篡改可达)。
- **launcher**:`--multi-branch` 与 `--branch` 同给时 `--branch` 被静默忽略;`_residual_sentinel` 返回值无人消费(异 target 残留哨兵被静默覆写,sanctioned 流程造不出该状态);子宿主进程继承 stdout,launcher 末尾 JSON 与 opencode 响应文本共 stdout(cron 消费建议看退出码)。
- **diff_group**:边缓存按裸符号名键控(同名方法跨类共享边 → 单元过包含,hunk 跨单元重复属设计,不丢内容);git 调用无 per-call timeout(编排器 Bash 层 timeout 是设计兜底,但 git 挂起无自救);`_split_interface` 用 id() 标记 hunk 归属(对象生命周期内正确,脆弱);方法级映射注解 `path = "/x"`、数组 `{"/a","/b"}` 形式不识别(命中时仍被方法区间认领、覆盖不丢,但路由串坍缩为 base,报告路由列失真——启发式精度,可后续扩正则)。
- **resume_sdr_state**:rearm 无条件覆写既有哨兵、缺 arm 侧的异 target 拒绝(target 派生自本 run 自己的 context.json,sanctioned 流程无风险,仅手工搬运场景)。

## 8. 健康面确认清单(修复时无需重审)

- **授权与 fail-closed**:未授权外部仓零读取 + `unapproved` 分流(not-found ≠ unapproved);坏 JSON/错型配置零授权不崩;sdr_context / read_roots_config / 守卫三方读取语义锁步一致;`--approve-external` 与 `read_roots_config --add` 共享同一验证-原子写实现(单一真相源)。
- **哨兵**:四方写入(arm/sdr_context co-write/rearm/launcher)schema `{"domain":"mgh-sdr","target","out_roots":[],"read_roots":[],"v":1}` 完全一致;`--arm-sentinel` 同 target 幂等 no-op、已细化 read_roots 绝不清空(有测试背书);`--rearm-sentinel` 消失根 fail-closed 丢弃;原子写 tmp + os.replace。
- **launcher 六缺陷修复(a6dc963)全部落实且有测试背书**:分支预检早败(先于任何副作用)、报告按 run 目录 manifest 认领(串目录结构性不可能)、spawn 剥离 PWD、opencode ERROR 日志 + --model 透传、launcher 二道门重判已批准根、退出码与部分失败语义(失败分支 stderr 逐行 + 末尾汇总,不静默)。
- **fanout 核心机制**:刚性三元组逐字透传(纯 str.replace + 残留 `{{` fail-loud + 越树预检拦截写 .failed 不 spawn);四级超时不变式 spawn 前 fail-loud;槽位补位/双流时戳失活检测/快败冷却(120s 窗口 3 阈值、预算封顶降级)/熔断前一次退避;杀树 Windows taskkill /T /F + POSIX killpg;线程安全(queue 迭代仅在 worker 全静止时)。
- **render 工程纪律**:单 dict 双载体 + --check 同源比对;静态模板零外部引用(自包含核验过);Windows 文件名清洗覆盖 9 字符 + 保留名回退;退出码/编码/幂等(同秒原子覆盖)合规。
- **文档/镜像**:`core/contracts/sdr/resume-state.md`、`core/contracts/fanout/runtime.md` 与实现逐条吻合(零 finding);三面壳全部 flag 经 argparse 核对真实存在(459 项机器对账全过);dsh SKILL 白名单差异运用整体到位;`sensitive_catalog.py` 与 `json.example` 三方一致(37 项/10 类别)且零 finding;`resume_sdr_state.py`/`list_sdr_steps.py` 步骤推导与纪律输出三方一致。

## 9. 每文件健康度小结

| 文件 | 一句话 |
| --- | --- |
| diff_group.py | 工程素养高(测量式字节门、三级处置、前向 marker),但两处实证的静默覆盖丢失(C1/C2)+ 一处 Windows 崩溃路径(H4),都在产品目标场景可触发 |
| sdr_tier.py | 小而干净,单一真相源设计到位,仅一条诊断精度 low |
| sdr_context.py | 安全主干(授权门/哨兵/预算披露)全部达标,外部仓物化层带 slug 冲突(H6)+ 三个 correctness/performance medium |
| read_roots_config.py | 事务性/原子写/fail-closed/幂等全达标,仅 mkdir 未入 try 的 low |
| sensitive_catalog.py / .json.example | 零 finding,三方一致 |
| render_sdr_report.py | 防御姿态最完整的渲染器,但两高危缝隙恰在防御接缝处(C3 scheme、H3 双转义)+ 降级路径数据损坏(H2)与错型崩溃(H1) |
| resume_sdr_state.py | 健康:核心面全部正确且有测试背书,仅两处死代码 low |
| list_sdr_steps.py | 健康:三方一致、字节级对齐,零 finding |
| mgh_sdr_launch.py | 总体健康,六缺陷修复未回退;残留 4 处 low |
| describe_artifact.py | 中等:功能正确,但两处「畸形输入/中文控制台即炸」medium 是本批最该先修的文件之一 |
| diff_seed.py【sast 侧】 | 中等:主逻辑正确,quotepath 漏 seed 是安全工具的真实覆盖缺口(M14) |
| fanout_runner.py | 架构面扎实,但 7 项 finding:kill-stale 静默失效(H5)最重,failed 双计/心跳失真/扫错目录/配方不可运行是真实正确性缺口,竞态使 clean HEAD 套件本机确定性红(M4) |
| sdr-task.md | 三元组/占位符/schema 咬合良好,但敏感目录下发声明描述了主路径无法行使的机制且无披露(M6) |
| runtime.md / resume-state.md | 与实现逐条一致,零 finding |
| hooks/runtime-enforcement.md | sdr 审批流落地后未回灌:两处 medium 文档债(M20) |
| 三面命令壳 | 结构健康、flag 面全过;超时段措辞漂移(M16)+ 转发槽位欠账(L10);dsh 面 launcher 口径失真(M15);SKILL token 贴顶 4994/5000 |
| 三面 agent 定义 | 职责/schema/ack 契约吻合;`{{ }}` 字面占位符(M17)+ 永不触发的机制句(L9) |
| pipeline.md | 契约中最滞后:字段清单欠载(M19)+ --dimensions 矛盾(M18),建议优先修 |
