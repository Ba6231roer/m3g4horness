# 实机笔记 — mgh-init scout 层 opencode 缺省原生派发(2026-10-21,本机)

本文件记录本 change 的本机闸门结果、过程中发现的宿主/环境事实,以及企业内网 2.0.32 的
交接清单(5.5,不阻塞归档)。任务 5.3 的四件套中 ②③ 两项在本机当前环境不可复现(见
§5 的环境限制说明),按诚实边界记录,任务框保持未勾。

## 环境

| 项 | 值 |
|---|---|
| 宿主 OS | Windows 10.0.26100(Git Bash;opencode shell 工具 = PowerShell) |
| opencode | 2.1.0(`%LOCALAPPDATA%\opencode2\opencode`,PATH 首位) |
| Python | 3.13.2(`py`;`python` 是本机 Store 占位——闸门脚本一律 `py`) |
| 闸门仓 A(页循环/抽查) | `C:\DEV\_mgh_init_native_gate`:400 个中性 Java 文件(无安全关键词,regex 零命中),`install.sh --opencode` 真装,无 `.mgh/env-profile.json` |
| 闸门仓 B(真会话全链) | `C:\DEV\_mgh_init_gate_e2e`:6 个中性 Java 文件,`plan_scout --batch-bytes 3072` → 6 批(1 文件/批,零 oversize),真装 + 无画像 |
| 闸门仓 C(子进程对照) | `C:\DEV\_mgh_init_gate_e2e_sub`:B 的副本 + 画像 `{"dispatch_mode":"runner"}` |
| 安装自检 | `install.sh --opencode` ✓ 行含 `init-scout-native-dispatch.md` fragment 与 `agent/…init-scout-native.md`(3.4 真装验证) |

## 1. 真会话 scout 原生全链(任务 5.1;opencode 2.1.0,`opencode run` 驱动)

编排提示词 = 命令壳 scout 原生路径的最小实例(纪律 fragment 先读 → 看门狗先行 → 物化 +
`--check` → 同消息波次派发 → 重物化收敛 → plan_aggregate/`init-scout-merge` →
`merge_scout.py` fold-in)。结果:

| 证据 | 结果 |
|---|---|
| 波次 | 波 1 = 同一消息 3 并发(`scout-4pdj`/`scout-45tj`/`scout-kkev`);重物化后波 2 = 3 并发(`scout-wtfg`/`scout-mcjf`/`scout-snpy`);第三次物化 `units_total==0` 收敛 |
| 回执 | 6/6 单行 `ok <checkpoint_path> 0`(中性算术代码,precision-over-recall 合法输出) |
| 磁盘标记 | `checkpoints/scout/` 6 个 `.done` + 记录体(schema `{batch_id,candidates,unresolved}`)+ `merge.json.done`;**零 `.failed`、零重派** |
| agent | 读者批全部经 `init-scout-native`(subagent 孪生);scout-merge 经 `init-scout-merge` 单上下文(`plan_aggregate` `needs_reduce=false`) |
| 令牌展开 | 编排器任务体 = 单行令牌 `mgh-dispatch: plan=… unit=<短号>`;子代理各自写出**只有任务文件里才有**的确切 checkpoint 路径 → `mgh_dispatch.ts` 展开钩子实机生效 |
| fold-in | `provenance.scout_merged: 0`(+0 候选 +0 簇,与 6×0 一致) |
| 子进程派发器 | `fanout_runner` 全程零调用(会话自证 + 磁盘无 liveness 文件) |
| 计划工件 | `<init-dir>/native_plan.json` 终态 `units_total: 0` |

**候选集合对照(5.1 对照腿)**:同输入子进程形态(闸门仓 C)headless **0/6 单元完成**——
18 波派发全部未产出标记,runner 零推进熔断干净收口(`stalled:true` + `stalled_pending[]`
+ `partial:true`,可 resume;run.log 面无子进程残留)。即:子进程对照腿在本机当前环境
无法产出可比候选集(恰恰是本 change 动机「企业 runner 不可用」的本机复现);原生腿输出
自洽(中性代码 0 候选、零丢失面由 6/6 终态标记背书)。发现本体(stage prompt)两形态
同源,孪生克隆由 `test_agent_stage_contract` 把守。

## 2. 页循环实证(任务 5.2;闸门仓 A,400 批)

确定性驱动(物化 → touch 当前页全部 `.done` → 重物化),无 LLM 参与:

```
page 1: units_total=111  waves=37  wave_size=3(concurrency) → 标记 111
page 2: units_total=111  → 标记 111
page 3: units_total=111  → 标记 111
page 4: units_total=67   → 标记 67
page 5: units_total=0    → 终止(共 5 页;111 = 64KB 编排预算页尺寸,非全量 400)
```

`units_total` 是**页**单元数(400 批 → 每页 111/67);派完即重物化;只有 `units_total==0`
才满足进入 merge 的终止条件。中途 `--check` 在全部落定后退出码 0(磁盘计划 = 空页 =
重物化结果,非 stale);任一单元落定后的 stale-`--check` → 退出码 2 + 重物化修复,由
`test_emit_native_plan` 锚定。

## 3. 缺省/回退/资产门六形态抽查(任务 5.4;真装副本)

| # | 形态 | 结果 |
|---|---|---|
| ① | opencode 无画像 `list_steps --step scout` | `dispatch.form=native, source=host-default, profile_exists=false, consumer=init, host_face=opencode`;scout 步 = `emit_native_plan.py`;`env_profile.py --consumer init` 同答 |
| ② | 画像显式 `runner` | 无 `dispatch` 字段;scout 步 = `fanout_runner.py`,无 `native_arc` |
| ②b | 画像显式 `native`(opencode) | `form=native, source=profile` |
| ③ | claude 面真装无画像 / dsh 布局(`mgh-core/` 无点段 = other 面) | 均:无 `dispatch`,scout 步 = 子进程 |
| ④ | claude 面显式 `native` | **退出码 2** + recipe「native dispatch exists only on the opencode face / 改 runner 或换 opencode 面」,stdout 零 manifest |
| ⑤ | 删 `init-scout-native.md`(解析 native) | **退出码 2** + recipe「re-run install.sh --opencode / 或显式 dispatch_mode:runner」;还原后恢复;`require_native_assets` 按 surface 只查 init 资产(sdr 门不受扰,单测锚定) |

## 4. 故障注入(任务 5.3;①④ 实测,②③ 受限)

- **① 单批 `.failed` → 至多一轮重派**:scout-001 写 `.failed`(reason 含 `429 rate
  limited`)→ 无 `--retry-failed` 重物化 `units_total=0`(失败 = 终态不回 pending);
  `resume_state` 给 `failed=1` + 「AT MOST ONE more」+ 「quota window」两条原生 note;
  重派轮 = 删旧 `.failed` + `--retry-failed` → 恰好 `units_total=1`、pending =
  `['scout-4pdj']`(短号跨轮稳定);补标记后 `done=6, failed=0`。
- **④ 中途打断 → resume 接上**:抹去 3 个已完成单元的 `.done`(模拟中断丢失)→
  `resume_state`:`step=scout`、`plan_present=true`、`next_action.kind=subagent`(波次
  派发相位,desc 含「ONE assistant message」)→ 重物化**恰好**重 pend
  `['scout-mcjf','scout-snpy','scout-wtfg']`,已完成 3 单元零重做。
- **② 权限 ask / ③ 挂死 → 看门狗中止:本机当前环境不可复现**(诚实记录,任务框保持
  未勾)。机制本体非 init 专属:权限询问闸门(插件 `permission.evaluate` 域内 ask→deny)
  与看门狗中止阶梯已在 sdr 面同机 2.1.0 实机验证(归档笔记:看门狗 25 巡检周期驻留、
  真实中止动作);init 面复用同一插件组 + 同一 `native_watchdog.py` + 孪生同级权限钉扎
  (`question/external_directory deny`,CI 锚)。本闸门环境的限制:`opencode run` 直跑
  形态下宿主未注入 `OPENCODE_SESSION_ID` 且本机无可达 opencode 服务(会话内看门狗首拉
  按 recipe 自退,`exit_reason=unreachable`;会话诚实披露后改 `--root` 手工锚,3 周期
  自退)——看门狗留痕工件(`watchdog/state.json`+`events.jsonl`)在 B 仓在场,但无活跃
  服务即无挂死可观测。②③ 的 init 专属增量 = 零(机制、参数、插件与 sdr 完全同源),
  待有活跃宿主服务/企业环境时按 §6 复现清单补测。

## 5. 环境事实(过程中发现,已记录)

- **`opencode run` 直跑形态不注入 `OPENCODE_SESSION_ID`**(本机 2.1.0 实测;归档 sdr
  笔记记录的「run 附着共享服务」在当前环境不成立——服务未运行时 run 形态无服务可达)。
  影响:直跑驱动的闸门里看门狗只能以 `--root` 手工锚运行,无观测对象即自退。真实施
  TUI/服务形态不受此限。
- **本机 headless 子进程派发当前整体不可用**(子进程形态 0/6,与归档 sdr 时代可跑的
  记录不同)——`fanout_runner` 的四级超时/零推进熔断防线按契约收口(partial:true、
  零脏标记、可 resume),无崩溃无孤儿。这正是「opencode 面缺省原生」的本机动机实证。
- **中性内容工程**:plan_scout 的 regex 闸门对 `Validator`/`audit` 等词敏感(首轮 300
  文件全数命中 regex、scout 0 目标)——闸门仓内容须彻底避开安全词表(两仓文件均为
  纯算术/日志填充)。
- **`python` 是本机 Store 占位**(exit 49 零输出);闸门全部经 `py`。维护者文档既有约定。

## 6. 企业内网 2.0.32 交接清单(任务 5.5;不阻塞归档,循前例保持未勾)

前置:目标机 `install.sh --opencode <仓>`(自检 ✓ 行须含 `init-scout-native` 与
`init-scout-native-dispatch.md`);opencode 2.0.32 在 PATH(注意 1.x 同名二进制前置覆盖
——本机教训);`py` 可用。

1. **解析**:任意项目根 `py .opencode/mgh-core/scripts/env_profile.py --target <abs>
   --consumer init` → 预期 `form=native, source=host-default, host_face=opencode`;
   `--consumer generic` → `runner`。
2. **步骤清单**:`list_steps.py --target <abs> --step scout` → `dispatch.form=native` +
   `emit_native_plan.py` 入口 + `native_arc`;`resume_state.py --target <abs>` → 顶层
   `dispatch` + 原生 `next_action`。
3. **真会话小链**(6 批仓):`/mgh-init` 至 scout 步,预期同消息 3 并发派
   `init-scout-native`、回执单行 `ok/failed`、`.done`/`.failed` 由子代理写、重物化收敛、
   `fanout_runner` 零调用。
4. **回退抽查**:画像 `{"dispatch_mode":"runner"}` → scout 步回 `fanout_runner.py` 行、
   无 `dispatch` 字段(企业如需暂时回退只写此画像,零代码改动)。
5. **差异回填**:2.0.32 的插件加载面(`tool.execute.before` 双插件)、`run` 对 subagent
   工具/权限闸门/`OPENCODE_SESSION_ID` 注入的行为差异,回填
   `core/contracts/fanout/runtime.md` 版本矩阵与本文件。
