## ADDED Requirements

### Requirement: Long-running deterministic Bash calls carry a per-call timeout

`/mgh-sra` 命令壳的编排器 SHALL 给**长跑确定性 Bash 调用**——尤其 `prepare_augment`/`merge_augment`/
`merge_memory`(及 `--check` 边界校验)——传一个慷慨的 per-call `timeout`(claude Bash 工具与 opencode
shell 工具均接受毫秒级 `timeout` 参数),使其在大仓上不被宿主默认超时(opencode 实测 60s / 官方 120s;
claude 120s)强杀。命令壳 SHALL 在边界/披露段说明:opencode 用户**可**经环境变量
`OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS`(默认 120000)提升全局默认,但该变量**须在 opencode
启动前就绪**(mid-session `export` 不被 opencode 插件进程继承,与 R5.7 `MGH_*_ACTIVE` 可靠性边界同根因);
per-call `timeout` 是跨宿主公共杠杆,可在会话中即时生效。本要求与 `control-discovery` 的同名横切 recipe
同形(承 `harden-mgh-init-shell-timeout`)。

#### Scenario: Shell recipe tells the orchestrator to pass a per-call timeout
- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-sra.md`
- **THEN** 两壳均显式要求 `prepare_augment`/`merge_augment`/`merge_memory` 等长跑确定性 Bash 调用携带
  per-call `timeout`

#### Scenario: opencode env-var boundary disclosed
- **WHEN** 审阅 `mgh-sra.md` 边界段
- **THEN** 其中明示 `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS` 须 opencode 启动前设置、mid-session
  `export` 不生效,并指 per-call `timeout` 为会话内即时生效的替代
