# add-mgh-dsh-host-foundation

## Why

> **人话序** 现象:m3g4h⊿rness 目前只能装在 Claude Code 或 opencode 上跑,DeepSeek 开源的
> agent 运行时 deepseek-harness(下称 dsh)用户无法使用这套 mgh-* 安全命令。根因:本项目的
> 全部平台耦合都集中在两层薄壳——宿主命令/子代理的 markdown 方言,和「工具执行前可阻断的
> 守卫」的宿主接线;判定逻辑本身(零依赖 Python 守卫 + 叶脚本)是平台无关的。改什么:本
> change 是路线 A(dsh 作为第三个宿主原生适配)的第一步——只打地基:把守卫接到 dsh 上
> (一个 TypeScript 薄 shim 订阅 dsh 的工具前置事件,喂给同一个 Python 守卫),把 dsh 特有
> 的旁路工具(内置代码执行器、PowerShell、补丁式编辑器等)纳入守卫判定面,并给 install 脚本
> 加 `--dsh` 方言负责落位与接线。怎么验证:守卫三端接线覆盖断言 + 双端 parity 测扩为三端
> 全绿;在真装 dsh 的机器上,一个 mgh 运行域激活后,树外写/读与微脚本内省尝试被 deny 且
> 理由回显给模型。命令壳与扇出派发不在本 change(见后续 change)。

- **机会/问题**:dsh 与本项目的需求面高度对口(原生支持 SKILL.md、TypeScript 插件挂
  `tools/pre-execute` 瀑布且 deny 理由对模型可见、headless 单发模式带 `--patch` 逐次叠加)。
  但没有任何一份现有资产能直接跑:守卫现在只接了 claude(settings.json PreToolUse)与
  opencode(`.opencode/plugins/*.ts`)两端,dsh 上等于**零执法**——而本项目的纪律定义是
  「能用 hook 闭环的绝不靠 agent 自觉」,所以守卫接线必须最先落地,后续命令面/扇出面 change
  都以本 change 为安全前提。
- **为何拆成三个 change 且本 change 先行**:命令壳转 skill、subagent→preset、fan-out 派发
  分别依赖「守卫已执法」「tier 配置可装载」等不同前提;地基(本 change)独立可验收
  (deny 语义 + parity 测),混在一起会让首跑排障无法归因。
- **dsh 侧现状锚点**(证据在 design.md):`--patch <path>` 可重复、headless 任务走参数或
  stdin、`tools/pre-execute` 瀑布支持 deny/ask、插件经 profile 目录的 cordis 配置层组合;
  dsh **不**自动发现目标项目内的 `.claude/`/`.opencode/` 配置,故 shim 装载必须走显式接线
  (本 change 的核心交付之一)。

## What Changes

- **新增 `releases/dsh/` 方言目录**:内含 ① Cordis TS 薄 shim 插件(订阅 `tools/pre-execute`,
  把 dsh 工具事件归一化为守卫既有 stdin payload 形状 `{tool_name, tool_input, cwd}`,spawn
  同一个 `block_adhoc_scripts.py`,deny 时把守卫 stderr recipe 作为拒绝理由回注模型);
  ② dsh profile 接线模板(cordis patch YAML,声明 shim 插件挂载与 mgh 运行期所需的最小配置)。
- **守卫判定面扩展**(改 `core/scripts/block_adhoc_scripts.py`,判定单源不变):
  - 工具名/参数归一化表:新增 dsh 方言 `read→Read`、`write→Write`、`edit→Edit`、
    `str_replace_editor→(Edit 同形判定)`、`glob/grep→Glob/Grep`、`bash→Bash`(参数
    `command` 字段名差异在 shim 层抹平,守卫内核不感知);
  - **新增旁路纳管**(dsh 特有、claude/opencode 不存在的执行面):`run_code`(内置 Python
    执行器,等价 `py -c` 违例面,运行域内直接 deny + recipe 指向合法出口)、`pwsh`
    (并入 Bash 动词+路径净网判定)、`terminal_open/terminal_send`、`job_*`(运行域内 deny,
    防经后台作业绕过前台判定)、`web_fetch` 落盘形态按 Bash 重定向同形判定;
  - 上述纳管项进入既有五张动词表/净网规则(m)与写侧越树判定,读侧沿用统一读允许集。
- **三端 parity 与接线覆盖**:双端字节级 parity 测(`tests/test_opencode_hook_parity.py` 模式)
  扩为 claude/opencode/dsh 三端「守卫分派工具集 ⊆ 各端接线面」断言;`TestWiringCoverage`
  同型扩展到 dsh shim 的工具 id 归一化表。
- **install.sh / install.ps1 新增 `--dsh` 方言**:镜像 `core/` → `<dest>/mgh-core/`(既有布局
  复用);shim 插件与 profile patch 落位到 dsh 宿主目录约定下并在 `$DSH_HOME/profiles` 完成
  接线(幂等,已接线则跳过并提示);安装自检由「双端对等」扩为三端;`--no-enforce-hook` 对
  dsh 同样生效。
- **运行域机制零改动声明(验证性任务)**:哨兵向上走查、`MGH_TARGET` 优先级、read-roots 并集
  在 dsh 上按既有契约工作(Cordis 插件进程不继承会话中途 env 的边界与 opencode 同形,磁盘哨兵
  机制正好闭合);本 change 只加真机验证任务,不改机制。
- **非目标(Non-goals)**:命令壳转 skill、subagent→preset 转换、fan-out 的 `--host dsh` 分支
  (分属后续两个 change);opencode 2.0 适配(另立任务);对 dsh 的 MCP/sandbox 深度集成。

## Capabilities

### New Capabilities

- `dsh-host-integration`: mgh 家族在 deepseek-harness 上的宿主集成面——shim 插件装载与
  payload 归一化契约、deny 理由回注通道、profile 接线与 install 第三方言、三端接线覆盖不变量。

### Modified Capabilities

- `runtime-hook-enforcement`: 守卫契约从「双端(claude/opencode)」扩展为「三端
  (claude/opencode/dsh)」:新增 dsh 工具名映射要求与 dsh 特有旁路面(`run_code`/`pwsh`/
  `terminal_*`/`job_*`/`web_fetch`)的纳管要求;parity/接线覆盖要求的措辞从双端对偶改为三端。

## Impact

- **新增**:`releases/dsh/`(shim 源码 + profile patch 模板)、`tests/test_dsh_hook_parity.py`
  (或既有 parity 文件扩面)、install 的 dsh 分支。
- **修改**:`core/scripts/block_adhoc_scripts.py`(判定表扩展)、`install.sh` / `install.ps1`、
  `tests/test_block_adhoc_scripts.py`(新工具面用例)、`tests/test_install_hook.py` /
  `tests/test_install_opencode_plugin.py` 的同型 dsh 安装自检、版本号文件(承「任何 md/脚本
  改动 bump 版本号」纪律)。
- **不受影响**:全部叶脚本 CLI 契约、提示词、产物 schema、哨兵/marker/resume 机制、
  claude 与 opencode 两端既有行为(新增判定只对 dsh 方言工具名生效,双端 payload 不可能
  出现这些 id)。
- **测试面映射**:命中「`block_adhoc_scripts.py` / hook 双端接线 → 定向跑」行的既有映射表,
  本 change 落地时同步把该行扩为三端。
