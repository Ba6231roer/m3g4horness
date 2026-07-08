## ADDED Requirements

### Requirement: T3 rule-output paths are deterministic absolute values

T3 fan-out 的每个待跑 category 的**输出路径** SHALL 是由确定性枚举脚本产出的**单一权威绝对路径值**,
而非相对路径或占位符模板。`list_rule_jobs.py` 的 stdout `pending[]` 每项 SHALL 包含绝对 `rule_path`
(claude:`<绝对 target>/.claude/rules/security-<cat>.md`;opencode:`<绝对 target>/.mgh-init/rules-parts/<cat>.md`)
与绝对 `done_marker`(`<绝对 checkpoints>/<cat>.<format>.json.done`),二者均由该脚本从其 `--target`
(经 `Path.resolve()`)与 `--checkpoints`(已 `resolve()`)参数拼出。`rule_path` MUST NOT 在 `--target`
缺省为 `.` 时仍是相对路径。

编排器 SHALL 把 `list_rule_jobs.py` stdout 的 `rule_path` / `done_marker` **逐字透传**进
`init-rulewriter` subagent 的 task 输入,MUST NOT 自行拼路径。`init-rulewriter` 的 stage 提示词 SHALL 把
`rule_path`(与 `done_marker`)列为**编排器逐字给定**的输入字段,其 Output 段 SHALL 要求「Write 恰好
`rule_path` 给定的绝对路径并 touch `done_marker`」;且 SHALL 以硬边界 `NEVER` 禁止:自行拼路径、
写相对路径、写到项目目录之外、直写 `AGENTS.md` 或受管块哨兵(既有约束,保留)。

路径 SHALL 为绝对路径(经 `Path.resolve()`),使其对 subagent 的任意工作目录安全。运行时 hook(在
`MGH_INIT_ACTIVE` 运行域内)的子树外写入拦截(见 `control-discovery` 同名要求)对 T3 的 `.claude/rules/`
与 `.mgh-init/rules-parts/` 写入同样生效——二者均在 resolved `MGH_TARGET` 子树内,故合法写入被放行。

#### Scenario: list_rule_jobs emits absolute rule_path and done_marker
- **WHEN** `list_rule_jobs.py --inventory …/controls_inventory.json --format claude --checkpoints …/checkpoints/t3 --target .` 运行
- **THEN** stdout `pending[]` 每项的 `rule_path` 与 `done_marker` 均为**绝对路径**(即使 `--target` 取默认 `.`),
  分别等于 `<绝对 target>/.claude/rules/security-<cat>.md` 与 `<绝对 checkpoints>/<cat>.claude.json.done`

#### Scenario: Orchestrator passes rule_path verbatim
- **WHEN** 编排器取得 T3 `pending[]` 并起 `init-rulewriter` subagent
- **THEN** subagent task 输入里的输出路径**逐字等于** `list_rule_jobs.py` stdout 的 `rule_path`,
  编排器**不**自行拼 `<target>`/`<category>` 占位符

#### Scenario: Rulewriter writes exactly the given absolute path
- **WHEN** 一个 init-rulewriter subagent 在工作目录 ≠ 项目根的隔离上下文运行
- **THEN** 它把规则文件(claude)或暂存 fragment(opencode)写到输入字段 `rule_path` 给定的绝对路径,
  **不**写到项目外目录,且 touch 输入字段 `done_marker` 给定的绝对 `.done` 路径

#### Scenario: Legit rule write under target tree is not blocked
- **WHEN** 运行域内 `init-rulewriter` 向 `<绝对 target>/.claude/rules/security-authentication.md` 写入
- **THEN** PreToolUse hook 放行(目标在 resolved `MGH_TARGET` 子树内),不被误判为越界
