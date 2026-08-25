# Design: improve-mgh-init-fanout-longrun-timeout-visibility

## Context

`add-mgh-init-scout-fanout-runner`(tasks 全勾、未归档)已交付 dispatcher 叶脚本
`fanout_runner.py`:`--time-budget-ms` 软时限、`--call-timeout-s`(默认 1800)、`--wave`(默认 5)、
marker 真相源状态机、stdout JSON / stderr 进度分流均已在位。首次大仓真机 resume(100/1000,
opencode)暴露:scout fragment 调用行**没引导传 `--time-budget-ms`**(FD1)→ 宿主 shell 900s
硬杀 → 「杀→查盘→重派→又被杀」循环(FD3)→ 15 分钟零可见输出(FD2,stdout 跑完才打一次 JSON、
stderr 不被 opencode 流式显示)。用户约束:可接受慢(FD5 内网慢接口)、可接受少数批失败
(`.failed` 已兜底);不可接受长时间零可见 + 杀-重派空转。功能定义见
[`task.260818.md`](../../../task.260818.md)(方案 A/B/C 已定采纳,A+B 合并本 change,C 文档化并入)。

## Goals / Non-Goals

**Goals:**

- 软时限**确定性先于**宿主硬超时触发:三级超时成文不变式 + 接线(fragment 调用行示例 +
  path_recipes 纪律),消除 FD1/FD3(附带 FD4 触发概率大降)。
- 人可零 token 实时看进度:sidecar 文件每波原子写(FD2),兼作挂死判别依据。
- 超时默认值按内网慢接口现实标定(FD5),推导依据成文(`--help` + 文档),非拍脑袋。

**Non-Goals:**

- 不改 stdout=一次性 JSON / stderr=诊断契约(流式 stdout 破坏 R5.3b,task.260818 方案 D 弃)。
- 不做编排器轮询进度(把 dispatcher 省下的 token 烧回去,弃);sidecar 编排器 NEVER 读。
- 不做进程组整体终止(FD4 孤儿:有界危害,A 落地后触发概率大降,暂观察不立项)。
- 不治 T1/T3/sra-augment 同类接线(后续 change 按需复制本模式)。
- 不引入 pip 依赖(sidecar 用 stdlib json/tempfile/time)。

## Decisions

### D1: 三级超时不变式 —— 写进 `--help` 文案 + fragment 调用行,不写死运行时校验

不变式(自内向外,内层必须 < 外层,每级 ≥20% 余量):

```
call-timeout-s(单子进程)× 收敛余量 < time-budget-ms(dispatcher 软时限) < 宿主 per-call timeout(Bash timeout)
```

- **推荐值(FD5 标定,成文于 `--help` + 文档)**:`--call-timeout-s` 默认 **1800→7200**(单批 =
  一次完整 LLM subagent 跑,内网接口慢数倍,冒烟实测单批分钟级,取 ~4×;宁慢勿杀:被杀单批无
  marker 留 pending,重派浪费一整跑);`--time-budget-ms` = **宿主 per-call timeout × 0.8**
  (如宿主 900s → 720000)。
- **运行时不做强制校验**(如 `time-budget-ms < call-timeout-s` 时报错):软时限语义是「停发新波、
  等在飞收敛」,budget < call-timeout 时最坏情况 = 等一个 call-timeout 才退出(仍干净、仍可
  resume),不是契约破损;把建议关系写成硬校验反而制造合法组合下的假失败。**弃**:argparse 互斥
  校验;**采**:文案不变式 + 单测锚定文档断言。
- claude 侧 Bash timeout 上限 600s < 720s 推荐软时限 → claude 宿主**必然多次重派**(每重派一个
  编排器回合 token;对比原「每波 1–3K × 180 波」仍是量级节省)。这是平台钳制非设计缺口,文档
  明示;claude 侧 fragment 示例按 600s 标(`--time-budget-ms 480000`)。

### D2: sidecar = 每波尾 + 退出前原子写,与 stdout 摘要同源派生

- **文件**:`<init-dir>/fanout_progress.json`(init-dir = `scout_plan.json` 所在目录,即
  `<target>/.mgh-init/`);schema 见 task.260818 方案 B(`ts/host/total/done/failed/pending/
  wave/waves_run/wave_done_avg_s/eta_batches/state`)。
- **写点**:每波 `pool` 收敛 + `_snapshot()` 重派生之后(计数即 list stdout 派生值,与最终
  stdout 摘要**同一来源**——单测断言两者一致,防两套计数漂移);软时限 break 后、正常退出前
  各写终态(`exited-partial`/`exited-clean`)。
- **原子性**:tempfile 同目录写 + `os.replace`(stdlib;崩溃不留半文件)。
- **ts 用 `datetime.now().isoformat()`**(本地时区带 offset);`eta_batches` = pending(保守,
  每批一波的口径)——ETA 是人读参考量,不承诺精度。
- **编排器 NEVER 读**:sidecar 不进任何 agent 面指令(壳/fragment/list_steps);`resume_state.py`
  / `init_manifest.json` 不读不校验它(非契约产物;残留旧 sidecar 不影响 resume 正确性)。

**备选弃**:① stderr 已有逐波进度(`[fanout_runner] wave N …`)再加密——opencode 不流式显示
  stderr,加了也看不见(FD2 实证);② 编排器轮询 `list_scout_batches`——烧 token(方案 D 弃);
  ③ sidecar 进 init_manifest——运行态≠终态,混淆契约边界。

### D3: 接线面三处(fragment 调用行 / path_recipes / man page),手动直跑成文(C)

1. `core/prompts/fragments/init-stage/scout.md` dispatcher 调用行:补
   `--time-budget-ms 720000`(opencode 900s 宿主示例;claude 侧 `480000`)+ 「MUST < 宿主
   per-call timeout(留 ≥20% 收敛余量)」一句;同段尾补手动直跑一句(「大仓长跑可由人开终端
   直跑同一命令,stderr 逐波进度直读,跑完回会话 `--resume` 接续」)。token 复测(scout fragment
   现状 ~1.0K,增量 ~3 行,远离上限)。
2. `discipline_core.py` `scout-fanout-dispatcher` recipe:补「重派传 per-call `timeout` >
   `--time-budget-ms`(软时限先于宿主硬杀)」半句。
3. `docs/man/mgh-init.md`(人话版)风险与边界段:补「大仓长跑可见性」三句——第二终端看
   `fanout_progress.json` 进度、内网慢接口下总时长以小时计是正常、可自己开终端直跑 dispatcher
   命令(进度条照写、断点照存,跑完回来 `/mgh-init --resume` 接续)。

### D4: 归档序依赖 —— 本 change MUST 排在 add-mgh-init-scout-fanout-runner 之后

`fanout-dispatch` 能力 baseline spec 尚不存在(该 change 未归档)。本 delta 对其 requirement 用
MODIFIED(内容 = 原 ADDED 全文 + 增量),`openspec validate` 通过(只查 delta 形态);但归档时
MODIFIED 需要 baseline 存在 → **apply/archive 前 `add-mgh-init-scout-fanout-runner` MUST 先
归档**。已在 delta 头部注明依赖序。apply 侧影响:无(实现只改 `fanout_runner.py`/fragment/
recipe/man/测试,这些文件已在该 change 中落地,本 change 是纯增量编辑)。

## Risks / Trade-offs

- [推荐值是经验标定,非硬契约(内网接口慢度无精确测量)] → 成文推导依据(~4× 余量 + 宁慢勿杀
  论证),用户可按环境覆写;不变式(内<外 + ≥20% 余量)才是契约,具体数值是默认值。
- [sidecar 与 stdout 摘要两处计数漂移] → 同源派生(都来自 `_snapshot()`/list stdout)+ 单测
  断言一致;sidecar 写失败仅 stderr warn 不影响主流程(它人面参考件,非契约)。
- [claude 侧 600s 平台钳制 < 720s 推荐软时限] → claude 示例按 600s 标(480000);多次重派
  语义已由 R5.4 覆盖(resume 零全损),文档明示 token 成本仍量级优于手派。
- [`--call-timeout-s` 默认翻 4 倍,快环境下单批真挂死要等更久才被判 timeout] → timeout 后
  单元留 pending 可 resume,`.failed`/crash 语义不变;快环境用户可显式传小值;「宁慢勿杀」
  是用户约束下的正确取舍(被杀 = 浪费一整跑 vs 慢判 = 浪费一个 call-timeout)。
- [soft-limit break 后在飞收敛期间 sidecar 停在 running] → 收敛期每 worker 完成时也刷新 sidecar
  (写点 = 波收敛后,非仅波边界;break 后最终写 `exited-partial` 终态,窗口有界)。

## Migration Plan

1. 实现(dispatcher 改动 + 三处接线 + 测试)→ 契约 lint / token lint / 纯净性 lint / 既有回归
   全绿。
2. 真机复跑事故场景:同一大仓(900 批级)resume——断言软时限先于宿主硬杀触发、sidecar 进度
   推进可见、杀-重派循环消失(重派轮轮干净早退)。
3. 归档序:先 `add-mgh-init-scout-fanout-runner` 后本 change(见 D4)。
4. 回滚 = git revert 单 commit;sidecar 文件残留无害(无人读它);默认值回退无磁盘状态迁移。

## Open Questions

(无——方案 A/B/C 已由用户在 task.260818 定采纳;FD4 明确暂不立项;推荐值推导依据已定。)
