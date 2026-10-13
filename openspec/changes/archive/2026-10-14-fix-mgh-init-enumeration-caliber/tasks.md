# fix-mgh-init-enumeration-caliber — Tasks

> 实施纪律:先红后绿;红测一律 CLI 级(真跑脚本 + 真产物树)。本机 `py` 坏,用 `python`。
> `test_fanout_runner` 有存量失败(TestRateLimitStorm waves_run 3≠2,HEAD 即败)——回归以
> 「不新增失败」为准,勿追查。实现顺序建议按组号(单文件项先,锁步组 7 最后合入,便于 bisect)。

## 1. 簇级计数三分(H4 / design D1)

- [x] 1.1 红测:`test_list_clusters` 增两组——①无打包:1 簇 2 片全 `.failed` → 断言 stdout
      `{done:0, failed:1, pending:0}`(现状 `{done:1, failed:0}` → 红);混合形态(2 簇:1 簇
      全 done、1 簇 1 done 1 failed)→ 计数三分各自正确;②打包:独立(oversize)簇全片
      `.failed` → 计 failed 不计 `independent_done`
- [x] 1.2 实现:两条计数路径改逐簇三分(单元终态 forward 计数 → 簇级三分),替换残差公式;
      `--include-failed` 重入语义与 `clusters_reincluded` 回加保持;跑 1.1 转绿
- [x] 1.3 `test_list_clusters` 全量绿(既有打包/整装守卫/超长 id 用例零回归)

## 2. t2 聚合物化口径(H8 / design D2)

- [x] 2.1 红测:`test_plan_aggregate` 增——构造触发 part 切分的 t2 输入,`--materialize` 后
      断言每个被派发 shard 落盘文件 `st_size` ≤ `--budget` 且 `pending[].bytes == st_size`
      (现状紧凑计量,实测超预算 ~1.23× → 红)
- [x] 2.2 实现:t2 分桶/瘦身判定统一物化口径(镜像 scout-merge `_materialized_bytes` 家族);
      `bytes` 回填 `st_size`;跑 2.1 转绿
- [x] 2.3 scout-merge 节点既有用例零回归(同文件共享路径)

## 3. scout 计划自描述(M2 / design D6)

- [x] 3.1 红测:`test_scout_plan` 增三组——①自定义 `--batch-bytes 204800` 生成的 plan 在缺省
      `--check` 下零违例(现状按 98304 误报 → 红);②损坏 plan(JSON 非法/wrapper 形状错)
      `--check` 退出码 **2**(现状 1 → 红);③存量无预算记录 plan 回退 CLI 值(兼容锚)
- [x] 3.2 实现:生成时顶层记录 `batch_bytes`/`batch_cap`;`_run_check` 优先 plan 记录值;损坏
      plan 返回 2;跑 3.1 转绿

## 4. 切片器三修(M3 / design D7)

- [x] 4.1 红测:`test_chunk_sources` 增三组——①Java 文件含 while/for-each/catch/switch/
      synchronized 块 + 真方法 → 骨架函数节点只含真方法,真方法 `line_end` 不被内层控制流
      截断,synchronized 修饰真方法仍识别;②`--in` 不存在 → 退出码 2(现状空骨架 exit 0 →
      红);③`--line 0` → 退出码 2(现状落骨架模式 → 红)
- [x] 4.2 实现:JAVA_DEF 匹配后控制流关键字确定性后过滤;`--in` 存在性 fail-loud;`--line`
      改 `is not None` + `<1` 拒识;跑 4.1 转绿

## 5. fold-in 韧性(M4 / design D8)

- [x] 5.1 红测:`test_merge_scout` 增四组——①未映射类别(`runtime-guard`)在 fold-in 主路径
      退出码 2(现状 skip+warn → 红;audit 路径同判);②缺字段候选仍 skip+warn + `skipped`
      计数(既有语义锚,防误伤);③合法 JSON 形状错(candidates 是 dict/audit_found 元素非
      dict/wrapper 非 dict)→ 结构化错误 + 退出码 1 不裸崩(现状 AttributeError → 红);
      ④两写之间崩溃模拟(写完 clusters 后中断)→ 重折幂等收敛、无重复簇追加
- [x] 5.2 实现:两文件原子写 + 写序 clusters→candidates(凭证最后);未映射类别收集违例后
      exit 2;形状错结构化错误 exit 1;跑 5.1 转绿
- [x] 5.3 `scout-tier-gate` 相关既有用例零回归(`--check` 镜像违例语义不变)

## 6. 枚举器卫生(B2/B3/M1/L1 / design D4/D5/D10)

- [x] 6.1 红测:`test_list_scout_batches` 增——bid 含 `::` 与超长 id 两组,pending 广告的
      cp/dm/fm 路径与 forward 编码判定路径逐字符相同,且派发器写 marker 后重列该批从
      pending 消失(现状广告/判定分叉 → 永久 pending → 红)
- [x] 6.2 红测:`test_list_rule_jobs` 增——①done/failed 判定正向化锚(canonical category 单元
      marker 判定;孤儿 marker stderr 告警不抬高 done);②`_safe_name` 与
      `init_tier.safe_unit_filename` parity(脚本不再持私有拷贝——源形态断言)
- [x] 6.3 红测:`--limit <1` 四脚本(list_clusters / list_scout_batches / list_rule_jobs /
      plan_aggregate)退出码 2 + recipe(现状空页 effective_limit=0 → 红)
- [x] 6.4 实现:pending 路径经 `forward_marker_paths`(死 import 转正);T3 判定正向化 + 孤儿
      审计 + `_safe_name` 别名;四脚本 `--limit` 校验;删 `list_clusters` 本地
      `MAX_UNIT_FILENAME_STEM` 重定义;跑 6.1-6.3 转绿

## 7. 单元预算消费闭环(B1 锁步 / design D3 — 最后合入)

- [x] 7.1 红测:`test_fanout_runner` 增——init 目录置 `run_config.json`
      (`budgets.max_unit_bytes: 65536`),`--tier scout|t1|t3` 内部调用枚举 CLI 时命令行携带
      `--max-unit-bytes 65536`(现状不透传 → 红);缺 run_config 时命令行不附加该 flag(兼容锚)
- [x] 7.2 红测:`test_resume_state` 增——`run_config` 记 65536 的 run,某簇按 64KB 已切 2 片且
      全终态 → `tiers.t1.total` 含 2 分片、step 越过 t1(现状复算锚 192KB 默认只见整簇 id →
      step 卡 t1 → 红,即 CR-1 复活形态);缺 run_config 的 run 回退共享默认(兼容锚)
- [x] 7.3 实现(三件套一次合入):runner 读 run_config 透传 list_args;
      `canonical_unit_ids_for_run` 增可选预算参数;`resume_state` 传 run_config 值;更新该
      函数 docstring 的 COUPLING LOCKSTEP 注释(锁步条款保留,「today does not forward」
      过时陈述改实况);跑 7.1/7.2 转绿
- [x] 7.4 `test_list_clusters` 的 canonical id 收集器既有用例(默认参数路径)零回归

## 8. rollup manifest(M5 / design D9)

- [x] 8.1 红测:`test_plan_aggregate` 增——needs_reduce 大 shard 数形态(如 50 片)断言
      stdout `rollup` 段为 `{summary_paths_manifest, output, done_marker}`(无 `summary_paths`
      数组)、整份 stdout ≤ `--orch-budget-bytes`、`rollup_manifest.json` 含全量路径且幂等
      (现状 stdout 携带全量数组 → 红);`needs_reduce:false` stdout 逐字节不变(兼容锚)
- [x] 8.2 实现:`plan_aggregate` 物化 manifest(原子写)+ stdout 形态切换;跑 8.1 转绿
- [x] 8.3 消费面同步:`init-synthesis-rollup.md` / `init-scout-merge-rollup.md` stage 提示词
      Input + 读白名单增 manifest 分支;opencode + claude 两面 rollup agent 定义镜像同步;
      契约 `aggregate-sharding.md` stdout 示例与 `scout-plan.md` rollup 行改新形态(只动
      相关段,不重写全文——契约批量同步归批次 7)
- [x] 8.4 分发面 lint:`python tools/check_distributed_purity.py` + budget lint +
      contracts lint 全过;`test_distributed_md_purity` 绿

## 9. 回归与收尾

- [x] 9.1 定向面全绿(AGENTS.md 映射表):`test_list_clusters` / `test_list_scout_batches` /
      `test_plan_aggregate` / `test_scout_plan` / `test_chunk_sources` / `test_merge_scout` /
      `test_fanout_runner`(存量 TestRateLimitStorm 失败除外,不新增失败)/ `test_resume_state` /
      `test_list_rule_jobs` + `test_zero_deps` + `test_no_compile_warnings`
- [x] 9.2 `git diff --stat` 确认涉改面 = 9 脚本 + 2 stage 提示词 + 2 面 agent 定义 + 2 契约 +
      测试文件(+ VERSION/CHANGELOG);守卫三镜像、壳 flag 表、install 接线零触碰
- [x] 9.3 VERSION bump 0.1.71 → 0.1.72 + CHANGELOG 条目(按本批 11 项一句一条)
- [x] 9.4 `openspec validate "fix-mgh-init-enumeration-caliber" --strict` 过 + purity 零违例
      + `check_plain_language.py`(exit 2 = 既有噪音)
- [x] 9.5 实机冒烟(建议):小仓跑 `mgh-init` 确定性段至 plan_scout/--check 与 list_* 枚举
      正常;`plan_aggregate --node t2` needs_reduce 形态人工构造一次验 manifest 落盘
- [x] 9.6 `/opsx:archive`(归档会话执行;specs 增量回写 5 能力 11 MODIFIED)
