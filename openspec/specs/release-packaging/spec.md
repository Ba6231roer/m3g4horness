# release-packaging Specification

## Purpose

面向企业内网 skillhub 分发通道的一键打包能力:开发者在本仓一条命令产出 opencode 安装 zip
包,包根携带 skillhub 上传格式要求的惰性 SKILL.md;企业用户把包内容解压到项目根即完成安
装,效果与跑安装脚本字节等同。

## Requirements

### Requirement: 打包命令与边界

install.sh SHALL 提供打包模式 `--pack[=<输出.zip>]`,且打包模式仅限 opencode 安装面。打包
成功 SHALL 产出一个 zip 文件,缺省文件名为 `m3g4horness-<版本>-opencode.zip`,版本号取自
仓库 VERSION 文件。以下组合 SHALL 以退出码 2 拒绝并输出原因、不产出任何 zip:与
`--claude` 或 `--dsh` 同传(这两类安装面需要改写用户既有配置或机器本地宿主状态,zip 解压
覆盖不了);与 `--no-enforce-hook` 同传(分发包固定含守卫与派发插件的缺省姿态);VERSION
文件缺失或为空。

#### Scenario: 缺省打包产出带版本的 zip

- **WHEN** 在本仓根执行 `install.sh --pack`,且 VERSION 文件存在
- **THEN** 当前目录产出 `m3g4horness-<版本>-opencode.zip`,退出码 0,终端输出包路径

#### Scenario: 显式输出路径

- **WHEN** 执行 `install.sh --pack=<指定路径>.zip`
- **THEN** zip 写到指定路径,退出码 0

#### Scenario: 与非 opencode 面同传被拒

- **WHEN** 执行 `install.sh --pack --claude` 或 `install.sh --pack --dsh`
- **THEN** 退出码 2,stderr 说明仅 opencode 支持打包及原因,无 zip 产出

#### Scenario: 与关闭守卫同传被拒

- **WHEN** 执行 `install.sh --pack --no-enforce-hook`
- **THEN** 退出码 2,stderr 说明分发包固定含守卫插件,无 zip 产出

#### Scenario: VERSION 缺失被拒

- **WHEN** VERSION 文件缺失或内容为空,执行 `install.sh --pack` 或 `install.sh --pack=<指定路径>.zip`
- **THEN** 退出码 2,stderr 说明版本号缺失,无 zip 产出

### Requirement: 包结构契约

打包产出的 zip 顶层 SHALL 恰为三个条目:`SKILL.md`、`.opencode/`、`.mgh-sra/`,此外零多余
条目。`.opencode/` 内 SHALL 完整包含安装面五树:command(全部命令壳)、agent(全部 subagent
定义,含扇出与原生存量)、hooks(守卫脚本)、plugins(守卫插件与派发插件两件)、mgh-core
(全量核心:scripts、prompts、contracts、profiles 等)。`.mgh-sra/` 内 SHALL 含敏感目录模
板示例文件。`SKILL.md` SHALL 满足标准 skill 格式:frontmatter 含 `name: m3g4horness` 与非
空 `description`,正文声明本文件仅为上传格式要求、非功能入口、解压后可删除。

#### Scenario: 顶层条目闭集

- **WHEN** 研发仓库中存在大量非分发目录(规格树、回归测试、构建工具、私有资料等)时执行打包
- **THEN** zip 顶层仍恰为 `SKILL.md`、`.opencode/`、`.mgh-sra/` 三条目,上述非分发内容零出现

#### Scenario: 关键资产逐项在场

- **WHEN** 解包任一次打包产物
- **THEN** 全部命令壳、全部 subagent 定义、守卫脚本、两件插件、mgh-core 全量与敏感目录模板
  均在场,与一次脚本安装的落地内容一致

#### Scenario: SKILL.md 形态

- **WHEN** 解包读取根上 SKILL.md
- **THEN** frontmatter 含 `name: m3g4horness` 与非空 description,正文含「仅为上传格式要
  求、解压后可删除」的惰性声明

### Requirement: 完整性硬闸与包纯净

打包模式 SHALL 把安装流的各项 fail-soft 自检(脚本族同目录共存、fan-out 资产、subagent 清
单完备性、分发纯净检查)升格为硬闸:任一失败即退出码 2,不产出 zip,并保留 staging 目录、
在 stderr 打印其路径供排查。压缩前 SHALL 对 staging 内残余的 `__pycache__` 目录与散装
`.pyc/.pyo` 字节码做确定性清除,最终 zip 内零字节码条目。打包失败不产出半成品 zip。

#### Scenario: 缺件不出包

- **WHEN** 人为从发行树抽掉任一关键资产(如一件插件、守卫脚本、自检清单中任一脚本)后执行打包
- **THEN** 退出码 2,stderr 指明缺失资产,无 zip 产出,staging 保留且路径可见

#### Scenario: 分发纯净失败不出包

- **WHEN** 分发纯净检查失败(分发内容携带研发私有引用)时执行打包
- **THEN** 退出码 2,无 zip 产出

#### Scenario: 包内零字节码

- **WHEN** 发行树存在本机运行残留的字节码(`__pycache__` 目录或散装 `.pyc/.pyo`)时执行打包
- **THEN** zip 内零字节码条目,且退出码 0(清除是打包流程的确定性动作,不要求打包者手工清理)

### Requirement: 解压等价与普通安装零影响

把 zip 内容解压到一个干净项目根,结果 SHALL 与在该项目根执行 `install.sh --opencode` 的落
地树逐字节等同,唯一差异为项目根多出的 SKILL.md 文件。不带 `--pack` 的普通安装行为 SHALL
保持不变:不产出 SKILL.md,落地树除「字节码清理扩展同样生效(目标树零散装字节码)」外与既
有一致。

#### Scenario: 解压与脚本安装字节等同

- **WHEN** 对同一干净目录分别执行「解压包内容」与「install.sh --opencode 安装」
- **THEN** 两棵落地树逐字节比对一致,差异恰为前者多出的根上 SKILL.md

#### Scenario: 普通安装不受影响

- **WHEN** 不带 `--pack` 执行 `install.sh --opencode`
- **THEN** 落地树无 SKILL.md、无任何打包残留,且目标树零 `__pycache__` 与散装字节码
