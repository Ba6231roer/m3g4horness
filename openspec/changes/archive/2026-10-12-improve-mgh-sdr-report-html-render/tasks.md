# Tasks: improve-mgh-sdr-report-html-render

## 1. 渲染器数据层(先立 canonical 数据,后换呈现)

- [x] 1.1 `render_sdr_report.py`:把报告全量内容抽成单一数据 dict(头部元信息、单元行
      `rows[]` 纯文本短形、去重后 `findings[]` 含 P-NN、分支链图数据、诚实边界条目),
      现有 MD 渲染临时改为消费该 dict——中间态行为等价,确认无回归后再换呈现
- [x] 1.2 新增 `<run-dir>/sdr_report_data.json` 原子写出(canonical 数据文件,与 manifest
      并列;`rows[]` 字段与 manifest 纯文本语义一致)

## 2. HTML 呈现层(自包含单文件)

- [x] 2.1 内嵌 HTML 模板常量(骨架 + CSS + JS,分节注释):章节结构按 spec(头部/简报表/
      问题详述/分支调用链图/无问题单元/诚实边界),简体中文,零外部引用
- [x] 2.2 内嵌 JS 渲染逻辑:唯一 `escapeHtml` 转义入口、动态文本一律 `textContent`/属性
      转义(NEVER 拼接原文进 innerHTML);简报表渲染、severity/维度筛选(纯视图态)、
      P-NN 页内锚点跳转
- [x] 2.3 内嵌数据块写入:同一 dict 序列化进 `<script type="application/json">`,其中
      `</` 全部转义为 `<\/`;报告产物 `<repo>/mgh-sdr-<分支>-<ts>.html` 原子覆盖;移除
      `.md` 产出路径
- [x] 2.4 SVG 调用链图生成:确定性分层布局(入口 depth 0、depth=最长上游路径、同 depth
      首现序纵排、冲突纵向让位)、正交折线边、mapper 终端(`⇢`)虚线、未变更节点 `†`
      前缀、节点悬停提示 `file:line`、viewBox + 内嵌 JS 缩放平移(wheel + 指针拖拽);
      线性链单元不入章节三

## 3. `--check` 与确定性消费面同步

- [x] 3.1 `render_sdr_report.py --check` 扩展:数据文件存在且可解析、与报告内嵌数据块
      JSON 等价(解析比较)、报告文件若存在则为 `.html` 且含内嵌数据块与各章节锚点标记
      (文本级断言,不开浏览器);任一违例退出码 2
- [x] 3.2 `list_sdr_steps.py` render 步 `path_pattern` 改 `.html`;核对
      `resume_sdr_state.py` 渲染判定键仍为 `sdr_manifest.json`(零改动声明成立)
- [x] 3.3 `mgh_sdr_launch.py`:报告收集 glob 改 `mgh-sdr-*.html`,多分支收尾提示同步,
      新增 `--open`(默认 off,stdlib `webbrowser.open`,`--help` 契约同步)

## 4. 壳与文档面(三面镜像)

- [x] 4.1 三面命令壳 `mgh-sdr.md`(claude / opencode / dsh)step 4 章节描述与 Always
      disclose 同步:报告形态 `.html` 自包含、历史 `.md` 不迁移不回写、源文件链接在部分
      浏览器可能下载而非打开;dsh 面路径根 `mgh-core/`,三面逐字镜像(方言白名单五类之外)
- [x] 4.2 `AGENTS.md`:命令表 `/mgh-sdr` 行的报告描述、诚实边界节 sdr 报告形态 bullet
      同步;维护者私有文档区里的术语词典补新术语条目(自包含 HTML、canonical 数据文件等)
- [x] 4.3 核对 `README.md` 与分发面文档中的 sdr 报告形态字样并同步(无则声明零改动)

## 5. 测试与回归

- [x] 5.1 重写 `tests/test_render_sdr_report.py`(stdlib `html.parser` + JSON 断言):
      章节结构、数据文件与内嵌块 JSON 等价、自包含(无 http/https 外链)、P-NN 锚点
      与章节二条目一一对应、SVG 存在且 mapper 虚线/`†`/线性链排除、注入用例(数据含
      `<script>`/`</script>`/引号不破坏结构)、failed 单元不阻断/三元组去重/draft 缺
      `line` 降级/前端两列三态/排除集披露 沿用现行场景
- [x] 5.2 适配 `tests/test_mgh_sdr_launch.py`(glob `.html`、`--open` 契约)与
      `list_sdr_steps` 相关断言
- [x] 5.3 定向回归:`py tests/test_render_sdr_report.py tests/test_mgh_sdr_launch.py
      tests/test_distributed_md_purity.py` + `py tools/check_contracts.py` +
      `py tools/check_plain_language.py` + `py tests/test_zero_deps.py
      tests/test_no_compile_warnings.py` 全绿
- [x] 5.4 真仓人工验收(非 CI):一次真实 run 渲染,断网 Chrome 打开(拍板验收口径)——
      全章节可读、SVG 缩放平移、P-NN 跳转、筛选、源链接、大 run 目测流畅

## 6. 收尾

- [x] 6.1 `VERSION`/`CHANGELOG.md` bump(承 R5.8:任何分发面改动 bump 版本)
- [x] 6.2 主 spec `openspec/specs/security-design-review/spec.md` Purpose 摘要行
      「确定性汇总渲染一份 md 报告到项目根」改为自包含 HTML 报告表述(Purpose 属主
      spec 直改面,不走 delta)
- [x] 6.3 发布前全量回归(本 change 碰脚本 + 壳文案,属跨面):`for f in
      tests/test_*.py; do py "$f" || exit 1; done`
