# Design: improve-mgh-sdr-report-html-render

## Context

现状链路:fan-out 子代理产 `drafts/*.json`(严格 JSON schema)→ `render_sdr_report.py`
(868 行,标准库)确定性渲染 `<repo>/mgh-sdr-<分支>-<ts>.md` + `<run-dir>/sdr_manifest.json`。
报告含 mermaid 调用链图(每 branched 单元一张);规格因 obsidian/Zed 不支持 MD 内部锚点而
禁用编号跳转。动机与判断修正(为什么做、token 假设为何不成立)见 proposal.md 的 Why,
行为契约见本 change 的 specs delta;此处只讲实现层。

受影响的硬编码面(已核实):

| 位置 | 现状 | 影响 |
|---|---|---|
| `resume_sdr_state.py` | 渲染完成判定键 = `sdr_manifest.json` 存在 | **零改动**(扩展名无关) |
| `list_sdr_steps.py` render 步 | `path_pattern: "<target>/mgh-sdr-<branch>-<ts>.md + …"` | 改 `.html` |
| `mgh_sdr_launch.py` 多分支收尾 | `repo.glob("mgh-sdr-*.md")` 收集报告路径 | 改 `.html` |
| 三面命令壳 step 4 + Always disclose | 描述 `.md` 与 mermaid 章节 | 文案同步 |

## Goals / Non-Goals

**Goals:**

- 一次数据组装、两种载体:canonical 数据文件(机器面)+ 自包含 HTML(人面),二者
  by construction 同源,`--check` 可校验一致性。
- 调用链图从「依赖编辑器 mermaid 插件」变为「页面内自绘 SVG + 缩放平移」。
- 源文件链接、页内锚点跳转、筛选等浏览器原生交互,零外部依赖、file:// 可用。

**Non-Goals:**

- `/mgh-srr`(`render_report.py`)与 `/mgh-sast` 报告形态——不在本 change;若验证成功,
  未来以同一「数据 + 自包含 HTML」模式另行立项复用。
- 本地 HTTP 服务、报告索引页、多 run 聚合视图。
- 历史 `.md` 报告的迁移/回写。
- mermaid 语法兼容输出(不产 mermaid 备用块)。
- 调用链图布局通用化(只做评审链场景的确定性分层布局,不做通用图布局器)。
- token 优化(已证伪,见 proposal;fan-out 契约零改动)。

## Decisions

**D1 报告形态:HTML 全面替代 MD(维护者已拍板:不保留 MD)。** 双产方案 B 的
成本是每次 run 落两份人读报告 + 渲染器/规格/测试长期背两套呈现语义;MD 的文本工具消费面
由数据 JSON 承接。回退成本集中在渲染器尾部补一个 MD emitter,specs 增量一个需求块。

**D2 渲染架构:数据驱动,浏览器端渲染。** 渲染器把报告全量数据组装成一个 dict →
① 原子写 `<run-dir>/sdr_report_data.json`(canonical);② 同一份数据以
`<script type="application/json">` 内嵌进 HTML;③ 页面 JS(内嵌,~200 行 vanilla)从
内嵌数据渲染 DOM(表格/详述/筛选)。HTML 骨架模板是静态字符串常量,不含任何按 run
变化的插值——**一致性与安全性都由这个结构兜住**:

- 数据文件与内嵌块天然等价(同一 dict 两次序列化),`--check` 解析比较即可;
- 所有动态文本经唯一 `escapeHtml` 入 DOM(`textContent`/属性转义),never 拼接 innerHTML
  原文——finding 风险/建议文本来自 LLM、切片含目标仓源码,是真实注入面;
- 内嵌 JSON 块写入时把 `</` 替换为 `<\/`(JSON 字符串内合法、解析等价),防数据中的
  `</script>` 字面量截断脚本块。

否决的替代:服务端(Python)直接拼 HTML、JS 只做交互——交互与渲染本就都要 JS,两条
代码路径必然漂移,且一致性校验退化为脆弱的文本比对。

**D3 调用链图:Python 标准库生成 SVG(维护者已拍板)。** 验收口径(拍板原文):**只要零
其他依赖、Chrome 打开就能用即可**——本方案天然满足:SVG 是内嵌标记,无图形库、无网络
引用、file:// 即开;Chrome 是验收浏览器(实现仍不得依赖 Chrome 专属特性,保持任意现代
浏览器可用的余量)。布局是确定性分层:入口
depth 0,节点 depth = 最长上游路径;同 depth 按首次出现序纵排,冲突纵向让位;边为正交
折线,mapper 终端(`⇢`)虚线、未变更节点(`†`)保留前缀;坐标进 `viewBox`,缩放平移由
内嵌 JS(wheel + 指针拖拽,~60 行)完成。数据从 grouping.json `units[].chain[]` 来,
与现行 mermaid 同一数据源。alternatives(留档):**B 内嵌 vendored mermaid.js**(~1MB
静态资产,分发体积与零依赖克制相悖——已被拍板否决);**C 纯 HTML 树/列表**(最简,但
分支拓扑不可视化,章节三失去存在意义)。风险与缓解见 Risks。

**D4 HTML 模板载体:内嵌 `render_sdr_report.py` 字符串常量(维护者已拍板)。**
脚本预计 868 → ~1600 行,仍是单文件叶脚本(R5.3 runtime 自包含、零新安装面、零路径
定位问题);模板按 `<!-- section: css/js/骨架 -->` 分节注释维持可编辑性。alternatives:
**B 独立资产文件**(`core/assets/**` + install.sh 三端接线 + purity 扫描面扩展 +
安装路径解析)——install/测试/parity 三倍接线成本,买到的只是编辑体验;若未来模板
膨胀超出单文件可维护阈值,再 shard(留口,不预设)。

**D5 launcher:尾部提示同步 + `--open`(维护者已拍板:加,默认 off)。** 多分支 sweep 跑完人工逐个
找报告是真实摩擦;`webbrowser.open`(标准库)3 行解决,默认 off 维持 launcher 零副作用
纪律。alternatives(留档):默认 on——违背「launcher 静默完成」预期,否决;不提供——
摩擦保留,否决。

**D6 `--check` 语义扩展。** 保留现行(manifest 计数 vs draft、报告结构齐备)并新增:
① `<run-dir>/sdr_report_data.json` 存在且 JSON 可解析;② 与 HTML 内嵌数据块 **JSON
等价**(解析后比较,非字节);③ 报告文件若存在则为 `.html` 且含内嵌数据块与各章节锚点
标记(文本级断言,`--check` 不开浏览器)。任一违例退出码 2。

**D7 兼容与切换。** 渲染 CLI(参数/退出码/`--out-dir`)不变;manifest schema 不变;
`resume_sdr_state.py` 判定键不动;`list_sdr_steps.py` path_pattern 与 launcher glob 同步
改 `.html`;三面命令壳(三面镜像,方言白名单五类之外逐字一致)step 4 章节描述与
Always disclose(报告形态、历史 .md 不迁移披露)同步;真仓一次首跑人工验收(浏览器
打开全章节 + 缩放/跳转/筛选)。

## Risks / Trade-offs

- [LLM/切片文本注入 HTML(结构破损或脚本注入)] → D2 三层兜底:唯一转义入口、
  `textContent` 优先、内嵌 JSON `</` 转义;测试加注入用例(数据含 `<script>`/`</script>`/引号)。
- [浏览器对 `.java` 等扩展名的 file:// 呈现不一(可能触发下载)] → 链接保持仓内相对
  href(报告就躺在仓根,最常见的阅读位置语义正确);诚实边界披露「源文件链接在部分
  浏览器可能下载而非打开」;SVG 节点不承载链接,减少误触面。
- [大 run(数百单元)单页 DOM 偏重] → 数据单份、vanilla 无框架、千行级表格浏览器可
  承受;筛选为纯视图态(隐藏行),不重排不重渲染。
- [SVG 分层布局在多分支宿主链上重叠] → 纵向让位 + 真仓样例验收;图形支持缩放平移兜底
  可读性;布局只求「拓扑正确、可缩放」,不求美观最优。
- [双载体漂移] → D2 by construction 同源 + D6 `--check` 等价断言双保险。
- [测试重写面大(`test_render_sdr_report` 全量重写)] → 断言用标准库 `html.parser` +
  JSON 解析,不引浏览器;真浏览器验收列为 tasks 人工项(非 CI)。

## Migration Plan

单 commit 落地(渲染器 + 壳文案 + launcher/steps + 测试同 commit);install 重装即得;
用户侧零操作。回滚 = git revert 单 commit;run 目录内历史产物(`.md` 与新 `.html`)
互不干扰。

## Open Questions

无——四项拍板(MD 去留 / 调用链图技术 / 模板载体 / `--open`)已由维护者全部确认,与
specs/design/tasks 的现行内容一致,无遗留分歧。
