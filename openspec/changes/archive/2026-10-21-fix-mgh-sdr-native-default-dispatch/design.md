## Context

本 change 要修的是「原生派发已经接上,但实际跑不到」的断点。真仓观测到的链路是:

| 观察点 | 现状 | 后果 |
|---|---|---|
| 环境画像缺省 | `core/scripts/env_profile.py` 把缺文件或 `auto` 解析为 `auto`,各消费者再比较 `profile.dispatch_mode == "native"` | 项目不手写画像时,形态判定永远是子进程 |
| 首选入口 | `core/scripts/mgh_sdr_launch.py` 的 `_build_prompt()` 把第 3 步写死为 `fanout_runner.py` 调用,完全不读画像 | 即使项目显式写了 `native`,经 launcher 启动也走子进程 |
| 命令壳 | `releases/opencode/command/mgh-sdr.md` 的「fan-out 刚性三元组」、stage 表、确定性调用清单仍以 `fanout_runner.py` 为主路径;原生步只是其中一段条件分支 | 弱模型读到的多数提示仍是「跑子进程」,容易回到旧路径 |
| 步骤与恢复 | `core/scripts/list_sdr_steps.py` / `core/scripts/resume_sdr_state.py` 只认画像显式 `native`;缺省画像时 fanout 步与 `next_action` 直接给 `fanout_runner.py` | 新会话/压缩恢复会把已经走原生意图的 run 拉回子进程 |
| 报告披露 | `core/scripts/render_sdr_report.py` 要求「计划工件在场 ∧ 画像显式 native」才披露原生 | 缺省画像的原生 run 报告不披露形态,事后无法对账 |
| 特殊授权 | `install.sh` 把维护者随包的 `mgh-special-auth.md` 装到 `<mgh-core>`;launcher、三面 sdr 壳、`resume_sdr_state` 与 `fanout_runner` 都按它硬编码凭证准备与 `--cred-file` | 该文档已证实失效后,流程仍在教错误的鉴权操作;原生形态用的是宿主会话自身 provider 配置,根本不需要子进程凭证注入 |

约束:

- `fanout_runner.py` 是 claude/dsh 面的主路径,也是 opencode 显式回退与既有 run 的兜底,**不能
  删除**;本 change 改的是「缺省选哪个」与「提示词口径」。
- opencode 面有原生落地的全部资产:`sdr-review-native` agent、`emit_native_plan.py`、
  `native_watchdog.py`、`mgh_dispatch.ts` 令牌展开钩子;claude/dsh 没有原生 agent,不能把缺省
  改成原生。
- 命令壳有 5,000 token 的硬预算(`R5.6`);当前 opencode 壳约 4.8K,删子进程细则腾出的空间
  正好容纳「原生为主」的措辞,不能再把子进程细则全文留在壳里。
- 分发面纯净性、三面镜像白名单、壳预算都有确定性 lint;改壳必须同时过这四件套。

## Goals / Non-Goals

**Goals:**

- opencode 安装面在用户不写任何配置时,`/mgh-sdr` 的缺省派发形态就是原生;命令壳、步骤
  清单、恢复查询、报告披露、launcher 提示词给出同一个答案。
- 显式 `dispatch_mode:"runner"` 仍能回到子进程形态,回退路径的调用行、超时不变式与派发行为
  保持现状。
- 特殊授权说明退化为可选项目入口:存在则先读,不存在零动作;sdr 流程不再硬编码任何凭证命令。
- claude/dsh 安装面的输出与行为逐字节不变。
- 用确定性测试锚住「缺省 opencode = 原生」与「缺省 claude/dsh = 子进程」,防止未来再漂回。

**Non-Goals:**

- 不删除 `fanout_runner.py`,不改其 wave / 配额 / 重派 / 标记行为。
- 不在本 change 删除 `fanout_runner --cred-file` 与 `mgh_credentials.py`;它们保留为手动/遗留
  能力,只是不再被 sdr 流程引用。
- 不改六维检查本体、draft schema、写作纪律、基线投影、敏感目录、看门狗与权限闸门。
- 不把 `mgh_dispatch` 工具接进 sdr 派发;本 change 后 sdr 仍用内置子代理 + 令牌展开钩子。
- 不新增项目侧必填配置文件;环境画像仍是可选的覆盖面。
- 不做企业内网实机认证;本机 opencode 2.1.0 闸门 + 企业交接清单即可。

## Decisions

### D1 缺省按「宿主安装面 + 消费者」解析:sdr 在 opencode = native,其余仍 runner

- **决策**:`env_profile.py` 增加宿主面与消费者两个解析维度。安装路径含 `.opencode` 段 →
  `opencode`;含 `.claude` 段 → `claude`;其余(dsh 的 `mgh-core/`、开发树、自定义拷贝)→
  `other`。消费者由调用方显式传入(`/mgh-sdr` = `sdr`;未传 = `generic`)。画像缺失或
  `dispatch_mode:"auto"` 时:仅 `consumer=sdr ∧ host=opencode` 解析为 `native`;
  `consumer=generic`、其它消费者与 claude/other 面一律解析为 `runner`。显式
  `native`/`runner` 覆盖缺省。
- **理由**:用户不写配置是常态;opencode 2.x 是绝大多数 sdr 用户的实际宿主。把「安装面」
  作为能力信号是确定性的:opencode 安装树必然带 `sdr-review-native` 与派发插件,claude/dsh
  安装树没有。同时把缺省限定在 sdr 消费方,`/mgh-init` 等尚未验证原生的命令继续按原缺省
  runner,避免一个 change 顺带切换多条命令的形态。
- **备选否决**:
  - **install 时写一份 `.mgh/env-profile.json`**:会在用户项目里制造一个需要维护的配置文件,
    升级/迁移时容易过期;且「不写配置 = 原生」本来可以由安装面直接表达。
  - **`auto` 继续等于子进程,只靠文档劝用户写 native**:正是本次真仓失败的原因,等于没修。
  - **所有宿主/所有命令缺省 native**:claude/dsh 没有原生 agent,init 等命令也未接原生;会在
    spawn 时失败或把未验证的路径变成缺省,属于把问题后移。

### D2 形态解析单一真相源:`env_profile` 出一个 `form`,各编排面只消费

- **决策**:`env_profile.py` 暴露三项可观测结果:
  - `host_face ∈ {opencode, claude, other}`;
  - `consumer`(调用方显式传入,`sdr` 或 `generic`);
  - `form ∈ {native, runner}`(解析后的派发形态);
  - CLI stdout 在既有 `profile` 之外增 `host_face`、`consumer` 与 `form`;`--check` 同样报告;
    CLI 增 `--consumer <sdr|generic>`(缺省 `generic`),供命令壳 step 0 与 launcher 使用。
  `list_sdr_steps.py` / `resume_sdr_state.py` / `render_sdr_report.py` 的形态判断改为调用
  同一个解析函数(consumer=`sdr`),不再各自比较原始 `dispatch_mode`。原生分支的 `dispatch`
  字段增 `source:"profile"|"host-default"`、`profile_exists`、`host_face` 与 `consumer`,供
  恢复与报告对账。
- **理由**:本次问题的根因之一就是「形态判定散落在四个消费者」;每个消费者都只认显式
  `native`,缺省语义自然分裂。把解析收敛到一个模块后,容器/宿主差异只在一个地方处理。
- **备选否决**:每个脚本各写一份「缺省 opencode = native」;后续再加宿主或再改缺省时会
  出现第二、第三套判断,重现本次漂移。

### D3 launcher 按宿主与画像生成提示词,不再硬编码子进程

- **决策**:`mgh_sdr_launch.py` 在 `sdr_context` 之后、spawn 宿主之前读取画像,以
  `consumer=sdr` 解析形态。
  - 宿主 `opencode` + `form=native` → 第 3 步生成原生提示词:看门狗先行 → 每轮
    `emit_native_plan.py` 物化 + `--check` → 同一条 assistant 消息派 `sdr-review-native` 子代理
    (任务体 = 计划短号的令牌行)→ 重物化重枚举;提示词给出 `sdr-native-dispatch.md` 的绝对
    路径,细节按该 fragment 执行。
  - 宿主 `opencode` + `form=runner` → 保持现行子进程提示词。
  - 宿主 `claude` → 保持现行子进程提示词。
  - 宿主 `claude` 但画像显式 `native` → 退出码 2 + recipe(原生形态仅 opencode 支持;改
    `dispatch_mode:"runner"` 或换 `--host opencode`),NEVER 静默降级。
  - 坏画像 → 退出码 2 + recipe,不 spawn 宿主。
  - 特殊授权说明只加一句项目级入口(`<repo>/.mgh/special-auth.md` 存在则先 Read);原生与
    回退提示词都不再出现 `mgh_credentials.py`/`--cred-file`/`cred_source.json` 的凭证准备块。
- **理由**:launcher 是「人/cron 一条命令」的首选入口,真仓失败很可能就是经它启动的。它的
  提示词必须与命令壳同源,否则改壳也白改。把它置于「宿主 + 画像」的确定性解析之下,才能
  同时服务 opencode 原生与 claude 回退。
- **备选否决**:让 launcher 直接调用 `list_sdr_steps.py` 并解析 JSON 生成 prompt;步骤清单
  是静态契约,不携带 run 目录与本次 `sdr_context` 产物,仍要 launcher 拼 run 相关路径,反而
  多一层解析。保持 launcher 自己按解析形态拼提示词,路径全部来自本进程已知的 run 目录。

### D4 opencode 壳原生为主,子进程只留「显式 runner」一句回退指引

- **决策**:重写 `releases/opencode/command/mgh-sdr.md` 的编排流:
  - 删除「fan-out 刚性三元组 = 子进程派发器」,改为原生三元组:
    `[diff_group pending[]] → [emit_native_plan 计划 + 任务文件] → [sdr-review-native 子代理 + 磁盘标记]`。
  - step 3 只展开原生步骤;子进程回退不再在壳里展开超时/配额/凭证细则,只写「解析形态为
    `runner` 时,按 `list_sdr_steps.py --step fanout` 的 invocation 与 discipline 执行」。
  - stage 表、确定性调用清单、Always disclose 里的 `fanout_runner.py` 调用行与「缺省/回退」
    措辞全部移除;opencode 壳正文不出现 `fanout_runner` 字面量。
  - `--quota-*` 参数保留为「runner 回退专用」一行说明;原生形态的配额从环境画像 `quota` 读取。
- **理由**:命令壳是弱模型最可靠的行为指令源。只要壳里还有「主路径 = 子进程」的句子,模型
  就可能忽略条件分支。把子进程细节移出壳,既满足「不出现 fanout_runner 说明」,也腾出
  token 预算给原生步骤。
- **备选否决**:保留子进程主路径、只把画像缺省改成 native。模型仍会读到互相矛盾的指令,
  真仓很可能再次跑子进程;这是本次已经观测到的失败模式。

### D5 步骤、恢复、报告的形态判断改为「解析形态」,保留 subprocess 字段形状

- **决策**:
  - `list_sdr_steps.py`:解析形态为 native 时 fanout 步 = `emit_native_plan.py` + `native_arc`
    + 顶层 `dispatch`;否则保持既有 `fanout_runner.py` 步与「无 `dispatch` 字段」的字节级
    形状。
  - `resume_sdr_state.py`:解析形态为 native 时走既有原生分支(计划在场 → 派波次;缺席 →
    物化 + 看门狗);否则走既有子进程 `next_action`。`dispatch` 字段增
    `source`/`profile_exists`/`host_face`。
  - `render_sdr_report.py`:披露条件从「画像显式 native」改为「本次 run 的 `native_plan.json`
    在场 ∧ 解析形态 native」。证据串同步写明是画像显式选择还是宿主缺省。
- **理由**:这三个脚本是编排器在压缩/新会话后的磁盘真相源。它们若继续只认显式 `native`,
  缺省原生 run 在恢复时仍会被提示子进程,等于把问题延迟到下一次中断。
- **备选否决**:只在壳里改,脚本保持旧判断;恢复路径会立即把用户拉回子进程,不可接受。

### D6 claude/dsh 与 `fanout_runner` 原样保留

- **决策**:`fanout_runner.py` 源码、claude/dsh 壳、两者 agent 定义零改动;`env_profile.py`
  在 claude/other 安装面与 `consumer=generic` 时的缺省解析仍是 runner;`/mgh-init` 等其它
  消费者不传 `consumer=sdr`,因此保持原缺省。opencode 面显式 `runner` 时,
  `list_sdr_steps.py` 仍给出原来的子进程调用行与完整 discipline。
- **理由**:企业里仍有 claude/dsh 宿主与「opencode 但想用子进程」的场景;删掉回退会把一个
  可选路径变成不可用。保留回退也让本 change 可以独立回滚(画像写 runner 即可)。
- **备选否决**:删除 `fanout_runner.py`;破坏两面与全部既有 run,超出本 change 目标。

### D7 原生资产在场检查,缺失时 fail-loud 而不是静默回退

- **决策**:opencode 面解析为 native 时,sdr 编排面在进入 fan-out 前检查安装树内的
  `sdr-review-native` agent 与 `sdr-native-dispatch.md` fragment 在场;缺失 → 退出码 2 +
  recipe(重跑 `install.sh --opencode` 或显式 `dispatch_mode:"runner"`),NEVER 静默改跑子进程。
  安装自检同步增加这两个条目的存在性检查。
- **理由**:本 change 把 native 变成缺省;若安装树版本错配(脚本新、agent 旧/缺),用户会得到
  一个无法派发的 run。静默回退 runner 会重现「以为 native 实际 runner」的不可见错配;显式
  失败 + 重装指引更诚实。
- **备选否决**:缺 agent 就回退 runner;与 fail-closed 的既有画像契约冲突,且会把安装问题
  伪装成正常回退。

### D8 特殊授权只留项目级入口,删除硬编码凭证流程

- **决策**:特殊授权说明的唯一入口 = `<repo>/.mgh/special-auth.md`(项目所有、手工放置)。
  `list_sdr_steps.py` 的 `special_auth` 字段探测该路径并给绝对路径(命令壳调用时传
  `--target <abs>`,不依赖 cwd);命令壳、launcher 与恢复输出在它存在时只加一句「先 Read 该
  说明,按其鉴权说明执行」,不存在时零动作。sdr 编排面 SHALL NOT 再出现 `cred_source.json`、
  `mgh_credentials.py`、`--cred-file`、`credential_expired` 的硬编码步骤。
- **理由**:这份说明是上一轮为子进程派发写的企业鉴权 runbook,实际已证实失效;继续把它
  当作流程的固定分支,会让每次 sdr run 都执行一套错误的凭证准备。原生形态使用宿主会话自身
  的 provider 配置,也不需要子进程凭证注入。把说明降级为「项目级可选入口」后,流程只承诺
  「存在就先读」,具体要做什么由说明自己决定;失效说明不再随安装自动出现。
- **备选否决**:
  - 保留安装树路径 + 继续自动安装:失效文档会跟随每次安装,入口必然触发,等于继续注入错误
    指引。
  - 继续按文档硬编码 `mgh_credentials.py`/`--cred-file`:把已失效的具体命令写死进流程,文档
    一改就要再改代码,且 native 形态根本不需要。
  - 彻底删除入口:未来若出现有效的企业鉴权说明,流程没有任何合法入口,只能再改一次代码。

### D9 停止自动安装失效文档;手动凭证能力保留但退出流程

- **决策**:`install.sh` 不再把维护者仓库根部的 `mgh-special-auth.md` 复制进目标项目;如果
  目标里存在旧的 `<dest>/mgh-core/mgh-special-auth.md`,install 删除它并打印一行迁移提示
  (改放到 `<项目>/.mgh/special-auth.md`)。维护者私有源文件不删除。`fanout_runner.py
  --cred-file` 与 `mgh_credentials.py` 保留为手动/遗留能力,帮助文本与契约标注「不在任何
  命令流程中使用」,派发行为与测试保持。
- **理由**:失效文档跟随安装是「流程仍在用错误鉴权」的源头;停装后入口只由部署方主动放置
  有效说明才触发。删除 `--cred-file`/`mgh_credentials.py` 需要动 fanout_runner 的主流程与
  大批测试,超出本 change 的目标;保留为手动能力既不影响 sdr 流程,也给非 opencode 宿主留
  一个显式逃生口。
- **备选否决**:本 change 直接删除 `mgh_credentials.py` 与 `--cred-file`(改动面大、破坏手动
  能力、与「先修默认派发」目标不匹配);继续自动安装(见 D8 备选)。

## Risks / Trade-offs

- **[多面安装的项目:`.opencode` 与 `.claude` 同时存在,脚本从哪面运行决定宿主面]** → 宿主面
  以脚本自身安装路径为准(路径段 `.opencode`/`.claude`),不按项目目录里有什么文件猜;launcher
  用 `--host` 与宿主 CLI 探测结果显式覆盖。测试覆盖多面目标下的 claude/dsh 输出不变。
- **[共享 `env_profile` 的其它消费者被误切到原生]** → 缺省解析带 `consumer` 维度:只有显式传
  `sdr` 的 sdr 编排面在 opencode 面拿到 native 缺省;`/mgh-init` 等消费者不传该参数,仍按原
  缺省 runner。测试同时锚定「sdr + opencode = native」与「generic/init + opencode = runner」。
- **[既有 runner run 在升级后恢复,形态从 runner 变成 native]** → 两种形态共用同一套
  drafts/markers;已完成单元按磁盘标记出局,未完成单元由原生计划重新物化。若 run 目录还残留
  旧 `fanout_runner.*.pid`,恢复查询继续按现状提示清理;不阻断。显式 `runner` 的项目保持旧形态。
- **[弱模型仍可能凭旧记忆跑子进程]** → opencode 壳不出现 `fanout_runner` 字面量;步骤清单与
  恢复输出在缺省画像下只给原生动作;launcher 提示词只给原生步骤。三道提示面同时收口,测试
  锚定三处都不含子进程调用。
- **[既有部署依赖安装树里的特殊授权文档]** → install 删除旧安装树副本并打印迁移提示;需要
  特殊授权的部署方把有效说明放到 `<项目>/.mgh/special-auth.md`。失效文档不再自动出现;入口
  仍可用,但内容由部署方负责。
- **[手动 `--cred-file` 变成无流程引用的遗留能力]** → 保留实现与测试,帮助文本/契约标注
  「手动/遗留,不在 sdr 流程中」;本 change 不删除,后续确认无使用方再单独清理。
- **[用户手工放置的说明本身仍有错]** → 流程只承诺「存在则先读」,不再替它预设命令;说明的
  正确性由部署方维护,流程不会把错误命令写死进编排。
- **[`list_sdr_steps --target` 从占位参数变成实际探测路径]** → 默认 `.` 仍可用;所有调用方
  已传 `--target <abs>` 或使用 run 目录布局;测试覆盖缺省/绝对路径两种形态。
- **[显式 native 但宿主是 claude/无原生 agent]** → launcher 退出码 2 + recipe;命令壳在
  claude 面不读 native 分支(仍子进程),保持原有披露。安装自检检查 agent 在场,减少版本
  错配面。
- **[壳预算回归]** → 删除的子进程细则(超时不变式、配额三 flag、凭证块)远多于新增的原生
  指引;预算 lint 入任务,opencode 壳目标 < 4.8K mid tokens。
- **[报告披露条件改变导致既有快照变化]** → 只在「计划工件在场 ∧ 解析 native」时增字段;
  runner run 与 claude/dsh run 输出保持逐字节不变;新增测试覆盖两种缺省。
- **[多分支 launcher 遇到坏画像]** → 坏画像在 spawn 前 fail-closed;单分支与多分支都在同一
  个解析点失败,不会出现「部分分支跑了 runner」的混合形态。

## Migration Plan

1. 先落 `env_profile.py` 的宿主面/解析形态与单测;此步不改变任何 shell 行为。
2. 改 `list_sdr_steps.py` / `resume_sdr_state.py` / `render_sdr_report.py` 消费解析形态,跑
   定向测试(缺省/显式/坏画像/三面)。
3. 改 `mgh_sdr_launch.py` 的原生提示词与 fail-closed 分支,补 launcher 测试。
4. 重写 opencode 壳与 fragment 的形态措辞;同步三面壳的特殊授权入口;跑预算、纯净性、
   契约 lint。
5. 特殊授权退役:`list_sdr_steps`/`resume_sdr_state`/`fanout_runner` 的探测路径改项目级、
   launcher/壳删除凭证细节、`install.sh` 停装并清理旧副本;跑 `test_install_special_auth`
   与 launcher/resume/list 的入口测试。
6. 本机 opencode 2.1.0 真仓闸门:无画像跑一条分支,确认零 `fanout_runner` 进程;再写
   `runner` 画像跑回退对照;有/无 `.mgh/special-auth.md` 各跑一次,确认只有一句入口、零
   凭证命令;claude/dsh 做输出不变抽查。
7. 更新 VERSION/CHANGELOG 与根 AGENTS.md 的命令族说明;企业 2.0.32 只做交接清单,不阻塞
   归档(沿用前例)。

回滚:opencode 项目写 `{"dispatch_mode":"runner"}` 即回到旧形态;或 revert 本 change 的壳/
脚本。特殊授权文档如仍需使用,放在 `<项目>/.mgh/special-auth.md`;不再依赖安装树副本。run
目录产物两形态互通,无需数据迁移。
