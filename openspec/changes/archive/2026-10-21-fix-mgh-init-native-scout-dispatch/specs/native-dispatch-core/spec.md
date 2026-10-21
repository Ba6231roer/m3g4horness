## MODIFIED Requirements

### Requirement: 环境画像的读取、缺省与 fail-closed

`env_profile.py` SHALL 是模块导入 + CLI 双形态的确定性脚本(零依赖、`--help` 即契约),
读取项目级 `<项目>/.mgh/env-profile.json`,schema(未知字段忽略):

```
{"v":1, "dispatch_mode":"auto|runner|native",
 "native_concurrency":<int 1..5>,
 "quota":{"calls":<int>0>, "window_s":<int>0>, "calls_per_unit":<int>0>}}
```

全部键可选。**缺文件或 `dispatch_mode:"auto"` SHALL 按宿主安装面与消费者解析派发形态**:
宿主面由确定性来源判断(脚本所在安装路径的 `.opencode` / `.claude` 路径段;调用方也可显式
传入宿主面,launcher 用它覆盖自动判断);消费者由调用方显式传入(缺省 `generic`)。仅
`consumer ∈ {sdr, init} ∧ host=opencode` 时解析为 `native`;`consumer=generic`、其它消费者与
claude/other 安装面一律解析为 `runner`。显式 `dispatch_mode:"native"` / `"runner"` SHALL
覆盖缺省。解析结果 SHALL 可通过模块与 CLI 读取(宿主面 + 消费者 + 解析形态),CLI 增
`--consumer <sdr|init|generic>`(缺省 `generic`),stdout 仍为单行 JSON。**坏 JSON、未知 `v`、
枚举域外的取值、超范围并发 = fail-closed**(CLI 退出码 2 + recipe;导入形态抛类型化异常)。
`--check` SHALL 零副作用校验(不存在 schema 级失败时报告缺省解析结果,含宿主面、消费者与
解析形态)。本 change 之前「缺失/auto 一律等于现行子进程形态」的钉死 SHALL 被本条取代;
`consumer=generic`、claude 与其它安装面的缺省行为 SHALL 保持不变;`consumer=init` 是本
change 新增的缺省原生消费者(mgh-init 全流程转向 opencode 原生,用户已拍板)。

#### Scenario: 缺文件走缺省且零行为变化

- **WHEN** 项目无 `.mgh/env-profile.json`,命令从 claude 或其它安装面(dsh、开发树、自定义
  拷贝)运行,或从 opencode 面但消费者为 `generic`
- **THEN** 画像解析为缺省(auto/缺省并发/无配额参数),解析形态为 `runner`,与本次改动前
  的行为一致——这些安装面或消费者仍是「选择加入」的原生配置面;opencode 面的 sdr/init
  缺省变化见下两场景

#### Scenario: opencode 面 sdr 缺文件即原生

- **WHEN** 项目无 `.mgh/env-profile.json`,消费者为 `sdr`,命令从 opencode 安装面
  (`.opencode/mgh-core/...`)运行
- **THEN** 画像原始值仍为缺省(`dispatch_mode:"auto"`、并发 3、无配额),解析形态为
  `native`;不创建任何配置文件,也不要求用户手写画像

#### Scenario: opencode 面 init 缺文件即原生

- **WHEN** 项目无 `.mgh/env-profile.json`,消费者为 `init`(如 `/mgh-init` 的 scout 步),
  命令从 opencode 安装面运行
- **THEN** 画像原始值仍为缺省(`dispatch_mode:"auto"`、并发 3、无配额),解析形态为
  `native`——mgh-init 全流程的缺省原生与 sdr 同规则;不要求用户手写画像

#### Scenario: 其它消费者在 opencode 面仍非原生

- **WHEN** 项目无画像或画像为 `auto`,消费者为 `generic`,命令从 opencode 安装面运行
- **THEN** 解析形态仍为 `runner`,与本次改动前逐字节一致;opencode 的 sdr/init 缺省变化
  不扩散到未接原生的其它命令

#### Scenario: 显式 runner 在 opencode 面回退

- **WHEN** opencode 安装面的项目画像写着 `{"dispatch_mode":"runner"}`,消费者为 `sdr` 或
  `init`
- **THEN** 解析形态为 `runner`;原生形态不启用,子进程派发回退路径保持可用

#### Scenario: claude 与其它面缺省不变

- **WHEN** 无画像或画像为 `auto`,命令从 claude 安装面或其它安装面(dsh、开发树、自定义拷贝)
  运行
- **THEN** 解析形态为 `runner`,与本次改动前逐字节一致;不因 opencode 的缺省变更而改变

#### Scenario: 显式 native 保持原生

- **WHEN** 项目画像写着 `{"dispatch_mode":"native"}`,消费者为 `sdr` 或 `init`,命令从
  opencode 安装面运行
- **THEN** 解析形态为 `native`,与显式选择前的原生分支行为一致

#### Scenario: 坏文件 fail-closed

- **WHEN** `.mgh/env-profile.json` 存在但不可解析,或 `dispatch_mode` 取枚举域外值,或
  `native_concurrency` 为 0/6/非整数
- **THEN** CLI 退出码 2 + 一句 recipe(文件路径 + 违规字段);导入形态抛类型化异常——
  NEVER 静默回退缺省,包括 NEVER 把坏画像当成 opencode 的 native 缺省(静默回退会让「以为
  配了 native 实际跑 runner」的错配不可见)

#### Scenario: --check 零副作用校验

- **WHEN** 执行 `env_profile.py --check --consumer init`(或 sdr/generic)
- **THEN** 只读校验 schema 与取值域,stdout 报告宿主面、消费者与解析形态(或失败原因),
  不写任何文件
