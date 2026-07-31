## ADDED Requirements

### Requirement: Merge path tolerates scout candidates missing required fields

`merge_scout.py::_normalize`(把 scout candidate 子集归一到完整 Candidate shape 的路径,非 `--check` 路径)SHALL 对缺任一必填字段(`category` 或 `file`)的 candidate 返回 `None`,由调用方 skip 并向 stderr 打印 warn(warn SHALL 如实指出缺哪个必填字段、candidate 的 `index`、以及可得的 `file:line` 定位),而非直索引抛 `KeyError` 中止整次 merge。`_normalize` 内所有字段取值 SHALL 统一用 `.get`,不得残留对必填字段的直索引。

此要求为 defense-in-depth:正常流程下 `merge_scout.py --check` 已挡缺字段候选(退出码 2 回退重跑);本要求覆盖 `--check` 被绕行(如编排器上下文压力下跳过 merge 闸门、或畸形 `scout_candidates.json`)时的脚本侧鲁棒性,使 merge 优雅丢弃个别畸形 candidate 并继续,而非整体崩溃。

#### Scenario: Candidate missing file is skipped with a warning, merge continues
- **WHEN** `merge_scout.py` 归一一条缺 `file` 字段的 scout candidate(且 `--check` 未先运行或被绕行)
- **THEN** `_normalize` 返回 `None`,该 candidate 被 skip;stderr 打印指出**缺 `file`** 的 warn(含
  candidate `index` 与可得 `file:line` 定位);merge 继续处理其余 candidate;进程**不**抛 `KeyError: "file"`,
  正常产出(退出码 0)

#### Scenario: Candidate missing category is still skipped (behavior unchanged)
- **WHEN** 某 scout candidate 缺 `category` 字段
- **THEN** 行为与现状一致:`_normalize` 返回 `None`,candidate 被 skip,stderr 打印指出缺 `category` 的 warn,
  merge 继续

#### Scenario: Candidate missing both required fields is skipped once
- **WHEN** 某 scout candidate 同时缺 `category` 与 `file`
- **THEN** candidate 被 skip 一次,stderr warn 如实列出所缺字段(含 `category` 与 `file`),不重复 skip、不抛异常

#### Scenario: Well-formed candidate is unaffected
- **WHEN** 某 scout candidate 含完整 `category` 与 `file`
- **THEN** `_normalize` 正常归一产出完整 Candidate dict,不打 warn,merge 正常进行
