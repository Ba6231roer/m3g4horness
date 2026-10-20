## Context

现状与约束(动机见 proposal「Why」,不重复):

- 插件壳是 1.x 形态:`export const BlockAdhocScripts = async (ctx) => ({ "tool.execute.before":
  async (input, output) => … })`,判定全部下沉 Python 守卫(单一真相源)。2.x 模块契约只接受
  `export default { id, effect|setup }`,实测拒载(fail-soft 仅 WARN)。
- 2.x 插件回调是**单事件对象** `{ tool, sessionID, agent, messageID, id, input }`(本机 2.1.0
  实测);1.x 的第二参数 `output.args` 不存在,参数在 `event.input`。
- 2.x 插件随**常驻服务进程**运行:服务进程 cwd 与项目无关;插件 `setup(ctx)` 的
  `ctx.location.directory` 是项目根(实测可用)。守卫锚点 = payload `cwd` > 守卫进程 cwd,
  该优先级链已存在,Python 侧零改动即可吃显式注入。
- 工具更代(2.1.0 源码 + 官方迁移映射):`bash → shell`、`task → subagent`;
  `write/edit/read/glob/grep` 名字不变;补丁工具在 2.x 存在 `patch` 形态(与 `apply_patch`
  的关系按实测定,双收)。`permission:` map 由 2.x 自动迁移(bash→shell 等改名内建处理)。
- 版本矩阵:**企业 2.0.32(共享服务形态,D8 已过)+ 本机 2.1.0**;1.x opencode 不再被本仓
  插件文件支持(旧安装保留旧文件)。
- 插件运行时 import 白名单(2.1 源码 `runtime-modules.ts`):仅 `effect`、`@opencode/plugin`
  与 node 内建——现壳只用 `node:fs`/`node:url`/`Bun.spawn`,迁移后仍满足;**不引入 npm 依赖**
  (R2 定性:插件是宿主原生胶水)。

## Goals / Non-Goals

**Goals:**

- 插件在 opencode 2.0.32 与 2.1.0 双版本加载成功、拦截行为与 1.x 语义一致(同套越权样例
  对照)。
- 锚点在服务进程形态下仍指向项目根(哨兵发现 + 相对 token 判定同源)。
- 「未来再被静默拒载」被 CI 静态形状断言拦住。
- 判定逻辑零漂移:Python 守卫一行不改。

**Non-Goals:**

- 不做 `permission.evaluate` 权限闸门 / ask→deny(下一个 change)。
- 不做原生子代理派发、不动 fanout_runner。
- 不动 claude/dsh 两面的接线与 matcher。
- 不承诺 1.x opencode 继续可用本仓最新插件(见 D1)。
- 不在本 change 内验证 agent 定义全部 33 个的行为等价(只做加载与权限面抽查,见任务)。

## Decisions

### D1 单文件迁移到 2.x 契约,不做双形状

- **决策**:插件文件整体改为 `export default { id: "block-adhoc-scripts", async setup(ctx) {…} }`;
  不尝试同时满足 1.x(具名导出 + hook map)与 2.x(default 导出)。
- **理由**:同一模块同时出具两种导出,1.x 加载器收 hook map、2.x 收 default——2.1 源码的
  模块 schema 校验 default 字段,1.x 校验具名导出,两者可共存;但共存意味着两套回调签名
  (双参 vs 单事件)长期并行维护,且 1.x 面在企业已无部署(D8 确认 2.0.32)。维护两套签名
  的回归成本 > 保留 1.x 的收益。
- **备选否决**:双形状导出(共存)——被否,理由如上;发两个插件文件(`*_v1.ts`/`*_v2.ts`)
  ——被否,`.opencode/plugins/` 目录自动发现会同时加载两份,1.x 装 v2 文件会拒载(WARN)、
  2.x 装 v1 文件会拒载,「装错版本」的静默面反而翻倍,且 install 自检要区分两代文件名。

### D2 锚点:`setup` 捕获 `ctx.location.directory`,逐调用注入 payload `cwd`

- **决策**:`setup` 里记 `const projectRoot = ctx.location.directory`;每次守卫调用构造
  payload 时带上 `cwd: projectRoot`(与既有 `{tool_name, tool_input}` 并列)。守卫优先级
  payload `cwd` > 进程 cwd 已存在,Python 零改动。
- **理由**:2.x 服务进程 cwd 不可控(D8 实测服务由用户任意目录拉起);`ctx.location.directory`
  是插件能拿到的唯一权威「本项目在哪」信号(实测)。逐调用注入(而非 setup 时改 env)避免
  多项目/多 location 并存时互相踩。
- **备选否决**:spawn 守卫时 `cwd: projectRoot`(改子进程 cwd)——同样有效,但守卫进程
  cwd 同时还是「无 payload cwd 面」的回退锚,改它会把回退语义一并改掉,影响面大于注入
  payload 字段;env 注入 `MGH_TARGET`——语义过宽(不等价锚,且会盖过哨兵优先级),被否。

### D3 工具名双代收敛:两代 id 并存映射同一守卫面

- **决策**:`HANDLED` 与 `normalize` 同时收两代 id:`bash` 与 `shell` → `{tool_name:"Bash",
  tool_input:{command}}`;补丁面 `apply_patch` 与 2.x 的 `patch` id(实测确认字段形态后)
  → ApplyPatch 提取;其余沿用。守卫侧零改动。
- **理由**:同一安装可能被 2.0.x/2.1.x 任一版本加载(版本升回落都存在);删旧 id 或漏新 id
  都是静默漏收。接线覆盖回归测新增「两代 id 并存」断言。
- **未知项(apply 期实测定)**:2.x 补丁工具的确切 id 与参数形态(`patch`/`apply_patch`、
  `patchText` 字段是否沿用)。按防御原则:两 id 都收、字段按 `patchText` 优先缺失即空的
  提取——不猜分支语义,守卫对空 paths 自然放行(缺提取 = fail-open 于补丁面,在实机闸门
  验证时收口)。

### D4 诊断通道降级:去掉 `ctx.client.app.log`,阻断契约不变

- **决策**:v1 的非阻断诊断(fail-soft 提示)经 `ctx.client.app.log` 上报;2.x 上下文无此
  通道。迁移后诊断改 `console.warn`(best-effort,服务日志可见则可见);**阻断路径(退出码
  2 → throw stderr)逐字不变**。
- **理由**:诊断是可观测性糖,阻断才是安全语义;为糖引入 2.x 版本敏感的内部 API(其形状
  在 2.0.32 与 2.1.0 间可能漂移)不值。fail-soft 契约「守卫不在 → PASS」不变。

### D5 CI 静态形状断言(防再次静默拒载)

- **决策**:`tests/test_opencode_hook_parity.py` 增源码形状断言:`export default` + `{ id`
  + `await ctx.tool.hook(` 在场;`export const BlockAdhocScripts` 与双参回调形态缺席;
  `ctx.location.directory` 捕获 + payload `cwd` 注入在场;既有 Blob stdin/预检查断言保留。
- **理由**:宿主对插件加载失败按其设计 fail-soft(WARN 后继续),运行期无症可查;唯一能
  fail-loud 的位置是 CI。断言源码形态而非跑 Bun——CI 无 opencode 运行时,沿用本仓
  「source-form assertion」先例(既有 D7 Blob 断言同款)。

### D6 agent 定义 frontmatter:验证优先,最小修正

- **决策**:opencode 面 agent 的 `permission:` map 依赖 2.x 自动迁移(官方迁移映射含
  bash→shell)。本 change 只做:实机验证迁移后语义等价(`edit: deny` 仍拒、`bash: allow`
  仍放);对 2.x 无对应断言的惰性键(`doom_loop`、`list`)**保留不动**(惰性 = 无害,
  删除属清理,不混入安全 change)。
- **备选否决**:全量改写成 2.x `permissions:` 规则集——被否,33 个 agent 的改写收益
  (可读性)不抵风险(改写即重写权限语义,需逐个验证);等 opencode 1.x 退役后再做一次
  性清理。

## Risks / Trade-offs

- [2.0.32 与 2.1.0 插件 API 有差异(如事件字段名/setup 签名)] → 双版本实机闸门是 apply
  的硬性验收;先本机 2.1.0 实现验证,企业 2.0.32 复测;若两版契约冲突,以「两版都接受的
  公共面」实现并在契约里记录版本矩阵。
- [2.x 补丁工具形态未知,防御性双收可能空提取(fail-open 于补丁面)] → 实机闸门含一条
  补丁工具越树样例;空提取形态若确认存在,补最小字段映射(仍是胶水,不进判定)。
- [`ctx.location.directory` 在多 location/worktree 场景的取值] → 实机验证单项目场景正确;
  多 location 场景记录为已知边界(哨兵发现按项目根走链,与 1.x 语义一致或更严)。
- [形状断言误伤未来合法重构(如改 id 字符串)] → 断言锚「结构特征」(default 导出 + await
  注册 + cwd 注入)而非逐字文案;重构只要保留结构即过。
- [1.x opencode 用户升级本仓后插件失效] → install 自检输出披露「本插件面向 opencode 2.x」;
  README/CHANGELOG 随版本说明。这是接受的断代(企业已 2.0.32)。

## Migration Plan

1. 实现 + 本机 2.1.0 实机验证(加载、拦截样例、锚点)。
2. 企业 2.0.32 复测(同套样例;由内网执行,参照实机闸门清单)。
3. 合入后随下一次 install 分发;旧 1.x 安装在重装时自然换新文件(文件名不变)。
4. 回滚:revert 插件文件即可(判定逻辑无迁移);1.x 环境回滚后需同时回退本仓版本。

## Open Questions

- ~~2.x 补丁工具的确切 id/参数形态~~ → **已收口(apply 期,源码 + 实测)**:id = `patch`
  (与 1.x `apply_patch` 并存双收),参数 = `{ patchText }`,标记语法与 1.x 完全同形
  (同一解析器);运行时注记:2.1.0 默认模型工具集不暴露该工具(TOOL_UNAVAILABLE 实录),
  映射正确性由源码钉扎 + CI 双代断言 + 单测等价承担(实机笔记 §1/§2.4)。
- 2.0.32 的事件对象字段是否与 2.1.0 完全同名(双版本闸门回答;若不同,取公共面)——
  待企业闸门回执(复现清单在实机笔记 §4)。
