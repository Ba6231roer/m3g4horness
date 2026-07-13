## Why

`/mgh-init` 的 scout→merge 折入(`merge_scout.py`)在两种 LLM 产出的畸形
`scout_candidates.json` 下以**原始 traceback 崩溃**(非结构化错误、stdout 空、编排器无法决策):

1. **缺 `category`**:S4 `init-scout-merge` 合并时偶发丢弃个别 candidate 的 `category`。
   `merge_scout.py --check`(`:54-83`)只校验 `source/file/line`,**不校验 `category`** →
   过闸;`_normalize`(`:35`)用 `c["category"]` 直索引 → 未捕获 `KeyError`。audit 路径
   (`audit_found[]` 经 `main():111` 进 `_normalize`)更连 `--check` 都没过。
2. **非法 JSON**:`evidence_snippet` 内嵌原始代码文本,引号/反斜杠转义错误 → 整份 JSON 非法。
   `--check` 捕获了但返回**退出码 1**(非 2),而编排器闸门只在退出码 2 回退(`mgh-init.md:89`);
   于是放行到 `main()`,`json.loads`(`:106`)无 try/except → 原始 `JSONDecodeError` traceback。

两者同形:**LLM 产物可畸形,`--check` 未覆盖/退出码错位,`main()` 无防御 → 崩溃**。需在边界校验、
消费侧防御、生产侧提示词三处同时收口。

## What Changes

- **`merge_scout.py --check` 扩展(边界闸门,主防御)**:增「每条 candidate `category` 非空」校验;
  破损 JSON 的退出码由 `1` 改 `2`(R5.9 边界失败 → 编排器回退重跑 S4);诊断从裸 `str(e)` 升级为
  `JSONDecodeError.lineno/colno/msg` + 错位附近字节窗。
- **`merge_scout.py main()` 防御化(消费侧,belt-and-suspenders)**:`--scout`/`--candidates`/`--clusters`
  的 `json.loads` 包 try/except → 破损 JSON 出结构化 stderr+stdout 错误、退出码 `1`、**无 traceback**;
  `_normalize` 改 `c.get("category")`,缺失则跳过该 candidate + stderr warn + stdout `skipped` 计数
  (覆盖 `--check` 不校验的 `audit.json` 路径与直调 `main()` 场景)。**不**改 `discover_controls.form_clusters`
  (共享稳定脚本;`_normalize` 跳过即阻断畸形 candidate 进入)。
- **生产侧提示词(防患于未然)**:`init-scout.md`/`init-scout-merge.md`/`init-scout-audit.md` 三处
  (双 shell 共享 `core/prompts/stages/`,一次改双端):`category` 每条必带(S4 合并时 **NEVER** 丢弃);
  `evidence_snippet` SHALL 是**单行、`"`→`'`、去 `\`** 的安全子串——结构上不可能破坏 JSON 字符串,
  消除手转义脚枪。
- **回归测**:新增 `tests/test_merge_scout.py` 覆盖 `--check` 拒绝缺 category / 拒绝破损 JSON(退出码 2 +
  诊断)、`main()` 跳过缺 category / 破损 JSON 结构化错误、合法输入回归。
- **VERSION** `0.1.5` → `0.1.6`(承 R5.8)。

非目标(明确不做):**不**加 JSON salvage/恢复解析器(从半畸形文件抢救合法 candidate)——违 R5.9
「不带着破损产物继续」;改为 fail-loud + 可操作诊断 + 生产侧预防,回退重跑 S4 不行时用户据 line:col
手修(已验证可行,用户曾产 `scout_candidates_fixed.json`)。salvage 列为 design 的已考量备选。
**不**改 `scout_candidates.json`/`controls_candidates.json`/`clusters.json` schema;**不**改
`form_clusters`/T1–T4;**不**新增 CLI flag(`tools/check_contracts.py` 不变)。

## Capabilities

### New Capabilities
<!-- 无。本变更是对既有 control-discovery 能力的健壮性加固,不引入新能力。 -->

### Modified Capabilities
- `control-discovery`: `merge_scout.py --check` 边界校验扩展(增 `category` 非空 + 破损 JSON 退出码 2 +
  `lineno/colno` 诊断);scout 生产侧 `scout_candidates.json` SHALL 为合法 JSON 且每条 candidate 带非空
  `category`、`evidence_snippet` 为安全子串;`merge_scout.py` 折入 SHALL NOT 在畸形输入上崩溃(破损 JSON
  → 结构化错误退出码 1;缺 `category` → 跳过+告警+`skipped` 计数)。

## Impact

- **代码**:`core/scripts/merge_scout.py`(`_run_check`/`_normalize`/`main()`);`core/prompts/stages/
  init-scout.md` + `init-scout-merge.md` + `init-scout-audit.md`(双 shell 共享 core/,双端对等);新增
  `tests/test_merge_scout.py`。
- **契约/安装**:`merge_scout.py` CLI 无新 flag → `tools/check_contracts.py` 不变;`install.sh` 自检清单
  已含 `merge_scout`(无新脚本随装);VERSION bump。
- **下游零感知**:`controls_candidates.json`/`clusters.json` schema 不变;`form_clusters`/T1–T4 契约不变;
  `controls_inventory.json` 不变。
- **研发铁律对齐**:R5.9(边界校验 fail-loud 退出码 2 + 回退重跑)、R5.3b(stdout=JSON / stderr=诊断 /
  退出码 0-1-2 / 无 traceback)、R2(零依赖,仅用标准库 `json.JSONDecodeError.lineno/colno`)、
  R5.8(回归测 + VERSION bump)。
