# fix-mgh-init-enumeration-caliber

> **人话序**:mgh-init 的扇出由一组确定性枚举脚本驱动(list_clusters / list_scout_batches /
> list_rule_jobs / plan_aggregate),它们决定「还有哪些单元要跑、每个单元多大、超预算怎么切」。
> 2026-10-13 全流程深度评审(维护者私有文档区)在这一层确认了一批**口径分裂**缺陷:① 切片簇
> 的分片全部失败时,簇级计数把它算成 done——失败被吞掉,`--retry-failed` 永远看不到它(实测
> 1 簇 2 片全 `.failed` → stdout 报 `{done:1, failed:0}`);② T2 聚合的分片按「紧凑序列化字节」
> 计量预算,但落盘文件带缩进 + 信封 + CRLF,实测 96KB 预算物化出 121KB(超 23%),姊妹节点
> scout-merge 早已改用物化口径、T2 漏改;③ 用户在 step 0 传入的自定义单元预算
> (`--max-unit-bytes`)被记进 run_config 后**没有任何消费方**——派发器不透传给枚举器、状态机
> 复算用共享默认值,预算静默失效;④ scout 枚举广告的 marker 路径用裸 id 拼接、判定侧却用
> 编码函数,id 一旦含 `::` 或超长就「广告的路径 ≠ 判定的路径」→ 无限重派;⑤ T3 枚举的
> done/failed 判定用 glob + 文件名反推(违反全家族「正向计算」不变量),且是三枚举器中唯一
> 无孤儿审计、唯一私有文件名编码拷贝的;⑥ 一批小病:三枚举器 `--limit <1` 不校验(编排器空页
> 自旋)、scout 计划 `--check` 对损坏文件退退出码 1(闸门只认 2)且不记录生成预算、切片器把
> Java 的 while/switch/catch 块当函数节点、指向不存在的文件静默成功、`--line 0` 落入骨架模式、
> fold-in 双文件写非原子且跨文件不一致窗口无守卫、未映射类别 fold-in 路径 skip+warn 与 fail-loud
> 契约相悖、合法 JSON 形状错裸崩、超长 shard 列表(1000 片 ≈100KB)随每页 stdout 击穿 64KB
> 编排器预算。本 change 按「同一计数/编码/预算只用一份实现」的横切根因逐一收口,含与批次 1
> 的锁步项(预算消费切换必须同 change 落在派发器与状态机两侧,漏一侧会复活 CR-1 死锁)。
> 验证 = 每项先红后绿 + 定向测试面(9 个测试文件)全绿。

## Why

评审基线(VERSION 0.1.60)之后批次 1-4 已落地;本批全部发现按**内容**在 HEAD(8b7e7a8,
VERSION 0.1.71)重定位并逐一确认仍在。批次 1 的修复在本批区域留下了**显式锁步注释**
(`list_clusters.py::canonical_unit_ids_for_run` docstring:「COUPLING LOCKSTEP: when the
runner gains --max-unit-bytes forwarding, materialization AND this recomputation MUST switch
to the run_config value in the SAME change」)——本批兑现该契约,派发器转发与状态机复算
同 change 切换,不会复活 CR-1(分片簇永久卡死)。

| # | 缺陷 | 评审定级 | HEAD 验证锚点 |
| --- | --- | --- | --- |
| H4 | 切片簇「全片终态但含失败」被计为 done,failed 吞失(packed 路径同病) | High | `list_clusters.py` 两条计数路径:无打包 `done_count = total - pending - failed` 把全片失败簇漏进 done;打包 `if not emitted: independent_done += 1` 同病 |
| H8 | t2 聚合预算按紧凑 `_byte_len` 计量,物化(indent=2+信封+CRLF)超预算 ~23%;`bytes` 字段低报 | High | `plan_aggregate.py` t2 分支分桶/瘦身全用 `_byte_len`;scout-merge 分支已用物化口径(漏改实锤) |
| B1 | run_config `budgets.max_unit_bytes` 无消费者:runner TIERS 不透传,resume_state t1 复算锚共享默认 | Medium | `--max-unit-bytes` 全仓仅 `write_runconfig.py` 出现;`canonical_unit_ids_for_run` docstring 自证锚 DEFAULT |
| B2 | scout pending 广告路径裸 bid 拼,判定侧 forward 编码 → 分叉无限重派 | Medium | `list_scout_batches.py` pending 段 `checkpoints_dir / f"{bid}.json"`(同文件 `_safe_name`/`slice_dir` 均已编码,唯 marker 路径裸拼) |
| B3 | T3 done/failed 判定 glob + stem/记录体反推;无孤儿审计;私有 `_safe_name` | Medium | `list_rule_jobs.py` `_done_categories`/`_failed_categories` 全程 glob;`_safe_name` 私有拷贝 |
| M1 | 三枚举器 `--limit <1` 未校验(空页自旋;`--offset` 有校验,不对称) | Low | 三脚本 argparse `--limit` 均无 `<1` 拒识 |
| M2 | `plan_scout --check` 对损坏 plan 退出码 1(闸门 recipe 只认 2);plan 未记录生成预算 → 自定义批字数的合法 plan 在缺省 `--check` 下误报违例 | Medium | `_run_check` 两处 `return 1`;校验用 CLI `--batch-bytes`(缺省 98304)而非 plan 记录值(plan 无此字段) |
| M3 | `chunk_sources` JAVA_DEF 把 while/for-each/catch/switch/synchronized 块识别为函数节点;`--in` 不存在文件静默成功(空骨架 exit 0);`--line 0` 真值判断落骨架模式 | Medium | JAVA_DEF 正则无控制关键字排除;`p.stat().st_size if p.exists() else 0`;`if args.line:` |
| M4 | `merge_scout` fold-in 双文件裸写非原子 + 跨文件不一致窗口(provenance 先写 → clusters 缺失时带病进 T1);未映射类别 fold-in 路径 skip+warn 与 fail-loud 契约不一致;合法 JSON 形状错裸崩 | Medium | 两处 `write_text` 直写;`cd.get("candidates")` 对非 dict wrapper 裸崩 |
| M5 | `plan_aggregate` needs_reduce 时每页 stdout 携带完整 `rollup.summary_paths`(1000 shard ≈100KB,击穿 64KB 编排器页预算承诺) | Medium | `summary_paths` 全量 append 进 result(注释自证「stay FULL」) |
| L1 | `list_clusters` 本地 `MAX_UNIT_FILENAME_STEM = 200` 重定义遮蔽同名 import(自称 alias 实为独立副本) | Low | import 后独立赋值 |

以上全部为异常/边界分支,正常小仓流程不经过;架构评审的正面结论(正向 marker、slim 分页、
原子写体系)不受影响,但触发即产生吞失败 / 无限重派 / 预算失效 / 带病进综合——与全仓
fail-loud 文化相悖。

## What Changes

涉改 = 枚举/聚合/切片层 8 个脚本 + 2 份 rollout 提示词消费面 + 派发器 TIERS + 状态机预算源
(锁步),全部确定性脚本域,零 LLM 提示词语义变化(仅 rollup manifest 消费分支):

1. **簇级计数三分(H4)**:`list_clusters.py` 两条路径(无打包/打包)的簇级计数改三分——
   全部单元 done → done;≥1 单元 failed 且无 pending → failed(对 `--retry-failed` 可见);
   否则 pending。stdout 形状补 `failed` 字段进规格。
2. **t2 物化口径(H8)**:`plan_aggregate.py` t2 分支分桶/瘦身统一改物化口径(镜像
   scout-merge 的 `_materialized_bytes` 形态);`pending[].bytes` 回填 `st_size`;补
   「落盘文件 ≤ 预算」回归不变量。
3. **预算消费闭环(B1,批次 1 锁步)**:`fanout_runner.py` 从 init 目录的 `run_config.json`
   读 `budgets.max_unit_bytes`,存在即向 scout/t1/t3 枚举器透传 `--max-unit-bytes`;
   `list_clusters.canonical_unit_ids_for_run` 增可选预算参数,`resume_state.py` t1 复算同
   change 切到 run_config 值——派发物化与状态机复算**恒同源**(缺 run_config 时同退共享默认,
   行为不变)。
4. **pending 广告路径编码同源(B2)**:`list_scout_batches.py` pending 的
   checkpoint/done/failed 路径改经共享 forward 编码函数产出(消灭裸 bid 拼;判定与广告同源)。
5. **T3 判定正向化(B3)**:`list_rule_jobs.py` done/failed 判定改 forward marker 路径计算
   (canonical category 单元集正向判),glob 降级为孤儿审计(镜像另两枚举器);`_safe_name`
   改 `init_tier.safe_unit_filename` 别名。
6. **分页卫生(M1)**:三枚举器 + `plan_aggregate` 的 `--limit <1` → 退出码 2 + recipe
   (与 `--offset` 校验对称)。
7. **scout 计划自描述(M2)**:`plan_scout.py` 生成时把 `batch_bytes`/`batch_cap` 记进
   scout_plan.json 顶层;`--check` 优先用 plan 记录值校验;损坏 plan(JSON 不可解析/wrapper
   形状错)退出码 **2**(闸门 recipe 只认 2)。
8. **切片器三修(M3)**:`chunk_sources.py` JAVA_DEF 排除控制流关键字头(while/for/do/if/
   switch/catch/finally/synchronized/try/return/new,匹配后按名字确定性过滤);`--in` 不存在
   → 退出码 2 fail-loud;`--line` 改 `is not None` + `<1` 拒识(0 不再静默落骨架模式)。
9. **fold-in 韧性(M4)**:`merge_scout.py` fold-in 两文件写改原子写 + 写序反转(clusters
   先写、candidates〔携 provenance 凭证〕后写——崩溃重折幂等收敛,凭证存在 ⟺ 两文件一致);
   未映射非规范类别在 fold-in 主路径 fail-loud(退出码 2,镜像 `--check`;缺字段候选保持
   skip+warn 既有语义);合法 JSON 形状错(wrapper 非 dict/candidates 非 list/candidate 非
   dict)→ 结构化错误 + 退出码 1,不裸崩。
10. **rollup manifest(M5)**:`plan_aggregate.py` needs_reduce 时物化
    `rollup_manifest.json`(shard 摘要路径全列表 + output + done_marker,原子写,幂等);
    stdout `rollup` 段不再携带 `summary_paths` 数组,改携带 `summary_paths_manifest`
    (绝对路径)+ `shards` 计数——stdout 单次回复恒 ≤ `--orch-budget-bytes` 承诺对聚合
    枚举同样成立;rollup stage 提示词(`init-synthesis-rollup.md` / `init-scout-merge-rollup.md`)
    与两面 rollup agent 定义增「先 Read manifest 取 summary_paths」分支;两份契约
    (aggregate-sharding / scout-plan)同步。
11. **死常量清理(L1)**:删除 `list_clusters.py` 本地 `MAX_UNIT_FILENAME_STEM` 重定义
    (单源 = import)。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `control-discovery`: 4 条 requirement——「Deterministic cluster enumeration for T1
  fan-out」(簇级计数三分 + stdout 形状补 failed)、「Fan out scout across parallel isolated
  byte-bounded batches」(plan_scout 记录生成预算 + `--check` 退出码 2)、「Shard large files
  for stable LLM analysis」(切片器三修)、「Merge scout fold-in normalizes non-canonical
  categories deterministically」(fold-in 主路径 fail-loud + 原子双写 + 凭证写序)、「Scout
  candidate JSON robustness at the merge boundary」(形状错结构化错误)——共 5 条。
- `request-context-budget`: 3 条 requirement——「Per-unit inputs are materialized and
  bounded」(pending 广告路径与判定同源 forward 编码)、「Orchestrator context is bounded by
  a slim paged work-list」(`--limit <1` 拒识 + rollup manifest 消费)、「Init aggregate node
  dispatched shards are hard-bounded」(t2 物化口径统一 + bytes=st_size + manifest)。
- `fanout-dispatch`: 1 条 requirement——「Dispatcher 脚本消费 pending 清单并零 LLM 驱动
  槽位补位循环」(dispatcher 透传 run_config 单元预算给 scout/t1/t3 枚举器)。
- `resume-step-discipline`: 1 条 requirement——「T1 终态闸门按单元口径收敛(分片簇不死锁)」
  (t1 复算预算同 change 切 run_config 值,与派发侧恒同源)。
- `rules-emission`: 1 条 requirement——「Deterministic rule-job enumeration for T3
  fan-out」(done/failed 判定正向化 + 孤儿审计 + 编码单源)。

## Impact

- **涉改脚本**:`list_clusters.py` / `plan_aggregate.py` / `fanout_runner.py`(TIERS list_args
  面,批次 3 新形态基线上小改)/ `resume_state.py`(t1 预算源一行)/ `list_scout_batches.py` /
  `list_rule_jobs.py` / `plan_scout.py` / `chunk_sources.py` / `merge_scout.py`。
- **消费面**:`core/prompts/stages/init-synthesis-rollup.md` + `init-scout-merge-rollup.md`
  (manifest 分支);`releases/opencode/agent/` + `releases/claude-code/agents/` 的两个 rollup
  agent 定义镜像同步;契约 `core/contracts/init/aggregate-sharding.md` + `scout-plan.md`
  同步 stdout 形状。提示词/agent/契约改动 → purity + budget lint + 三面镜像纪律必跑。
- **stdout 契约变化**:`plan_aggregate` needs_reduce 时 `rollup.summary_paths` 数组移除、
  新增 `rollup.summary_paths_manifest` + 恒有 `shards` 计数(编排器/rollup 消费面同 change
  切换);`list_clusters` stdout 形状无增删(`failed` 字段早已在输出,规格补记)。其余脚本
  stdout 字段零增删。
- **回归面**:`test_list_clusters` / `test_list_scout_batches` / `test_list_rule_jobs` /
  `test_plan_aggregate` / `test_scout_plan` / `test_chunk_sources` / `test_merge_scout` /
  `test_fanout_runner`(TIERS 转发面,注意存量失败 TestRateLimitStorm 勿追查)/
  `test_resume_state` + zero_deps / no_compile_warnings;分发面改动
  (rollup agent/契约)加跑 `test_distributed_md_purity` + budget lint + contracts lint。
- **VERSION**:脚本 + 分发面改动 → apply 会话 bump(0.1.71 → 0.1.72)+ CHANGELOG。
- **不改动**:discover/expand 扫描韧性(批次 6)、stage 提示词与契约批量同步(批次 7)、
  守卫三镜像、壳 flag 表。H11 `--merge` 拍板项不在本批。
