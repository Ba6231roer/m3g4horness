# test-convention-discovery Specification

## MODIFIED Requirements

### Requirement: Parse arguments and guard zero-token no-op

`/mgh-ut-init` SHALL accept `--target <dir>`(默认 `.`)、`--format opencode|claude`(默认 `opencode`;显式传
`claude` 渲染 `.claude/rules/test-*.md`)、`--out <path>`、`--rules-dir <path>`(opencode 详述文件目录,透传
`list_test_groups.py`/`assemble_test_rules.py`)、`--scope path:<dir>|package:<pkg>|file:<glob>`、`--resume`、
`--merge <partials-dir>`、`--skip-consistency`、抽样预算 flag(`--uniform-sample`/`--hetero-sample`/
`--subsplit-threshold`)、请求上下文预算 flag(`--max-unit-bytes`/`--orch-budget-bytes`/`--max-aggregate-bytes`)。
当无 actionable 参数或传 `--help` 时 SHALL 仅打印参数表并 STOP(零 token 消费)。ut-init **不**接受 `--language`
(本版 JVM-only,无下游消费者)或 `--config <profile>`(ut 是 LLM-first 流水线,无 profile 概念;`core/profiles/`
无 ut 条目)。

#### Scenario: No actionable args prints flag table and stops

- **WHEN** 以无参或 `--help` 调用 `/mgh-ut-init`
- **THEN** 仅打印 flag 表并 STOP,不扫描、不 spawn subagent、不产产物

#### Scenario: Omitted --format defaults to opencode

- **WHEN** 以 `--target .`(省略 `--format`)调用
- **THEN** 按 `--format opencode` 继续(`<target>/AGENTS.md` 惰性索引 + `docs/test-conventions/<cat>.md`),
  不报错、不 STOP;`run_config.json::format == "opencode"`

#### Scenario: Explicit --format claude overrides default

- **WHEN** 以 `--target . --format claude` 调用
- **THEN** rules 落 `<target>/.claude/rules/test-*.md`,`run_config.json::format == "claude"`
