## MODIFIED Requirements

### Requirement: Guard tool-surface wiring coverage enforced by CI

The guard's decision-branch tool set (every tool name the guard's `main()` dispatches on:
`Bash`, `Write`, `Edit`, `MultiEdit`, `NotebookEdit`, `ApplyPatch`, `Read`, `Glob`, `Grep`, plus
the dsh-dialect names mapped in by the third wiring face) SHALL be fully covered by ALL THREE
host wiring faces, and a CI regression test SHALL enforce it: (a) the claude-side default
PreToolUse matcher injected by `tools/install_hook.py` SHALL contain every guard tool name;
(b) the opencode `.ts` shim's `HANDLED` set (plus its `normalize` mapping) SHALL cover every
guard tool name (via its lowercase mapping); (c) the dsh `.ts` shim's handled-tool set (plus its
dsh→guard name mapping, including the tools admitted only through the dsh dialect: the bundled
code runner, the PowerShell tool, the terminal I/O tools, the job tools, and the patch-shaped
editor) SHALL cover every guard tool name reachable on dsh. Adding a guard decision branch
without extending all wiring faces SHALL fail the regression test (exit non-zero), structurally
closing the "dead branch" gap class on all three hosts — the claude matcher previously covered
only `Bash|Write|Edit`, leaving the read-side branches unconsulted (an out-of-tree `Read`
reached the host permission prompt and interrupted the run instead of failing loud with a
recipe), and nothing prevented the same drift on either host.

#### Scenario: matcher covers the full guard tool surface on fresh install
- **WHEN** `install.sh --claude <target>` 注入 PreToolUse hook
- **THEN** settings.json 的 matcher 含守卫全部分派工具名(`Bash|Write|Edit|MultiEdit|NotebookEdit|Read|Glob|Grep`)

#### Scenario: reinstall evolves a narrower legacy matcher in place
- **WHEN** 目标项目 settings.json 已有 `block_adhoc_scripts` 条目且 matcher 为旧的
  `Bash|Write|Edit`,重跑 `install.sh --claude`
- **THEN** 该条目的 matcher 被更新为全工具面默认值(按 command 内 `block_adhoc_scripts` marker 锚定,
  只改 matcher、不动用户自定义 command;用户自定义非子集 matcher 不动 + stderr 提示;幂等)

#### Scenario: CI fails when a guard branch lacks wiring coverage
- **WHEN** 守卫源新增一个分派工具名(如未来加 `WebFetch`),而 matcher、opencode shim `HANDLED`
  或 dsh shim 分派集任一端未同步扩
- **THEN** 接线覆盖回归测 fail(非零退出)——「新增分支忘扩接线面」从「静默死代码」变为 CI 拦截

#### Scenario: out-of-tree Read is consulted by the guard on claude
- **WHEN** claude 会话处于 `mgh-init` 运行域(激活),模型 `Read` 一个越树路径(如 `..` 链折叠后落
  `D:\xxxx`)
- **THEN** PreToolUse hook 被触发(matcher 含 `Read`)→ 守卫退出码 2 → 工具调用被阻断、模型看到
  read-side recipe;**不出现**宿主 D 盘根权限询问(报告的中断形态消除)

## ADDED Requirements

### Requirement: dsh-exclusive bypass tools are confined by the guard

When any mgh run-domain is active, the guard SHALL treat the dsh-dialect execution surfaces as
bypass-capable and confine them with the same fail-loud posture as their claude/opencode
analogues: (a) the bundled code-runner tool (in-process Python execution, the direct analogue of
the blocked `py -c` inline-interpreter form) SHALL be denied with a recipe pointing to the
legitimate exit (running declared leaf scripts via the shell tool); (b) the PowerShell tool SHALL
be subject to the same verb-enumeration + path-token allowlist judgment as the `Bash` face,
including the redirect and destructive-delete rules; (c) terminal I/O and background-job tools
SHALL be denied inside an active run-domain (they would let a blocked foreground command
continue out-of-sight); (d) file-mutating use of the network-fetch tool SHALL be judged like a
Bash redirect target. Denials SHALL carry the guard's recipe on stderr so the host can surface
the reason to the model. These rules key on dsh-only tool ids and SHALL NOT alter any existing
claude/opencode judgment.

#### Scenario: bundled code runner denied inside run domain
- **WHEN** mgh 运行域激活,dsh 会话尝试经内置代码执行器运行任意 Python 片段(等价 `py -c` 内省)
- **THEN** 守卫退出码 2 + recipe(指向合法出口:经 shell 工具跑声明的叶脚本),该工具调用被宿主阻断

#### Scenario: PowerShell out-of-tree write denied
- **WHEN** mgh 运行域激活,dsh 会话经 PowerShell 工具向 `MGH_TARGET` 子树外路径写文件
  (如 `Set-Content D:\out\x`)
- **THEN** 同 Bash 写动词净网判定 → 退出码 2 + 允许集 recipe

#### Scenario: claude/opencode judgment unchanged
- **WHEN** 双端既有回归测全量运行
- **THEN** dsh 方言工具名不可能出现于双端 payload,既有判定与基线逐一一致(零 diff)
