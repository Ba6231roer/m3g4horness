> **人话序** 现象:本工具族目前只有一种分发形态——请使用者在自己的机器上跑一遍安装脚本;
> 企业内网实际的批量分发通道是一个 skillhub 性质的内网服务,它只收 zip 包,还要求 zip 根目录
> 有一个标准格式的 SKILL.md,现在的仓库完全产不出这个东西。根因:「安装能力」和「分发物产出
> 能力」是两回事,仓库只有前者;围绕发行目录手工压 zip 不可控——要么漏装散件、要么把研发机
> 上的私有资料压进去、要么发出无版本标记的陈旧包。改什么:给 install.sh 加一个打包模式
> `--pack[=输出.zip]`,仅限 opencode:同一条安装流程先完整跑进一个临时 staging 目录(镜像、
> 字节码清理、各项自检全部复用,零第二份拷贝清单),过一道「缺任一关键资产就不出包」的完整性
> 硬闸,再用 Python 标准库压成 zip;zip 根放一个仅供 skillhub 上传格式校验的 SKILL.md(用项
> 目名命名,不承载任何功能,解压后可删)。企业用户从 skillhub 下载后把包内容解压到项目根即完
> 成安装,效果与跑脚本安装字节等同。怎么验证:打包集成测试真跑一次打包,断言 zip 的顶层条目
> 闭集、关键资产逐项在场、纯净无研发私物、缺件与非法选项组合全部 fail-loud;本机实机打一次
> 包人工抽查。

## Why

- 分发通道的现实:企业内网的 skillhub 只接受 zip 上传,且要求 zip 根有标准格式 SKILL.md。
  本仓今天的唯一分发形态是「使用者跑 install.sh」,对 bash 环境、脚本执行许可都有前置要求,
  也接不进 skillhub 通道。
- 手工打包不可控:围绕发行目录手工压 zip,每次都要人肉记得「command + agent + hooks + 两个
  插件 + mgh-core 全量 + 敏感目录模板」的完整清单;任何一次安装面演进(新增 agent、新增
  fragment、插件文件变动)都要同步记进人肉清单,漂移只是时间问题。打包能力必须复用安装流本
  身,让「装进 staging」与「装进用户项目」是同一段代码。
- 统一分发物收窄支持面:全企业用户拿到字节等同的同一个包,「你装的是哪个版本」有唯一答案;
  文件名携带版本号后,陈旧包一目了然。
- 顺带修一个打包才会暴露的卫生问题:发行树里存在本机运行残留的散装 `.pyc` 字节码(未被 git
  跟踪,但安装的整树拷贝会把它原样带进用户项目);现行清理只删 `__pycache__` 目录,漏掉散装
  字节码文件。本 change 把清理扩成「目录 + 散装字节码」两类,普通脚本安装同样受益。

## What Changes

- **install.sh 新增打包模式 `--pack[=<输出.zip>]`,仅限 opencode 面**:
  - 与 `--claude`/`--dsh` 同传 → 退出码 2 + 原因说明(claude 面要改写用户既有的宿主配置文件、
    dsh 面要写机器本地的宿主 profile,这两类动作 zip 解压覆盖不了);
  - 与 `--no-enforce-hook` 同传 → 退出码 2 + 说明(打包面向企业分发,固定含守卫插件与派发插
    件的缺省姿态,不出「无守卫」变体);
  - 缺省输出文件名 `m3g4horness-<版本>-opencode.zip`,版本号取自仓库 VERSION 文件(缺失或
    空 → 退出码 2)。
- **打包流程 = 既有安装流原样进 staging**:临时 staging 目录 → 既有安装步骤逐字执行(镜像、
  字节码清理、特殊文档迁移清理、各组自检)→ 完整性硬闸 → 压缩 → 成功删 staging、失败保留
  staging 并打印路径供排查。安装流的既有 fail-soft 自检在打包模式**升格为硬闸**:脚本族同目
  录共存、fan-out 资产、subagent 清单完备性、分发纯净检查,任一失败即退出码 2 不出包——理
  由:脚本安装时用户还能在终端看到 warn,zip 用户什么都看不到,缺件包一旦上传就是大面积静
  默失效。
- **新增 `tools/pack_release.py`(纯标准库)**:把 staging 目录压成 zip,条目相对 staging 根、
  路径用前向斜杠;压缩前对 staging 内残余的 `__pycache__` 目录与散装 `.pyc/.pyo` 做确定性清
  除并断言为零。
- **新增 `releases/opencode/SKILL.md`(惰性文件)**:frontmatter `name: m3g4horness`(项目
  ASCII 名)+ `description` 一句功能概括;正文声明本文件仅为内网 skillhub 上传格式要求、非
  功能入口、解压后可删除。普通安装零影响——opencode 安装分支只拷 command/agent/hooks 三个
  子目录,该文件只被打包步骤放进 staging 根。
- **包结构契约(测试按闭集断言)**:zip 顶层恰为三个条目——`SKILL.md`、`.opencode/`
  (command、agent、hooks、plugins、mgh-core 五树)、`.mgh-sra/`(敏感目录模板);除此之外
  零多余条目,研发机上的任何其它内容结构性不可混入。
- **非目标**:claude/dsh 不出包;install.ps1 不扩展打包模式(打包是研发机动作,研发机有
  Git Bash;install.sh 与 install.ps1 在维护者随包文档语义上的既有分歧本 change 不收敛,
  记录在 design);不做卸载与旧文件清理(解压覆盖语义与脚本安装的整树覆盖一致);SKILL.md
  与包内不携带使用说明(使用方式由发布说明页承载);维护者随包的企业环境/授权文档不进包,
  维持「部署方放项目内 `.mgh/special-auth.md`」的现行立场——若维护者希望它随包走,属一行
  语义 + 一个测试锚的增量,apply 前可改。

## Capabilities

### New Capabilities

- `release-packaging`: 面向内网 skillhub 通道的一键分发包产出能力——打包 = 完整安装流进
  staging + 缺件即失败的完整性硬闸 + 标准库压缩;包根带 skillhub 格式要求的惰性 SKILL.md;
  包内容与脚本安装字节等同、顶层条目闭集、纯净无研发私物;平台与选项组合的 fail-loud 边界。

### Modified Capabilities

<!-- 无:既有能力(各命令行为、分发纯净、hook 强制等)的 Requirement 层零变更;install.ps1
     不动。 -->

## Impact

- **代码**:`install.sh`(`--pack` 参数与分支、fail-soft 自检在打包模式升格硬闸、字节码清理
  扩为「目录 + 散装 `.pyc/.pyo`」两类——最后一项对普通安装同样生效;apply 期补充:与
  install.ps1 一并补 step 0 解释器探测,见 design D10);新增 `tools/pack_release.py`、
  `releases/opencode/SKILL.md`。
- **零改动面**:三端命令壳与 agent、`core/` 全部脚本与提示词、既有工具脚本。
- **测试**:新增 `tests/test_install_pack.py`(真跑 `install.sh --pack` 到 scratch 目录:
  zip 存在且文件名携带 VERSION、顶层条目闭集、关键资产逐项在场、SKILL.md frontmatter 形状、
  纯净断言、fail-loud 四形态——与 claude 同传/与 dsh 同传/与 no-enforce-hook 同传/人为抽掉
  插件;本机跑该测试需按仓库惯例垫 py 转发);`test_zero_deps`/`test_no_compile_warnings`
  顺手覆盖新脚本;lint 四件套。
- **文档**:VERSION bump、CHANGELOG 条目、根 AGENTS.md(快速命令补打包一行、诚实边界补 zip
  分发通道一条)、README 补发布渠道一句。
- **实机闸门**:本机真跑一次 `--pack`,解压抽查 + 与一次普通安装的落地树做逐字节比对,确认
  等同。
