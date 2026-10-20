# fix-mgh-sdr-fanout-auth-isolation

> **人话序**:企业内网 Linux 真仓跑 `/mgh-sdr`,fan-out 派出的多个 opencode 复核子进程几乎全灭
> (6 个单元只活 1 个 standalone):每个子进程都想自己弹一遍浏览器做 CAS 登录,而登录票据一次
> 有效、本地回调端口还会互抢,注定只有最先一个能收敛,其余 300 秒零输出转停滞;Windows 侧则是
> 所有子进程共用同一个 opencode 全局数据目录,并发读写踩出 `database is locked`、`EPERM` 随机
> 崩溃,重试吃满槽位后转停滞。切片→草稿→marker→报告链路本身已被跑通的单元证明没有问题,问题
> 集中在子进程的起法与执行环境。修法 = 凭证与状态都不再让子进程自理:开工前由一个确定性脚本
> 一次性取到 token(Linux 读现成文件;Windows 优先继承当前会话环境变量,必要时起一次带插件的
> 登录进程取证),然后按单元生成各自的子配置目录(把厂商入口覆盖成带 token 的静态地址,子进程
> 不再自登录)与独立数据目录(消除互踩)再派发;凭证过期单独识别为一种失败并暂停,重新取证后
> `--resume` 续跑。同时把 `fanout_runner.py --dry-run` 收紧为纯计划零写盘;企业定制内容全部收进
> 不入 git 的 `mgh-special-auth.md`(命令无关、全部 mgh-* 流程共用的认证与执行环境手册;
> install 见到就复制安装,在场流程见到就以它为准),企业环境约束汇总到
> `docs/enterprise-environment.md`(同样不入 git,AGENTS.md 只留必读指引)。
> 验证 = 单测(dry-run 零写盘/子配置物化/env 注入/过期分类/续跑)+ 隔离小仓冒烟 + 企业真仓重跑对照。

## Why

/mgh-sdr 的 fan-out 复核依赖「一个宿主会话派 N 个 `opencode run` 子进程」。在企业的 CAS 单点
登录网关环境下,这套起法结构性失败,真实仓实测 6 个复核单元仅 1 个轻量单元存活;同时 Windows
补充实测暴露了所有子进程共享 `~/.local/share/opencode`(sqlite 状态库 / 日志 / repos 缓存)的
并发互踩。两条根因都出在「让每个子进程自己登录、自己持有全局状态」,靠调参(降并发、拉超时)
无法修复——降 wave 从 5 到 2 无改善已实测排除并发过载。伴生两个工程问题:`fanout_runner.py
--dry-run` 仍写审计副本(使用者误以为零副作用);宿主对单次 Bash 调用的超时上限一到就强杀
runner,已派发的子进程成孤儿累积。

## What Changes

- **凭证中心一次性取证,子进程共用**:新增确定性脚本 `core/scripts/mgh_credentials.py`(命令
  无关,全部 mgh-* 流程共用),按
  参数文件(编排器写入 `<run>/cred_source.json`,路径与变量名等企业参数由 special-auth 文档
  提供)执行三种模式取证——继承当前会话环境变量 / 读环境文件 / 起一次带插件的一次性登录进程
  (临时给全局 opencode 配置追加一个本地探测插件,捕获鉴权回调写入的 token,`try/finally`
  外科式还原配置)——产出统一 secret 载荷 `<run>/cred.json`(权限收紧,`--check` 校验)。
- **静态 provider 注入,子进程不再自登录**:`fanout_runner.py` 新增 `--cred-file <run>/cred.json`
  (仅 opencode host)。激活时按单元物化子配置目录 `<run>/childcfg/<unit>/opencode/opencode.json`
  (复制全局 opencode 配置,保留 plugin/agent/model,仅把指定 provider 覆盖为静态入口
  baseURL + apikey),spawn 时设 `XDG_CONFIG_HOME` 指向该单元子配置目录——子进程只见自己的
  配置,不触发登录闭环。apikey 只来自凭证中心,永不进 stdout/stderr/marker/报告/遥测。
- **子进程数据目录隔离**:`--cred-file` 激活时同设 `XDG_DATA_HOME=<run>/ocdata/<unit>`(log/
  sqlite/repos 全部随变量隔离),消除 `database is locked` / `EPERM` 互踩;另提供独立的
  `--isolate-data` 开关供无凭证注入场景单独使用。两开关全不传时派发行为零变化。
- **凭证过期独立分类与暂停续跑**:非 ok 终态单元的输出尾部按 `cred.json` 携带的特征集扫描,
  命中记 `credential_expired`(与 stall、限流分开统计),立即停止派发剩余单元并以退出码 2
  收口:stdout 摘要报 `credential_expired` + 单元清单,stderr 给「重新取证 → 更新 cred.json →
  同参 `--resume --retry-failed` 续跑」配方。已派发在飞单元照常收割,已完成单元零丢失。
- **`--dry-run` 收紧为纯计划**:不再写 `<inputs-dir>/*.task.md` 审计副本、不建目录、零写盘零
  spawn,计划(单元清单与将写的路径)只走 stdout。
- **special-auth 部署面覆盖机制(命令无关)**:可选部署面文件 `mgh-special-auth.md`(企业
  定制认证与执行环境手册,wizard 插件、CAS 细节、取证三步、故障对照只写在里面,不进
  git、不进通用流程)。引导两路落地:sdr 面 = `list_sdr_steps.py` stdout 新增 `special_auth`
  在场性字段(探测 `<mgh-core>/mgh-special-auth.md`)+ 三面 mgh-sdr 壳在 fan-out 步前按该
  字段引导(在场 → 先读文档、凭证准备与派发 flag 追加以文档为准,优先范围仅限凭证与环境
  准备、NEVER 链硬边界不可被文档放宽;缺席 → 通用流程逐字节不变);通用面 =
  `fanout_runner.py` 在「文档在场但未传 `--cred-file`」时发一行 stderr advisory——mgh-init
  等其余命令的扇出零改壳即被覆盖。`install.sh` / `install.ps1` 复制安装该可选文件(源在场
  才落盘,源缺席时移除目标侧残留副本,收敛态 = 目标副本当且仅当源存在)。
- **仓库策略**:`.gitignore` 排除 `mgh-special-auth.md` 与 `docs/enterprise-environment.md`;
  后者汇总该企业定制环境约束(150K 上下文窗口、限频、CAS 登录、共享数据目录危害、宿主 Bash
  上限等),`AGENTS.md` 的运行环境约束细节改为一句概括 + 必读指引(文件缺席时降级为普通公开
  clone 语境)。
- **超时不变式不动**:`stall-timeout < call-timeout < budget×0.8 < 宿主上限` 四级不变式与全部
  默认值维持现状(默认值经 mgh-init 专项实验校准);凭证注入移除子进程登录等待后,首 token
  时延本身下降,慢模型场景经既有 wave/配额机制消化。

## Capabilities

### New Capabilities

(无——本变更全部落在既有能力的增量上)

### Modified Capabilities

- `fanout-dispatch`:
  - ADDED「子进程执行环境隔离与静态凭证注入(可选激活)」——`--cred-file` / `--isolate-data`
    的激活语义、子配置物化、secret 卫生、缺席零变化,special-auth 在场未注入的通用
    advisory;
  - ADDED「凭证过期分类与暂停续跑」——特征扫描、独立计数、暂停收口与 resume 配方;
  - ADDED「派发 `--dry-run` 纯计划(零写盘零 spawn)」;
  - ADDED「凭证中心一次性取证(mgh_credentials.py)」——参数文件驱动的三模式取证、
    外科式还原全局配置、secret 卫生;
  - MODIFIED「宿主 CLI 探测与 headless spawn 映射」——spawn 环境在注入模式下的 per-unit
    `XDG_CONFIG_HOME` / `XDG_DATA_HOME` 扩展(无注入时 env 形状不变)。
- `security-design-review`:
  - ADDED「特殊认证部署面覆盖机制(mgh-special-auth.md 在场时以其为准)」——命令无关的
    可选部署面文件、`list_sdr_steps.py` 在场性字段、三面壳引导行、resume 提示、install
    可选复制收敛、缺席零变化。

## Impact

- **脚本**:`core/scripts/fanout_runner.py`(env 注入/物化/分类/截断/dry-run)、新增
  `core/scripts/mgh_credentials.py`、`core/scripts/list_sdr_steps.py`(在场性探测)、
  `core/scripts/resume_sdr_state.py`(fanout 步在场提示)、`core/scripts/discipline_core.py`
  (如需静态纪律行)。
- **分发面**:三面 mgh-sdr 壳(opencode/claude/dsh)各加 special-auth 引导行与披露条;
  `install.sh` / `install.ps1` 可选复制步骤;`.gitignore` 两项新增。
- **不入 git 的交付物**(维护者随包分发):仓库根 `mgh-special-auth.md`(企业认证运行
  手册,含 wizard 插件/CAS/取证三步/故障对照表);`docs/enterprise-environment.md`(企业环境
  约束汇总)。
- **契约与文档**:`core/contracts/fanout/runtime.md`、`core/contracts/sdr/pipeline.md` 同步;
  `docs/glossary.md` 补词条(凭证中心、静态注入、子配置目录、数据目录隔离);
  `tools/check_distributed_purity.py` 的 SDD 豁免清单登记本 change(交付物含 docs/ 路径);
  `AGENTS.md` 环境约束节改指引 + 改动面→测试映射表补行。
- **测试**:`test_fanout_runner`(注入/隔离/dry-run/过期分类/截断)、新增 `test_mgh_credentials`、
  `test_list_sdr_steps`(special_auth 字段)、`test_resume_sdr_state`(提示行)、安装面测试
  (可选复制收敛)、purity / budget / contracts lint。
- **不受影响**:超时四级不变式与默认值、配额三 flag 语义、claude/dsh host 派发路径、
  init/ut-init 等其它 tier 的默认派发行为(注入开关缺席时零变化);mgh-init / mgh-ut-init
  的壳与步骤清单零改动(通用 advisory 由 runner 承载,后续按需各接各的清单字段)。
