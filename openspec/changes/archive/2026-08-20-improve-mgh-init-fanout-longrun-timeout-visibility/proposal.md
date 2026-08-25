# Proposal: improve-mgh-init-fanout-longrun-timeout-visibility

> **人话序**
> **现象**:`add-mgh-init-scout-fanout-runner` 落地后首次大仓真机 resume(进度 100/1000,
> opencode 宿主),dispatcher 一次 `Bash` 调用跑了 15 分钟零可见输出,被宿主 shell per-call
> timeout=900s 硬杀;编排器靠磁盘 marker 自愈重派,又被杀——「杀→查盘→重派→又被杀」循环
> (900 批 ≈ 60–180 回合),人全程无法判断是慢还是挂死。**根因**三个:① scout fragment 的
> dispatcher 调用行没引导传 `--time-budget-ms`(软时限设计有、接线缺),dispatcher 永远跑不过
> 宿主硬超时;② stdout=一次性 JSON / stderr=诊断的契约只照顾机器,「人看进度」的通道不存在;
> ③ 内网慢 LLM 接口下单批跑数分钟,默认 30min call-timeout 与宿主 15min 硬杀的组合参数从未按
> 此标定。**改什么**:超时三级(单批 call-timeout / dispatcher 软时限 / 宿主硬超时)成文不变式
> + 内网慢接口推荐值接进 fragment 调用行与 `--help`;dispatcher 每波原子写人读进度 sidecar
> `fanout_progress.json`(编排器 NEVER 读,零 token);宿主外手动直跑模式文档化(逃生门)。
> **怎么验证**:`tests/test_fanout_runner.py` 增超时关系/sidecar 单测 + 契约 lint + 双壳 token
> lint + 真机大仓 resume 复跑(软时限先于硬杀触发、sidecar 可见进度推进、循环消失)。

## Why

dispatcher 消灭了波次边界的 LLM 回合,但把「长跑可观测 + 可恢复」的契约执行面从编排器集中到了
单次 `Bash` 调用:R5.4 的软时限早退(`--time-budget-ms`)+ 编排器重派机制**设计上已存在**,
但 scout fragment 的调用行没有引导传该 flag——首跑即被宿主 900s 硬杀(FD1),进而触发
「杀→查盘→重派→又被杀」空转(FD3,下游放大);硬杀时在飞子进程可能孤儿(FD4,有界危害);
且 15 分钟零可见输出让人无法区分「内网慢」(FD5,环境现实)与「挂死」——用户约束明确:
可接受慢、可接受少数批失败,**不可接受**长时间零可见 + 杀-重派空转(烧 token + 无法判断)。

## What Changes

- **方案 A — 超时参数分级加大 + 成文不变式**:
  - `fanout_runner.py --call-timeout-s` 默认 1800→**7200**(单批 = 一次完整 LLM subagent 跑,
    内网慢接口实测分钟级,取 ~4× 余量;宁慢勿杀——单批被杀 = 无 marker 留 pending 重派,
    浪费一整跑);
  - scout fragment dispatcher 调用行补 `--time-budget-ms` 显式示例 + 「MUST < 宿主 per-call
    timeout(留 ≥20% 收敛余量)」不变式提示;
  - `--help` 文案注明三级超时自内向外不变式:
    `call-timeout-s < time-budget-ms < 宿主 per-call timeout`,每级 ≥20% 余量;
  - `list_steps.py` scout 步 path_recipes 补软时限重派纪律一句。
- **方案 B — 进度 sidecar 文件(人可实时看,编排器零介入)**:dispatcher 每波结束及软时限/
  正常退出时**原子写**`<init-dir>/fanout_progress.json`(计数 + 波次 + ETA + state ∈
  running|exited-partial|exited-clean);人第二终端 `Get-Content -Wait` 即可看进度;编排器
  **NEVER 读它**(人面运行态披露件,不进任何 agent 上下文);顺带成为挂死判别依据
  (done 数分钟不涨 + state=running → 人为介入,而非编排器盲等)。
- **方案 C — 宿主外手动接管模式文档化(零代码)**:dispatcher 与编排器都以磁盘 marker 为
  唯一真相源、天然互斥 → 大仓场景成文允许人开终端直跑 `py fanout_runner.py …`(无宿主超时
  钳制、stderr 逐波直读),跑完回会话 `--resume` 接续;scout fragment + man page 各一句。
- **不改**:stdout=一次性 JSON / stderr=诊断的 R5.3b 契约(流式 stdout 弃,方案 D);磁盘
  marker 真相源 / `.failed` 终态 / `--resume` 语义;零 pip 依赖(sidecar 用 stdlib json+tempfile);
  不做编排器主动轮询(把省下的 token 烧回去,弃)。
- **FD4(孤儿进程)不单独立项**:软时限早退落地后被硬杀不再发生,触发概率大幅下降;有界危害
  (浪费非破损),暂观察。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `fanout-dispatch`:dispatcher 长跑超时关系确定性化(软时限 MUST 先于宿主硬超时触发、
  三级超时成文不变式与内网慢接口默认值)+ 运行态进度 sidecar(每波原子写、人读、编排器
  NEVER 读)+ 宿主外手动直跑逃生门(磁盘真相源互斥语义成文)。
- `request-context-budget`:「Orchestrator context is bounded by a slim paged work-list」
  requirement 的 dispatcher 路径增量补一句——编排器重派 dispatcher 时 SHALL 传 per-call
  `timeout` > `--time-budget-ms`(软时限先于宿主硬杀;否则重派退化为硬杀循环);进度查询
  的零 token 路径 = 人读 sidecar,编排器 NEVER 为查进度发起 LLM 回合/读 sidecar。

## Impact

- **代码**:`core/scripts/fanout_runner.py`(call-timeout 默认值 + sidecar 写盘 ~15 行 +
  `--help` 文案)、`core/prompts/fragments/init-stage/scout.md`(调用行补 `--time-budget-ms`
  + 手动直跑一句)、`core/scripts/list_steps.py`(path_recipes 一句)、`docs/man/**`(手动
  接管 + 超时标定说明,若有 mgh-init man 分册)、`tests/test_fanout_runner.py`(超时关系
  文档断言 + sidecar 内容与 stdout 摘要一致性断言)、CHANGELOG/VERSION bump。
- **既有安装项目**:重跑 `install.sh` 获更新;无磁盘 schema 变更(sidecar 是新增运行态文件,
  非契约产物,`resume_state.py`/`init_manifest.json` 不动)。
- **风险**:① claude 侧 Bash per-call timeout 上限 600s < 推荐软时限 → claude 宿主必然
  多次重派(每次一个编排器回合 token;对比原每波 1–3K × 180 波仍是量级节省,文档明示);
  ② sidecar 与 stdout 摘要一致性靠单测锚定(两处计数同源派生,防漂移);③ 超时推荐值是
  经验标定(内网慢接口实测),成文标注推导依据,非硬契约。
- **非目标**:不治 T1/T3/sra-augment 的同类接线(后续 change 按需复制);不做流式 stdout /
  编排器轮询(方案 D 已弃);不做进程组整体终止(FD4 暂观察);不改 marker/resume 语义。
