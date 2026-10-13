# Tasks — fix-mgh-sdr-report-integrity

> 单文件收口:`core/scripts/render_sdr_report.py`。每组先红后绿;缺陷位置以 2026-10-13
> 评审明细为准,实施时以实际代码为准。

## 1. C3 — href 注入防线

- [x] 1.1 `_href_of` 相对分支:入口原始值首段含 `:` → return None
- [x] 1.2 归一后最终 rel 首段复查(normpath 折叠不得复活 scheme 载荷)
- [x] 1.3 回归(`HrefTest` 扩):`javascript:` 载荷、`javascript://`(双斜杠归一形态)、`C:foo` → 均降级纯文本;canonical 数据中字段原样保留;修复前红

## 2. H1 — severity 错型容错

- [x] 2.1 `_merge_findings` severity 取值单点守卫:`isinstance(sev, str) and sev in _SEVERITY_ORDER` 否则 `"medium"`;NEVER 在 `_run`/`_check` 调用点各写守卫
- [x] 2.2 回归:`"severity": ["high"]` 与 `"severity": {}` → 渲染与 `--check` 双路径退出码合规、该条落默认级;修复前双双裸 traceback(退出码 1)

## 3. H3 — 嵌入转义闭集

- [x] 3.1 `_json_embed` 追加 `.replace("<!--", "<\\u0021--")`(在既有 `</` 转义之后)
- [x] 3.2 回归(端到端):草稿引述含 `<!--<script>` → 渲染产物页面渲染 JS 存活(六章节完整)、嵌入数据与 canonical 数据语义逐值等价、`--check` exit 0;修复前页面 JS 被吞、报告空白壳

## 4. H2 — failed 单元行列对齐

- [x] 4.1 把「跳过 failed 单元」谓词提取为单一具名判定;前端两列的单元侧与行侧共用(design D3 首选:过滤后 zip)
- [x] 4.2 回归:1 failed + 2 ok 且 route_hits 命中一条 ok 路由 → 命中单元显示命中、未命中显示无、failed 行不残留占位/不继承他人取值;manifest/data/HTML 三载体一致、`--check` exit 0;修复前两列错位且校验放行

## 5. M11 — 前端两列精确 join

- [x] 5.1 `_frontend_pair` 子串包含改精确匹配(分号段集合内相等或整串相等)
- [x] 5.2 回归:`/api/user` 与 `/api/user/list` 前缀嵌套、命中计量仅覆盖其一 → 仅该路由显示命中;修复前短路由被标「有」

## 6. L7/L8 — 死代码与恒假守卫

- [x] 6.1 删除页面 `escapeHtml` 死函数;上方注释改为如实陈述(textContent/setAttribute 全程,无字符串级拼装)
- [x] 6.2 `--check` 恒假守卫改为校验 `manifest['report']` 解析后落在 repo 根内;回归:report 指向仓外路径 → exit 2

## 7. 收口

- [x] 7.1 定向回归:`python tests/test_render_sdr_report.py`;顺手 `python tests/test_zero_deps.py`、`python tests/test_no_compile_warnings.py`
- [x] 7.2 `python tools/check_contracts.py`、`python tools/check_distributed_purity.py`
- [x] 7.3 `CHANGELOG.md` + `VERSION` bump
