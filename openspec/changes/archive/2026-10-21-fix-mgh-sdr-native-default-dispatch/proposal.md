> **人话序** 现象:上一轮改造已经给 `/mgh-sdr` 接上了 opencode 原生派发(编排会话直接派子代
> 理,不再另起子进程),但真仓实测仍然跑了 `fanout_runner.py`;看主提示词和恢复脚本的输出,到
> 处仍在教人跑子进程派发。根因有两层:一是原生形态此前只在项目里手工写环境画像、明确选
> `native` 时才启用,缺省仍解析为子进程;二是即便选了 native,首选入口 `mgh_sdr_launch.py`
> 生成的编排提示词把第 3 步写死成子进程派发,命令壳、步骤清单、恢复脚本和报告也仍把子进程
> 当主路径。改什么:opencode 面不再需要手写画像,缺省即原生派发;子进程只在画像显式写
> `runner` 时作为回退,opencode 主提示词与恢复输出不再出现子进程派发指引;claude/dsh 两面
> 维持现状。怎么验证:opencode 面不带画像跑一条真分支,确认全链只走原生、零子进程派发;显式
> runner 时回退仍可用;claude/dsh 输出逐字节不变。

## Why

- 企业内网里 opencode 2.x 是绝大多数用户的实际宿主,而子进程派发在内网鉴权体系下几乎全灭。
  上一轮改造把原生派发做出来了,却把它藏在「项目手工写 `.mgh/env-profile.json` 并显式选
  `native`」之后;用户不写这份配置(绝大多数人不会写),真仓跑起来仍然是子进程派发,等于改
  造没有生效。
- 更直接的缺陷:首选零打断入口 `mgh_sdr_launch.py` 生成编排提示词时,第 3 步固定写死为
  `fanout_runner.py` 调用,完全不读环境画像。即使项目已经显式选了 `native`,经 launcher 启
  动的 run 仍然会跑子进程派发。这是与形态选择无关的硬编码缺陷。
- 命令壳、`list_sdr_steps.py`、`resume_sdr_state.py` 与报告披露也仍以子进程为主路径:缺省
  画像时恢复输出直接提示 `fanout_runner.py`;报告只在「计划工件在场且画像显式 native」时才
  披露原生形态。弱模型在多个「跑子进程」的提示中很容易回到旧路径。
- 上一轮为子进程派发补充的企业鉴权流程依赖随包安装的 `mgh-special-auth.md`,并把写
  `cred_source.json`、跑 `mgh_credentials.py`、追加 `--cred-file` 写死进 launcher/命令壳/
  恢复输出。该说明实际已失效,继续让流程按它执行只会把用户引向错误的鉴权操作;原生形态也
  不需要子进程凭证注入。

## What Changes

- **`/mgh-sdr` 在 opencode 面缺省改为原生派发(只作用于 sdr 消费方)**:
  - `env_profile.py` 增加「宿主面」与「消费者」两个解析维度:`/mgh-sdr`(consumer=sdr)在
    opencode 安装面(`.opencode/mgh-core/...`)且画像缺失或 `dispatch_mode:"auto"` 时解析为
    `native`;claude/dsh 安装面仍解析为 `runner`。其它命令(如 `/mgh-init`)继续按原缺省
    `runner`,本 change 不切换它们的形态。
  - 环境画像仍可显式覆盖:显式 `native` 保持原生,显式 `runner` 是 opencode 上唯一回到子进程
    的开关;坏画像继续 fail-closed(退出码 2 + recipe)。
  - 画像文件不是安装产物、也不需要用户创建;「不写配置 = sdr 在 opencode 原生」成为缺省事实。
- **sdr 链路全面去子进程主路径(opencode 面)**:
  - `releases/opencode/command/mgh-sdr.md` 主流程改为原生派发;删除「fan-out 刚性三元组 = 子进
    程派发器」、stage 表与确定性调用清单里的子进程调用行、以及「缺省/回退」措辞。子进程回退
    只在画像显式 `runner` 时出现,由 `list_sdr_steps.py` 的该步调用行承载,壳不再展开子进程
    的超时/配额/特殊认证细则。
  - `list_sdr_steps.py` / `resume_sdr_state.py` 使用解析后的派发形态:opencode 缺省画像时
    fanout 步直接给原生 arc(物化 → 同消息派子代理 → 重枚举),恢复 `next_action` 不再提示子
    进程;显式 runner 时才给子进程调用行。
  - `render_sdr_report.py` 的原生披露依据从「画像显式 native」改为「本次 run 的计划工件在场 ∧
    解析形态为 native」,使缺省画像的原生 run 也能在报告与 manifest 如实披露。
  - `mgh_sdr_launch.py`(首选零打断入口)按宿主与画像解析形态生成编排提示词:opencode 缺省
    生成原生第 3 步(看门狗 → 物化 → 同消息派子代理 → 重枚举),不再硬编码子进程派发;显式
    `runner` 或 claude 宿主仍生成现行回退提示词。
- **原生波次纪律 fragment 与契约同步**:明确 opencode 缺省即原生、`runner` 是显式回退、
  claude/dsh 仍为子进程;同步 `core/contracts/sdr/pipeline.md` 与
  `core/contracts/fanout/runtime.md` 的激活条件、缺省解析与三面披露。
- **特殊授权说明退役为可选项目入口**:
  - 从 `/mgh-sdr` 流程中删除针对子进程派发的硬编码鉴权步骤:不再在编排提示词/命令壳/恢复
    输出里要求写 `cred_source.json`、跑 `mgh_credentials.py`、追加 `--cred-file`,也不再要求
    处理 `credential_expired:true`。这些是上一轮为子进程派发加的企业鉴权接线,实际已失效。
  - 保留唯一入口:项目根 `.mgh/special-auth.md` 存在时,步骤清单的 `special_auth` 字段给出
    绝对路径,命令壳/launcher/恢复输出用一句话要求「先 Read 该说明,按其鉴权说明执行」;
    不存在则零动作、零额外提示。流程不再预设该说明会要求什么命令。
  - 停止把维护者随包的 `mgh-special-auth.md` 自动装进用户项目;install 只清理旧的安装树副本,
    不再复制源文件。需要特殊授权的部署方在 `<项目>/.mgh/special-auth.md` 放置有效说明即可
    重新启用入口。维护者私有源文件本身不删除。
  - `fanout_runner.py --cred-file` 与 `mgh_credentials.py` 保留为手动/遗留能力,但不再被任何
    sdr 流程引用;是否彻底删除留后续 change,不在本次扩大 fanout_runner 的改动面。
- **非目标**:
  - 不删除 `fanout_runner.py`;它仍是 claude/dsh 的主路径、opencode 显式 runner 的回退路径,
    也是非 opencode 宿主与既有 run 的兜底。
  - 不改六维检查本体、draft schema、写作纪律、基线投影、看门狗与权限闸门。
  - 不改 claude/dsh 命令壳的主路径;不改 `/mgh-init` 等其它命令的缺省形态(它们仍按原
    缺省 `runner`,本 change 不切换)。
  - 不做 `mgh_dispatch` 工具接入 sdr(本次只把「默认形态」与「提示词口径」修正到原生,派发
    仍走内置子代理调用)。

## Capabilities

### New Capabilities

<!-- 无。 -->

### Modified Capabilities

- `native-dispatch-core`: 环境画像的缺省解析从「缺失/auto 一律等于现行子进程形态」改为「按宿
  主安装面与消费者解析:`/mgh-sdr` 在 opencode 面 = native,其它消费者与 claude/dsh 面仍 =
  runner」;新增解析结果、宿主面与消费者的可观测字段;显式 `native`/`runner` 与坏画像
  fail-closed 语义保持不变。
- `security-design-review`: fan-out 派发要求从「opencode 面仅画像显式 native 才原生」改为
  「opencode 面缺省原生,显式 runner 才子进程回退」;新增 launcher、步骤清单、恢复与报告在缺
  省画像下的一致形态要求,以及 opencode 壳不把子进程派发当主路径的提示词口径要求。另新增
  「特殊授权说明只作可选项目入口」要求:存在 `<项目>/.mgh/special-auth.md` 时先读,
  不存在零动作;sdr 流程不得再硬编码 `mgh_credentials.py`/`--cred-file`/`cred_source.json`
  等凭证步骤;install 不再自动安装该文档。

## Impact

- **代码**:
  - `core/scripts/env_profile.py`(宿主面/解析形态);
  - `core/scripts/list_sdr_steps.py`、`core/scripts/resume_sdr_state.py`、
    `core/scripts/render_sdr_report.py`(按解析形态分支);
  - `core/scripts/mgh_sdr_launch.py`(按宿主与画像生成原生/回退提示词;特殊授权只留一句入口);
  - `core/scripts/discipline_core.py`(如需把 sdr 缺省纪律与解析形态对齐);
  - `core/scripts/fanout_runner.py`(仅特殊授权指针改为项目级入口;派发行为零改动);
  - `releases/opencode/command/mgh-sdr.md`、`releases/claude-code/commands/mgh-sdr.md`、
    `releases/dsh/skills/mgh-sdr/SKILL.md`、`core/prompts/fragments/sdr-native-dispatch.md`;
  - `install.sh`(停止自动安装 `mgh-special-auth.md`,清理旧安装树副本);
  - 分发树中的 `mgh-core/scripts/*` 与三面壳随 install 自动更新。
- **契约**:`core/contracts/sdr/pipeline.md`、`core/contracts/fanout/runtime.md`。
- **测试**:`test_env_profile`(宿主面/消费者/缺省解析/显式覆盖)、`test_list_sdr_steps`、
  `test_resume_sdr_state`、`test_render_sdr_report`、`test_mgh_sdr_launch`(原生提示词与零子
  进程 + 特殊授权入口)、`test_install_special_auth`(不再安装/清理旧副本)、
  `test_distributed_md_purity`、`test_dsh_command_surface`、opencode 壳/agent 形状锚;
  定向回归另带 `test_sdr_tier`、`test_fanout_runner`(回退路径与手动 `--cred-file` 不破)、
  `test_zero_deps`、`test_no_compile_warnings`;lint 四件套 + 壳预算 lint。
- **用户可见行为**:opencode 用户跑 `/mgh-sdr` 不写环境画像即走原生派发;要回到子进程必须
  显式写 `"dispatch_mode":"runner"`。claude/dsh 用户与其它命令(如 `/mgh-init`)的缺省行为
  无变化。`mgh-special-auth.md` 不再随安装进入用户项目;需要特殊授权的部署方在
  `<项目>/.mgh/special-auth.md` 放置说明,流程只保留「存在则先读」这一句入口。
- **实机闸门**:本机 opencode 2.1.0 真仓零画像跑 `/mgh-sdr`,确认 fan-out 步只出现原生派发、
  零 `fanout_runner` 进程;再用显式 `runner` 画像跑一次回退对照;claude/dsh 做输出不变抽查。
- **VERSION/CHANGELOG**:按仓库惯例 bump。
