## Purpose

定义 mgh 命令家族与 deepseek-harness(dsh)宿主的集成契约:工具执行前拦截的装载与接线形态、
守卫 payload 的跨方言归一化、运行域激活在 dsh 进程模型下的生效路径,以及安装器第三方言的
幂等落位行为。使 dsh 与 claude/opencode 一样成为守卫执法的完整宿主。

## ADDED Requirements

### Requirement: dsh pre-execute shim feeds the single Python guard

On dsh, enforcement SHALL be delivered by a thin shim plugin that subscribes to the host's
tool pre-execution waterfall and, for every handled tool call, spawns the SAME Python guard
script (`block_adhoc_scripts.py`, byte-identical to the claude/opencode faces) with a stdin
payload normalized to the guard's existing shape `{tool_name, tool_input, cwd}`. The shim SHALL
contain NO decision logic (glue only: event-to-payload mapping, process spawn, outcome
translation). When the guard exits with code 2, the shim SHALL deny the tool call on the host
and pass the guard's stderr recipe through as the deny reason so it is visible to the model;
any other exit SHALL not block (mirroring the opencode face's fail-soft posture, including when
no Python interpreter is discoverable, with one diagnostic on the host log).

#### Scenario: out-of-tree write is denied with a model-visible recipe
- **WHEN** mgh 运行域激活,dsh 会话发起一次目标树外的文件写入工具调用
- **THEN** shim 将其归一化喂守卫 → 守卫退出码 2 → 宿主阻断该次调用,且守卫 stderr 的 recipe
  文本作为拒绝理由进入模型上下文(模型可据此自我纠正,而非静默失败)

#### Scenario: python absence degrades without wedging the host
- **WHEN** 机器上找不到可用 Python 解释器,dsh 会话发起任意受管工具调用
- **THEN** 调用放行(与 opencode 端同形的 fail-soft),宿主会话不报错、不挂起

### Requirement: dsh tool-name and argument normalization to the guard surface

The dsh wiring face SHALL map dsh tool ids and argument field names onto the guard's dispatch
names such that every guard decision reachable on claude/opencode is reachable on dsh: the
shell tool onto the Bash face (with its command-string field renamed), read/write/edit onto the
Write/Edit faces (with path fields renamed), the patch-shaped editor onto the ApplyPatch face
(paths extracted from the patch body), and glob/grep onto Glob/Grep with `pattern`/`path`
equivalents. Renaming SHALL happen in the shim, NEVER by adding dsh field names to the guard
core. Unknown/unmapped tool ids SHALL be passed through unhandled (host-native approval still
applies) rather than guessed at.

#### Scenario: same violation, same verdict across three faces
- **WHEN** 同一次「向树外路径写文件」分别经 claude `Write`、opencode `write`、dsh 写入工具发起
- **THEN** 三端均被守卫拒绝且 recipe 同源(判定文本一致,仅宿主阻断协议不同)

#### Scenario: unmapped tool ids do not reach guard judgment
- **WHEN** dsh 会话调用映射表之外的工具(如宿主内置检索类工具)
- **THEN** shim 不喂守卫、不猜测归一化,交由宿主自身权限体系处理

### Requirement: Run-domain activation reaches the dsh guard via disk sentinel

Because dsh host-process plugins do not inherit environment exported mid-session by the
orchestrator's shell tool (the same boundary the opencode face documents), activation of the
guard on dsh SHALL rely on the existing disk-sentinel mechanism: the guard subprocess spawned
by the shim SHALL discover `<dir>/<run-root>/.active` by walking upward from the payload `cwd`
under the same bounded-ancestor contract as the other two faces, and `MGH_TARGET` SHALL resolve
with precedence env > sentinel.`target` > degraded. No dsh-specific activation channel SHALL be
introduced.

#### Scenario: sentinel written by a leaf script arms the dsh guard
- **WHEN** init 域叶脚本(`write_runconfig.py`)落哨兵后,dsh 会话发起越树操作
- **THEN** 守卫经哨兵发现链激活并拒绝(无需任何 env 注入 dsh 宿主进程)

#### Scenario: no sentinel, no domain, no interference
- **WHEN** dsh 在与任何 mgh 运行域无关的仓库里正常使用文件与 shell 工具
- **THEN** 守卫休眠,shim 全部放行,零打扰

### Requirement: install.sh --dsh lays out the third host dialect idempotently

`install.sh`(与 `install.ps1` 对等)SHALL accept a `--dsh` target-platform dialect that:
(a) mirrors `core/` to `<dest>/mgh-core/` exactly as the existing dialects do; (b) installs the
shim plugin plus its profile wiring so that dsh loads it when booting the user's chosen profile
— dsh does not auto-discover project-local hook configuration, so wiring SHALL be written into
the dsh home profile layer, idempotently (a second install detects the existing wiring and
skips without duplicating entries); (c) run the same zero-dependency and co-location self-checks
as the other dialects, extended to assert the shim file exists alongside the guard; (d) honor
`--no-enforce-hook` by skipping step (b) while still mirroring (a). Install SHALL fail loud
(exit non-zero, no partial wiring) when the dsh home directory cannot be located.

#### Scenario: fresh install wires the shim into the profile layer
- **WHEN** 维护者在装有 dsh 的机器跑 `install.sh --dsh <target>`
- **THEN** `<target>/mgh-core/` 就位、shim 与 profile 接线写入 dsh 宿主目录、自检通过;随后
  dsh 会话内守卫即执法

#### Scenario: reinstall is a no-op
- **WHEN** 同一目标重复执行 `install.sh --dsh`
- **THEN** 已存在接线不被重复追加,镜像文件被覆盖更新,自检仍全绿

#### Scenario: enforcement opt-out honored
- **WHEN** `install.sh --dsh <target> --no-enforce-hook`
- **THEN** 仅镜像 `core/`,不写任何 profile 接线,自检提示守卫未执法(warn 不阻断)
