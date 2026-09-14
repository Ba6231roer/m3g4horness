# proposal — harden-mgh-init-t2-oversize-shard

> **人话序** 测试环境实跑 `/mgh-init` 时 T2 fan-out 单元 `t2 authorization` 崩溃(退出码 1,run.log 显示模型报请求上下文过大);现场 `.mgh-init/input/t2/t2-authorization.input.json` 达 400KB。根因:T2 聚合分桶按「一个 category 一个 shard」设计(保整 category 判定视图),但单 category 本身超过预算(默认 256KB)时,`plan_aggregate.py` 只在 stderr 告警一行就照原样物化派发——这个注定超限的请求直接打爆模型上下文。改什么:单 category 超预算时自动把它切成多个 ≤ 预算的 part shard,同 category 跨 part 的 canonical/competing 归并由 rollup 阶段承接;单条记录本身就超预算的病态场景,先做确定性瘦身投影、仍超则退出码 2 明确报错,不再派发注定崩的单元。怎么验证:在该测试仓复跑 T2 无 oversize 单元;新增单测覆盖切分/瘦身/报错;rollup 产物仍过 `validate_inventory.py --check`。

## Why

实测失败形态:聚合总量超预算已正确触发 map-reduce,但 `authorization`(最常见的最大 category)单桶 400KB > 预算,`plan_aggregate.py` 现行为是 `oversize:true` + stderr 告警 + **照发**(`core/scripts/plan_aggregate.py:270-273`),`init-synthesis-partial` 收到 400KB 输入 → 模型 API 拒绝(上下文超限)→ 单元 crash。该缺口被 `core/contracts/init/aggregate-sharding.md:70-71` 显式记为「无法再拆而不损整 category 视图……该 shard 仍发(部分有界)」——即**已知且被容忍的缺口**,本次以确定性兜底关闭它。spec 层「每请求 SHALL ≤ 预算」的承诺(control-discovery「Aggregate nodes enforce a hard request budget via map-reduce」)在单 category 超预算时今天不成立。

## What Changes

- **T2 分桶支持 category 内切分**:`plan_aggregate.py --node t2` 对超预算 category 按 T1 记录确定性贪心打包切成多个 ≤ 预算 part(`shard_id = t2-<category>-part<N>`,如 `t2-authorization-part0`);shard 输入 envelope 增加显式 `part_index`/`part_count`(map-reduce 路径统一携带)。marker-aware 重列、`.done`/`.failed` 语义、dispatcher 波次机均不变(parts 只是更多普通 shard)。
- **原子超限兜底**:单条 T1 记录自身 > 预算(贪心打包无法再切)时,`--materialize` 层做**确定性 prose 瘦身投影**(仅截 `description`/`usage`/`protects`/`gaps`/`entry_points` 等非判定关键字段,带 `_slimmed` 标记;**NEVER** 改写 `checkpoints/t1` 原件,evidence 锚点不截);瘦身后仍超预算 → 退出码 2 fail-loud(报出记录文件与字节数,不派发)。
- **rollup 语义扩展**:`init-synthesis-rollup.md` 的跨 shard 归并从「仅跨 category」扩为「跨 shard(含**同 category 跨 part** 与跨 category)」,复用同一组 canonical 判定信号;`init-synthesis-partial.md` 废除「category 永不跨 shard」不变式,改为「本 shard 可能是某 category 的一个 part,跨 part 判定归 rollup」。summary schema 不变。
- **披露闭环**:stdout 每 shard 携带 `part_index`/`part_count`/`slimmed`;`oversize:true` 不再出现于已派发 shard(字段保留、恒 false,兼容);part 切分与瘦身痕迹进 `init_manifest.json::boundaries[]` + `report.md`(无静默溢出)。
- **P2 诊断**:`fanout_runner.py` 对单元 crash 的 stderr 做上下文溢出签名分类,run.log 单元行附 `reason:context-overflow` + 收窄预算 recipe 提示(仅诊断增强,不改成败判定)。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `control-discovery`:「Aggregate nodes enforce a hard request budget via map-reduce」requirement 扩展——单 category 超预算不再「告警 + 照发」,而 MUST 切 part;原子超限 MUST 瘦身或 fail-loud;rollup 承接同 category 跨 part 归并;对应 scenario 增补与改写。

## Impact

- **代码**:`core/scripts/plan_aggregate.py`(分桶/瘦身/退出码/stdout 字段);`fanout_runner.py`(P2 stderr 签名分类;t2 tier 无结构变化)。
- **提示词**:`core/prompts/stages/init-synthesis-partial.md`、`init-synthesis-rollup.md`、`core/prompts/fragments/init-stage/t2.md`(oversize 措辞)、双壳 `releases/{claude-code/commands,opencode/command}/mgh-init.md`(step-5 披露措辞,若有重复)。
- **契约/文档**:`core/contracts/init/aggregate-sharding.md`(oversize 段重写)、`docs/man/mgh-init.md`、CHANGELOG、VERSION bump。
- **测试**:`tests/test_plan_aggregate.py`(parts / slim / exit 2 / marker-aware 续跑 / envelope 字段)、`tests/test_fanout_runner.py`(P2 分类)。
- **无新 flag、无新依赖**:切分与瘦身均为脚本内部确定性逻辑,`--budget`/`--materialize` 语义不变;`check_contracts.py` 无需新增断言。小仓路径(`needs_reduce=false`)逐字不变,零回归。
