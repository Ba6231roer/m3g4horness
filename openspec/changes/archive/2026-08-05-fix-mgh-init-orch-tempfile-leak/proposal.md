## Why

`harden-mgh-init-slice-and-tool-pinning` 把 **subagent** 的切片输出路径钉到了项目树内(`<target>/.mgh-init/slices/…`),但 **编排器自身** 在消费确定性脚本 stdout 时,使用 shell 重定向把 JSON 写到 `$env:TEMP`(系统临时目录,树外),再回读解析——触发宿主 agent 的「访问外部目录」权限提示,中断 `mgh-init --resume` 长跑。钩子(`block_adhoc_scripts.py`)只能拦截 `Write`/`Edit`/`Read` **工具调用**,对 shell 内部重定向(`>`/`>>`)不可见;编排纪律也未明确禁止编排器自身写临时文件。这是一个「编排器自身 I/O 泄漏到树外」的系统性缺口,与 subagent 切片泄漏同形但处于钩子盲区。

## What Changes

- **编排纪律补强**:`orchestrator-discipline.md` 增显式 `NEVER`——编排器 MUST NOT 把确定性脚本 stdout 重定向到磁盘文件(尤其 `$env:TEMP`/`%TEMP%`/`/tmp`/`TMPDIR`);stdout 从 Bash 工具返回值直接消费(NEVER 文件中介)。
- **钩子防御纵深**:`block_adhoc_scripts.py` 增 Bash 命令字符串检测——发现向已知临时目录模式(`$env:TEMP`/`%TEMP%`/`/tmp`/`$TMPDIR`)的写入重定向 + 后续回读 → fail-loud(退出码 2)+ recipe 指向编排纪律。
- **命令壳**:`mgh-init.md`(双端)在确定性调用段增 temp-file 禁令,明确 "stdout is in the Bash tool result — no file redirection needed"。
- **测试**:`test_block_adhoc_scripts.py` 增 temp-dir 重定向检测用例;`check_contracts.py` 增命令行禁令断言。

## Capabilities

### New Capabilities
<!-- 无全新能力;均为既有能力的 requirement 增订。 -->

### Modified Capabilities
- `orchestration-substrate`:编排纪律增「编排器自身禁止向系统临时目录写中间文件」requirement + stdout 直消费 recipe。
- `runtime-hook-enforcement`:钩子增「Bash 命令字符串中检测临时目录写入重定向 + 回读」防御纵深规则(defense-in-depth;主修复在纪律)。

## Impact

- **确定性脚本**:不改(`list_scout_batches.py` 等输出格式已正确;问题在消费侧)。
- **提示词/契约**:`core/prompts/fragments/orchestrator-discipline.md`;`core/contracts/hooks/runtime-enforcement.md`。
- **钩子守卫**:`releases/claude-code/hooks/block_adhoc_scripts.py`(双端字节级 parity;opencode `.ts` 胶水不变)。
- **命令壳**:`releases/{claude-code/commands,opencode/command}/mgh-init.md`(双端对等)。
- **测试**:`tests/test_block_adhoc_scripts.py`。
- **依赖/平台**:零新增运行时依赖(承 R2);纯提示词 + 标准库正则。
- **版本**:受影响 `.md`/脚本 bump 版本号(承 R5.8)。
