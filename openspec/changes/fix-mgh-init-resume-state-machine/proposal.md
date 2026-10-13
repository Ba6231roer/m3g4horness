# fix-mgh-init-resume-state-machine

> **人话序**:深度评审发现 /mgh-init 的断点续跑状态机对「含分片簇的 run」会永久卡死:超预算大簇会被
> 切成 `::shard-<n>` 分片单元、只写分片级完成标记,而 `resume_state.py` 计算 T1 进度时传的是空候选集,
> 推导不出分片单元 id——「完成数恒为 0 < 簇总数」永不收敛,`--resume` 无限空转重派。根因是**计数口径
> 分裂**(状态机与枚举器各算各的 id 集)。本批改:状态机改用与枚举器同源的真实候选 + 预算**复算**单元
> id 集(顺带修掉复算路径上实测复现的「幽灵 shard-0」缺陷)、T3 计数同改前向口径、done 步收尾纪律恢复
> 可加载(哨兵移除不再失联)、`--invalidate-stale` 补前置判定、`--check` 补「run 完成后哨兵残留」违例、
> 两份滞后契约对齐实现。验证:新增「分片簇全 done → step 越过 t1」等回归测试先红后绿,既有 35 测零受扰。

## Why

2026-10-13 的 /mgh-init 全流程深度评审(97 文件全覆盖、关键结论均实机复现;报告存于维护者私有文档区)
给出 1 Critical + 14 High + 68 Medium + 19 Low,零整体误报。修复按评审建议顺序分七批落地,本 change 是
**批次 1**,处理唯一的 Critical 及其同根(口径分裂 / per-step 加载失同步)的状态机簇。

**CR-1(唯一 Critical)——含分片簇的 run 永久卡死在 step=t1**:`list_clusters.py` 物化超预算簇时按候选
字节贪心切成 `<cluster_id>::shard-<n>` 单元,分片各自落 `.done`/`.failed` marker,整簇 marker 无写入者;
而 `resume_state.py:517` 调共享收集器 `collect_canonical_ids(clusters, {}, 0, None)` 时传**空候选集 + 零
预算**,该入参下返回值只含整簇 id → T1 完成度按整簇口径数 marker 恒为 0,`(done+failed) < total` 永真,
step 永卡 t1、枚举器却报 pending=0,编排器按纪律(进度纯信 resume_state)无限循环。目标环境(数百万行
Java 仓,注解簇极易超 192KB 单元预算)下分片是常态而非边角。评审以单簇切 2-3 分片全部 touch `.done`
实机复现(`list_clusters` 报 done=1/pending=0,`resume_state` 报 done=0/total=1 + step=t1,输出逐字一致)。

**连带缺陷**(同一退化 id 集的直接后果,一并修):`--check` 把合法分片 marker 误报为「孤儿 marker」
advisory;`resume_state.py:508-510` 首次赋值被 517 行无条件覆盖(死代码 + 二次读盘);完成态 run(manifest
已在)因闸门排在 manifest 检查之前也被波及。

**本批同时收口的同簇缺陷**(评审 medium/low + 复现实验新发现,详见 design):

- **幽灵 shard-0(新发现,评审未直接点名)**:`_shard_plan` docstring 声称「簇整装时返回 []」但代码无该
  守卫——用真实候选调收集器会给**每个**含候选的簇派生一个永无 marker 的 `::shard-0` id。不先修它,
  评审建议的「真复算」方向会把死锁变成更彻底的死锁(实测复现:默认预算下两个小簇也各得一个 shard-0)。
- **T3 计数裸 glob**(孤儿 marker 抬高 done 可静默跳过 pending category;`--check` 孤儿审计只扫 scout/t1)。
- **done 步收尾纪律不可达**(H12):`_FRAGMENT_STEPS` 明确排除 done,而「run 完成后移除哨兵
  `.active`」的纪律只在 done.md / bootstrap.md——长跑压缩后恢复到收尾态时加载不到,哨兵残留会锁死目标
  项目的日常开发;`--check` 也不查完成态哨兵残留。
- **survey/resolve/t4 三个 fragment 头注虚假声明**「Loaded per-step via resume_state」——step 派生从不
  路由到这三步(它们 optional 或并入 assemble 分支),头注与机制不符。
- **t2 fragment 缺无条件前置闸门**:resume 直落 t2 时 T1→T2 的 `validate_t1_records --check` 闸门被静默
  跳过,破损 T1 记录不带校验进综合。
- **`--invalidate-stale` 无前置判定**:对 no_scout / scout 已完成的 run 会删**有效**下游凭证迫使 T2-T4
  全量重跑;unlink 失败仍 exit 0;与 `--check`/`--rearm-sentinel` 组合时静默短路。
- **merge 模式 stdout 缺 `stale_fanout` 字段**(契约承诺「字段恒存在」,消费方会 KeyError)。
- **两份契约滞后于实现**:`resume-state.md` 缺 `--run-root`/`--rearm-sentinel` 两个实装 flag、缺
  `discipline_reminders`/`stage_flow_files`/`stale_fanout` 三个恒存在 stdout 字段、`--check` 清单缺哨兵
  违例;`step-manifest.md` 的 Step→IO 表 4 行漂移(scout/t1/t3 的 script 应为 `fanout_runner.py`、t2 应为
  bash 派发、scout 漏 extra_invocations——失同步约 7 周横跨 dispatcher 化架构演进)。

**与已落地修复的重叠核实**:评审基线(VERSION 0.1.60)之后仓库落了 5 个 mgh-sdr 修复 change,其中
`fix-mgh-sdr-fanout-recovery` 动过六域共用的 `fanout_runner.py`(评审 H1 的 wmic/CIM 与 failed 双计已
顺带修复)。本批涉及的 `resume_state.py`/`list_clusters.py`/`list_steps.py`/`core/contracts/init/**`/
`init-stage/**` 经 git diff 核实**自基线以来零改动**,评审行号全部有效、无重复劳动。

## What Changes

- **T1 口径合一(CR-1 主体)**:`_shard_plan` 补整装守卫(簇整装 ≤ 预算时返回 [],分片派生仅对真超预算
  簇;守卫用与 `_resolve_units` 同一「绝对化后整装字节」判据);`resume_state.py` 删 508-510 死赋值,
  T1 canonical id 集改经 list_clusters 生产者侧共享函数**复算**(真实候选 + 共享默认单元预算);
  `tiers.t1` 改单元口径(whole + shard id 数),t1 闸门按单元总数判终态;step 派生把 manifest 短路提到
  全部 tier 闸门之前(完成态 run 不再被下游计数波及)。
- **T3 前向口径**:t3 done/failed 计数从裸 glob 改为「inventory categories × format」的 canonical id
  前向 marker 判定(id 公式由 `list_rule_jobs.py` 单一来源导出);`--check` 的孤儿审计与判定一致性审计
  扩到 t3。
- **done 步可达性(H12)**:`_FRAGMENT_STEPS` 增 `done`,step=done 时 `stage_flow_files[]` 返回 done.md
  (收尾纪律:manifest 收尾 + 哨兵移除恢复可达);`--check` 新增违例「manifest 已在(run 完成)但
  `<init-dir>/.active` 哨兵仍存在」+ 移除 recipe;survey/resolve/t4 fragment 头注改为如实可达性陈述,
  assemble.md 尾部补「T4 前 Read t4.md」固定路径配方。
- **t2 闸门前置**:t2.md fragment 增无条件前置行 `validate_t1_records --strip-bom`+`--check`(幂等;
  resume 直落 t2 亦不跳闸门)。
- **`--invalidate-stale` 收口**:复用「scout 启用 + 未完成」前置判定(前置不满足 → 诚实空结果 + stderr
  提示、删零文件);unlink 失败 → exit 2 fail-loud;与 `--check`/`--rearm-sentinel` 互斥(argparse 误用
  exit 2)。
- **merge 模式补 `stale_fanout` 字段**(全 step 字段恒存在承诺兑现)。
- **契约同步**:`resume-state.md`(CLI flag、stdout 字段、t1 单元口径、`--check` 清单含新旧哨兵违例、
  `--invalidate-stale` 语义、manifest 短路);`step-manifest.md`(Step→IO 表 4 行纠偏 + extra_invocations;
  merge 行留待「--merge 模式出口」拍板项处理,不在本批)。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `resume-step-discipline`: T1/T3 计数口径与枚举器合一(含复算预算的单一真相)、manifest 优先短路、
  `--invalidate-stale` 前置判定与互斥语义、`--check` 新增完成态哨兵残留违例与 t3 审计覆盖、merge 模式
  `stale_fanout` 恒存在。
- `control-discovery`: T1 canonical id 收集器补整装守卫——分片 id 派生 SHALL 仅对真超预算簇(收集器
  返回集 = 物化可写集,消除幽灵 shard-0)。
- `orchestration-substrate`: `stage_flow_files[]` 的 done 步从「恒空」改为加载 done.md;Step→IO 契约表
  与 `list_steps.py` 实现的同步义务(scout/t1/t2/t3 = fanout_runner 派发优先)。

## Impact

- **代码**:`core/scripts/resume_state.py`(口径/短路/flag 语义/检查项)、`core/scripts/list_clusters.py`
  (`_shard_plan` 守卫 + 生产者侧复算函数)、`core/scripts/list_rule_jobs.py`(仅导出 t3 单元 id 公式助手,
  行为零变化)。
- **提示词**:`core/prompts/fragments/init-stage/{survey,resolve,t4,assemble,t2}.md`(头注如实化 + 闸门前
  置行;随 install 分发面,purity/budget lint 复跑)。
- **契约**:`core/contracts/init/resume-state.md`、`core/contracts/init/step-manifest.md`。
- **测试**:`tests/test_resume_state.py`(新增先红后绿回归)、`tests/test_list_clusters.py`(整装守卫)、
  `tests/test_list_steps.py`(契约表同步断言);`test_zero_deps`/`test_no_compile_warnings` 顺手带上。
- **兼容性**:旧 run 产物零迁移——分片 marker 本来就在盘上,修复后**开始被正确计数**;`tiers.t1.total`
  语义从簇数改为单元数(含分片),stdout 形状不变、消费方(壳/编排器)只读 step/next_action 不受扰;
  无新增 CLI flag。
- **战役上下文**:本 change 是七批修复的批次 1;后续批次见下节路线图,各自独立 propose/apply。

## 修复战役分批路线图(本 change = 批次 1;供维护者校对分批边界)

| 批次 | 域 | 覆盖发现 | 状态 |
| --- | --- | --- | --- |
| 1 | resume 状态机 + per-step 加载 | CR-1 + H12 + t3 裸 glob / --invalidate-stale / merge stale_fanout / manifest 排序 / 508-510 死赋值 / fragment 头注 / t2 闸门 / 契约同步 + 新发现幽灵 shard-0 | **本 change** |
| 2 | 守卫(block_adhoc_scripts) | H2(redirect 越树对 sast/sra/srr/sdr 四域放行)、H3(stdin 强制 UTF-8,GBK 中文 Windows 守卫整域休眠)、H13(哨兵残留文档语义与实现矛盾)+ 守卫域 medium×7 / low×3 | 待做 |
| 3 | fanout_runner 派发器 | H1(wmic/CIM)与退出摘要 failed 双计**已由 sdr 批次顺带修复**;剩:冷却期 100% CPU 忙等、`_kill_tree` 返回值忽略、path-drift 检测后反写越树路径、kill-stale 子串匹配误杀、spawn 未剥离 PWD、`_safe_name` 私有拷贝漂移 | 待做(缩量) |
| 4 | 分发死链与壳/agent 面 | H10(codegraph-hint ×4 死路径)、H14(rules-format ×4 面)、H9(dsh 派发披露不完整)、待实测(opencode `edit: deny` vs Write)、壳/agent 定义 medium×9 + install.sh 卫生 | 待做 |
| 5 | 枚举/聚合/切片口径 | H4(切片簇失败吞失,簇级三分)、H8(t2 聚合预算按物化字节计量)、list_scout_batches 裸拼 / list_rule_jobs 反推 / runner 不透传 `--max-unit-bytes` / rollup summary_paths 击穿预算 / chunk_sources 切片缺陷群 / plan_scout·merge_scout 原子性与退出码 | 待做 |
| 6 | discover / expand_scope 扫描韧性 | H5(callgraph 单遍丢边)、H6(limit 配额被非源文件消耗 + 静默截断)、H7(`--scope path:` 不存在静默空集)、discover 续点/检查/写放大 medium 群、write_runconfig 持久性 | 待做 |
| 7 | stage 提示词与契约批量 + 拍板项 | 剩余 stage 提示词 medium×10、契约 medium×12、H11(`--merge` 无确定性出口:**实现 `merge_inventories.py` vs 三面拒绝该模式,需维护者拍板**) | 待做(含拍板) |
