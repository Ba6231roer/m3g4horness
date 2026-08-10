## Context

`harden-mgh-init-slice-and-tool-pinning` 钉死了 subagent 切片输出路径(落 `<target>/.mgh-init/slices/…`),但**编排器自身**在消费确定性脚本 stdout 时仍可把 JSON 重定向到系统临时目录并回读。触发宿主 agent 的外部目录权限提示,中断 `mgh-init --resume` 长跑。

当前防线:
- **编排纪律**(`orchestrator-discipline.md`):三条 `NEVER` 覆盖脚本扩展名 Write + `py -c` 内省 + Read 叶脚本源码。fan-out 路径 recipe(line 25)提及 `NEVER cwd/Temp 派生`,但这是**子路径拼装**上下文(针对 subagent 输入/输出路径),未明确覆盖编排器自身的 stdout→temp-file→read-back 中间文件模式。
- **钩子**(`block_adhoc_scripts.py`):拦截 `Write`/`Edit`/`Read` **工具调用** + Bash 整读多单元聚合文件。shell 内部重定向(`>`)在钩子可见层之下——钩子仅见外层 `Bash` 工具调用,无法检视命令字符串内的文件级 I/O。故 `> $env:TEMP/x.json` + `Get-Content $env:TEMP/x.json` 完全绕过写限制(规则 3)与读限制(规则 4)。
- **宿主权限模型**:Claude Code 自身的「访问外部目录」权限提示是**最后一层兜底**,但它是交互式阻断,恰好违背「长跑不中断」的编排纪律要求。

## Goals / Non-Goals

**Goals:**
1. 编排纪律显式禁止编排器向系统临时目录写中间文件 + 回读(stdout 从 Bash 工具返回值直消费)
2. 钩子增 Bash 命令字符串级 temp-dir 重定向检测(防御纵深;主修复在纪律)
3. 双端命令壳增 temp-file 禁令提醒

**Non-Goals:**
- 不改确定性脚本输出格式(已正确:stdout=JSON / stderr=诊断 严格分流)
- 不改 subagent prompt(切片输出路径已由前一个 spec 钉死)
- 不限制编排器使用临时文件的**合法**场景(如 `mktemp` 后立即 `mv` 进受信子树——但当前无此场景,故简单禁令即可)

## Decisions

### D1: 主修复在纪律(prompt),不在钩子(code)

**选择**:在 `orchestrator-discipline.md` 增显式 `NEVER`——编排器 MUST NOT 把 stdout 重定向到磁盘文件中介,直接从 Bash 工具返回值消费。钩子增 regex 检测作为**防御纵深**(defense-in-depth)。

**被否决的替代方案**:仅扩钩子,不改纪律。
- **否决理由**:钩子能拦已知临时目录模式(`$env:TEMP`/`%TEMP%`/`/tmp`/`TMPDIR`),但 agent 可以发明新的树外路径(`~/Desktop/scout.json`、`C:\scratch\x.json`)。正则检测永远有漏网之鱼。纪律从根因纠正行为——"不需要写文件,stdout 已在工具返回值里"。

### D2: 钩子检测范围为 Bash 命令字符串 regex,不做 AST 级 shell 解析

**选择**:在钩子 `main()` 增 regex 扫描 `command`(来自 tool input):匹配已知临时目录模式后接 `>`/`>>`(写入重定向)或 `Get-Content`/`cat`/`type`(读取)的**同一条 Bash 调用内读写对**。

**被否决的替代方案**:用 `shlex`/shell 解析器做 AST 级重定向分析。
- **否决理由**:① PowerShell 语法与 POSIX sh 不兼容,通用 shell 解析器不存在(Windows 上 opencode 可能用 PowerShell);② 正则匹配已知 temp 模式 + `>` 已覆盖真实失败形状(agent 的一行式 PowerShell 惯用写法);③ 零依赖(R2)。

### D3: 违纪 recipe 指向 stdout 直消费,而非仅说"别写 temp"

**选择**:纪律增 **positive recipe**:「要取确定性脚本的 JSON 输出:经 Bash 跑、从工具返回值取 stdout(最后一行是 JSON)、在你的推理里解析 `pending[]`。NEVER 把 stdout 重定向到文件、NEVER `$env:TEMP`/`%TEMP%`/`/tmp`/`TMPDIR`。」

理由(R5.5①):recipe > prohibition,正引导优先于禁令。

## Risks / Trade-offs

- **[钩子 regex 漏检]** → 主防线在纪律(prompt),钩子是 defense-in-depth。regex 覆盖已观测的失败形状(PowerShell `> $env:TEMP/x.json; Get-Content ...` 与 POSIX `> /tmp/x.json; cat ...`),不承诺穷举。
- **[假阳性——合法脚本用 `/tmp` 做编译/缓存]** → 检测限定在 stdin 有 `import json`/`open(`/`load(` 特征 OR stdout 来自已知 `list_*` 脚本产物的场景。更安全策略:仅检测「写 + 同一条 Bash 调用内读」的配对模式,因为编排器没有理由在同一条 Bash 调用中既写 temp 又读 temp。
- **[平台特异性——open PowerShell vs posix sh]** → regex 同时覆盖两种平台的 temp 路径模式;真假阳性边界由「同调用内读写对」进一步收紧。
