> **人话序** 现象:opencode 升级到 2.x 后,mgh 的运行时守卫插件还是 1.x 的导出形状,被新版本
> 拒载——而且拒载只是日志里一行 WARN,界面照常运行。也就是说,从升级当天起,工具族在
> opencode 上的整条运行域防线(越树读写拦截、微脚本阻断、叶脚本只读)就已经不存在了,使用
> 者却看不出任何异常。根因:2.x 把插件模块契约改成了「default 导出 {id, setup}」,事件回调
> 从双参数改成了单个事件对象;同时核心逻辑搬进了常驻后台服务进程,插件随服务进程跑,它的
> 工作目录不再是被分析的项目目录,守卫靠工作目录向上找哨兵标记的锚点链断了。改什么:只迁
> 移壳——插件改成 v2 形状、把 2.x 的新工具名映射给守卫、锚点改由插件位置显式注入;判定逻
> 辑一行不动,仍然全部住在 Python 守卫里。怎么验证:单测锚住新形状与映射;企业机
> opencode 2.0.32 与本机 2.1.0 双版本实机加载,用同一套越权样例对照拦截结果与 1.x 一致。

## Why

- opencode 2.x 的插件模块契约只接受 `export default { id, effect|setup }`;mgh 现有插件是
  1.x 的具名导出(`export const BlockAdhocScripts`),实测被拒载,日志原话
  「Plugin must export a default definition with an id and an effect or setup function」,
  且加载失败是 fail-soft(仅 WARN、会话继续)——守卫静默失效,比报错更危险。
- 企业内网已确认部署 opencode 2.0.32(共享服务形态),并实测默认 `run` 复用已登录共享服务;
  本机为 2.1.0。也就是说企业环境随时会踩中这个拒载,而当前没有任何拦截。
- 2.x 把会话执行搬进常驻服务进程,插件在该进程内运行:其一,插件进程 cwd 不再是项目目录,
  守卫「payload.cwd 缺省时回退守卫进程 cwd」的锚点链在 2.x 上必然指错地方(哨兵发现静默失
  效,守卫对整个 run 休眠);其二,工具名更名(bash→shell 等)使旧 HANDLED 集漏收新名。
- 这是扇出转向(原生子代理派发)的第一个前置:守卫不先在 2.x 活过来,任何无人值守原生派
  发都在裸奔。

## What Changes

- **插件壳迁移到 2.x 模块契约**:`export default { id, async setup(ctx) }`,钩子经
  `await ctx.tool.hook("execute.before", cb)` 注册;回调从 `(input, output)` 双参改为读单个
  事件对象(`event.tool` / `event.input`);`setup` 必须 await 注册完成,避免首个工具调用
  早于注册的竞态。1.x 会话(若仍装 1.x opencode)的兼容策略见 design(双形状导出不可行时
  以 2.x 为准并在 install 自检披露)。
- **工具名映射更新**:HANDLED 集与 normalize() 增补 2.x 新名(`shell`,以及补丁工具的 2.x
  形态),保留旧名兼容收玫;守卫侧工具面不变(仍是 Bash/Write/Edit/Read/Glob/Grep/
  ApplyPatch 等判定分支)。
- **锚点显式注入**:插件在 setup 时记住 `ctx.location.directory`(项目根),每次调用把它作
  为 payload 的 `cwd` 字段喂给守卫;守卫既有优先级(payload.cwd > 守卫进程 cwd)不变,
  Python 侧零改动即恢复正确锚定。
- **fail-soft 语义原样保留**:守卫缺席/不可达/抛错一律放行不阻断;v1 的 `ctx.client.app.log`
  诊断通道在 2.x 不存在,改为 best-effort 诊断输出,阻断契约(退出码 2 → throw stderr 作
  recipe)不变。
- **静态形状自检**:测试断言插件文件满足 2.x 模块 schema(default 导出、id 字符串、setup
  函数),防止未来再被静默拒载;安装器(纯拷贝、文件名不变)与 install 自检清单同步。
- **agent 定义 frontmatter 验证**:opencode 面 agent 的 `permission:` map 在 2.x 走自动迁移,
  实测确认语义等价(`bash`→`shell` 等);惰性键(2.x 无对应断言的键)做最小修正,不改行为
  语义。
- **非目标**:不做 `permission.evaluate` 权限闸门(无人值守永不弹授权,属下一个 change);
  不做原生子代理派发;不动 Python 守卫判定逻辑;不动 claude/dsh 两面。

## Capabilities

### New Capabilities

<!-- 无。 -->

### Modified Capabilities

- `runtime-hook-enforcement`: opencode 壳面四条要求变更——①「opencode shim feeds the guard
  payload via a Bun-compatible stdin」增补 2.x 模块契约与单事件对象形状(default 导出、
  await 注册、event.input 取参);②「opencode shim normalizes read-side tools to the guard」
  与「Guard tool-surface wiring coverage enforced by CI」增补 2.x 工具名(shell 等)的收
  敛与不变量;③「哨兵发现与路径判定共用单一 cwd 源」增补 2.x 下锚点由插件
  `ctx.location.directory` 显式注入 payload.cwd 的形态;④「opencode shim arg-name
  defense-in-depth for write/edit/read」在 2.x 参数形态下保持回退链语义。

## Impact

- **代码**:`releases/opencode/plugins/block_adhoc_scripts.ts`(壳迁移,判定逻辑零改动);
  `releases/opencode/agent/*.md` 仅在实测发现惰性键时最小修正。
- **契约**:`core/contracts/hooks/runtime-enforcement.md` 同步 opencode 壳的 2.x 形态(模块
  契约/事件形状/工具名表/锚点注入)。
- **测试**:`tests/test_opencode_hook_parity.py`(v2 形状断言、事件映射、双版本工具名表)、
  `tests/test_block_adhoc_scripts.py`(payload.cwd 锚点场景)、`tests/test_install_opencode_plugin.py`
  (拷贝不变 + 形状自检)、`tests/test_distributed_md_purity.py` 随分发面。
- **安装**:install.sh 的 opencode 自检清单条目不变(文件名不变);新增静态形状检查。
- **版本兼容闸门(实机)**:企业 opencode 2.0.32 与本机 2.1.0 双版本各做一次「加载成功 +
  同套越权样例拦截一致」验证;1.x opencode 的继续兼容性按 design 决策项处理。
- **VERSION/CHANGELOG**:按仓库惯例 bump。
