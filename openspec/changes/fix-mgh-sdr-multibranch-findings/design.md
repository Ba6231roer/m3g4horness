# Design: fix-mgh-sdr-multibranch-findings

> **受众**:agent(apply 执行者)+ 维护者。问题事实与证据见本 change `proposal.md` 的
> Why 表与验证战役 findings(archive/2026-10-12-test-mgh-sdr-multibranch-realrepo,
> evidence/ 含四轮全量输出)。本文只写「怎么改、为什么这么改、弃了哪些替代」。

## 问题 → 改法总览

| 问题 | 触点 | 改法 | 决策 |
| --- | --- | --- | --- |
| P1 探针被标 ok | `mgh_sdr_launch.py` `_run_one` | spawn 前分支 ref 预检,失败记 FAILED 跳过 | D1 |
| P6 dry-run 对坏清单报 ok | 同上 | 预检在 dry-run 与真跑共用(同一点位) | D1 |
| P2 跨分支报告认领 | 同上,ok 路径末尾 | 认领来源 = 本分支 run 目录 manifest 的 `report` 字段 | D2 |
| P3 opencode 会话落错项目 | `_spawn_host` | 子进程 env 剥离 `PWD` | D3 |
| P4 失败不可诊断 | `_spawn_host` + argparse | opencode 追加 ERROR 级日志开关;新增 `--model` 透传 | D4 |
| P5 守卫误拦 glob 命令 | `block_adhoc_scripts.py` Bash 路径判定 | 入口单点归一:引号拼接 + 去通配前缀 | D5 |

## D1 — 分支预检:点位、判定与覆盖面

**决策**:预检放在 `_run_one` **最入口**(run 目录创建、sdr_context、哨兵写入、spawn 全部
之前),用 `git rev-parse --verify --quiet` 把分支 ref 解析到一个 commit;解析失败 →
返回 `(False, "branch not found: <branch>")`,记入既有 `failed[]` 汇总,循环继续。真跑与
`--dry-run`、单分支与 `--multi-branch` 走同一预检(单分支模式显式传不存在 `--branch` 同样
退出 1 + FAILED 汇总,而非烧一轮宿主后在 diff_group 才死)。

**弃掉的替代**:

| 替代 | 为什么不取 |
| --- | --- |
| 宿主侧改退出码语义(编排提示词让「分支不存在」退出非 0) | 仍烧一次完整 spawn 与 LLM 轮次(P1 的影响①原样保留);且要动编排提示词(三面壳 + launcher 提示词),改动面更大、语义更绕 |
| 靠 `diff_group.py` 的闸门早死 | 它已经在宿主会话内,发现「分支不存在」时 spawn 与上下文准备的钱已经花了;闸门只对「宿主已启动」的世界有效 |
| 预检放 sdr_context 之后(省一次 git 调用) | sdr_context 有外部仓检索副作用,坏分支不该走到那;`rev-parse` 是毫秒级,不是瓶颈 |

**细节**:解析形式取「可解到 commit」宽口径(分支 / tag / 短 SHA 都算存在),与
`git diff base..branch` 的接受面一致;spec 不钉具体 rev-parse 参数形态,实现取
`--quiet` + 退出码判定即可。

## D2 — 报告认领:manifest 单一来源 + no-report 即失败

**决策**:宿主退出 0 后,launcher 读**本分支 run 目录**内 `sdr_manifest.json` 的 `report`
字段(渲染器的确定性副产物,`render_sdr_report.py` 渲染时原子写,值 = 报告绝对路径)。
manifest 存在且 `report` 文件在盘 → 认领;否则 → `(False, "no report produced for <branch>")`。
仓根 glob(`sorted(repo.glob("mgh-sdr-*.html"), key=mtime)[-1]`)**整体删除**。

**为什么比 findings 建议的「前缀 + mtime 双条件 glob」更强**:前缀过滤仍是一种文件系统
启发式——同名分支安全的两个分支前缀可能重叠、mtime 在同秒原子覆盖下有竞态读法、
「mtime 晚于 run 起始」要再引入一次时钟比较。manifest 是渲染器与报告**同一事务**写的
(`os.replace` 原子落盘),按 run 目录天然隔离,零启发式。真跑路径上渲染成功 ⟹ manifest
必在(含「无变更」分支,渲染器照常出报告 + manifest),所以「manifest 缺失 = 渲染没发生」
是可靠推断。

**严格度拍板**:宿主退出 0 但未产报告 → **FAILED**(非 ok + 警告)。理由:报告是分支的
交付物,「退出 0 + 无产物」按现规格已是违约形态(验证规格明文「launcher 不得把历史报告
记为该分支产物」);记 FAILED 让退出码 1 + 汇总行天然承担 findings §4 想要的「转场警告」,
且自动化消费者拿到真信号。弃掉的宽松版(ok + stderr 警告 + `reports[]` 留空)会让 sweep
「全绿」收场,回到 P1 的老问题形状。

**边界**:`--open` 语义不变(outcome 以 `.html` 结尾且文件在盘才开;dry-run outcome 仍是
提示词路径,不开);stdout `reports[]` 形状不变(只是取值来源变了)。

## D3 — spawn 环境卫生:剥离 `PWD`,不追 `--dir`

**决策**:`_spawn_host` 给 `subprocess.run` 传 `env = {k: v for k, v in os.environ.items()
if k != "PWD"}`(两宿主同路径;claude 不读 PWD,无害)。`cwd` 参数照旧传目标仓——opencode
按 `PWD ?? cwd` 解析,`PWD` 缺失即回落到真实 cwd = 目标仓。

**弃掉的替代**:

| 替代 | 为什么不取 |
| --- | --- |
| opencode `--dir <repo>`(findings 认为语义最正) | 给 launcher 加了对移动中宿主 CLI 的**硬 flag 耦合**:上游改名/移除该 flag = 所有分支 spawn 即死。PWD 剥离是零耦合、全版本成立的同一效果 |
| 覆写 `PWD=<repo>` 而非剥离 | 等效,但覆写要回答「写 Windows 形还是 POSIX 形」,剥离让宿主自己回落,少一个格式决定 |

**验证方式**:单测对 `_spawn_host` 断言传入 subprocess 的 env 不含 `PWD` 且 `cwd` = 目标仓;
真机回归从开发仓 cwd 启动一轮,opencode 日志确认会话 `directory` = 测试床。

## D4 — 可诊断性:opencode 默认开 ERROR 日志 + `--model` 透传

**决策**:① opencode cmd 由 `[opencode, run]` 扩为 `[opencode, run, --print-logs,
--log-level, ERROR]`(claude 不加);② 新增 `--model <provider/model>` argparse flag,
两宿主透传同名 flag(opencode `run --model` / claude `-p --model`),未传不附加。docstring
usage 行同步(launcher `--help` 是唯一契约面)。

**弃掉的替代**:

| 替代 | 为什么不取 |
| --- | --- |
| `--print-logs` 做成 opt-in 透传 flag | run1/run2 的教训恰是「默认路径上拿不到诊断信息」;让操作者预知需要它 = 要求未卜先知。ERROR 级常态开启噪声可控(只出错误行) |
| 宿主输出落 `<run>/host.run.log` | 需要重定向继承流或 tee 线程,丢「实时看 stderr」的现有体验;ERROR 日志并入 stderr 已解决定位诉求 |
| launcher 加 `--log-level` 透传 | 一个默认值已覆盖诉求,不加第二个面 |

**已知耦合(接受)**:`--print-logs`/`--log-level` 与 opencode 版本耦合,上游移除 = 首分支
spawn 即错、launcher 退出 1、stderr 指名道姓——fail-loud 且首轮即暴露,非静默劣化;维护
姿势与本仓「宿主显式钉版本验证」一致。E2(默认模型失效)的产品侧出口即 `--model`:
不再需要手改测试床项目级 `opencode.json`。

## D5 — 守卫通配 token:入口单点归一,三判定共用

**决策**:在守卫 Bash 分派入口(**单点**)对命令串做一次归一,再进既有各判定:
① **拼接**:引号闭合绝对路径后紧邻的 glob 段(`"C:\t"/*.html`、`"C:\t"\*.log`)剥引号
拼成单 token——治「提取器把引号闭合路径后的 `/…` 碎片按盘符根解析」的假阳性(证据形态
即 P5 的被拦命令);② **前缀判属**:含 `*`/`?` 的 token 按首个元字符前的前缀 resolve 判定
(前缀在允许集 → 放行;树外 → 照旧拦)。文件搜索 / 目录列举 / 兜底净网三个判定共用归一
后的 token 流,无需逐规则补丁。

**弃掉的替代**:仅改 step 5 提示词(让宿主不跑 glob 命令)——守卫缺陷本体还在,任何其他
「树内路径 + 通配」形态照拦;提示词只是减少一种触发形态,不做修复。

**残余与诚实边界(随本 change 同步 AGENTS.md 诚实边界节)**:归一仍是 regex-over-string
(别名 / 变量间接照旧不可见,既有立场不变);按**前缀**判属意味着「前缀在树内、shell 展开
结果」不判定——glob 展开只会命中前缀子树内的路径,新增暴露面可忽略,但如实记录。

## 测试策略

定向跑优先(改哪面跑哪面),全量留给发布闸门:

| 改动面 | 测试文件 | 新用例要点 |
| --- | --- | --- |
| launcher 预检/认领/env/flags | `tests/test_mgh_sdr_launch.py` | 探针分支 FAILED 且零 spawn 零 run 目录;后续分支不受影响;dry-run 坏清单退出 1;manifest 认领 + 缺失记 no-report + 仓根他人报告不被认领;spawn env 无 `PWD`;opencode cmd 含日志开关、claude 不含;`--model` 两宿主透传 |
| 守卫通配归一 | `tests/test_block_adhoc_scripts.py` | 证据形态命令放行(搜索/列举/净网三判定各一例);树外前缀 glob 照拦;`"t"/../x*` 前缀含 `..` 照拦;非运行域不判 |
| 接线不漂移 | `test_opencode_hook_parity` + `test_dsh_hook_parity` | 守卫源码改动后回归,确认 parity 源断言不破 |
| 顺手两件套 | `test_zero_deps` `test_no_compile_warnings` | 任何 `core/scripts` 改动标配 |
| 契约面 | `py tools/check_contracts.py` | launcher docstring usage 更新后过 lint |

**已避开的坑**(R5.8 既载):本轮不碰 `fanout_runner` / `diff_group`,无 300s cooldown
默认值风险;`test_mgh_sdr_launch` 走真 launcher `main()` + 假宿主,不涉长等待。

## 交付外核(非代码)

- `install.sh` 版本号 bump(脚本改动)。
- AGENTS.md 诚实边界节补 D5 残余一句(前缀判属语义)。
- 真仓回归一轮(验收证据):测试床同清单(含探针)重跑,断言——探针 FAILED(branch-not-found)
  且其后分支照常、退出码 1 + 汇总完整、`reports[]` 无跨分支认领、从开发仓 cwd 启动时 opencode
  会话 `directory` = 测试床、`ls "<床>"/*.html` 形态命令在运行域内放行。
