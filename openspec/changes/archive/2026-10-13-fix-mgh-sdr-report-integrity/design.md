# Design — fix-mgh-sdr-report-integrity

> 修复对象:2026-10-13 评审在 `render_sdr_report.py` 确认的 C3/H1/H2/H3/M11/L7/L8。
> 单文件收口;每条配先红后绿的回归用例。

## D1 — C3 修法:「首段含冒号即放弃链接化」,非 scheme 白名单

- **否决白名单**(只放行 `http/https/file` 等):维护成本高、变体风险大(`java\nscript:`
  形态、tab/换行洗白),而报告链接的**唯一合法用途是仓内相对路径**(产品已承诺源文件链接
  为仓内相对路径)——凡是"像 scheme 或盘符"的取值都没有合法场景。
- **判定点两处**:① `_href_of` 相对分支入口的原始值;② 路径归一(normpath)后的最终 rel——
  normpath 把 `//` 折叠为 `/`,而 WHATWG URL 解析对特殊 scheme 容忍单斜杠
  (`javascript://…` → `javascript:/…` 仍可解析),因此仅查入口会被归一"洗白",最终值必须
  复查。判定式:`rel.split('/')[0]` 含 `:` 即 `return None`(降级纯文本)。
- canonical 数据文件中该字段**原样保留**(只不做链接,不删数据)——复核人仍可读到 LLM
  声称的位置,诚实边界不收缩。

## D2 — H1 修法:单点 isinstance 守卫,双路径自然同源

- `_merge_findings` 的 severity 取值点改为:`sev = f.get("severity")`,采信条件
  `isinstance(sev, str) and sev in _SEVERITY_ORDER`,否则 `"medium"`。
- 渲染(`_run`)与 `--check`(`_check`)共用该函数 → 一处修复双路径生效,NEVER 在两个
  调用点各写一份守卫(谓词漂移风险)。
- stderr 允许对"非字符串 severity 被降级"给一次性提示(诊断流,不进 stdout 契约);是否
  提示由实现取简,spec 只要求不崩不静默进产物。

## D3 — H2 修法:过滤谓词同源(过滤后 zip 为首选)

- **首选**:`zip(rows, [u for u in _sorted_units(g_units) if u.get("status") != "failed"])`
  ——过滤条件与第一趟建 rows 跳过 failed 的谓词**提取为同一个具名判定**(常量或函数),
  两处消费同一判定,杜绝第二处谓词漂移。
- 备选(并入第一趟循环):耦合更大——需确认 route_hits 与 external 数据在第一趟时已聚合
  (聚合顺序是实现细节,牵动更大);仅当首选实现中发现行/单元序不一致时才升级。
- 回归必须覆盖「failed + 外部仓命中」组合(评审确认现有三个相关测试恰好都缺此组合):
  1 failed + 2 ok 且 route_hits 命中其中一条 ok 路由 → 命中单元显示命中、未命中显示无、
  failed 行不显示他人取值。

## D4 — H3 修法:`<!--` 转义为 `<!‑‑` 的 parse 等价形态

- `_json_embed` 转义链在既有 `.replace("</", "<\\/")` 后追加
  `.replace("<!--", "<\\u0021--")`(`\u0021` = `!`)。
- **为何有效**:HTML 解析器的 script-data-double-escaped 状态由**字面** `<!--` 触发;
  数据中出现 `\u0021` 转义形后字面序列不存在,解析器不再进入该状态,页 JS 不被吞。
- **为何无损**:JS/JSON 字符串字面量中 `<\u0021--` 与 `<!--` 反序列化后逐字符相等
  (parse-identical)——嵌入数据经 JS `JSON.parse` 后与 canonical 数据文件语义逐值等价,
  `--check` 的同源比对继续成立(两侧同经 `_json_embed`)。
- 模板侧数据块终止符同行紧随注释的结构不动(转义后该结构不再构成危害)。

## D5 — M11 修法:精确匹配

- `_frontend_pair` 的 `rt in main` 子串包含改为精确匹配:main 为分号连接的多路由串时,
  按「分号段集合内存在等于 rt 的段」判定;单路由时整串相等。route_hits 的计量本身是精确
  的,join 精确化后双向一致:既不把短路由计数算给长路由,也不漏报。

## D6 — L7/L8:删死代码,守卫改真实校验

- L7:删除页面 `escapeHtml` 死函数;其上方失实注释改为如实陈述(页面全程
  textContent/setAttribute,无字符串级 HTML 拼装——这才是真实的安全性质,写对它比留着
  死函数与失实注释更有价值)。
- L8:`--check` 的「manifest 须在 run 目录」守卫因构造方式恒假 → 改为校验
  `manifest['report']` 解析后落在 repo 根内(报告落仓根是产品承诺,该校验有真实拦截力:
  报告写到别处即 exit 2)。

## 测试与验收口径

- 定向回归:`tests/test_render_sdr_report.py`;新增用例:
  - `HrefTest` 补:`javascript:` 载荷(无空格无圆括号)、`//` 归一洗白形态、`C:foo` 盘符
    相对路径——均断言降级纯文本;
  - severity 数组/对象:渲染与 `--check` 双路径退出码 + 产物 severity 落默认级;
  - 含 `<!--<script>` 引述的端到端:页面 JS 存活(断言 `</script>` 计数/结构)+ 数据
    语义等价 + `--check` exit 0;
  - failed + 外部仓组合行列对齐(见 D3);
  - 嵌套路由不串位(见 D5)。
- 每条用例修复前红、修复后绿;`tests/test_zero_deps.py` / `tests/test_no_compile_warnings.py`
  顺手。不跑全量(非跨面改动)。
