# fix-mgh-init-enumeration-caliber — Design

> 范围:枚举/聚合/切片层 9 个脚本 + rollup 消费面(2 stage 提示词 + 2 面 agent 定义 + 2 契约)
> + 派发器 TIERS + 状态机预算源。横切根因 = 评审第九节第 1 类「口径分裂」:同一计数/编码/预算
> 在多份实现间漂移。修法一律「收敛到单源」,NEVER 新增并行实现。

## D1 — 簇级计数三分(H4)

现状两条路径都用**残差公式**(`done = total - pending簇 - failed簇` / `if not emitted: independent_done += 1`),
「全片终态但含失败」的簇两头都不落 → 滚进 done。修法:逐簇跟踪其单元集
(整簇 id 或其全部分片 id)的 forward 终态,簇级三分:

- 全单元 `.done` → done;
- ≥1 单元 `.failed` 且无 pending 单元 → **failed**;
- 否则 → pending。

实现:单元循环内累计 per-cluster `{done,failed,pending}` 计数(单元 id 集在物化路径已知;
非物化 lite 路径簇 = 整簇单元,id 同源),替换两处残差公式。`--include-failed` 重入语义不变
(重入簇按普通 pending 簇计,`clusters_reincluded` 回加保留)。stdout 字段零增删(`failed`
本就在输出,只是值修正)。**被否的替代**:簇级 marker 由枚举器代写(整簇 `.done` 当全片 done)
——引入第二写入者,违反「marker 由派发器/subagent 写」的职责边界,且跨 run 幂等复杂。

## D2 — t2 聚合物化口径(H8)

现状 t2 分桶(`_shard_by_category`)、瘦身触发/收敛(`_byte_len`)全按紧凑序列化计量,落盘
`_write_shard_input` 写信封 + indent + CRLF。修法镜像 scout-merge 既有形态:分桶与瘦身的预算
判定统一走**物化口径**度量(对将落盘的同一信封形态序列化计量,`_materialized_bytes` 家族);
`--materialize` 写盘后 `pending[].bytes` 回填 `st_size`。`total_bytes`(聚合输入总量,判
`needs_reduce`)保持紧凑口径不变——它是「原始输入规模」披露,不是派发界;派发界不变量 =
「落盘 shard 文件 ≤ `--budget`」,补回归断言(跑真实物化,断言每个被派发 shard 的 st_size ≤ budget)。

## D3 — 单元预算消费闭环(B1,批次 1 锁步兑现)

三件套**同一 change** 落地,漏任一侧即口径分叉:

1. **runner 侧**:`fanout_runner` 各 tier 已从 plan-artifact 锚定 init-dir(liveness/sidecar 同源);
   派发前读 `<init-dir>/run_config.json` 的 `budgets.max_unit_bytes`,为正整数即向
   scout/t1/t3 的 `list_args` 追加 `--max-unit-bytes <v>`;缺失则不附加(枚举器默认,既有 run
   行为零变化)。**不新增 runner CLI flag**——预算唯一来源 = run_config(step 0 已记录),
   CLI 覆盖会造第二真相源。t2/sdr tier 不在范围(t2 的聚合预算是另一 flag 族,sdr 无此约定)。
2. **枚举器侧**:`list_clusters.canonical_unit_ids_for_run(clusters_path, max_unit_bytes=None)` 增
   可选参数(None → 共享默认,既有调用零变化);枚举器自身 `--max-unit-bytes` CLI 早已在位。
3. **resume 侧**:`resume_state` 读 `run_config`(本就加载)的 `budgets.max_unit_bytes`,为正
   整数即作 `canonical_unit_ids_for_run` 的预算参数——与 runner 透传值同源同值。这正是
   `canonical_unit_ids_for_run` docstring 的 COUPLING LOCKSTEP 契约兑现;删该注释中「today
   (fanout_runner does not forward)」的过时陈述,保留锁步条款(未来再改预算来源时仍需双侧)。

**被否的替代**:runner 读 run_config 失败即退出码 2——过刚(run_config 缺失 = 宿主外手动直跑
合法场景,回退枚举器默认即可,stderr 一次性提示)。

## D4 — scout pending 广告路径同源(B2)

`list_scout_batches` pending 段的 `checkpoint_path`/`done_marker`/`failed_marker` 从裸
`checkpoints_dir / f"{bid}.json"` 改为 `forward_marker_paths(checkpoints_dir, bid)` 产出
(init_tier 单源;判定侧本就经 forward 判)。`slice_dir`/input 物化的 `_safe_name` 已同源,不动。
canonical slug id 下输出逐字符不变(编码对 slug 是恒等),`::`/超长 id 下广告与判定重合——
消灭「写得到、看不见」的无限重派形态。死 import(`forward_marker_paths` 导入未用)随之转正。

## D5 — T3 判定正向化(B3)

`_done_categories`/`_failed_categories`(glob + 记录体/stem 反推)改为:canonical 单元集 =
`rule_unit_ids(categories, fmt)`(单源公式,已在位)逐 id 经共享编码算 marker 路径判存在性
(与 T1/scout 同构);磁盘 glob 降级为孤儿审计(镜像 `init_tier.orphan_markers` 家族形态,
stderr 告警不改计数)。私有 `_safe_name` 改 `init_tier.safe_unit_filename` 别名
(list_scout_batches 同款形态)。failed marker body 的 `unit` 字段读取保留仅作诊断对照(非判定)。

## D6 — scout 计划自描述(M2)

`plan_scout` 生成时顶层记录 `batch_bytes`/`batch_cap`(生成所用值);`_run_check` 优先取 plan
记录值(缺记录的存量 plan 回退 CLI `--batch-bytes`,零破坏);损坏 plan(JSON 解析失败/wrapper
形状错)从 `return 1` 改 `return 2`(R5.9 边界校验统一退出码;闸门 recipe 只认 2)。

## D7 — 切片器三修(M3)

- **控制流排除**:JAVA_DEF 匹配后按捕获名字做确定性后过滤(小写比较 ∈ {while, for, do, if,
  else, switch, case, try, catch, finally, synchronized, return, new, throw})→ 不产节点。
  真方法(含 `synchronized` 修饰前缀的方法)不受影响(其捕获名是方法名,非关键字)。选后过滤
  而非改正则:正则负向前瞻在修饰符/泛型组合下易错(批次 2 守卫域同款教训),后过滤可测且零回归面。
- **`--in` 存在性**:main 里 `Path(args.inp)` 后 `is_file()` 为假 → 退出码 2 + 路径(recipe 指向
  subagent 路径 typo 形态)。
- **`--line` 判定**:`if args.line:` → `is not None`;`< 1` → 退出码 2 + recipe(骨架模式 =
  不传 `--line`,显式 0 不再静默落骨架)。

## D8 — fold-in 韧性(M4)

- **原子 + 写序**:两文件各改原子写(tmp + `os.replace`,仓内既有 `_atomic_write_json` 家族
  形态);写序 clusters 先、candidates(携 `provenance.scout_merged` 凭证)后。幂等收敛论证:
  崩溃于两写之间 → 凭证缺 → 重折;已折候选已在 candidates 内 → 去重集判重 → `fresh` 空 →
  clusters 追加空集,两文件收敛一致。凭证在 ⟹ 两文件必一致(写序保证)。
- **未映射类别 fail-loud**:fold-in 主路径(含 audit 路径)遇未映射非规范类 → 收集全部违例后
  退出码 2(镜像 `--check` 语义);**缺字段**候选保持 skip+warn + `skipped` 计数(1160 契约
  不变)。判据二分:缺字段 = LLM 输出质量噪声(可跳过披露);未映射类名 = 确定性漂移(必须拦)。
- **形状错结构化错误**:wrapper 非 dict / `candidates` 非 list / candidate 非 dict / audit
  `audit_found` 非 list 或元素非 dict → 结构化错误 JSON + 退出码 1(1160 破损 JSON 同形),
  NEVER 裸 traceback(audit 路径同判)。

## D9 — rollup manifest(M5)

`plan_aggregate` needs_reduce 时原子写 `<shard_cp_dir>/rollup_manifest.json`
(body `{summary_paths[], output, done_marker}`,幂等覆盖);stdout `rollup` 段改
`{summary_paths_manifest, output, done_marker}`(数组移除;`shards` 计数在顶层既有)。
`needs_reduce:false` 路径零变化(无 manifest、stdout 逐字节不变)。消费面同 change 切换:

- stage 提示词 ×2(`init-synthesis-rollup.md` / `init-scout-merge-rollup.md`):Input 段改
  「manifest 绝对路径(编排器逐字透传)→ 先 Read manifest 取 summary_paths → 逐份吞摘要」;
  读侧白名单同步把 manifest 列入合法 Read 面。
- agent 定义 ×2 面(opencode `.opencode/agent/` + claude `agents/` 的两个 rollup agent,
  三面镜像纪律:dsh 无 rollup 派发实例,不涉)。
- 契约 ×2(`aggregate-sharding.md` stdout 示例 + `scout-plan.md` rollup 行)同步新形态。

**为什么 manifest 而非分页数组**:rollup 需要全量路径,1000 片时任何「数组进 stdout/任务消息」
形态都击穿 64KB 页预算承诺;manifest 是唯一让「全量可取」与「单次回复有界」并立的形态,且
编排器 NEVER 自读 manifest(R5.2 内省禁令)——读它的是 rollup subagent(树内 Read 合法)。
**被否的替代**:数组按页截断 + truncated 标志——rollup 语义要求全量,截断即静默丢摘要路径,
违反「无静默截断」铁律。

## D10 — 分页卫生(M1)与死常量(L1)

`--limit <1` → 退出码 2 + recipe,统一落 `list_clusters` / `list_scout_batches` /
`list_rule_jobs` / `plan_aggregate`(与各自 `--offset` 校验同款消息形态)。删除
`list_clusters` 本地 `MAX_UNIT_FILENAME_STEM = 200` 重定义(单源 = init_tier import;本地行
自称 alias 实为独立副本,上游改值即静默漂移)。

## D11 — 测试策略与共用面纪律

- 先红后绿分组对应 M1-M5/D1-D10;红测全部走 CLI 级(真跑脚本 + 真产物树),不起 in-process
  harness 内省私有函数(fanout TIERS 转发用 `--pending-file`/mock 枚举器现有测试形态)。
- `test_fanout_runner` 有**存量失败**(`TestRateLimitStorm::test_all_rate_limit_storm_truncates_fast`,
  waves_run 3≠2,HEAD 8b7e7a8 同败)——本批回归以「不新增失败」为准,勿追查该条(战役交接
  情报三.12);本批若动 TIERS,新增用例仍 MUST 显式 `--cooldown-s 0`(R5.8)。
- 分发面(rollup agent/契约/stage 提示词)改动 → purity + budget + contracts lint 必跑;
  两面 agent 定义按逐字镜像纪律同步(方言差异仅白名单五类)。
- 实现顺序建议:D3(锁步三件套)最后合入——它跨 runner/枚举器/resume 三文件,先落单文件项
  (D1/D2/D4-D8/D10)各自转绿,锁步项独立红测组一次合入,便于 bisect。

## D12 — 批次边界

- discover/expand 扫描韧性(H5/H6/H7)= 批次 6;stage 提示词与契约批量同步(11 项 medium/Low)
  = 批次 7;H11 `--merge` 拍板项 = 批次 7。本批不碰。
- 守卫三镜像、壳 flag 表、install 接线零涉及。`scout-plan.md` 契约的「flag 名失真」
  (`--scout-batch-bytes` 等幻影名)属批次 7 的契约同步面——本批只动该契约的 rollup 行与
  stdout 形状段,不顺手重写全文(避免与批次 7 冲突)。
