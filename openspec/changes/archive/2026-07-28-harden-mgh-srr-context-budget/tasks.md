# Tasks — harden-mgh-srr-context-budget(srr 采纳)

> 依赖地基 `harden-mgh-init-context-budget` + sra 采纳 `harden-mgh-sra-context-budget`(共享 `sra-augment.md` 引擎)。
> 机制照搬地基。承 R2/R5.2/R5.3a/b/R5.5/R5.8/R5.9/R5.10。

## 1. srr intake 适配器

- [x] 1.1 `ingest_requirements.py`:增 `--materialize`/`--offset`/`--limit`/`--max-unit-bytes`/`--orch-budget-bytes`;per-unit
      物化到 `<out-dir>/inputs/<unit>.input.json`;`pending[]` 加 `input_path`/`bytes`/`oversize`;oversize 标注
      (`--split`/收窄,不切单元);页宽自动收紧(`effective_limit`/`shrunk:true`);退出码/依赖/cwd(承 R5.3a/b);
      保留无 `--materialize` 旧路径
- [x] 1.2 `ingest_requirements.py --check`:校验新增 `input_path`(绝对、落子树)+ `bytes`/`oversize` 字段(承 R5.9)

## 2. srr 渲染聚合披露

- [x] 2.1 `render_report.py`:读全部定稿(聚合输入)上报 `bytes`(stdout 字段);超 `--max-aggregate-bytes` → 在
      `srr_manifest.json::boundaries[]` + `security_review_report.md` 披露(P0 软边界;不阻塞)

## 3. srr 命令壳(双端)

- [x] 3.1 两份 `mgh-srr.md`「Orchestrator discipline」:增 recipe「需某单元完整输入 → `ingest_requirements --materialize`
      的 `pending[].input_path`;NEVER 整份读 sra-shape `change_context.json`,NEVER `py -c`,NEVER 内联传记录」
- [x] 3.2 两份 flow:统一「`ingest_requirements --materialize <inputs>` → 按 `offset`/`effective_limit` 分页迭代
      `pending[]`(透传 `input_path`)→ 复用 sra 引擎 stage 读 `input_path`」;翻页循环由编排器(NEVER wrapper `.py`)
- [x] 3.3 两份 parse 段 + flag 表:加 `--max-unit-bytes`/`--orch-budget-bytes`/`--max-aggregate-bytes` 及默认值
- [x] 3.4 两份 disclose:增「单次请求 ≤ 配置阈值;`oversize`/`shrunk`/聚合超限披露」;保持 R5.6 token 预算 + R5.10 纯净性

## 4. 契约 lint + 测试

- [x] 4.1 `tools/check_contracts.py`:扩 `ingest_requirements` flag + `mgh-srr.md` flag(R5.1 CLI lint)
- [x] 4.2 `tests/` 增 `ingest_requirements` 物化/分页/`--split` 单元/oversize 测 + 纪律回归(整份读 srr `change_context.json`
      在 `MGH_SRR_ACTIVE=1` 下被 hook 拦,exit 2 + recipe)
- [x] 4.3 性能不退化 + 零依赖 AST 扫描集不变 + R5.1 CLI lint 过

## 5. 版本 + 收尾

- [x] 5.1 `mgh-srr.md` 壳 + `ingest_requirements.py` bump 版本号
- [x] 5.2 `openspec validate harden-mgh-srr-context-budget --strict` 过;`/opsx:apply` ready(地基 + sra 先行)
