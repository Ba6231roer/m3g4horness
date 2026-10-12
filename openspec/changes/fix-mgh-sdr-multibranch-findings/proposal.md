# Proposal: fix-mgh-sdr-multibranch-findings

> **人话序**
> **现象**:`/mgh-sdr --multi-branch` 首次真仓验证(2026-10-12)暴露 6 个产品缺陷。最重的
> 三个:清单里故意放的「不存在的分支」没有按规格提前失败,而是照常启动宿主烧了一轮 LLM
> (约 2.5 分钟),随后被标成「成功」,还把第 1 个分支的报告认领成自己的产物,整个 sweep
> 以退出码 0「全绿」收场;从开发仓目录启动 launcher 时,4 个 opencode 会话全部落错项目、
> 整轮全灭。另有:失败现场只有一句「Unexpected server error」无从定位;运行域守卫把
> 「仓根找报告」这条提示词要求的合法命令误拦。
> **根因**:launcher 只看宿主退出码,spawn 前不预检分支是否存在;报告认领用「仓根最新
> HTML」而非本分支 run 目录里的产物;spawn 只改工作目录、不清 `PWD` 环境变量(opencode
> 按它判断项目归属);守卫路径提取把「树内路径+通配符」连写拆成越树碎片。
> **改什么**:launcher 加分支预检(真跑/dry-run 同一预检)、报告认领改读本分支 run 目录
> manifest 的 `report` 字段、spawn 剥离 `PWD`、opencode 加 ERROR 级日志开关与 `--model`
> 透传、守卫通配 token 按去通配前缀判属。
> **怎么验证**:单测覆盖预检/认领/环境/守卫四面;真仓同测试床回归一轮,断言探针
> FAILED、退出码 1、失败汇总完整、无跨分支认领。

## Why

验证战役 [findings.md](../../archive/2026-10-12-test-mgh-sdr-multibranch-realrepo/findings.md)(同目录含全量 stdout/stderr 证据)交付了 6 条可立项问题。按严重度与修法归类:

| # | 问题(自足摘要) | 严重度 | 一句根因(代码定位) |
|---|---|---|---|
| P1 | 失败探针语义反转:不存在的分支照常 spawn 宿主、消耗真实 LLM 轮次,宿主按提示词「干净停」退出 0,launcher 标 ok | 高 | `mgh_sdr_launch.py` 以宿主退出码为唯一成败判据,spawn 前无分支存在性预检 |
| P2 | 报告认领 = 仓根最新 `mgh-sdr-*.html`,不按分支过滤:探针分支认领了第 1 分支的报告,跨分支产物污染 | 高 | `_run_branch` 末尾对仓根整体 glob 取 mtime 最新 |
| P3 | spawn 不清 `PWD`:opencode 按 `PWD ?? cwd` 解析项目归属,从非目标仓 cwd 启动时全部会话落错项目(配置/插件/权限全取错) | 高 | `_spawn_host` 只传 `cwd` 参数,子进程原样继承父 shell 的 `PWD` |
| P4 | 失败不可诊断:8 次宿主失败只有错误信封一句话,opencode 自身日志零 ERROR,真因(模型 ID 失效)要手工 DEBUG 复现才可见 | 中 | launcher 的 opencode cmd 未透传任何日志开关 |
| P5 | 守卫误拦合法命令:`ls "<target>"/*.html`(提示词要求的仓根找报告动作)被判越树搜索,宿主每轮烧额外轮次绕行 | 中 | 路径 token 提取把引号闭合路径后的 glob 段拆成裸 `/…` 碎片,按盘符根解析判越树 |
| P6 | dry-run 对不存在分支报 ok:绿色冒烟对清单有效性零校验,批量打错分支名不会被发现 | 低 | 与 P1 同根:分支存在性不在任何闸门内 |

**为什么是现在**:P1+P2 让「失败记录后继续 + 退出码 1 + FAILED 汇总」这组已写进 launcher
docstring 与规格的合同整体失效——依赖失败汇总的任何自动化断言(含验证规格的场景)都拿不到
真信号;P3 让 opencode 宿主的 sweep 只能从目标仓 cwd 启动(未披露的隐含前置)。三者都是
真机验证刚确证的合同违背,越晚修,叠加其上的自动化越多。

## What Changes

- **launcher 分支预检(修 P1+P6)**:每个分支在创建 run 目录 / 写哨兵 / spawn 之前先做
  `git rev-parse --verify` 存在性预检;不可解析 → 该分支确定性早败(零宿主 spawn、零 LLM、
  零产物),记 FAILED(reason=branch-not-found)后继续后续分支;真跑与 `--dry-run` 同一预检
  (dry-run 由此获得对清单的真实校验力:含无效分支 → 退出 1)。
- **报告认领以本分支 run 目录为准(修 P2)**:宿主退出 0 后,launcher 只认 `<run-dir>/
  sdr_manifest.json` 的 `report` 字段(渲染器的确定性副产物,天然分支隔离);manifest 缺失
  或其 `report` 文件不存在 → 该分支记 FAILED(reason=no-report);**NEVER** 再用「仓根最新
  HTML」glob 认领任何产物。验证战役的「历史残留报告不被误认」场景由此闭环。
- **spawn 环境卫生(修 P3)**:spawn 宿主 CLI 时剥离子进程环境中的 `PWD`(opencode 回落
  到真实 cwd = 目标仓);claude 宿主同路径处理(无害)。
- **opencode 可诊断性 + `--model` 透传(修 P4)**:opencode spawn 追加
  `--print-logs --log-level ERROR`(provider 形失败在 launcher stderr 可定位);新增
  launcher `--model <provider/model>` flag 透传两宿主(替代「手改项目级 opencode.json」
  的环境绕行)。
- **守卫通配 token 判定(修 P5)**:Bash 路径判定(文件搜索 / 目录列举 / 兜底净网)对
  「引号闭合绝对路径 + 紧跟 glob 段」先拼接为单 token,对含 `*`/`?` 的 token 按去通配前缀
  判属;树外前缀的 glob 照旧拦截。
- **不变**:渲染器 / 分组 / fan-out 全不动;三面命令壳不动(壳未逐字枚举 launcher flags,
  契约面在 launcher `--help`);退出码合同 0/1/2 语义不变(仅 1 的覆盖面扩为三类失败:
  分支不存在 / 宿主非零退出 / 退出 0 但未产报告);哨兵 schema 与生命周期不变。

**范围拍板备忘(立项时记录的假设,apply 前可推翻)**:

| 项 | 结论 |
|---|---|
| P1–P6 全修 | 一次 change 收口;按问题分 6 个任务簇,复杂度由 tasks.md 分阶段消化 |
| E1/E2(环境因素) | **不在范围**:opencode 上游行为与维护者全局模型配置,后者 findings 已声明由维护者自行决定;真机问题单独立项 |
| findings §4 建议件 | `--model` 透传 → **收编**(P4 同面);「上一分支未产报告的转场警告行」→ 被 FAILED(no-report) 语义**取代**(失败行即警告);`--print-logs` 透传 → 被 opencode 默认开 ERROR 日志**取代** |
| 真仓回归 | 收尾含一轮同测试床人工回归(清单含探针),作为验收证据 |

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `security-design-review`:「launcher 单命令外壳与运行域激活」需求——新增分支存在性预检
  (真跑/dry-run 同一预检、确定性早败)、报告认领改为 run 目录 manifest 单一来源、spawn
  环境卫生(PWD 剥离)、opencode ERROR 级日志开关与 `--model` 透传;usage 行补齐既有
  `--read-root/--open/--dry-run` 与新 flag;随动新增 5 个场景。
- `runtime-hook-enforcement`:「Bash path-token allowlist judgment」「Bash file-search
  command confinement」「Bash directory-listing command confinement」三个需求——通配形态
  路径 token 的判定语义(拼接 + 去通配前缀)与正反场景。

## Impact

- **代码**:`core/scripts/mgh_sdr_launch.py`(预检 / 认领 / spawn env / flags,主战场);
  `core/scripts/block_adhoc_scripts.py`(Bash 路径 token 归一点,三判定共用);`install.sh`
  版本号 bump(脚本改动,承安装自检约定)。
- **测试**:`tests/test_mgh_sdr_launch.py`(预检 / 认领 / env / flags 四组新用例);
  `tests/test_block_adhoc_scripts.py`(通配正反用例 × 三判定);顺手跑三端 hook parity 与
  零依赖 / 编译警告两件套。
- **规格**:上述两个能力的 delta(见 `specs/`)。
- **风险与边界**:① `--print-logs` 等flag 与 opencode 版本耦合(升级改名 = spawn 立即失败,
  fail-loud 可检测,首个分支即暴露,非静默);② 守卫通配按前缀判属后,「前缀在树内但展开
  结果逃逸树」的形态不判定(与既有 regex-over-string 立场一致,AGENTS.md 诚实边界同步);
  ③ FAILED(no-report) 比现状严格:宿主退出 0 但没渲染 = 失败——这是把「报告是分支交付物」
  的既有规格语义落到 launcher 判据上,不是新增要求。
