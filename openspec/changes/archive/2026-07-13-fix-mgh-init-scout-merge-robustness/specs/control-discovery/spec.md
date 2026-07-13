## MODIFIED Requirements

### Requirement: Stage-boundary contract checks

每个 stage 产物的产出者 SHALL 暴露 `--check`(或独立 validator),编排器跑完一步、进下一步前 MUST
运行之;失败 MUST fail-loud(退出码 2)并回退重跑(泛化既有 `assemble_rules.py --check` 范式,承
openspec validate-at-boundary,FD7)。覆盖:`discover_controls.py --check`(candidates/clusters wrapper
+ 每条 `source` + cluster_id 唯一)、`plan_scout.py --check`(batches 非空除非 0 target、每批 bytes≤
budget、needs_slice 仅含超批文件)、`merge_scout.py --check`(每条 `source:"scout"` + `file:line` +
**每条 `category` 非空** + **破损 JSON(无法 parse)亦属边界失败、退出码 2** + 给 `JSONDecodeError` 的
`lineno/colno/msg` 与错位附近字节窗诊断)、`validate_inventory.py`(vvah design_controls 兼容 + evidence
锚点 + category→kind 归一)、既有 `assemble_rules.py --check`(rules 纯净性)。

`merge_scout.py --check` 对破损 JSON SHALL 返回退出码 `2`(非 `1`),使编排器闸门(仅在退出码 2 回退)
正确触发重跑 S4;诊断 SHALL 含 `lineno`/`colno`/`msg` 字段供定位。`category` 校验 SHALL 断言非空(不断言
枚举归属,枚举归一交给 `validate_inventory.py`)。

#### Scenario: Check passes on a well-formed artifact
- **WHEN** 编排器对刚产出的 `scout_plan.json` 运行 `plan_scout.py --check`
- **THEN** 退出码 0,编排器进入下一步

#### Scenario: Check fails loud on a corrupted artifact
- **WHEN** 某 batch 的 `bytes` 超过 `--scout-batch-bytes`(或 wrapper 损坏)
- **THEN** `--check` 退出码 2,编排器回退重跑该步,不带着破损产物继续

#### Scenario: merge_scout --check rejects a candidate missing category
- **WHEN** `scout_candidates.json` 的某条 candidate 缺 `category` 字段(或为空)
- **THEN** `merge_scout.py --check` 退出码 2,violations 报告该 candidate 的 index 与 issue,编排器回退重跑 S4

#### Scenario: merge_scout --check rejects malformed JSON with line:col diagnostics
- **WHEN** `scout_candidates.json` 不是合法 JSON(如字符串值内转义错位)
- **THEN** `merge_scout.py --check` 退出码 `2`(非 `1`),stderr/stdout 诊断含 `lineno`/`colno`/`msg` 与错位附近字节窗,编排器回退重跑 S4

#### Scenario: Inventory validated against design_controls schema
- **WHEN** T2 产出 `controls_inventory.json`
- **THEN** `validate_inventory.py`(或 T2 后 check)断言 vvah 兼容字段 + 每条 evidence 锚点 + category→kind 归一,失败退出码 2

## ADDED Requirements

### Requirement: Scout candidate JSON robustness at the merge boundary

LLM subagent 产出的 scout 候选 JSON SHALL 是合法 JSON,每条 candidate SHALL 携带非空 `category`,
`evidence_snippet` SHALL 是单行安全子串(以 `'` 代 `"`、去 `\`)——结构上不可能破坏 JSON 字符串。
产出者:S3 `init-scout`(per-batch `checkpoints/scout/<batch_id>.json`)、S4 `init-scout-merge`
(`scout_candidates.json`)、`init-scout-audit`(`audit.json::audit_found[]`);S4 合并时 MUST NOT 丢弃
`category`。该约束 SHALL 写入 `core/prompts/stages/init-scout.md`、`init-scout-merge.md`、
`init-scout-audit.md` 三份提示词(双 shell 共享 `core/`,一次改双端)。

`merge_scout.py` 折入(`main()`)SHALL **NOT** 在畸形输入上抛未捕获异常(原始 traceback):
- 破损 JSON(`--scout`/`--candidates`/`--clusters` 任一 `json.loads` 失败)→ stderr 出 `lineno/colno/msg`
  诊断、stdout 出结构化错误 JSON(含 `error`/`file`/`lineno`/`colno`/`nearby`)、退出码 `1`;
- 缺 `category` 的 candidate(含 `audit_found[]` 路径,该路径不经 `--check`)→ `_normalize` **跳过**该
  candidate、stderr warn、退出码 `0`,stdout 成功摘要 SHALL 含 `skipped` 计数显式披露丢弃数。

`_normalize` 取 category SHALL 用 `c.get("category")`(非 `c["category"]` 直索引)。本要求**不**改
`discover_controls.form_clusters`(共享逻辑;`_normalize` 跳过即阻断缺 category 候选进入)。

#### Scenario: merge_scout fold-in does not crash on malformed JSON
- **WHEN** `merge_scout.py --candidates … --scout <malformed.json> --clusters …` 被调用,且 `<malformed.json>` 不是合法 JSON
- **THEN** 进程退出码 `1`、**不**抛未捕获 traceback;stdout 为含 `error`/`file`/`lineno`/`colno` 的结构化 JSON,stderr 出可操作诊断

#### Scenario: merge_scout fold-in skips missing-category audit candidates
- **WHEN** `audit.json::audit_found[]` 含一条缺 `category` 的 candidate(该路径不经 `--check`)
- **THEN** `merge_scout.py` 折入跳过该 candidate、stderr warn 指明丢弃、退出码 `0`,stdout 摘要的 `skipped` 计数 ≥1,合法 candidate 仍正常折入

#### Scenario: merge_scout fold-in reports skipped count on success
- **WHEN** 折入完成且有 candidate 因缺 `category` 被跳过
- **THEN** stdout 成功摘要 JSON 含 `skipped` 字段(非 0),`scout_candidates_added` 仅计合法折入数

#### Scenario: Scout prompts require category and a JSON-safe snippet
- **WHEN** 审阅 `core/prompts/stages/init-scout.md` / `init-scout-merge.md` / `init-scout-audit.md`
- **THEN** 每份显式声明:每条 candidate `category` 必带(S4 合并 NEVER 丢弃)、`evidence_snippet` 为单行且以 `'` 代 `"`、去 `\` 的安全子串

#### Scenario: form_clusters untouched by the robustness fix
- **WHEN** 本变更生效后审阅 `discover_controls.py::form_clusters`
- **THEN** 其 `category` 取值方式与变更前一致(未改为 `.get`);缺 `category` 的 scout 候选在 `merge_scout._normalize` 即被跳过,不进入 `form_clusters`
