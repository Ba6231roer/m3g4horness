# Tasks — fix-mgh-init-scout-merge-robustness

> 依赖顺序:`merge_scout.py`(边界校验 + 消费防御,核心)→ 生产侧三提示词 → 回归测 → 契约/纯净性/VERSION → 端到端验证。
> 每条可独立验收。遵守 AGENTS.md R1–R5(零依赖、文档简练、确定性脚本黑盒、双端对等)。
> 不改 `scout_candidates.json`/`controls_candidates.json`/`clusters.json` schema;不改 `form_clusters`/T1–T4。

## 1. `merge_scout.py` 边界校验 + 消费防御(核心)

- [x] 1.1 `_run_check` 增 `category` 非空校验:每条 candidate 缺 `category` 或为空 → violations 记 `{index, issue:"missing category"}`,并入既有退出码 2 路径(不新增退出码)。
- [x] 1.2 `_run_check` 破损 JSON 路径退出码 `1`→`2`(R5.9 边界失败);诊断从裸 `str(e)` 升级为 `JSONDecodeError.lineno/colno/msg` + 错位附近字节窗(≈±40 chars),stderr 出可操作诊断、stdout JSON 仍分流。
- [x] 1.3 `main()` 的 `json.loads`(`--scout`/`--candidates`/`--clusters` 三处,`:104/106/134`)包 try/except → 破损 JSON 出结构化 stdout 错误 JSON(`{error,file,lineno,colno,nearby}`)+ stderr 诊断、退出码 `1`、**无未捕获 traceback**。
- [x] 1.4 `_normalize`(`:35`)`c["category"]` → `c.get("category")`;缺失/空则**跳过**该 candidate + stderr warn(指明 index)+ 累计 `skipped`;stdout 成功摘要(`:143`)增 `skipped` 字段。
- [x] 1.5 **不**改 `discover_controls.form_clusters`;核验:scout 缺 `category` 候选经 `_normalize` 跳过后不进入 `form_clusters`,故 `form_clusters` 的 `c["category"]`(`:465/469/496`)无新风险。

## 2. 生产侧提示词(防患于未然,双 shell 共享 `core/`)

- [x] 2.1 `core/prompts/stages/init-scout.md`:Hard rules 增「每条 candidate `category` 必带」+「`evidence_snippet` SHALL 是单行、以 `'` 代 `"`、去 `\` 的安全子串(结构上不可能破坏 JSON 字符串)」。
- [x] 2.2 `core/prompts/stages/init-scout-merge.md`:增「合并时 **NEVER** 丢弃 `category`」+ 同 `evidence_snippet` 安全子串纪律(S4 合并 snippet 亦须保 JSON 合法)。
- [x] 2.3 `core/prompts/stages/init-scout-audit.md`:同 2.1(audit 产 `audit_found[]` 候选亦经 `merge_scout._normalize`,须同约束)。
- [x] 2.4 双端对等核验:三提示词在 `core/prompts/stages/`,claude/opencode 均从 `core/` 镜像(`install.sh` cp 整树),一次改双端;无 shell 专属副本须同步。

## 3. 回归测(`tests/test_merge_scout.py`,新增)

- [x] 3.1 `--check` 拒绝缺 `category` 的 `scout_candidates.json`:退出码 2,violations 报 index + `missing category`。
- [x] 3.2 `--check` 拒绝破损 JSON:退出码 **2**(非 1),诊断含 `lineno`/`colno`/`msg`。
- [x] 3.3 `--check` 合法输入通过:退出码 0,`ok:true`。
- [x] 3.4 `main()` 破损 JSON → 结构化 stdout 错误 JSON + 退出码 1,**无 traceback**(子进程 stderr 不含 `Traceback`)。
- [x] 3.5 `main()` `audit_found[]` 含缺 `category` candidate → 跳过 + stderr warn + stdout `skipped` ≥1,退出码 0,合法 candidate 仍折入。
- [x] 3.6 `main()` 合法 scout+regex+audit 折入回归:`scout_candidates_added` 计数正确、`clusters.json` 追加 scout 簇、regex 簇与 usage_sites 不变。

## 4. 契约 / 纯净性 / 零依赖 / VERSION

- [x] 4.1 `tools/check_contracts.py`:`merge_scout.py` **无新 flag**,既有 `--check/--candidates/--scout/--audit/--clusters/--sample` 仍双壳镜像(应不变,核验通过)。
- [x] 4.2 零依赖 AST 扫描:`merge_scout.py` 仅标准库(改动不引入新 import;`json.JSONDecodeError` 已在 `json` 内)。
- [x] 4.3 `tools/check_distributed_purity.py`:三提示词改动只加操作性约束(category 必带 / snippet 安全子串),无 dev-meta(`R5.x`/`FDn`/`Dn`/变更夹名)泄漏。
- [x] 4.4 `py tests/test_merge_scout.py` + 既有 `tests/test_scout_plan.py` / `test_list_scout_batches.py` / `test_init_*` / `test_stage_check.py` 全绿(回归)。
- [x] 4.5 bump `VERSION` `0.1.5` → `0.1.6`(承 R5.8)。

## 5. 端到端验证

- [x] 5.1 缺 `category` 场景:构造 `scout_candidates.json` 含一条缺 `category` candidate → `--check` 退出码 2 + 诊断;直调 `main()`(绕过 `--check`)→ 跳过 + `skipped`,不崩。
- [x] 5.2 非法 JSON 场景:构造 `evidence_snippet` 转义错位的 `scout_candidates.json` → `--check` 退出码 2 + `lineno/colno`;`main()` 结构化错误 exit 1,无 traceback。
- [x] 5.3 对照:合法 `scout_candidates.json` → `--check` exit 0,`main()` 折入成功;下游 `form_clusters`/T1/T2 契约不变(`clusters.json` wrapper + 簇 schema 不变)。
