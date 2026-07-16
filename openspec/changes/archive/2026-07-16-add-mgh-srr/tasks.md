# Tasks — add-mgh-srr

> 顺序依 design.md「Migration Plan」:契约 → 两适配器(+`--check`)→ 命令壳双端 →
> `MGH_SRR_ACTIVE` hook 域 → `install.sh` → 单测 / lint / purity → 文档 → 版本号。
> stage 提示词 / subagent / 维度目录 / `merge_memory.py` **零新增**(逐字复用)。

## 1. 契约与 profile

- [x] 1.1 写 `core/contracts/srr/intake-report.md`:自由文本 intake 的 `change_context.json` shape delta(相对 sra:单 capability 默认、`endpoints/data_fields/role_hints` 可选 hint、`degraded` 标注字段)+ `security_review_report.md` / `srr_manifest.json` shape + `ingest`/`render` `--check` 规则。
- [x] 1.2 写 `core/profiles/srr.yaml`(profile 名 `srr`,引用复用的 sra subagent + 两新脚本)。

## 2. 输入适配器 `ingest_requirements.py`(标准库)

- [x] 2.1 骨架:`argparse`(`--doc <path|dir|->`、`--text <str>`/stdin、`--rules <path>`、`--split`、`--out <dir>`、`--dry-run`、`--no-interactive`、`--check`)+ `Usage:` docstring;stdout=结构化 JSON、stderr=进度,退出码 `0/1/2`;`sys.path` 自定位、`encoding="utf-8"`、任意 cwd 可跑(R5.3a)。
- [x] 2.2 text-native 抽取:`.txt/.md/.csv/.json` 原生读(完美,无 `degraded`)。
- [x] 2.3 `.docx` 抽取:stdlib `zipfile` 读 `word/document.xml`,**按 `<w:p>` 段落拼接所有 `<w:t>`**(含 `<w:tab/>`/`<w:br/>` 处理),命名空间正确;`degraded` 标注(列表编号丢失 / 文本框 / 嵌入对象)。
- [x] 2.4 `.xlsx` 抽取:`zipfile` 读 `sharedStrings.xml` + 各 `xl/worksheets/sheetN.xml`,解析 `t="s"`/`inlineStr`/数值;`degraded` 标注(日期=序列号 / 格式单位丢失 / 合并单元格)。
- [x] 2.5 `--text`/stdin 透传:逐字用,跳过抽取、无 `degraded`(D3 兜底口)。
- [x] 2.6 不支持格式(`.doc`/`.xls`/扫描 PDF/加密)→ 退出码 2 + stderr recipe(另存为 `.docx`/导出 `.csv`/复制到 `.txt`),不产半成品。
- [x] 2.7 产出 sra 同 shape `change_context.json`:`change`=文档名、`capabilities=[1]`、`requirements[]`=段落/section 标题作锚、`endpoints/data_fields/role_hints`=可选 hint(可空)、`candidate_controls`(若有 `--rules`,复用 prepare 的 category 派生 + 文件重叠逻辑)、`pending[]`(默认 1 项,绝对 `draft_path`/`done_marker`,resolve 进子树)、`memory`(读 `<project>/.mgh-sra/business_context.json`)。
- [x] 2.8 `--split`:按 markdown `#`/`##` 确定性切分 → 多 `pending[]`(扇出 = 脚本枚举,R5.3)。
- [x] 2.9 `--check`:`change_context` 结构完整 + `pending[]` 路径绝对且在 `project_root` 子树内 + `degraded` 字段合法。

## 3. 输出适配器 `render_report.py`(标准库)

- [x] 3.1 骨架:`argparse`(`--drafts-dir <abs>`、`--memory <path>`、`--out <dir>`、`--check`)+ stdout JSON / stderr 进度 / 退出码 `0/1/2`;自包含、任意 cwd。
- [x] 3.2 读定稿 draft(逐字读绝对路径,**NEVER** `py -c`)聚合 gaps / security_requirements / recommended_control。
- [x] 3.3 渲染 `security_review_report.md`(简体中文·简要·面向人读):按维度 / 锚点列缺口 + 可选复用建议(`--rules` 时)+ 澄清过的问 + 边界。
- [x] 3.4 渲染 `srr_manifest.json`:counts(`gaps`/`augmented_requirements`/`referenced_controls`/`clarifications_asked`/`unconfirmed_defaults`/`call_path_*`)+ `boundaries[]`(SRR 专属 + 复用 sra 五条)。
- [x] 3.5 输出落 `<out-dir>`(默认 `<project>/.mgh-srr/`);**NEVER** 写 `openspec/`。
- [x] 3.6 `--check`:报告 / manifest shape 完整 + 无 `openspec/` 路径被触及。

## 4. 命令壳双端(claude + opencode)

- [x] 4.1 写 `releases/claude-code/commands/mgh-srr.md`:薄壳(≤500 行 / ≤5000 tokens,R5.6),编排流(intake → 复用 sra a2/a3/a4 → render)+ stage→组件表 + 确定性调用 + 边界披露;`--help`/无参 → 打印 flag 表 STOP;复用 sra subagent + `merge_memory.py`(NEVER 写新提示词)。
- [x] 4.2 写 `releases/opencode/command/mgh-srr.md`:与 claude 壳编排流逐字对等(opencode 路径规约)。
- [x] 4.3 两壳 MD 纯净(R5.10):仅操作性内容,无研发态悬空引用(R5.x / FDn / 变更夹名 / `task.*.md` / dev-meta)。

## 5. 运行域 hook(`MGH_SRR_ACTIVE`)+ 双端 parity

- [x] 5.1 扩 `block-adhoc_scripts` 守卫(Python 标准库,单一判定源):加运行域 `MGH_SRR_ACTIVE`(平行 `MGH_SRA_ACTIVE`),`MGH_TARGET`=项目根判树(覆盖报告输出 + 项目记忆)。
- [x] 5.2 claude 端:`install.sh` 注入 `PreToolUse` 命令含 `MGH_SRR_ACTIVE`。
- [x] 5.3 opencode 端:`.ts` 插件 `tool.execute.before` 含同域(等价事件归一化 + 据退出码阻断;双端字节级 parity 守卫)。
- [x] 5.4 注:`MGH_SRR_ACTIVE` 在 opencode 仅启动时就绪才激活(fail-soft,承 sra 同款可靠性边界)。

## 6. `install.sh` 纳入 + 自检

- [x] 6.1 `install.sh` 镜像 srr 资产(命令壳双端 / 两新脚本 / profile / 契约;**复用 sra subagent 与提示词不重复分发**)。
- [x] 6.2 自检:校验族同目录共存 + fail-soft(install 不阻断,CI 必 fail,R5.8)。
- [x] 6.3 回归测:导入鲁棒(非脚本目录 cwd 子进程能跑)、性能不退化、零依赖 AST 扫描含两新脚本。

## 7. 单测 + 契约 lint + purity

- [x] 7.1 `tests/test_srr_ingest.py`:text-native 完美 / docx 跨 run 拼接不断词 / xlsx 单元格解析 / `degraded` 标注正确 / `--text` 透传 / 不支持格式退出 2 + recipe / `--split` 枚举 / `--check` 拒畸形。
- [x] 7.2 `tests/test_srr_report.py`:报告 + manifest shape / 简体中文 / `openspec/` 未被触及 / counts 取自 draft。
- [x] 7.3 `tests/test_mgh_srr_codegraph_parity.py`(若 sra 有 parity 测试则对齐):复用 sra 提示词未漂移、codegraph on/off 行为等价。
- [x] 7.4 扩 `tools/check_contracts.py`:提取双壳 MD 里 `ingest_requirements.py`/`render_report.py` 的所有 flag,对每个跑 `--help` 断言存在(R5.1 CLI lint)。
- [x] 7.5 扩 `tests/test_distributed_md_purity.py`:两壳 MD 不携带研发态悬空引用(R5.10)。
- [x] 7.6 扩 opencode hook parity 测试:`MGH_SRR_ACTIVE` 双端等价。

## 8. 文档 + 状态表 + 版本号

- [x] 8.1 写 `docs/mgh-srr-工作流程详解.md`(宣导版,平行 sra 文档风格:intake 三层 / 复用引擎 / 普通报告 / 诚实边界 / 与 sra 的关系)。
- [x] 8.2 `AGENTS.md` 命令表加 `/mgh-srr` ✅ + 简述;`README.md` 登记。
- [x] 8.3 `docs/upstream-index.md` 登记 mgh-srr = rewrite-original(无 vvah 源,与 sra 同性质)。
- [x] 8.4 bump `VERSION` + `CHANGELOG.md`(任何 `.md`/脚本改动触发,R5.8)。
