# Proposal: improve-mgh-sdr-report-html-render

> **人话序**
> **现象**:`/mgh-sdr` 的评审报告是一个 Markdown 文件,里面还有调用链图。读者必须用
> Obsidian / VSCode 这类工具打开;调用链图用的是 mermaid(一种"写文字、让编辑器画图"
> 的语法),大图要么装插件、要么点开才能放大,要么在阅读视图里来回拖滚动条;问题编号
> P-NN 不能点击跳转——因为目标编辑器不支持 Markdown 内部锚点,现行规格干脆禁止了锚点。
> **根因**:报告数据早已是结构化 JSON,但"人读呈现"被绑死在 Markdown 形态上,编辑器
> 的限制全数转嫁给了读者。**改什么**:渲染器改产**自包含单文件 HTML**(数据、样式、
> 脚本全部内嵌,双击用浏览器打开,不联网、不装任何工具),调用链图改为页面内可缩放
> 的矢量图,问题编号页内可点击跳转;另落一份结构化 JSON 数据文件供下游程序消费。
> **怎么验证**:对既有测试 run 目录重跑渲染,断言 HTML 无任何外部引用、与数据文件
> 内容一致、`--check` 通过;浏览器人工打开核对交互。
> **诚实修正**:本次改动**不减少 LLM token**——现状已经是"子代理只写 JSON + 脚本
> 渲染报告",报告正文本来就不花 token;真实收益是阅读体验与数据/呈现分离(详见 Why)。

## Why

本次动议源于一个双重假设:"HTML 渲染能让阅读体验更佳,同时只写 JSON 能减少 token 输出"。
对现状代码与规格逐项核实后,结论是**一半成立、一半不成立**,提案按修正后的动机立项:

**假设一:阅读体验——成立。** 三条代码/规格证据:

| # | 现状事实 | 对读者的代价 |
|---|---|---|
| 1 | 报告是 `.md` 文件,面向"人类·随包分发"受众 | 读者必须装有 Markdown 阅读工具;没装的看到的是带 `#`、`|` 记号的原始文本 |
| 2 | 章节一规格**明令禁止** Markdown 内部锚点(`spec.md`「无锚点纯文本编号引用」),理由原文:"目标编辑器(obsidian/Zed)不支持报告内部锚点跳转,编号即可定位" | 简报表里的 `是 [P-03]` 无法点击跳到问题详述,读者全靠肉眼找 |
| 3 | 章节三用 mermaid `flowchart LR` 画分支调用链 | 图的呈现质量取决于编辑器插件;大图缩放/平移在各编辑器里体验参差,Obsidian 需插件点击放大 |

这些妥协全部是**Markdown 形态强加的**,不是评审语义本身的需要。浏览器是唯一免安装、
免插件、离线可用的普遍呈现介质;自包含 HTML 能同时解锁:页内锚点跳转、severity/维度
筛选、调用链图缩放平移、长表折叠。

**假设二:token——不成立,方向需要修正。** 核实到的现状链路:

```mermaid
flowchart LR
    A["fan-out 子代理<br/>(LLM)"] -- "已是严格 JSON draft<br/>+ 单行 ack(禁回显正文)" --> B["drafts/*.json"]
    B -- "render_sdr_report.py<br/>确定性渲染,零 LLM token" --> C["报告 .md"]
    A -.->|"报告改 HTML 后<br/>此链路 token 零变化"| B
```

- 子代理输出**已经**是严格 JSON(`sdr-task.md` 的 Draft schema 一节),回执是单行
  ack,模板明令"NEVER echo finding bodies"(就是为省 token 设计的);
- 报告正文由 `render_sdr_report.py`(Python 标准库脚本)从 JSON 确定性渲染,**今天
  就不花任何 LLM token**;
- 因此"改成只写 JSON"在这个流水线里没有 token 可省——它已经是事实。

**立项后的真实收益**(替代 token 论):① 上述阅读体验;② **数据/呈现分离**——新增的
结构化数据文件让下游确定性消费(未来 `/mgh-blst`、报告 diff 工具、让 agent 用
`describe_artifact` 读报告而不必整读大文件)有正式接口,这一方向 `sdr_manifest.json`
的 `rows[]` 已经开了头;③ 解除现行规格里两条"为编辑器妥协"的禁令(内部锚点禁令、
mermaid 节点禁链),规格回归评审语义本身。

## What Changes

- `render_sdr_report.py` 报告产物从 `<repo>/mgh-sdr-<分支>-<时间戳>.md` 改为
  **`<repo>/mgh-sdr-<分支>-<时间戳>.html` 自包含单文件**(CSS/JS/数据全部内嵌,
  file:// 直接打开、零外部引用)。**BREAKING**:报告文件扩展名与格式变更;历史
  `.md` 报告不回写、不迁移。
- 新增 `<run-dir>/sdr_report_data.json`:报告全量结构化数据(单元行、findings、
  链图数据、诚实边界条目),HTML 内嵌同一份数据——人读 HTML 与机器读 JSON 同源。
- 章节三调用链图:mermaid 文本 → **页面内嵌 SVG**(渲染器确定性生成),支持缩放
  与拖拽;mermaid 依赖彻底移除。
- 简报表升级为可交互表格:按 severity / 维度筛选、P-NN 页内锚点跳转(解禁原
  MD 编辑器限制下的锚点禁令)。
- 三面命令壳(claude / opencode / dsh)step 4 与披露文案、launcher 尾部提示同步;
  `--check` 扩展校验 HTML 与数据文件一致性。
- **不变**:渲染器 CLI 形状(参数/退出码)、`sdr_manifest.json` schema、诚实边界
  ≥7 条语义、fan-out 侧一切(子代理契约、token 花费零变化)。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `security-design-review`:「统一问题记录汇总与确定性报告渲染」需求的报告产物形态
  (.md → 自包含 .html + 数据 JSON)、章节三呈现技术(mermaid → 内嵌 SVG)、
  Markdown 锚点禁令改为页内锚点可用、以及随动的全部 Scenario(文件名可追溯、
  链节点链接形态、manifest 纯文本投影语义保留等)。

## Impact

- **代码**:`core/scripts/render_sdr_report.py`(主战场,现 868 行,标准库不变);
  `mgh_sdr_launch.py` 尾部报告路径提示;三面命令壳 `mgh-sdr.md`(step 4 章节描述 +
  Always disclose)。
- **测试**:`test_render_sdr_report` 重写(HTML/数据断言);`test_mgh_sdr_launch`、
  `test_distributed_md_purity`、`check_contracts` 随文案面核对。
- **规格**:`openspec/specs/security-design-review/spec.md` 渲染需求整节 delta。
- **风险与边界**:① 源文件链接在 HTML 里指向仓内相对路径,浏览器对 `.java` 等
  扩展名的 file:// 呈现行为不一(设计里给降级与披露);② 页内 SVG 布局是确定性
  简化布局(分层、非通用图布局器),复杂分叉链的可读性需真仓验证;③ 分支名/时间戳
  命名规则不变,旧报告文件残留由用户自行清理(披露)。

## 拍板结果(维护者已确认)

| # | 决策点 | 结论 |
|---|---|---|
| 1 | Markdown 报告去留 | **不保留 MD**——HTML 全面替代;历史 `.md` 报告不迁移不回写 |
| 2 | 调用链图技术 | **标准库自绘 SVG**;拍板给的验收口径:只要零其他依赖、Chrome 打开就能用即可 |
| 3 | HTML 模板载体 | **内嵌 `render_sdr_report.py` 字符串常量**,零新安装面 |
| 4 | launcher `--open` | **加**,默认关(显式传参才自动开浏览器,维持 launcher 零副作用默认) |

回退备忘:若未来需要 MD 形态,成本集中在渲染器尾部追加一个 MD emitter(specs 增量一个
需求块);方案 B(双产)的优缺点对比见本 change 的 git 提交历史。
