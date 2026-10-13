## MODIFIED Requirements

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
**守卫脚本缺失时 SHALL fail-soft 放行**:shim 在 spawn 前做守卫文件存在性预检(缺失 → 放行 +
一条诊断,不 spawn)——python 对不存在的脚本文件以退出码 2 退出(`can't open file`),与守卫的
阻断退出码同值;无预检时一次守卫文件缺失/错位(不完整安装、镜像错位)会被误判为 deny,阻断与
fail-soft 契约「守卫不在 → PASS」矛盾的合法调用。stderr 含 python「can't open file」签名的
退出码 2 亦 SHALL 按 fail-soft 处理(存在性预检的兜底)。

#### Scenario: out-of-tree write is denied with a model-visible recipe

- **WHEN** mgh 运行域激活,dsh 会话发起一次目标树外的文件写入工具调用
- **THEN** shim 将其归一化喂守卫 → 守卫退出码 2 → 宿主阻断该次调用,且守卫 stderr 的 recipe
  文本作为拒绝理由进入模型上下文(模型可据此自我纠正,而非静默失败)

#### Scenario: python absence degrades without wedging the host

- **WHEN** 机器上找不到可用 Python 解释器,dsh 会话发起任意受管工具调用
- **THEN** 调用放行(与 opencode 端同形的 fail-soft),宿主会话不报错、不挂起

#### Scenario: missing guard file degrades to a pass, not a deny

- **WHEN** 守卫脚本文件在 shim 解析路径上缺失/被移动(不完整安装),受管工具调用发生于运行域内
- **THEN** 存在性预检失败 → 放行 + 宿主日志一条诊断(fail-soft);python「can't open file」的
  退出码 2 NEVER 被解读为 deny(修复前该形态 = 误判 deny,恰与阻断退出码同值)
