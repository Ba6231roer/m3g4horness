# native-dispatch-core Specification

## Purpose

为「编排器直派原生子代理」的扇出形态提供确定性计划基座:把每单元的完整任务消息、波次划分
与短单元号物化为磁盘工件,把派发形态/并发/配额的环境画像变成机器可读配置;自身不派发、不
持凭证、不起任何模型宿主进程,是现有子进程派发器的旁路供给面而非替代。

## Requirements

### Requirement: 计划物化入口的确定性与零派发副作用

`emit_native_plan.py` SHALL 是确定性叶脚本(R5.3 形态:零依赖、任意 cwd、`--help` 即契约、
stdout 恰好一行结构化 JSON、stderr 进度、退出码 0/1/2),按 `--tier` 复用子进程派发器的同
一套模块级资产(tier 表、枚举器调用与 run 目录锚定、模板加载、逐字填充、路径锚树校验、安
全文件名),**派发器源码零改动、其行为零变化**。物化产出:

- `<run>/inputs/<unit>.task.md`:每单元的完整任务消息,内容 = 模板逐字填充(与派发器执行
  时写的审计副本同路径同内容);
- `<run>/native_plan.json`:波次表与单元映射(见下)。

计划内容 SHALL 确定性:不含时间戳、单元按规范 id 稳定排序、同输入两次物化**逐字节一致**。
物化 SHALL 零派发副作用:不 spawn 任何模型宿主进程、不读写凭证、不创建子进程隔离目录、不
写/touch 任何完成或失败标记;枚举器子进程(待办清单的确定性来源)除外。stdout 摘要 SHALL
至少含 tier、单元总数、波次数、波次尺寸及其来源(并发上限与配额算术的较小者)、计划与
inputs 目录的绝对路径。

#### Scenario: 同输入两次物化逐字节一致

- **WHEN** 同一 run 目录与参数下连续执行两次物化(中间不派发任何单元)
- **THEN** `native_plan.json` 与全部 `<unit>.task.md` 两次产出逐字节一致(内容无时间戳、排
  序稳定)——计划是纯函数产物,可作断点续跑与审计的对账基准

#### Scenario: 零派发副作用

- **WHEN** 执行一次物化
- **THEN** 全程无模型宿主进程被 spawn、无凭证文件读写、无子进程隔离目录创建、无标记文件
  写入(枚举器子进程除外);`fanout_runner.py` 的任何运行路径未被触碰——「不改变现状」由
  构造保证(派发器源码零改动)

#### Scenario: 模板填充与锚树校验沿用派发器同一实现

- **WHEN** 某 tier 的单元经物化
- **THEN** 任务消息由派发器同一模板加载与逐字填充函数产出(无残留 `{{` 占位符),路径字
  段过同一锚树检查——原生形态与子进程形态的单元输入构造零漂移

### Requirement: 短单元号的稳定派生与防错抄

`emit_native_plan.py` SHALL 为每单元派生带 tier 前缀的短号(形如 `<tier>-<4 字符>`,字符集
去除易混淆字符),规则:

1. **稳定**:短号由规范单元 id 确定性派生(哈希后取字符)——pending 集变化(断点续跑、部
   分完成)后同一单元得到同一短号;
2. **防错抄**:同一次产出的计划内,任意两个短号的编辑距离 ≥2(单字符错抄不会命中另一合法
   短号);不满足时按确定性加盐序列重派生(同输入同结果);
3. **映射闭合**:计划内保存「短号 ↔ 规范单元 id ↔ 任务文件/产物/标记绝对路径」三方映射;
   `--check` 对映射闭合性与防错抄不变量 fail-loud。

#### Scenario: 断点续跑后短号不漂

- **WHEN** 一批单元完成后(pending 集缩小)对剩余单元重新物化
- **THEN** 剩余单元的短号与首次物化时相同(派生自规范 id 而非序号)——跨波次/跨会话引用短
  号无歧义

#### Scenario: 防错抄不变量被 --check 强制

- **WHEN** 计划内存在两个短号编辑距离为 1(构造缺陷或人为篡改)时执行 `--check`
- **THEN** 退出码 2 + 指明冲突短号——「错抄一号命中另一合法单元」的静默错配面被收口

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

### Requirement: 计划自检 --check 的 fail-loud 契约

`emit_native_plan.py --check` SHALL 对既有计划工件做零修复校验,失败退出码 2 + 指明具体
违规项:①重物化比对——按当前磁盘状态重新计算计划,与磁盘上的 `native_plan.json` 及全部
`<unit>.task.md` 逐字节比对(差异 = 磁盘状态已前进或计划被篡改,均 fail-loud 并在 recipe
中说明「重物化即修复」);②单元集与枚举器当前 pending 一致(已完成单元应使计划过时——
`--check` 如实报告而非通过);③全部路径绝对且过锚树检查;④模板无残留占位符;⑤短号映射
闭合且两两编辑距离 ≥2。`--check` SHALL 与物化一样零派发副作用。

#### Scenario: 磁盘状态前进后 --check 如实报告

- **WHEN** 计划产出后若干单元已完成(marker 在场),执行 `--check`
- **THEN** 退出码 2,报告「单元集与当前 pending 不一致」并给出重物化指引—— stale 计划不
  被当作有效计划消费

#### Scenario: 篡改/漂移被逐字节比对捕获

- **WHEN** 计划或任一 task 文件被手工修改(或生成时环境不一致)后执行 `--check`
- **THEN** 重物化比对失败,退出码 2 + 指明差异文件——计划工件是可对账的确定性产物,不是
  可编辑的随手文件

#### Scenario: 干净计划通过

- **WHEN** 刚完成物化且无单元完成时执行 `--check`
- **THEN** 退出码 0,stdout 报告校验通过的单元数/波次数——「物化 → 自检 → 消费」是接入方
  的标准序列
