## Context

- **真仓实测(唯一承重证据)**:企业 java web 仓首跑 401 单元,~24–32 单元/百分钟,预计
  9–10h;slice 名单呈 `AaaBbbController__*.slice.md` + `AaaBbbService.slice.md` +
  `AaaBbbServiceImpl.slice.md` + `AaaBbbServiceTest.slice.md` + 各 Dto 独立散落。
- **源码定位的三个叠加根因**(`core/scripts/diff_group.py`):
  1. **无排除集**:测试树/构建产物/静态资源全量进入分组;callchain 模式第 5 步
     (`diff_group.py:778-781`)对 java 残余**每文件一个 standalone 单元**(上游 change D1
     的「拆多个不硬塞」粒度决策),`AaaBbbService.slice.md` 散落形态即源于此。
  2. **向上锚定缺失**:`_build_units_callchain` 步骤 3 只保留两端均在**变更集内**的边
     (`diff_group.py:719-724`),`_cg_edges` 已返回的未变更 caller 边被 `if e in adjacency`
     丢弃;「controller 未动、只改 Service/Impl/Dto」时变更集内无路由锚点 → 全体散落。
  3. **per-route 粒度**:每个变更路由方法独立闭包成单元(`diff_group.py:726-760`),同
     controller 改 10 个端点 = 10 个 subagent。
- **可观测缺口**:`codegraph:true` 仅是模式开关,无捕获率/锚定统计,真仓无法诊断「分组为什么
  没合并」。
- **codegraph CLI 已核实**:`callers/callees <sym> --json` 返回 `{name, filePath, startLine}`
  (filePath 相对 repo 根,正斜杠不保证——现码已做 `\` 归一);`node --file --symbols-only`
  是 markdown 符号表,无机器 endLine(上游 change D2 已裁定不作边界源)。
- **约束**:R2(零 pip;codegraph 仍是可选宿主二进制)、R5.3a/b(CLI 契约增量向后兼容、
  `pending[]` shape 不变、stdout/stderr 分流)、R5.9(`--check` 同步扩展)、R5.10(壳零
  dev-meta)、R5.6(壳 ≤5K tok,flag 表增量最小化)。

## Goals / Non-Goals

**Goals:**
- 单元数从 O(变更文件) 降到 O(变更接口链):真仓重跑预期 401 → 数十量级(验收看实测,不写死数)。
- 「codegraph 是否生效/捕获多少」从猜测变为 stdout 可诊断。
- 排除/锚定/合并全部确定性、可复现、可 `--check`;codegraph off 时行为与非回归基线等价
  (排除过滤器除外——它两模式共用且独立披露)。

**Non-Goals:**
- 不改 fan-out 派发机制、波次状态机、draft schema、render 去重算法。
- 不做 tree-sitter 调用链后端;不把 codegraph 变硬依赖。
- 不做「智能」测试影响分析(排除是文件级闭集,非调用图级)。
- 不改 mgh-sra/srr/init 的任何行为。

## Decisions

### D1 — 排除过滤器:分组前置的确定性闭集,双模式共用,`--include-excluded` 兜底

- **位置**:在 `parse_diff` 之后、`_build_units*` 之前对 `file_diffs` 过滤(单点,两模式天然
  共用;排除文件不进 `finfo`/`standalone`,自然零单元)。
- **闭集规则**(实现为脚本内常量表,逐条带 reason 标签):
  - `test-tree`:路径段 `src/test/`、`/test/`、`/tests/`(java 惯例 `src/test/java` 全覆盖;
    python/前端 `tests/` 一并收);文件名 `*Test.java`、`*Tests.java`、`*IT.java`。
  - `build-output`:顶级或任意级 `target/`、`build/`、`out/`、`dist/` 路径段。
  - `generated`:`generated/`、`generated-sources/` 路径段。
  - `static-asset`:扩展名闭集 `.png .jpg .jpeg .gif .ico .svg .webp .bmp .woff .woff2
    .ttf .otf .eot .map .min.js .min.css .pdf .zip .gz .jar .class`。
  - `lockfile`:`package-lock.json`、`yarn.lock`、`pnpm-lock.yaml`。
  - `build-script`:`pom.xml`、`build.gradle`/`build.gradle.kts`、`settings.gradle*`、
    `mvnw*`、`gradlew*`。
- **不排除**(显式白名单语义,写进 docstring):`*.sql`、`*Mapper.xml`、`application*.yml`/
  `*.properties`/`logback*.xml`——六维度检查面(SQL 注入/敏感信息/配置鉴权),且 standalone
  目录聚簇本就便宜。
- **披露**:stdout/grouping.json `excluded{count, by_reason{test-tree: n, ...}}`;render 报告
  诚实边界第 ⑦ 条披露(承 spec);`--include-excluded`(store_true)置空排除并恢复全量。
- **备选**:「git diff 排除 pathspec」(`.:(exclude)src/test/**`)在 git 侧做——被拒:排除
  集分散进命令行、`--check` 无法复核排除原因分类、git pathspec 语法跨平台脆弱。脚本侧闭集
  单点 + 理由分类可审计。〔确定性 + 可披露 + 可兜底〕

### D2 — 向上锚定:复用已返回的 callers 边,≤2 跳确定性找路由,零新增 codegraph 查询

- **数据流**:`_cg_edges` 现返回 `(callers, callees)`;改为**原样留存** callers(含未变更
  符号,折叠为 `filePath::name` 键,与现码同形)。对无变更路由可归属的变更符号,沿
  callers 向上 BFS ≤2 跳;对途经/终点符号跑**确定性本地注解扫描**(读该 filePath 的 branch
  内容,复用 `_base_route` + `_method_mappings` + `_java_symbols`,同一边界源)识别其是否
  (a) 是路由方法(携带方法级 mapping 注解)→ 锚定;(b) 非 java / 解析失败 → 断链。
- **命中**:变更符号(及其变更集内可达下游)并入该路由的 interface 单元;路由方法自身无
  hunks,slice 以**有界源码片段**呈现(路由方法 `_brace_end` 域 + 类 base route + 权限注解
  块,复用现有 `_anno_block`;片段上限 ~60 行,超长截断标注)。`ann_ctx` 机制沿用(已有
  `Annotation context` 渲染段),新增 `upstream-route` 上下文类型。
- **多锚定冲突**:一个变更符号向上命中多个路由(≤2 跳内两条链)→ 按现有共享下游语义**按
  接口拆**(hunk 重复进各单元,render 去重)——不新增语义。
- **循环与预算**:BFS visited 集防环;途经非变更符号**不再向下扩展**(只沿 callers 向上),
  途经符号仅作锚定判定,不产生单元。
- **查询成本**:**零新增**——callers 边本来就在 `_cg_edges` 返回值里,只是此前被过滤;途经
  符号的路由判定是本地文件读 + 正则,无 LLM、无子进程。
- **备选**:「把途经符号也作为图节点做全量闭包」被拒:闭包会拉入无关业务链,单元体积失控,
  且违背「只关心变更集」的边界。〔链归位 + 零成本 + 有界〕

### D3 — 共享链合并:同 controller 文件内,下游变更符号可达集相同的 route 合一

- **判定**:对同文件内每个变更 route 的闭包(步骤 4 现产物)+ 向上锚定归入的符号集,取
  **可达集指纹**(排序后的变更符号键元组);指纹相同或互为子集且同文件 → 合并一个单元。
- **route 字段**:合并单元 `route` = 各路由串分号连接(如 `/user/detail;/user/list`),
  `unit_id` 取 controller 词干;subagent 对多路由单元逐路由判定(draft 每 finding 自带
  `route`,schema 不变)。
- **跨 controller 不合并**:不同 controller 文件的 route 即使下游指纹相同也保持拆分(判定
  锚点 = 单个 controller 的鉴权面,跨文件合并会稀释;共享下游 hunk 重复进各单元,render
  去重)——承上游 D4,收窄其作用域到「跨文件」。
- **字节预算**:interface 单元新增 `--max-interface-bytes`(默认 256KB,≈64K tok 上界余量);
  合并后超限 → 按 route 组**确定性拆续单元**(`unit_id` 带 `-part2` 形态后缀;`route` 字段
  保留本 part 承载的路由串),`pending[]` 各 part 独立 `input_path`/`done_marker`。
- **备选**:「per-controller 无条件合并全部 route」被拒(用户评审已选共享链合并,粒度优先);
  「不设 interface 预算,靠 `--max-standalone-bytes`」被拒:interface slice 现无任何上限,
  合并放大后单 subagent 上下文可被打爆。〔单元数降 + 粒度不稀释 + 上下文有界〕

### D4 — java 残余回归目录聚簇(修正上游 D1 的粒度决策)

- 上游 change 的「java 残余每文件一单元」在真仓被证伪:锚定/闭包覆盖不到的 Service/Impl/
  Dto 残余是散落大头。改为与 `residual_other` 同路径:`_cluster_standalone_sel` + `cap`。
- **体积护栏**:java 残余簇沿用 `--max-standalone-bytes`(64KB);合并后 slice 首部列文件清单
  + 各文件符号表(方法名 + 行域,来自 `finfo.syms`,有界),subagent 仍有方法级寻址能力。
- **诚实边界更新**:报告第 ② 条措辞从「漏分组接口退入独立单元」改为「漏分组接口/链退入
  目录聚簇单元(粒度粗但覆盖不丢)」。
- 这是**有实测依据的回退**,不是软化:拆分的本意是防「不相关的链硬塞一个上下文」,但目录
  聚簇同样达成隔离(按物理模块聚),且单元数 O(目录) 而非 O(文件)。〔单元数降 + 隔离语义
  保持 + 少数残余合并便宜〕

### D5 — `codegraph_stats` 可观测:stdout + grouping.json + 报告披露

- 字段:`{symbols_queried, edges_captured(含未变更端点), edges_in_changed_set,
  anchors_changed(变更路由锚), anchors_upstream(向上锚定命中), chain_merged(合并掉
  的 route 数), excluded_files}`;codegraph off 时全零但结构在(诊断「为什么没走调用链」
  = probe 失败时 stderr 给原因:`no .codegraph dir` / `no binary`)。
- stderr 摘要行现码已打 unit 计数,追加排除计数 + 锚定/合并摘要;`render_sdr_report.py`
  读 grouping.json(或 manifest 透传)把统计写进报告头部「分组概览」小节 + 诚实边界。
- 〔真仓可诊断 + 零成本 + 承 R5.4 可观测精神〕

### D6 — 契约与接线:纯增量 flag、shape 不变、双壳 + lint 同步

- 新 flag:`diff_group.py` 增 `--include-excluded`、`--max-interface-bytes`(R5.1:双壳
  flag 表 + `tools/check_contracts.py` `DIFF_GROUP_REQUIRED_FLAGS` 同步);launcher 无需
  新 flag(默认值即新行为),`mgh_sdr_launch.py` 仅在提示词步骤 2 示例追加两个 flag 的
  可选项说明(可选,不强制)。
- `pending[]` shape 不变(字段集不动;`route` 值域扩展为可含 `;`);`unit_bytes`、marker、
  drafts 路径派生规则不变;`--check` 新增:part 单元的 `input_path` 齐备 + `route` 多值形态
  合法 + `excluded` 结构类型校验。
- 双壳 `mgh-sdr.md` 纪律段:排除集一句 + `--include-excluded` 兜底一句 + `codegraph_stats`
  诊断一句(各 ≤2 行,R5.6 预算内);`sdr-task.md` 增「多路由单元逐路由判定」「上游锚定
  上下文段语义」各 1–2 行。

## Risks / Trade-offs

- [排除集误伤(某仓把主源码放 `src/test/` 之外的非常规路径,或 mapper XML 放 `build/` 下被
  当产物)] → 排除集是路径段/扩展名闭集;报告披露排除清单计数,`--include-excluded` 一键兜底;
  mapper-in-build 属非常规布局,披露后可人工识别。
- [向上锚定拉入超长路由方法片段,interface slice 膨胀] → 片段有界(方法体 + 注解块,~60 行
  上限截断标注)+ `--max-interface-bytes` 硬顶 + part 拆分。
- [合并单元让单 subagent 承载多路由,判定稀释] → 仅同文件 + 可达集相同/子集才合并;多路由
  单元 task 模板要求逐路由判定、finding 自带 route;超预算先拆 part 再派发。
- [锚定途经符号的路由判定误判(本地正则 vs 真实框架路由)] → 与现有注解启发式同一边界源、
  同一误判率;误判后果 = 多并/少并一条链,退化为粗/细粒度,不丢覆盖;报告统计暴露
  `anchors_upstream` 供人工核对。
- [排除后 diff 为空(纯测试分支)] → `empty:true` 分支现有语义覆盖(渲染「无变更」报告);
  stderr 说明「全部文件被排除」与零 diff 区分。
- [shared hunk 在合并+拆分组合下重复放大] → 重复仅发生在真共享;`unit_bytes` 预算 + render
  三元组去重兜住(与上游 D4 同一结论)。

## Migration Plan

纯增量:重跑 install 覆盖 `diff_group.py`/`render_sdr_report.py`/双壳/`sdr-task.md`;无
schema 迁移、无状态迁移(旧 run 目录的 grouping.json 无新字段,`--check` 对缺字段按「结构
可选」处理不回溯校验)。回滚 = 还原脚本旧版。真仓验收:同 base/branch 重跑,对比
`grouping.json` 单元数 + `codegraph_stats`(401 → 预期数十;验收看实测不写死)。

## Open Questions

- `codegraph callers` 的 `--limit 500` 上限在超大仓是否够(单符号 caller 超千的极端);现网
  撞顶时该符号 callers 被截断 → 锚定漏链,`codegraph_stats.edges_captured` 可暴露异常值,
  按需再调。
- 排除集是否需要仓级自定义(如 `.mgh-sdr/exclude-globs`);首版闭集 + `--include-excluded`
  已覆盖显式需求,仓级配置等真仓出现第二类误伤再加。
