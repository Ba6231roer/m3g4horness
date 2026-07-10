## MODIFIED Requirements

### Requirement: Runtime enforcement hook for orchestrator script discipline

`install.sh` SHALL 在镜像 `core/` 后,**双端对等**注入运行时纪律守卫 `block_adhoc_scripts`(单一
Python 标准库脚本、零运行时依赖,承 R2),使 Claude Code 与 opencode 用户获得对等的运行时强制:

- **claude**:`install_hook.py` 向目标 `.claude/settings.json` 的 `PreToolUse` **幂等追加**一条命令
  hook(matcher `Bash|Write|Edit` → `py .claude/hooks/block_adhoc_scripts.py`)。
- **opencode**:`install_opencode_plugin.py` 向目标 `.opencode/plugins/` **幂等落**一个订阅
  `tool.execute.before` 的 `.ts` 插件(`block_adhoc_scripts.ts`)。opencode 的 hook 形态即 JS/TS
  插件(非 Claude 的 settings.json 命令式 hook),等价事件为 `tool.execute.before`(pre-tool,可阻断)/
  `tool.execute.after`(post-tool)。该插件是 opencode 原生胶水(非 Python `pip` 依赖),把 opencode
  工具事件**归一化**为 Claude PreToolUse 的 stdin 形态(`{tool_name, tool_input}`),管道喂给**同一**
  `block_adhoc_scripts.py`,据其退出码 2 阻断该工具调用、否则放行。

守卫在 `/mgh-init` 运行域(由编排器起步 `export MGH_INIT_ACTIVE=1` 标记)内:拦截 `Bash` 中
`py -c`/`python -c` 且含 `import json`/`open(`/`load(`/`\.json` 的内省模式,以及 `Write` 中 `*.py`
且不在白名单(`core/scripts`/`tests`/`tools`/`releases/*/hooks`)的写入,以及(init/sra 域)resolved
目标落在 `MGH_TARGET` 子树外的 `Write`/`Edit`。命中 SHALL fail-loud(退出码 2)+ stderr recipe,指向
合法出口(`list_*`/`describe_artifact.py`/脚本 stdout 字段)。非运行域会话 SHALL 直接放行(零日常
噪声)。`install.sh` SHALL 提供 `--no-enforce-hook` opt-out;仅当某端的 hook 注入或核验失败时(claude:
settings.json 写入失败;opencode:`tool.execute.before` 在目标 opencode 版本不可用/不触发)SHALL
stderr warn 并跳过**该端**注入(fail-soft,承 R5.8),此时纪律由命令壳明线 + R5.9 边界校验兜底。本条
兑现 R5.7「能 hook 就别靠自觉」——双端均有等价 hook 路径,opencode 不再被当作「无 hook 能力」而跳过。

#### Scenario: Hook blocks introspection py -c during a run (claude)
- **WHEN** `MGH_INIT_ACTIVE=1` 下编排器运行 `py -c "import json; json.load(open('.mgh-init/scout_plan.json'))"`
- **THEN** hook 以退出码 2 拦截,stderr 给出「用 list_scout_batches.py / describe_artifact.py」recipe

#### Scenario: Hook passes legitimate leaf-script invocation (claude)
- **WHEN** `MGH_INIT_ACTIVE=1` 下运行 `py .claude/mgh-core/scripts/discover_controls.py --repo . --out .mgh-init`
- **THEN** hook 放行,不误伤合法叶子调用

#### Scenario: Hook is idempotent across reinstalls (claude)
- **WHEN** 对同一目标项目连续两次 `install.sh --claude`
- **THEN** `PreToolUse` 中本工具的 matcher 只出现一次,不覆盖用户既有 hook

#### Scenario: opencode plugin blocks the same introspection via the shared gate
- **WHEN** `MGH_INIT_ACTIVE=1` 下 opencode 触发 `tool.execute.before`,且该 Bash 为 `py -c "import json; json.load(open('.mgh-init/scout_plan.json'))"`
- **THEN** `.ts` 插件把事件归一化为 `{tool_name:"Bash", tool_input:{command:...}}` 管道喂给 `block_adhoc_scripts.py`,据退出码 2 阻断该调用,stderr 出同一 recipe;守卫判定逻辑与 claude 端零差异(单一来源)

#### Scenario: opencode plugin is idempotent across reinstalls
- **WHEN** 对同一目标项目连续两次 `install.sh --opencode`
- **THEN** `.opencode/plugins/` 中本工具插件只落一份(幂等替换同名文件、不覆盖用户既有其它插件)

#### Scenario: Opt-out and per-platform fail-soft
- **WHEN** `install.sh --no-enforce-hook`,或某端 hook 注入/核验失败(含 opencode `tool.execute.before` 在目标版本不可用)
- **THEN** 该端 hook 不注入(warn 跳过),install 仍成功(fail-soft);命令壳明线 + R5.9 校验仍生效
