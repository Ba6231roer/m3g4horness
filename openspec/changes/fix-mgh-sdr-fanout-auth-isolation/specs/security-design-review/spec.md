## ADDED Requirements

### Requirement: 特殊认证部署面覆盖机制(mgh-special-auth.md 在场时以其为准)

/mgh-sdr SHALL 支持一个**命令无关**的可选部署面文件 `mgh-special-auth.md`(企业定制认证与
执行环境手册:登录闭环说明、取证参数取值、故障对照、并发与超时映射;全部 mgh-* 流程共用,
sdr 是首个落地消费面)。该文件**不进本仓 git**(`.gitignore` 排除),由维护者随包分发;
通用流程(壳/清单/契约/规格)SHALL NOT 携带任何企业定制内容(插件名、网关地址、取证
细节只住在该文件)——缺席该文件的目标项目按通用流程完整可用。

- **install 复制收敛**:`install.sh` 与 `install.ps1` SHALL 复制安装该可选文件:源
  (仓库根、install 脚本同级)在场 → 落 `<dest>/mgh-core/mgh-special-auth.md` 并在安装
  输出如实披露;源缺席 → 移除目标侧残留副本。收敛态 = 目标副本**当且仅当**源存在;源
  缺席的安装行为与现状零差异(可选步骤,自检清单不因它缺席告警)。
- **清单在场性字段**:`list_sdr_steps.py` stdout SHALL 顶层携带
  `special_auth{present, path}`(探测安装树 `<mgh-core>/mgh-special-auth.md`;在场 →
  present=true + 绝对路径,缺席 → present=false + null,其余字段逐字节不变)。这是该
  清单允许的唯一磁盘探测,「零磁盘前置」的既有 docstring 承诺据此收窄同步。
- **壳引导**:三面 mgh-sdr 壳(opencode/claude/dsh)SHALL 在 fan-out 步前消费该字段:
  present=true → 先 Read 该文档(路径取清单 stdout),凭证准备(取证调用与参数文件
  取值)、派发 flag 追加(如 `--cred-file`)与凭证过期处置**以文档为准**;文档的优先
  范围仅限凭证与执行环境准备及配套 flag,**NEVER 链硬边界**(脚本扩展名 Write、内联
  解释器喂入、越树读写)不可被文档放宽。present=false → 壳按通用流程执行,调用行与
  披露零变化。
- **resume 提示(执行路径级)**:`resume_sdr_state.py` 在当前待办步为 fanout 且文档在场
  时,SHALL 把指引前置进 stdout `next_action.desc`(先读文档 → 凭证准备 → 调用行追加
  `--cred-file`),而不仅写在 `notes[]`——恢复中的编排器逐字执行 desc,NEVER 假定它会读
  notes。
- **launcher 提示词面**:`mgh_sdr_launch.py` 生成的编排器提示词 SHALL 携带同样的引导
  (探测 `<mgh-core>/mgh-special-auth.md`;在场 → 提示词含凭证准备前置块,step 3 调用行
  条件追加 `--cred-file <run>/cred.json`,launcher 自身 stderr 发一行在场披露;缺席 →
  提示词逐字节不变)。launcher 是零打断优选入口,单分支与 `--multi-branch` 共用同一
  提示词构造,是该机制最关键的消费面。

#### Scenario: 在场时清单披露 special_auth 字段
- **WHEN** 安装树存在 `<mgh-core>/mgh-special-auth.md`,编排器跑 `list_sdr_steps.py`
- **THEN** stdout 顶层含 `special_auth{present:true, path:<abs>}`;文件缺席时
  `present:false`、`path:null`,steps 数组与其余顶层字段逐字节与现状一致

#### Scenario: 在场时壳在 fan-out 步前读文档并以其为准
- **WHEN** 三面任一壳执行到 fan-out 步,清单 stdout `special_auth.present == true`
- **THEN** 壳先 Read 该文档,按文档完成凭证准备并追加配套派发 flag 后再执行清单
  invocation;文档引导与壳通用步骤冲突时,凭证与环境准备范围內以文档为准

#### Scenario: 缺席时通用流程零变化
- **WHEN** 目标项目未安装该文件
- **THEN** 壳流程、清单输出、resume 行为与现状一致;通用面不出现任何企业定制内容

#### Scenario: install 复制收敛
- **WHEN** 仓库根存在 `mgh-special-auth.md` 时安装
- **THEN** 目标 `<dest>/mgh-core/` 出现该副本且安装输出披露;源缺席但目标有旧副本时,
  再次安装后目标副本被移除;源缺席且目标无副本时安装行为与现状零差异

#### Scenario: launcher 提示词携带凭证准备(文档在场)
- **WHEN** 安装树存在该文档,编排器经 launcher(单分支或 `--multi-branch`)启动评审
- **THEN** 生成的提示词含凭证准备前置块(读文档、写 `cred_source.json`、跑
  `mgh_credentials.py`)且 step 3 调用行携带 `--cred-file <run>/cred.json`;文档缺席时
  提示词与现状逐字节一致、调用行不含 `--cred-file`

#### Scenario: resume 的 next_action 携带指引(文档在场)
- **WHEN** run 处于 fanout 步且该文档在场,编排器跑 `resume_sdr_state.py`
- **THEN** `next_action.desc` 以文档指引开头(读文档 → 凭证准备 → 追加 `--cred-file`),
  而非仅出现在 `notes[]`;文档缺席时 desc 不含该指引

#### Scenario: 文档不可放宽硬边界
- **WHEN** 该文档内容包含与壳 NEVER 链冲突的指引(如引导编排器写脚本扩展名文件)
- **THEN** 硬边界仍以壳/守卫为准(运行域守卫确定性拦截),文档优先范围仅限凭证与执行
  环境准备
