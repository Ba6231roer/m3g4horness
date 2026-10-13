# fix-mgh-init-distribution-links — dsh-command-surface delta

## ADDED Requirements

### Requirement: dsh dispatch disclosure states the real wiring and stop surface

dsh 的 mgh-init skill 壳 SHALL 设一段**派发面实态披露**,且披露内容 SHALL 与实际接线一致,
机制自相矛盾 SHALL NOT 出现:

① **已接线 tier 闭集**:`fanout_runner` 波次派发在 dsh 上已接线的 tier 清单 SHALL 与
`fanout_runner.py` 的 TIERS 闭集(scout / scout-merge / t1 / t2 / t3)一致;同文档其他清单
(脚本 inventory 行)与该披露 SHALL NOT 各说各话。
② **交互 stage 停止清单闭集**:未建具名派发实例、运行至此 SHALL 停止并如实报告的 stage
清单 SHALL 闭集枚举——survey / resolve / T2 单上下文 `init-synthesis` / T2 rollup
(`init-synthesis-rollup`)/ scout 收尾 `init-scout-merge` / scout-merge rollup
(`init-scout-merge-rollup`)/ T4 `init-rules-consistency`;漏列任何一个会导致编排器在无派发
实例的 stage 上即兴内联执行(恰是本披露要禁止的形态)。
③ **mid-run flag 注入不可能性**:只能在 run 起始由 write_runconfig 落盘的 flag(如
`--skip-consistency`)SHALL 如实注明「run 启动后不可再注入」——编排器读到该披露时 run 已在
途中,任何「现在补传」的动作都不存在。
④ **非终态停止的处置**:停在最后一个派发 stage(t3)而 T4 未跳过时,run SHALL NOT 产生终态
`init_manifest.json`——披露 SHALL 写明该形态(`--resume` 可跨会话续跑收尾;需要跳过 T4 时
只能以 `--skip-consistency` 重新 bootstrap,已有磁盘进度按 run_config 幂等承接)、NEVER 宣称
「完成」。

#### Scenario: wired tier list matches the dispatcher's closed set

- **WHEN** 审阅 dsh mgh-init skill 的派发面披露段与同文档脚本 inventory 行
- **THEN** 披露的已接线 tier 清单为 scout / scout-merge / t1 / t2 / t3(与 TIERS 闭集一致),
  与脚本行无矛盾(现网披露漏 scout-merge 而脚本行含之,修复后两面同话)

#### Scenario: stop list is exhaustive over non-dispatched stages

- **WHEN** 编排器按披露段判断当前 stage 是否「无派发实例、须停止上报」
- **THEN** 判定依据是闭集枚举(survey / resolve / init-synthesis 单上下文 /
  init-synthesis-rollup / init-scout-merge / init-scout-merge-rollup /
  init-rules-consistency);该清单外且已接线的 stage(t1/t2/t3/scout/scout-merge 波次)照常
  派发;清单内 stage NEVER 内联执行、NEVER 自写循环替代 dispatcher

#### Scenario: mid-run skip-consistency is declared uninjectable

- **WHEN** 编排器在 run 途中读到「T4 可 `--skip-consistency` 跳过」的披露
- **THEN** 披露同时写明该 flag 属 run 起始的 write_runconfig 落盘参数、mid-run 不可注入;
  需要跳过时唯一路径 = 以该 flag 重新 bootstrap(磁盘进度幂等承接),NEVER 假装当前 run 能补传

#### Scenario: stop-at-t3-with-T4-pending discloses the no-terminal-manifest shape

- **WHEN** run 停在 t3 之后、T4 一致性未跳过,编排器核对产物
- **THEN** 披露已写明该形态无终态 `init_manifest.json`(`--resume` 续跑收尾),编排器
  NEVER 把「波次全部 done」误报为整个命令完成
