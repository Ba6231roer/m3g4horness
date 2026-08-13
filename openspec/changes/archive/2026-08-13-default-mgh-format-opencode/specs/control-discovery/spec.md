# control-discovery Specification

## MODIFIED Requirements

### Requirement: Parse arguments and guard zero-token no-op

`/mgh-init` SHALL accept `--target <dir>`(默认 `.`)、`--format opencode|claude`(默认 `opencode`;显式传
`claude` 渲染 `.claude/rules/*.md`)、`--out <path>`、`--scope <dir|package>`、`--language <lang>`、
`--config <profile>`、`--include-dotfiles`(默认关;传则回退到扫描点前缀路径,见「Skip dot-prefixed paths
during discovery」)、`--include-tests`(默认关;传则回退到扫描测试源码树,见「Skip test source directories
during discovery」)。当无 actionable 参数或传 `--help` 时,系统 MUST 仅打印参数表与指向 `task.260630.md`
的说明后**停止,不消耗 token、不做任何分析**。

#### Scenario: Omitted --format defaults to opencode

- **WHEN** 用户运行 `mgh-init --target ./svc` 未提供 `--format`
- **THEN** 系统按 `--format opencode` 继续(`<target>/AGENTS.md` 惰性索引 + `docs/security-controls/<cat>.md`),
  不报错、不停止;`run_config.json::format == "opencode"`

#### Scenario: Explicit --format claude overrides default

- **WHEN** 用户运行 `mgh-init --target ./svc --format claude`
- **THEN** rules 落 `<target>/.claude/rules/security-*.md`,`run_config.json::format == "claude"`

#### Scenario: Help / no actionable args

- **WHEN** 用户运行 `mgh-init --help` 或不带任何参数
- **THEN** 系统打印参数表后停止,零 LLM 调用、零代码扫描

#### Scenario: --include-dotfiles is a recognized flag

- **WHEN** 用户运行 `mgh-init --target . --format claude --include-dotfiles`
- **THEN** `--include-dotfiles` 被 `discover_controls.py` 接受(argparse 不报 unrecognized),
  发现阶段纳入点前缀路径;该 flag 出现在 `--help` 参数表(承 R5.1,`--help` 即契约面)

#### Scenario: --include-tests is a recognized flag

- **WHEN** 用户运行 `mgh-init --target . --format claude --include-tests`
- **THEN** `--include-tests` 被 `discover_controls.py` 接受(argparse 不报 unrecognized),发现阶段纳入测试
  源码树(回退到引入测试目录排除前的行为);该 flag 出现在 `--help` 参数表(承 R5.1)
