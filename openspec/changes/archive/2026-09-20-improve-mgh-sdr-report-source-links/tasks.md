## 1. 链接渲染 helper(render_sdr_report.py)

- [x] 1.1 `core/scripts/render_sdr_report.py` 新增模块级 `_source_link(text, file, line, repo)`:按 design D2 纯词法路径解析(绝对路径 `os.path.normpath`+`os.path.relpath` 对 `repo` 判子树、`normcase` 消 Windows 大小写盘符差异;相对路径反斜杠归 `/`;首段 `..`/仓外/空/缺失 → 原样返回 text),按 D5 拒链含空格与 `(`/`)` 的路径,产出 `[<text>](<rel>#L<line>)` 或无锚点形态 `[<text>](<rel>)`;text 含 `[`/`]` 时 `\[`/`\]` 最小转义;NEVER stat 文件系统
- [x] 1.2 `_node_text`/`_render_chain` 接入:链节点短形经 `_source_link(n.file, n.line)` 包装,`†` 前缀与分隔符(`→`/`·`/`⤷`/`⇢`)不入链接(短形构造与链接包装两层分离,design D4);mapper 终端 `line=null` 天然走无锚点形态
- [x] 1.3 standalone/无路由单元的入口列(`_standalone_entry`)接入同一 helper(route 串入口不链)
- [x] 1.4 章节二位置行接入:`file:line` → `[file:line](rel#Lline)`,draft 缺 `line` → `[file](rel)`;不可链化路径保持现行纯文本

## 2. manifest 与 --check 一致性

- [x] 2.1 `rows[]` 的 `entry`/`chain` 继续取纯文本短形(未经 `_source_link` 包装的构造点),确认无链接语法渗入 manifest(JSON 字段值不含 `[text](` 形态)
- [x] 2.2 `--check` 复核:现行锚点黑名单正则 `](#` 不误伤 `](src/...#L42)`(仓内文件链接 `#` 前有路径段);如实现中确有形态冲突再收敛正则,不冲突则仅加注释说明两类链接的区分
- [x] 2.3 模块 docstring 报告结构描述同步一句「入口/链/位置为仓内源文件相对链接(不可链化降级纯文本)」

## 3. 回归测(tests/test_render_sdr_report.py)

- [x] 3.1 `_source_link` 直测:相对 java 路径+line → 带锚点链接;`line=None` → 无锚点;仓外绝对路径 → 纯文本;仓内绝对路径(含盘符大小写差异)→ 转相对;空串/缺失 → 纯文本;含空格路径 → 纯文本;反斜杠相对路径 → 输出 `/` 分隔
- [x] 3.2 端到端:造 grouping.json(链节点含 file/line、mapper 终端 line=null、† unchanged 节点)+ drafts(file/line 与缺 line 旧格式)→ 断言章节一链单元格形态、章节二位置链接、`·`/`⤷`/`⇢` 分隔符不入链接、维度列仍纯文本 `P-NN`
- [x] 3.3 降级端到端:某 finding `file` 为仓外绝对路径 + 某链节点 `file` 空串 → 该两处纯文本、退出码 0、`--check` 通过
- [x] 3.4 manifest 一致性:`rows[]` `entry`/`chain` 无 `[`/`](` 链接语法;「rows 与表格一致」既有断言改为按去链接化单元格比对
- [x] 3.5 既有「无锚点纯文本编号引用」用例更新:全文断言仍无 `<a id=`/`{#`/`](#`(内部锚点),新增断言允许且仅允许 `](<仓内相对路径>` 形态外链

## 4. 契约与分发面复核

- [x] 4.1 `py tools/check_contracts.py`(无新 CLI flag,仅确认无漂移)+ `py tools/check_distributed_purity.py`(渲染器属分发脚本,新注释/docstring 不得引入 R5.10 禁引)
- [x] 4.2 双壳 `releases/{claude-code/commands,opencode/command}/mgh-sdr.md` 报告结构描述如有「纯文本短形」措辞,同步为「源文件相对链接(降级纯文本)」,R5.6 token 预算内;`tools/measure_prompts.py` 预算复核
- [x] 4.3 版本号 bump + `CHANGELOG.md` 条目(承 R5.8)

## 5. 验收

- [x] 5.1 定向回归:`py tests/test_render_sdr_report.py` 全过;顺带 `py tests/test_zero_deps.py` + `py tests/test_no_compile_warnings.py`
- [ ] 5.2 springBootTemplate 干跑渲染(复用 report-structure change 5.2 的只分组+手工 drafts 干跑环境):在 obsidian/VSCode 预览实际点击入口列/链节点/章节二位置,核对跳转到正确文件与行;抽查 mapper 终端无锚点形态、† 节点带链
- [x] 5.3 人工核对报告 diff 面:除三处呈现点外,其余章节(头部/章节三 mermaid/无问题单元/诚实边界)输出与改动前逐字节一致(防误伤);结果回填本 change

## 验收回填(5.2 / 5.3 执行结果)

- **5.3 已完成**:同一 dry1 环境分别用改动前渲染器(`git show HEAD` 版本)与改动后渲染器各出一份
  报告,时间戳归一化后 diff:变化的行**仅**为章节一调用链/standalone 入口单元格与章节二 5 条
  位置行;头部、分组概览、阅读方式注、章节三、无问题单元、诚实边界逐字节一致。
- **5.2 机器可验子集已完成**:渲染 59 个链接目标全部存在于工作树;抽查锚点行号精确落在方法声明
  行(`UserCacheController.java:44` = `directQuery`、`OrderController.java:52` = `detail`、
  `OrderServiceImpl.java:35` = `submit`);mapper XML 终端与无 line 节点呈无锚点形态、`†` 节点
  带链(断链入链接文本内)。`--check` 两份输出均退出码 0。
  **待人机页一步**:在 obsidian/VSCode 预览实际点击核对跳转手感(报告已生成过、验证后清理;
  重跑 `py core/scripts/render_sdr_report.py --run-dir C:/DEV/springBootTemplate/.mgh-sdr/runs/dry1 --repo C:/DEV/springBootTemplate` 可再生)。
