## MODIFIED Requirements

### Requirement: 统一问题记录汇总与确定性报告渲染

新增确定性叶脚本 `render_sdr_report.py`(标准库、退出码 0/1/2、`--check` 承 R5.9)SHALL 收
run 目录下全部 fan-out 单元 draft(`.done` 且 JSON 可解析者;`.failed` 单元以 stderr 汇总 +
manifest `failed_units[]` 计入,不阻断渲染),按 `{dimension, route, file}` 三元组去重合并,
渲染 `<repo>/<工具名>-<分支名>-<YYYYMMDD_HHMMSS>.html`(工具名固定 `mgh-sdr`;分支名取文件系统
安全命名;时间戳到秒、本地时区)。报告 SHALL 为**自包含单文件 HTML**:样式、脚本、数据全部
内嵌,SHALL NOT 引用任何外部资源(网络 URL 的脚本/样式/字体/数据、CDN、外链图片一概不产),
file:// 双击用任意现代浏览器打开即可阅读,不依赖联网与任何已安装工具。报告 SHALL 为简体中文、
面向人读,结构:

- **头部**(分支/base/时间/检查面/敏感目录来源/外部仓结论摘要 + 分组概览,保留现行);
- **章节一「简报表」**(本需求的核心结构):HTML 表格,**行 = 评审单元**(排序:interface 按
  route 升序、standalone 殿后按 unit_id;多路由单元按首路由参与排序),列 = 接口/方法入口、
  调用链、是否前端接口、前端使用次数、6 维度各一列(默认闭集维度;自由扩展维度各追加一列)。
  各列 SHALL 满足:入口列 = route 串(standalone 或无路由 = 该独立方法定义 `fqn_short`);
  调用链列 = 缩写链文本(按 grouping.json `units[].chain[]` 确定性渲染:仅保留类名/文件
  名:方法名,如 `OrderController.submit → OrderServiceImpl.submit`,真仓试用后由「包段
  首字母 + 类名」形态收敛,完整包路径可由 file 列还原,`·` 同类延续、`⤷` 分支(`branch_of` 宿主)、`⇢` mapper XML 终端、
  `†` 未变更节点;`chain[]` 为空(standalone/codegraph off)= 该单元方法定义短形;入口
  = 方法定义时链写到分析可达处);**入口列与调用链列的每个「类名.方法名」短形 SHALL 渲染为
  指向仓内源文件的链接**(见本需求「源文件链接渲染」段);前端两列 = 按 route join
  context.json `external_repos[].route_hits[]`(声明 ∧ 命中 >0 = `是`+`N 处`;声明 ∧ 0 命中 =
  `否`+`—`;无声明/不可达 = `未知`+`—`;多路由单元仅按主路由(分号串第一段)join,次路由命中
  不抬升主路由状态);维度列 = `否` 或 `是 [P-NN]`(该单元该维度的合并 findings 编号列表,
  **P-NN SHALL 为页内锚点链接**,点击跳转到章节二对应条目——HTML 形态下页内跳转由本报告
  自身保证,SHALL NOT 依赖任何外部工具;原 MD 形态下「SHALL NOT 产出内部锚点」的禁令
  系目标编辑器不支持所致,随报告形态切换一并废止;本约束 SHALL NOT 及于指向仓内源文件的
  链接,后者是本需求的交付内容);
- **章节二「问题详述」**:合并去重后的每条 finding 一小节,统一 `P-NN` 编号(全局递增,
  条目锚点 = 其页内跳转目标),标题形态 `P-01 · <维度中文标签> · <route 或独立方法> ·
  <severity 中文>`;正文含位置(`file:line`——line 取 draft 新增 `line` 字段(问题锚定行号,
  数值);draft 缺 `line` 时降级为 `file`(不硬失败,旧 draft 兼容);位置文本 SHALL 渲染为
  指向该源文件的链接(见「源文件链接渲染」段))、风险、建议、control_ref;排序 severity
  升序(高→提示)、同 severity 按 P-NN;
- **章节三「分支调用链图」**:仅含带真实分支(`chain[]` 存在 **非 external** 节点携带
  `branch_of`——即 java 调用扇出;mapper 终端节点按编码也带 `branch_of`,但不构成真实
  分支)的单元,每单元一张**内嵌 SVG 有向图**(渲染器按 `chain[]` 确定性生成分层布局:
  入口 → 逐节点 → mapper 终端虚线边;`⤷` 分支、`⇢` 终端、`†` 未变更节点语义全部保留),
  SHALL 支持缩放与平移(页内交互),SHALL NOT 依赖任何外部图形库;线性链单元(含仅 ⇢ 终端
  带 `branch_of` 的直连 dao 短链)SHALL NOT 入本节;SVG 节点 SHALL NOT 承载源文件超链接
  (源文件跳转统一由章节一表格与章节二承担,图形节点仅悬停提示 `file:line`);
- **「无问题单元」清单**(保留,供 merge 前放行参考)+ **诚实边界节**(≥7 条,含排除集披
  露,保留现行)。

**源文件链接渲染**(渲染规则,报告写在目标仓根目录 ⇒ 链接目标 = 源文件相对仓根的相对路径):

- 链接形态 `<a href="<相对路径>#L<line>">显示文本</a>`;`line` 缺失或为 `null` 时 SHALL
  退化为 `<a href="<相对路径>">显示文本</a>`(不带锚点)。
- 路径解析:chain 节点 `file` 与 finding `file` 为相对路径(相对 `--repo`)时直接作链接
  目标(输出统一 `/` 分隔);为绝对路径时,resolve 后在 `--repo` 子树内 → 转为相对路径,
  在子树外 → **不产链接**(降级纯文本,报告里没有指向仓外的死链);字段缺失/空 → 纯文本。
  路径解析 SHALL NOT 依赖文件真实存在(diff 分支的源文件可能未检出到工作树;链接坏与否由
  浏览器呈现,渲染器只做词法判定,NEVER 因此 stat 目标文件)。
- 显示文本 = 现行短形(`fqn_short` 等,含 `†` 前缀)逐字不变;`·`/`⤷`/`⇢`/`→` 分隔符不
  入链接;mapper XML 终端(`change=external`)与普通节点同等对待(有 `file` 即链)。
- 显示文本与属性值含 HTML 敏感字符(`<`/`>`/`&`/`"` 等)时 SHALL 做实体转义,NEVER 产出
  语法破损的标记;数据面(数据文件/manifest)SHALL NOT 因此引入任何 HTML 标记。
- `sdr_manifest.json` `rows[]` 与数据文件 `rows[]` 的 `entry`/`chain` 字段 SHALL 保持
  **纯文本短形**(不含任何链接语法/HTML 标记)——两者是机器消费面;表格链接是同一数据
  的渲染投影。

**数据文件**:渲染 SHALL 同步写出 `<run-dir>/sdr_report_data.json`,承载报告全量结构化
数据(单元行 `rows[]`、合并去重后的 `findings[]`(含 P-NN/维度/severity/位置/风险/建议/
control_ref)、分支调用链图数据、诚实边界条目、头部元信息),HTML 内嵌**同一份数据**
(JSON 等价一致)——人读 HTML 与机器读 JSON 同源;下游确定性消费(如未来 /mgh-blst、
报告后处理工具)SHALL 以数据文件为接口。`--check` SHALL 校验:数据文件存在且可解析、
与 HTML 内嵌数据一致、manifest 计数与 draft 实际一致。

同名报告文件已存在 SHALL 原子覆盖(时间戳到秒内重跑)。`sdr_manifest.json` `rows[]`
(`{unit_id, entry, chain, frontend_is, frontend_count, issue_refs[]}`;issue_refs = 该单元
各维度问题编号的展平列表)语义不变;`counts` 语义不变;其余字段保留现行(`excluded_files`
透传等)。draft 问题记录 schema 不变(`line` int 可选,任务模板与 agent 定义双端同步披露)。

诚实边界 SHALL 至少含 7 条(现行 7 条语义保留):① 发现是 LLM 候选需人工复核,非确认漏洞;
② 接口分组是启发式,漏分组接口退入独立单元(分析粒度粗但覆盖不丢);③ 引用存量控制断言存在、
不断言有效;④ 外部仓结论是检索时点快照(不保证前端分支已同步);⑤ 基线经字节预算投影,低优先
级细节可能未全量投影;⑥ 敏感目录来源与覆盖范围(目录外字段仅按回退规则识别);⑦ 排除集披露。
渲染器 NEVER 写 `openspec/`、NEVER 写 run 目录、数据文件与报告文件之外的目标仓文件;历史
`.md` 报告 SHALL NOT 被回写或迁移。

#### Scenario: 简报表行覆盖全单元形态

- **WHEN** 某 run 产 4 个 interface 单元(其一为多路由合并单元)、3 个 standalone 单元、其中
  2 个 interface 单元的 `chain[]` 带**非 external** 节点的 `branch_of`(真实分支)
- **THEN** 章节一表格 7 数据行(排序:interface 按 route 升序、standalone 殿后);interface 行
  调用链列为缩写链(含 `⤷`/`⇢`/`†`),standalone 行为方法定义短形;带分支的 2 单元在章节三
  各有一张内嵌 SVG,线性单元不出现;全部维度列为 `否` 或可点击的 `是 [P-NN]` 页内锚点链接

#### Scenario: 前端两列三态

- **WHEN** context.json 声明外部仓且 `/order/submit` 命中 2 处、`/cache/user/direct` 0 处,
  另一路由所在 run 未声明外部仓
- **THEN** `/order/submit` 行前端两列 = `是`+`2 处`;`/cache/user/direct` 行 = `否`+`—`;
  未声明仓的 run 其全部行 = `未知`+`—`

#### Scenario: 无锚点纯文本编号引用

- **WHEN** 渲染任意带 findings 的报告
- **THEN** `P-NN` 编号全局唯一且章节二可按编号定位;简报表格维度列的 `P-NN` 为**页内锚点
  链接**,点击在浏览器内跳转到章节二对应条目(页内跳转零外部依赖;原 MD 形态的内部锚点
  禁令随报告形态切换废止);数据文件与 manifest 的 `issue_refs[]` 仍为纯文本编号(不含
  链接语法)

#### Scenario: 链节点渲染为源文件链接

- **WHEN** 某单元 `chain[]` 含节点 `{fqn_short: "OrderController.submit", file:
  "src/main/java/com/x/controller/OrderController.java", line: 42}` 与节点 `{fqn_short:
  "OrderMapper.insertOrder", file: "src/main/java/com/x/mapper/OrderMapper.java", line: null}`
- **THEN** 调用链列依次渲染 `href="src/main/java/com/x/controller/OrderController.java#L42"`
  与 `href="src/main/java/com/x/mapper/OrderMapper.java"`(无锚点退化)的链接,显示文本为
  短形;分隔符不入链接,链的阅读顺序与短形文本不变

#### Scenario: 仓外与异常路径降级纯文本

- **WHEN** 某 finding 的 `file` 为仓外绝对路径,另一 chain 节点 `file` 为空串
- **THEN** 前者位置、后者链节点均保持纯文本形态(无 `<a>`),报告不含仓外路径链接;渲染退出码
  0,`--check` 不报不一致

#### Scenario: manifest rows 保持纯文本

- **WHEN** 渲染完成产数据文件与 manifest,HTML 表格调用链列含源文件链接
- **THEN** `sdr_manifest.json` 与 `sdr_report_data.json` 对应行 `chain`/`entry` 字段均为
  纯文本短形(不含 `<a>`/`href` 等任何链接语法/HTML 标记),与「去链接化后的表格单元格
  文本」一致

#### Scenario: 报告文件名与内容可追溯

- **WHEN** 对分支 `feature-pay` 于 2026-09-03 14:30:22 完成评审
- **THEN** 项目根出现 `mgh-sdr-feature_pay-20260903_143022.html`,头部含 branch/base/时间戳,
  章节一每行可溯源到 unit_id,章节二每条可溯源到 file:line(或 file)

#### Scenario: draft 缺 line 字段降级

- **WHEN** 某 `.done` draft 的 finding 无 `line` 字段(旧格式 draft)
- **THEN** 章节二该条位置写 `file`(无行号),有链接时渲染为不带 `#L` 锚点的文件链接,
  渲染不失败,`--check` 不视为不一致

#### Scenario: 部分单元 failed 不阻断渲染

- **WHEN** 10 个单元 9 个 `.done`、1 个 `.failed`
- **THEN** 渲染器汇总 9 份 draft 出报告,manifest `counts.failed_units = 1` + `failed_units[]`
  列出该单元 id 与 reason,报告诚实边界披露「1 个评审单元失败,该单元覆盖范围未复核」;失败
  单元不出现在章节一表格行(其覆盖未复核),仅在诚实边界披露

#### Scenario: 重复 finding 跨单元去重

- **WHEN** 同一接口路由的两个 hunk 被拆入同组或相邻单元,各产一条 `{dimension,route,file}` 相同
  的 finding
- **THEN** 渲染器按三元组去重合并为一条(line_hint 取并集),章节二仅一条 P-NN,引用它的
  单元行维度列共享该编号

#### Scenario: manifest rows 投影与表格一致

- **WHEN** 渲染完成产数据文件与 manifest
- **THEN** `sdr_report_data.json` `rows[]` 与 `sdr_manifest.json` `rows[]` 逐行一致,长度 =
  章节一表格数据行数,`unit_id`/`entry`/`chain`/`frontend_is`/`frontend_count` 与表格单元格
  一致(链接按「去链接化后的短形文本」比对);`issue_refs[]` 展平该行全部问题编号

#### Scenario: 报告披露排除集与分组统计

- **WHEN** 本次 run 排除了 120 个文件(测试 80/构建产物 30/静态资源 10)且 codegraph 捕获
  25 条变更集内调用边、向上锚定 8 条链
- **THEN** 报告诚实边界含排除计数与分类,manifest `counts.excluded_files == 120`;分组统计
  在报告头部「分组概览」可见,供操作者判断分组质量

#### Scenario: 报告离线自包含

- **WHEN** 渲染任意报告并在文本层面检查产物
- **THEN** HTML 内不含任何 `http://`/`https://` 的脚本、样式、字体、数据引用(外链图片同为
  零),样式与脚本全部内嵌,数据存在于内嵌数据块;断网环境下 file:// 打开全部章节可读、
  章节三图形可见

#### Scenario: 数据文件与内嵌数据一致且 --check 可校验

- **WHEN** 渲染完成,随后对同一 run 目录跑 `--check`
- **THEN** `<run-dir>/sdr_report_data.json` 存在、可解析,且与 HTML 内嵌数据块 JSON 等价
  (同数据两种载体);`--check` 退出码 0;人为破坏数据文件或内嵌块之一后 `--check` 退出码 2

#### Scenario: 章节三 SVG 零外部依赖且语义保留

- **WHEN** 某 branched 单元 `chain[]` 含一个 `branch_of` 分支宿主、一个 mapper 终端节点
  (`change=external`)与一个未变更节点(`†`)
- **THEN** 该单元章节三为内嵌 `<svg>`(非 mermaid 代码块、非 canvas、不加载任何图形库),
  mapper 终端边为虚线样式,未变更节点带 `†` 前缀,分支拓扑与 `chain[]` 一致;图形可缩放平移

#### Scenario: 视图筛选不回写数据

- **WHEN** 读者在章节一按 severity 或单维度筛选表格行
- **THEN** 仅不匹配行被隐藏(纯视图态),`sdr_report_data.json` 与 `sdr_manifest.json` 的
  `rows[]` 不因此变化;重新打开报告后全部行恢复
