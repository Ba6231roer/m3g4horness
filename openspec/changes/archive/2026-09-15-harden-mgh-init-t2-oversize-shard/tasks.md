# tasks — harden-mgh-init-t2-oversize-shard

## 1. plan_aggregate 确定性切分与兜底(core/scripts/plan_aggregate.py)

- [x] 1.1 `_shard_by_category` 增加超预算 category 的 part 切分:按记录(既有 glob 序)整条贪心打包成 ≤ budget 的多个 part,`shard_id = t2-<safe(category)>-part<N>`(N 自 0 起两位零填充);未超预算 category 行为与 shard_id 逐字不变
- [x] 1.2 shard 输入 envelope(map-reduce 路径)统一携带 `part_index`/`part_count`(未切分 = `0`/`1`);`_write_shard_input` 写出该字段
- [x] 1.3 原子超限兜底:单条记录 > budget 时,在 `--materialize` 物化层做确定性瘦身投影——截 `description`/`usage`/`protects`/`gaps`(str 与 list 两种形态)与 `entry_points` 至内部常量上限,`evidence` 与其余结构字段不截,投影记录带 `_slimmed` 标记(记录被截字段 + 原始字节数);`checkpoints/t1` 原件 NEVER 改写
- [x] 1.4 瘦身后仍 > budget → stderr 报记录文件与字节数,退出码 2,零派发;废除「单桶超预算 warn + 照发」路径
- [x] 1.5 stdout shard 项:`part_index`/`part_count`/`slimmed`(未瘦身 = 空对象)三字段;`oversize` 字段保留、已派发 shard 恒 `false`;`needs_reduce=false` 路径输出逐字不变;模块 docstring 的 stdout 契约同步更新

## 2. 提示词分态(core/prompts/)

- [x] 2.1 `stages/init-synthesis-partial.md`:废除「A category is never split across shards」不变式,改为「shard 可能是某 category 的一个 part(part_index/part_count 见输入文件),任何跨 shard 判定不做」;Input 段补 envelope 字段说明;Aggregate context budget 段与新的「输入必 ≤ 预算」保证一致
- [x] 2.2 `stages/init-synthesis-rollup.md`:Task step 3 从「跨 category」扩为「跨 shard——同 category 跨 part 与跨 category」,同一组 canonical 判定信号;补「多个摘要可能同 `category`」输入事实;「within-part 判定除跨 shard 重复强制变更外不重审」语义保留
- [x] 2.3 `fragments/init-stage/t2.md`:step 5 披露措辞同步——单 category 超预算 → 自动 part 切分;`oversize:true` 照发语义删除;`boundaries[]` 披露项含 part 切分与瘦身痕迹
- [x] 2.4 双壳同步:检查 `releases/claude-code/commands/mgh-init.md` 与 `releases/opencode/command/mgh-init.md` 中 T2/step-5 是否复述 oversize 旧语义,若有逐字同步;无则记录「无需改动」——**无需改动**:双壳 step-5 仅述「> 预算自动 map-reduce」(语义仍真),`oversize 簇切 ::shard-<n>` 指 `--max-unit-bytes` 的 T1/scout/T3 单元,非 T2 聚合

## 3. 契约与文档

- [x] 3.1 `core/contracts/init/aggregate-sharding.md`:重写「单 category(shard)> 预算」段——part 切分、原子瘦身投影、退出码 2、新 stdout 字段、`oversize` 恒 false;stdout 示例 JSON 更新
- [x] 3.2 `docs/man/mgh-init.md`(人类面):T2 降级行为一段更新为「单 category 超预算自动切 part;病态单记录自动瘦身并留痕;仍超则明确报错」;新术语入 `docs/glossary.md`(如「part 切分」「瘦身投影」按需)
- [x] 3.3 纯净性自检:改动涉及分发的 md(partial/rollup/t2 fragment/双壳)不触 R5.10 禁类(dev-meta、FDn、change 夹名等),跑 `py tools/check_distributed_purity.py` 验证(185 文件 clean;check_contracts 306 flag 全过)

## 4. P2 诊断:fanout_runner 溢出签名分类(core/scripts/fanout_runner.py)

- [x] 4.1 单元 crash 时对 stderr 尾部做常量签名集匹配(`context length`/`prompt is too long`/`request too large`/`maximum context` 等);命中 → run.log 单元行与 stdout 摘要附 `reason:context-overflow` + 「收窄 `--budget` 重跑」recipe 指针;不改成败判定
- [x] 4.2 签名集为模块常量并注释「新宿主报错措辞实测后增补」;`--tier t2` 之外的 tier 同样受益(tier 无关实现)

## 5. 测试(tests/)

- [x] 5.1 `tests/test_plan_aggregate.py` 新增:① 单 category 超预算 → 切出多个 ≤ budget part,shard_id/`part_index`/`part_count`/`input_path` 断言;② 多 category 混合(部分超预算)→ 仅超预算者切分,其余 shard_id 不变;③ 切分确定性(同输入两次运行 part 划分逐字节一致);④ 原子超限 → 瘦身投影生效(`_slimmed` 标记、`evidence` 未截、原件未动)且 shard ≤ budget;⑤ 瘦身后仍超 → 退出码 2 + stderr 含文件路径;⑥ marker-aware:part shard `.done` 后 pending 收缩、`summary_paths` 仍全集;⑦ `needs_reduce=false` stdout 与改动前逐字一致(字节级断言防回归)
- [x] 5.2 `tests/test_fanout_runner.py` 新增:crash stderr 含溢出签名 → run.log/摘要带 `reason:context-overflow`;无签名 → 行为不变
- [x] 5.3 回归全绿:`py tests/test_plan_aggregate.py`、`py tests/test_fanout_runner.py`、`py tests/test_fanout_stale.py` 及既有确定性测试套;`py tools/check_contracts.py` 与 `py tools/check_distributed_purity.py` 通过(全 55 个测试文件 OK;contracts 306 flags / purity 185 md 均过)

## 6. 收尾

- [x] 6.1 版本与变更记录:VERSION bump、CHANGELOG 条目(现象→根因→改法一句话)
- [ ] 6.2 实跑验证(需测试环境目标仓):在该仓复跑 `/mgh-init` 至 T2——`plan_aggregate --node t2` stdout 无已派发 `oversize:true`,authorization 拆为多个 part 且全部 `.done`,rollup 产物过 `validate_inventory.py --check`,run.log 无 `context-overflow`
