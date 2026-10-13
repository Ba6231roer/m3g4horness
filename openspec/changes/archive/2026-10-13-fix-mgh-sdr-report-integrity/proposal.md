> **人话序** 现象:2026-10-13 深度评审在报告渲染器确认四条高危缺口:① LLM 草稿的 file 字段可以把 `javascript:` 脚本地址原样送进报告「位置」链接,复核人一点即执行——对评审"可能含攻击者影响的分支代码"这一现实威胁面是主交付物的注入缺陷;② severity 字段是数组/对象时渲染与校验双路径裸崩溃;③ 引述里出现 `<!--` 加 `<script` 时,HTML 解析器进入双转义状态,报告页面全部 JS 被当数据吞掉,报告成空白壳而校验检不出;④ 存在失败单元时简报表前端两列整体错位,一列残留占位、一列填上**别的接口**的值——降级运行下错误数据还写进三份载体。另有嵌套路由计数串位、死代码与恒假守卫。根因:路径清洗不查冒号、错型未防、转义闭集少一项、两趟循环对失败单元的过滤不对称。改什么:四处小修各配回归测试,失败形状先红后绿。怎么验证:`javascript:` 载荷降级纯文本、severity 错型落默认级、敌意引述下页面 JS 存活、失败单元存在时两列对齐,定向回归全绿。

## Why

- 评审(2026-10-13,基线 main HEAD `6e6ac63`)在 `core/scripts/render_sdr_report.py` 确认的缺陷,全部落在**报告这一主交付物**上,且 findings 的 file/chain 字段来自 LLM 草稿(引述受审仓库与外部前端仓源码,文件头 docstring 自认注入面——对安全评审工具,受审分支可能含攻击者构造的内容,提示注入是现实威胁):
  - **C3**:`_href_of` 相对路径分支只拦 `..`/空格/圆括号,不查冒号;`javascript:…`(无空格无圆括号的载荷)原样通过全部检查进入 `<a href>`;normpath 把 `//` 折叠为 `/` 但 WHATWG URL 解析对特殊 scheme 容忍单斜杠,载荷存活。`C:foo` 盘符相对路径同样漏网成坏链接。
  - **H1**:severity 为 list/dict 时 `_merge_findings` 不可哈希 TypeError,渲染与 `--check` 双路径裸 traceback、退出码 1(违约 0/1/2 契约),打破「draft 质量永不使渲染器崩溃、坏单元走 failed_units」的设计意图(hashable 错值已安全降级,唯非字符串漏防)。
  - **H3**:JSON 内嵌只防 `</script>`;数据含 `<!--` + `<script` 时 HTML 解析器进入 script-data-double-escaped 状态,真正的 `</script>` 被忽略,页面全部渲染 JS 被当数据吞掉——报告六章节空白(结构破坏,非 XSS);`--check` 的 regex 取块恰好停在浏览器忽略的那个终止符上,对敌意产物 exit 0(校验盲)。findings 引述外部前端仓 `.vue`/`.html` 片段天然可能携带该序列。
  - **H2**:第一趟建 rows 跳过 failed 单元、第二趟对**全量**单元 zip → 从首个 failed 起整体错一位:failed 行残留占位「—」,其后每行拿到前一单元的前端值,错误数据同步写进 manifest/data/HTML 三载体;`--check` 两边同错检不出。降级运行(最需诚实呈现的场景)数据损坏。
  - **M11**:前端两列用子串包含匹配 join,而 route_hits 按精确路由串计量——REST 嵌套路由(`/api/user` 与 `/api/user/list`)把短路由计数算到长路由头上,把「无前端使用」标成「有」(方向性错误,误导复核人)。
  - **L7/L8**:页面 `escapeHtml` 死代码且上方注释失实(削弱对真实安全性质的表述);`--check` 的「manifest 须在 run 目录」守卫因构造方式恒假,零效检查给人已设防假象。

## What Changes

- **C3**:`_href_of` 相对分支与最终 rel 的首段(`split('/')[0]`)含 `:` 即放弃链接化,降级纯文本(拦 `javascript:` 与盘符相对路径,一次判定覆盖两者);补 scheme 载荷与 `C:foo` 回归。
- **H1**:severity 取值单点守卫——`isinstance(sev, str)` 且在闭集内才采信,否则落默认级;渲染与 `--check` 同源函数一次修复;补数组/对象 severity 回归(退出码与产物形态双断言)。
- **H3**:`_json_embed` 转义链追加 `"<!--"` → `"<\u0021--"`(parse 等价,JSON/JS 字符串语义不变);补含敌意序列引述的端到端回归(页面 JS 存活 + 数据块语义等价)。
- **H2**:前端两列的单元侧与行侧过滤谓词同源(failed 过滤后 zip,或并入第一趟——取改动最小且不引入第二处谓词的实现,design 定夺);补 failed + 外部仓组合回归(现有用例恰好都缺该组合)。
- **M11**:前端两列 join 改精确匹配(整串相等,或分号段集合内精确命中);补嵌套路由计数回归。
- **L7**:删除死代码 `escapeHtml`,注释改为如实陈述(实际全程 textContent/setAttribute,无字符串级拼装)。
- **L8**:恒假守卫改为校验 `manifest['report']` 指向 repo 根(有真实价值:报告落仓根是产品承诺),或删除——design 定夺,取能提供真实保护者。
- 版本收口:`CHANGELOG.md` + `VERSION` bump。

## Capabilities

### New Capabilities

<!-- 无。 -->

### Modified Capabilities

- `security-design-review`:新增 requirement「报告渲染的输入敌意防御与降级路径数据保真」——链接化白名单语义、草稿错型容错、嵌入转义闭集、failed 单元下的行列对齐与前端两列精确 join;「统一问题记录汇总与确定性报告渲染」既有 requirement 的容错与诚实呈现承诺由实现违约修复兑现,不改其文本。

## Impact

- **代码**:`core/scripts/render_sdr_report.py`(C3/H1/H2/H3/M11/L7/L8,单文件)。
- **测试**:`tests/test_render_sdr_report.py`(新增 scheme 载荷、错型 severity、双转义、failed+外部仓组合、嵌套路由用例;现有 `HrefTest` 补冒角/scheme 用例)。
- **契约**:无新增 CLI flag;`sdr_report_data.json` schema 零变化(severity 恒为字符串、loc.href 可为空语义不变);HTML 报告结构零变化。
- **分发面**:零改动(渲染器为已分发叶脚本的 bug 修复,三面壳调用行不变)。
- **版本**:`CHANGELOG.md` + `VERSION` bump。
