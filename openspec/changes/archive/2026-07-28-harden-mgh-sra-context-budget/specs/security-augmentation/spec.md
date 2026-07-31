# security-augmentation Delta

承 `harden-mgh-init-context-budget`(泛化):`/mgh-sra` 的 a3 per-capability 扇出采纳 `request-context-budget`
横切能力——`prepare_augment.py` per-capability **输入物化**(`change_context.json` 的全 cap requirements +
candidate_controls + memory 切成 per-cap input 文件)+ slim 分页 `pending[]` + 字节预算;编排器 **NEVER** 整份
读 `change_context.json`;`sra-augment` 读自己的 `input_path`。机制统辖见 `request-context-budget`。

## MODIFIED Requirements

### Requirement: Enumerate per-capability augmentation jobs with absolute draft paths

`prepare_augment.py` SHALL 输出 `pending[]`(每 capability 一个增补工作单元),每项 MUST 含 `capability`、
`draft_path`(绝对路径,`<change-root>/.mgh-sra/drafts/<cap>.md`,`Path.resolve()`)、`done_marker`、
`input_path`(绝对,per-capability 完整输入)、`bytes`、`oversize`。变更无 capability specs 时 `pending[]` 含
单个整体增补单元。所有 draft / input 路径 MUST 落在 `MGH_TARGET`(项目根)子树内。`prepare_augment.py` SHALL
支持 `--materialize <dir>`(把每 capability 的 `requirements[]` + 相关 `endpoints`/`data_fields`/`role_hints` +
`candidate_controls` 切片 + **增补后** `memory` 写到 `<dir>/<cap>.input.json`,从 `change_context.json` 切出,
脚本内部读聚合不进编排器上下文)、`--offset`/`--limit`(分页 `pending[]`)。单 cap input `bytes` >
`--max-unit-bytes` 时 SHALL 标 `oversize:true` + recipe(分变更 / `--focus` 收窄;**不**切分 capability,
sra-augment 需整 cap 视图)。当某页字节 > `--orch-budget-bytes` 时 SHALL 自动收紧 `--limit`、报
`effective_limit`+`shrunk:true`。`sra-augment` SHALL 读自己的 `input_path`(该 cap 的完整输入)而非编排器内联
传 `change_context` 切片。编排器 MUST NOT 整份读 `change_context.json` 进其请求上下文。

#### Scenario: Pending lists one job per capability with absolute draft + input paths
- **WHEN** 变更触及 3 个 capability
- **THEN** `pending[]` 含 3 项,各自 `draft_path`/`input_path` 为绝对路径且位于 `<change-root>/.mgh-sra/` 子树

#### Scenario: Draft/input paths stay under the project subtree
- **WHEN** 编排器把 `draft_path`/`input_path` 透传给 subagent
- **THEN** 二者解析后位于 `MGH_TARGET`(项目根)子树内;漂出子树触发 hook 拦截(退出码 2)

#### Scenario: sra-augment reads its own per-capability input file
- **WHEN** a3 扇出一个 capability,编排器 spawn `sra-augment`
- **THEN** `sra-augment` 输入含绝对 `input_path` → `<change-root>/.mgh-sra/inputs/<cap>.input.json`(该 cap 的
  requirements + endpoints/fields/role_hints + candidate_controls + memory),其 `bytes` ≤ `--max-unit-bytes`;
  编排器不内联传 `change_context` 切片,不整份读 `change_context.json`

#### Scenario: Oversize capability is flagged not sharded
- **WHEN** 某 capability input `bytes` > `--max-unit-bytes`
- **THEN** `prepare_augment.py` 标 `oversize:true` + recipe(分变更 / `--focus` 收窄);**不**切分 capability

#### Scenario: Work-list page shrinks to the orchestrator budget
- **WHEN** 一页 `pending[]` 序列化字节 > `--orch-budget-bytes`
- **THEN** `prepare_augment.py` 自动收紧 `--limit`,stdout 报 `effective_limit` + `shrunk:true`,编排器翻页
