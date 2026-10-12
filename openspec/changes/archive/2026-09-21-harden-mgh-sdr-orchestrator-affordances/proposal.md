> **人话序** 现象：一次真实的 `/mgh-sdr` 运行里，编排器（宿主 agent）连续做出四个违规动作——给外部仓检索脚本发明了一个不存在的审批参数、在脚本里套脚本地解析别人的输出、把输出重定向到临时文件再读回来、最后直接写内联 Python 处理产物。为什么防线没接住：三个洞叠在一起。第一，"哪个外部仓待批"由甲脚本报出来，"批准它"却是乙脚本的参数，编排器在甲身上发明了乙的能力；第二，安全守卫的开关挂在检索脚本**成功跑完之后**的副作用上，而编排器第一次尝试就因为猜错参数而死在跑之前——守卫整个试错期都在睡觉，什么违规都放行；第三，仓库其实早就有一个"合法看产物字段"的检查工具，但 `/mgh-sdr` 的命令壳从头到尾没提过它，而守卫拦人时推荐的恰是它——事发前看不见，事发后才被告知。改什么：把被发明的审批参数真的做进脚本；让守卫在第一步之前就确定性上膛；补上内联代码的另一种写法（heredoc）的拦截；把合法出口写进命令壳的对应步骤。怎么验证：每个新能力配定向回归测，并把这次失败链的四个动作固化成"必须被拦/必须被引导"的反例用例。

## Why

- **审批闭环跨脚本 → 模型发明参数**：`sdr_context.py` 产出 `pending_approval[]`（哪个外部仓待批），但批准动作 `--add` 住在 `read_roots_config.py`。真机 transcript 显示编排器直接给 `sdr_context.py` 发明了 `--approve-external`，argparse 报错后进入自我帮助的试错循环。
- **守卫激活寄生在 step 1 成功路径 → 失败窗口零防护**：sdr 哨兵是 `sdr_context.py` 完成工作后的副作用；opencode 宿主不继承跨调用的 env 导出。脚本在 argparse 阶段即告失败时，哨兵未写、env 未继承，守卫整个休眠——而违规高发的恰恰是失败/试错期。真机上后续三个违规动作（heredoc 内联解析、`> /tmp` 文件中介读回、`py -c` 处理产物）全部在无守卫状态下实际执行成功。
- **hook 拦截面有真实缺口**：守卫的内联代码判定只匹配 `-c` 形态（`python3 -c "…"`），`python3 - <<'EOF'` 的 stdin-heredoc 形态整条漏过（真机第二次尝试即为该形态，未被拦，模型因此得到"这条路走得通"的负强化）。
- **合法出口对 sdr 域不可见**：`describe_artifact.py`（产物结构/字段的受控内省）已存在且被 sra/srr 壳各引用 5 次，`/mgh-sdr` 双端壳 **0 次**；守卫 recipe 推荐的正是它，但它只在被拦后才出现在报错里。
- **大输出无摘要开关 → 文件中介诱因**：真机一次 step 1 产生 stdout 31KB + stderr 25KB，编排器用 `| tail -5` 盲探、再重定向到文件加工。产出者侧缺一个「只看关键量」的视图。

## What Changes

- `sdr_context.py` 新增 `--approve-external <abs>`（可重复）：校验目标为存在的目录后，经与 `read_roots_config.py` 同源的原子写逻辑登记进项目配置，当次运行即检索该仓并自动进哨兵 `read_roots[]`——把模型发明的能力做成真能力；审批语义不破（flag 仍只在用户同意后由编排器传入，`NEVER` 未经同意自批）。
- `sdr_context.py` 未知参数报错可操作化：flag 名命中审批/读根语义的模糊匹配（如含 `approve`/`external`/`read` 词根）时，stderr 打印「批准用 `read_roots_config.py --target … --add …` + 重跑同参」的确切命令行配方，把失败点变成出口。
- `sdr_context.py` 与 `diff_group.py` 新增 `--summary` 视图：stdout 只出关键计数与状态（字节量、外部仓摘要与 `summary_path`、待批清单、`top-level` 字段名；分组侧为单元计数/类型分布/排除计数），完整明细仍落盘可 `describe_artifact.py` 按需内省；step 1 的 `--check` 对 `pending_approval[]` 非空追加 stderr WARN（防审批环节被整体跳过后再无提醒）。
- 守卫失败窗口闭合：`resume_sdr_state.py` 新增 `--arm-sentinel` 确定性写最小哨兵（`read_roots[]` 为空、`target` 绝对根），`/mgh-sdr` 双壳 step 0 在首次调用 `sdr_context.py` **之前**执行；step 1 成功后的完整哨兵 co-write 语义不变（覆盖为含实际检索根的版本）。
- hook 双端拦截面扩展：内联代码判定从 `-c` 形态扩到「解释器 + stdin 内联」全形态（`-c`、独占 `-`（heredoc 喂入）、`- <<<` here-string），命令壳硬边界措辞同步；配双端 parity 测与真机失败形态反例测。
- `/mgh-sdr` 双端命令壳指令面补齐：step 1/2 就近给出「需看产物结构/字段 → `describe_artifact.py --in <abs> --keys/--field/--shape`」的正向配方与「stdout 直消费、正常路径 `NEVER` 重定向到文件」声明；恢复与试错段声明 step 0 上膛命令；审批闸门文案与新 flag 对齐（同意 → `--approve-external` 单命令闭环为推荐路径，`read_roots_config.py --add` + 重跑保留为等价路径）。

**非目标**：不实现 `--dimensions` 的实际下发（既有披露不变）；不改 launcher 的 run 目录新建语义（既有披露不变）；不把 `--approve-external` 做成绕过用户决策的自动批准；不扩契约检查器（调用域断言属另一 in-progress change）。

## Capabilities

### New Capabilities

<!-- 无：全部为既有能力的需求修改。 -->

### Modified Capabilities

- `security-design-review`: 「外部仓读取授权经用户确认并持久化到项目配置」新增 `--approve-external` 单命令审批路径与未知参数报错配方要求；「sdr 运行域守卫激活与幂等 resume」把哨兵写入时点从「step 1 成功副作用」扩为「step 0 确定性上膛 + step 1 覆盖细化」；新增「产出者 stdout 摘要视图与审批提醒」要求；「launcher 单命令外壳与运行域激活」对齐 step 0 上膛语义。
- `runtime-hook-enforcement`: 「Bash interpreter script-execution confinement」的内联代码判定从 `-c` 单形态扩为「解释器 stdin 内联」全形态（heredoc/here-string 反例进场景）。
- `resume-step-discipline`: 「sdr 运行域的状态重派生（resume_sdr_state.py）」的 CLI 契约新增 `--arm-sentinel` 子命令（既有 `--rearm-sentinel` 面向 re-arm 判据，新 flag 面向 step 0 首次上膛；差异与幂等语义在规格中钉死）。
- `orchestration-substrate`: 「单一共享 orchestrator-discipline fragment 持有宿主无关纪律正文」的硬边界措辞扩至 heredoc/here-string 内联形态；新增「合法出口在事发前可见」要求（守卫 recipe 推荐的每个 sanctioned primitive MUST 在对应命令壳的步骤级配方中出现，`/mgh-sdr` 为首个落地面）。

## Impact

- **代码**：`core/scripts/sdr_context.py`（`--approve-external`、模糊 flag 报错配方、`--summary`、`--check` WARN）、`core/scripts/diff_group.py`（`--summary`）、`core/scripts/resume_sdr_state.py`（`--arm-sentinel`）、`core/scripts/read_roots_config.py`（写逻辑若为内联则提取为可复用函数，语义不变）、`releases/{claude-code/hooks,opencode/hooks}/block_adhoc_scripts.py`（`_PYC_RX` 扩形态，双端字节级 parity）、`releases/{claude-code/commands,opencode/command}/mgh-sdr.md`（step 0/1/2 配方与硬边界措辞）、orchestrator-discipline fragment（若硬边界正文在 fragment 则改 fragment）。
- **测试**：新增/扩展 `test_sdr_context`（审批 flag、报错配方、摘要视图、check WARN）、`test_diff_group`（`--summary`）、`test_resume_state*` 系（`--arm-sentinel`）、`test_block_adhoc_scripts` + `test_opencode_hook_parity`（heredoc/here-string 反例）、`test_distributed_md_purity` 与契约 lint（壳内新增调用逐字镜像、`describe_artifact` 引用一致性）；把本次真机失败链四动作固化为反例用例。
- **契约文档**：`core/contracts/hooks/runtime-enforcement.md` 的内联代码拦截面与 sdr 激活时序同步更新。
- **版本与分发**：按既有发布纪律 bump 版本号；`--summary` 与 `--approve-external` 均为纯附加 flag，默认输出逐字不变（幂等/调用方零改动）。
- **风险与顺序**：step 0 上膛引入「提前退出残留哨兵」的新暴露面——由既有「下次 launcher 启动检测/清理残留哨兵」路径与 `--check` 的休眠判据共同兜底，需在设计中把「干净停止 MUST 移除 step 0 哨兵」写进壳收尾步。
