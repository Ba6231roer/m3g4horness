## Context

`render_sdr_report.py` 把 grouping.json `units[].chain[]`(节点含 `fqn_short`/`file`/
`line`/`change`)渲染为章节一短形文本(`_render_chain`/`_node_text`),把合并 findings
(`file`/`line`)渲染为章节二位置行;报告文件写在 `--repo` 根目录,故仓内源文件相对仓根的
相对路径即报告可点击的相对链接。数据来源(`diff_group.py` 链物化、draft `line` 字段)均已
存在,本 change 纯渲染层。约束:标准库、确定性、`--check` 自洽、manifest `rows[]` 为机器
消费面。

## Goals / Non-Goals

**Goals:**
- 章节一入口列/调用链列的每个短形节点、章节二位置行,可点击跳转到仓内源文件(有行号带
  `#L<line>` 锚点)。
- 任何路径异常(仓外绝对路径、空/缺失字段)零坏链接:降级现行纯文本,输出形态与今天的
  报告一致。

**Non-Goals:**
- 不改 `diff_group.py`/draft schema/manifest 结构;不做报告内部锚点(`P-NN` 维持纯文本);
  章节三 mermaid 图不加链接;不为链接新增任何 CLI flag(缺省即开,无关闭需求——降级路径
  天然覆盖不可链化的数据)。

## Decisions

**D1 — 单一链接渲染 helper,而非各呈现点各自拼串**
新增模块级 `_source_link(text: str, file: str, line, repo: Path) -> str`:产出
`[<text>](<rel>#L<line>)`,不可链化时原样返回 `<text>`。三个调用点(链节点、standalone
入口短形、章节二位置)共用,判定逻辑单点维护,契约 lint 与单测只针对一个函数。替代方案 =
每处内联拼 markdown,重复三遍降级逻辑,易漂。

**D2 — 路径解析纯词法,NEVER stat 文件系统**
- `file` 以盘符绝对(`C:\...`/`C:/...`)或 UNC(`\\...`)开头 → `os.path.normpath` 后用
  `os.path.relpath(nf, repo)`(纯词法,不要求两端存在);结果以 `..` 开头 = 仓外 → 不链。
- `file` 为相对路径 → 直接视为相对仓根,反斜杠统一换 `/` 输出;首段为 `..` → 不链。
- 理由:diff 分支的源文件可能不在当前工作树(design/渲染时零检出保证),stat 判定会让同一
  输入在不同检出状态下产出不同报告,破坏确定性(R5.3);词法判定对任意 cwd/平台稳定。
  代价 = 指向未检出文件的链接在编辑器里点开是「文件不存在」提示,这是可接受的呈现层信息
  (链接表达的是「该跳代码在仓内的位置」,不是「此刻工作树里有这个文件」)。
- Windows 大小写盘符/目录差异:`relpath` 前对两端同盘判定用 `ntpath.normcase` 等价物
  (`os.path.normcase`,POSIX 下为恒等),避免 `c:/` vs `C:/` 误判仓外。

**D3 — 锚点形态 `#L<line>`,line 缺失退化为无锚点文件链接**
GitHub/GitLab 系渲染原生支持 `#L42` 行高亮;obsidian/VSCode 预览不支持 fragment 时自动
退化为只打开文件,无害——故有 line 就带,不做「按编辑器配置开关」(增加 flag 面与契约漂移
无收益)。mapper XML 终端 `line` 恒为 `null`(diff_group 不解析 XML 行号),即天然走无锚
点形态。

**D4 — 显示文本与链接解耦,manifest 投影去链接**
`_render_chain`/`_node_text` 改造为「短形文本 + 可选链接包装」两层:短形逻辑(`†` 前缀、
`·` 同类延续)逐字不动;`rows[]` 继续吃短形纯文本(现行构造点不变),表格单元格吃
`_source_link` 包装结果。比对「manifest 与表格一致」的单测按去链接化文本断言。替代方案 =
manifest 也存链接,否决:下游 `/mgh-blst` 是机器消费,掺 markdown 语法是污染。

**D5 — 转义策略:显示文本最小转义,路径 percent-encode 不做**
短形文本来源受控(类名/方法名/文件名,字符集不含 `]`/`(`/空格以外符号),但 finding
`file` 是 LLM 回写、不可信:路径含空格在 md 链接里非法 → 含空格或 `(`/`)` 的路径不链
(降级纯文本),比对整条路径做 percent-encode 更简单且零坏链风险。显示文本含 `]`/`[` 时
`\]`/`\[` 最小转义。

## Risks / Trade-offs

- [词法判定把「实际不存在于工作树」的路径链出] → 编辑器给出明确的「文件不存在」提示,
  用户可感知;且 diff_group 的 `file` 本就取自 diff 时点工作树,概率低。
- [finding `file` 由 LLM 书写,可能有前导 `./`、`/` 引导等噪声形态] → D2 归一化
  (`normpath` 吃掉 `./`;`/` 引导 = POSIX 绝对,resolve 后按子树判定);仓外/畸形一律
  纯文本,错向是「少链」不是「坏链」。
- [表格单元格变长(链接语法)可能触发 R5.6 token 预算类 lint] → 预算 lint 只辖命令壳/
  提示词,不辖运行时产物;报告尺寸无契约约束,仅人读体验,可接受。
- [未来若报告改为可移动(用户把报告拷出仓)] → 相对链接断,属使用方式问题,不在本设计
  补救面(诚实边界已有「报告在仓根」前提的多处约定)。

## Migration Plan

纯渲染行为变化,无数据迁移:旧 run 目录的 grouping.json/drafts 直接可渲染出新报告(字段
早已存在);旧报告文件不回溯改写。回滚 = revert 渲染器 commit。

## Open Questions

(无)
