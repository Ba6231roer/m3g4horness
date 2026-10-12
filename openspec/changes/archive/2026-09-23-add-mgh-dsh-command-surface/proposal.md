# add-mgh-dsh-command-surface

## Why

> **人话序** 现象:地基(守卫三端执法)落地后,dsh 用户仍然没有任何入口触发 mgh 工作流——
> 本项目的命令壳(`/mgh-sast` 等 5 条)是 markdown 文件,靠 Claude Code 的 commands 目录或
> opencode 的 command 目录装载,而 dsh **没有 markdown 斜杠命令加载器**。根因:命令壳是宿主
> 方言资产,每个宿主需要一个承载插槽。dsh 恰好提供了等价插槽:它原生支持 Anthropic 式
> SKILL.md,且标了 user-invocable 的 skill 可以直接 `/名字` 调用(把 skill 正文注入当轮)。
> 改什么:为 5 条已发布命令各写第三方言壳(`releases/dsh/skills/mgh-*/SKILL.md`),约定
> 「`/mgh-x` 后续文字 = 参数」,丢失的 `allowed-tools` 白名单由守卫三面执法 + 宿主 approval
> 顶替;install 的 `--dsh` 方言扩一个 skills 落位步骤。怎么验证:契约 lint 三面化全绿 +
> 真机 `/mgh-sdr`(默认参数路径)从召起到出报告全程可跑,守卫拦截与双壳同形。
> mgh-blst 仍为空骨架,不在范围。

- **机会**:dsh 的 skill 装载器与本项目的「薄壳 + lazy 加载 fragments」模式几乎同构
  (一层 SKILL.md + 按需 Read 深文件,热更新目录 watch),迁移是方言映射而非重写。
- **为何独立成 change**:它只依赖 change 1 的守卫地基(命令壳无守卫不得上线);与扇出/
  subagent 面正交(skill 壳内部写的 Agent 派发动作在 change 3 才在 dsh 上可用,故本 change
  的端到端验收只挑**不依赖 fan-out 的短路径**——见 tasks 验收节;sdr/sra 的 fan-out 段在
  change 3 前显式降级披露)。
- **为何不做 dsh 原生 TS 命令**:dsh 正式 commands 面要求 TypeScript 插件 handler,会把
  参数解析逻辑复制进 TS 端、破坏「壳文本是调用示例单一镜像」的契约 lint 模型;user-invocable
  skill 路径零代码、同受 token 预算纪律约束。

## What Changes

- **新增第三壳方言** `releases/dsh/skills/mgh-{sast,init,sra,srr,sdr}/SKILL.md`:
  - frontmatter:`name`(kebab-case,与目录名一致)、`description`(与双壳同源,≤1536 字符)、
    `user-invocable: true`、`disable-model-invocation: true`(编排流程只许用户显式召起,
    防模型自行触发全流水线);
  - 正文 = 编排流骨架 + stage→组件表 + 确切确定性调用 + 边界披露(与 claude/opencode 壳
    逐字对等为第三镜像,仅方言差异白名单:frontmatter、召唤语义段、`allowed-tools` 缺失的
    边界披露段);
  - 参数语义:dsh 无 `$ARGUMENTS` 模板,`/mgh-x` 召唤后**用户消息余文原样在场**,壳 step 0
    从触发消息读取参数;`--help` → 打印参数表后 STOP;无参行为逐命令沿用既有参数表声明
    (sdr 默认集执行,其余 STOP);
  - `allowed-tools` 白名单缺失的顶替声明:dsh 端执行边界 = 守卫三面执法(读/写/Bash 净网)
    + 宿主 approval/sandbox,壳顶部纪律段显式披露该分歧。
- **lazy 加载约定保持**: fragments 仍经 `REQUIRED SUB-SKILL: Use X` 标记 + 按需 `Read`
  (dsh 与 opencode 同样无跨文件自动内联);引用路径统一指 `<target>/mgh-core/`。
- **install `--dsh` 扩面**:新增 skills 落位步骤(复制 5 个 skill 目录 →
  `<target>/.dsh/skills/`,幂等覆盖更新;自检断言 5 壳齐全 + frontmatter 必含字段)。
- **lint 三面化**:契约 lint(逐字镜像 flag 存在断言)与壳 token 预算 lint 的扫描集纳入
  `releases/dsh/skills/**`;分发纯净度 lint 自动覆盖新分发文件(扫描面按目录通配,无需改码,
  加断言用例证明)。
- **非目标**:不改 claude/opencode 两端既有壳正文;不实现 fan-out 在 dsh 上的可派发
  (change 3);不做 mgh-blst;dsh 壳与双壳的「同 PR 三镜像」维护纪律写入手册映射行。

## Capabilities

### New Capabilities

- `dsh-command-surface`: mgh 命令壳在 dsh 上的 skill 方言承载——frontmatter 契约、`/name`
  召唤与参数读取语义、白名单顶替的边界披露、落位与安装、三面 lint 覆盖。

### Modified Capabilities

- 无(纯净度/预算 lint 的既有要求本以「全部分发文件」为扫描面,新目录入扫属实现而非规格变化;
  守卫与 fan-out 规格分属 change 1/3)。

## Impact

- **新增**:`releases/dsh/skills/`(5 个 SKILL.md)、`tests/test_dsh_command_surface.py`
  (frontmatter 形状 + 三面 flag 镜像一致 + 预算)、install dsh 分支扩面。
- **修改**:`install.sh` / `install.ps1`(skills 落位)、契约 lint 与预算 lint 的工具扫描集
  (`tools/check_contracts.py`、预算 lint 入扫目录清单)、研发手册测试映射表与版本号。
- **不受影响**:双壳正文、全部叶脚本与产物 schema、提示词与 fragments 本体。
- **前置依赖**:change `add-mgh-dsh-host-foundation`(无守卫执法的命令壳不得分发)。
