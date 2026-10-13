# tasks — fix-mgh-init-resume-state-machine

> 约定:回归测试一律**先红后绿**(先在修复前写出并确认失败形态,再实现转绿);每完成一组跑
> design「Migration Plan」列出的定向面;`py` 为本机解释器。

## 1. 先红:回归测试(修复前确认失败形态)

- [x] 1.1 `tests/test_resume_state.py` 新增「分片簇死锁」组:单簇物化 3 shard——(a) 全
  `.done` → 断言 step≠t1 且 `tiers.t1={done:3,failed:0,total:3}`(修复前实测 `{done:0,total:1}`
  + step=t1);(b) 2/3 终态 → 断言 step 停 t1;(c) 2 done + 1 failed → 断言越过 t1 且
  `failed:1` 进 notes 披露
- [x] 1.2 同文件新增:manifest 在 → step=done 短路(构造 manifest + 残缺 tier 磁盘形态,断言
  step=done / resumable=false);合法 shard marker 不再进 `--check` 孤儿 advisory
- [x] 1.3 同文件新增:t3 前向口径——孤儿 `.json.done`(不对应 inventory category × fmt)不抬
  高 `tiers.t3.done`,`--check` notes 以孤儿披露(t3 审计面与 scout/t1 对齐)
- [x] 1.4 同文件新增:done 步 `stage_flow_files[]` 含 `init-stage/done.md` 绝对路径(含
  finalize 分支);merge 模式分支 stdout 恒含 `stale_fanout`(无残留时 `[]`)
- [x] 1.5 同文件新增:`--invalidate-stale` 三点——no_scout run 空转删零文件 exit 0;unlink
  失败(monkeypatch OSError)exit 2;与 `--check`/`--rearm-sentinel` 组合 exit 2;单独
  `--dry-run` exit 2
- [x] 1.6 同文件新增:`--check` 完成态哨兵残留违例(manifest + `.active` 同在 → exit 2 +
  violations 含移除 recipe);既有「进行中缺哨兵」用例零改动通过
- [x] 1.7 `tests/test_list_clusters.py` 新增:`collect_canonical_ids` 整装守卫——两个整装簇 +
  真实候选 + 默认预算 → 返回集恰为 `[c1, c2]`(修复前含 `c1::shard-0`/`c2::shard-0` 幽灵);
  超预算簇 → 分片 id 与 `_resolve_units` 物化单元逐 id 一致
- [x] 1.8 `tests/test_list_steps.py` 新增契约同步断言:解析 `core/contracts/init/step-manifest.md`
  Step→IO 表 bash 步的 script/kind,与 `list_steps.py` stdout 对应字段一致(修复前 scout/t1/t2/t3
  四行不一致)

## 2. 口径合一(list_clusters + list_rule_jobs 生产者侧)

- [x] 2.1 `list_clusters.py` `_shard_plan` 补整装守卫:绝对化整装体 `_byte_len` ≤ 预算 → 返回
  `[]`;判据注释注明与 `_resolve_units` 同度量(D2);docstring 既有「[] when fits」声明变为真
- [x] 2.2 `list_clusters.py` 新增生产者侧组合函数(读 clusters + `_load_candidates` +
  `collect_canonical_ids` @ `DEFAULT_MAX_UNIT_BYTES`),供 resume 复算共享导入;耦合注记:
  预算转发落地(批次 5)时物化/复算必须同 change 锁步切换(D1)
- [x] 2.3 `list_rule_jobs.py` 导出纯函数 `rule_unit_ids(categories, fmt)` 并在 marker 路径处
  消费(逐字节等价,零行为变化);`--help` 面零变化
- [x] 2.4 跑 `test_list_clusters` / `test_zero_deps` / `test_no_compile_warnings` 全绿(1.7 转
  绿;既有逐 id 断言如受幽灵 id 影响按新口径翻转并注明)

## 3. resume_state 主体(resume_state.py)

- [x] 3.1 t1 口径:删 508-510 死赋值与二次读盘,id 集改经 2.2 共享函数复算;`tiers.t1` 改单元
  口径 `{done,failed,total=len(ids)}`,t1 闸门按单元总数;stderr 摘要与 docstring「计数口径」段
  同步(D1/D3)
- [x] 3.2 manifest 短路:`init_manifest.json` 在 → step=done 提到全部 tier 闸门之前(D4)
- [x] 3.3 t3 口径:`_count_markers` 裸 glob 改 `forward_done_ids`/`forward_failed_ids` over
  `rule_unit_ids`(inventory categories × cfg format);孤儿/判定审计(`orphan_markers`/
  `check_init_markers`)循环扩到 t3 目录(D5)
- [x] 3.4 done 可达:`_FRAGMENT_STEPS` 增 `"done"`(+注释/docstring:「done 有收尾纪律加载」);
  merge 短路分支补 `stale_fanout` 字段(D6)
- [x] 3.5 `--invalidate-stale` 收口:前置判定(复用 scout_complete/no_scout 同判据)→ 空转删零
  文件 exit 0;unlink 失败收集 → exit 2;argparse 互斥组(`--invalidate-stale` vs
  `--check`/`--rearm-sentinel`;`--dry-run` 单独传 exit 2)(D8)
- [x] 3.6 `--check` 新增完成态哨兵残留违例(manifest 在 + `.active` 在 → violation + 移除
  recipe);既有检查项零回归
- [x] 3.7 跑 `test_resume_state` 全绿(1.1-1.6 转绿 + 既有 35 测零受扰)+ `test_list_scout_batches`
  (口径相邻面)+ `test_zero_deps` / `test_no_compile_warnings`

## 4. fragment 与契约(分发面)

- [x] 4.1 `init-stage/survey.md`/`resolve.md`/`t4.md` 头注如实化:删「Loaded per-step via
  resume_state」虚假声明,改为「编排器决定执行该(可选)阶段时 fixed-path Read 本文件」的可达性
  陈述(D7)
- [x] 4.2 `init-stage/assemble.md` 尾部补「进入 T4 前 Read `init-stage/t4.md`」配方行(与同文件
  既有调用行风格一致);`init-stage/t2.md` 头部补无条件前置闸门行(`validate_t1_records
  --strip-bom` + `--check`,幂等;exit 2 → 外科式重派,措辞与 orchestrator-discipline 闸门段
  对齐)(D7)
- [x] 4.3 `core/contracts/init/resume-state.md` 同步:CLI 补 `--run-root`/`--rearm-sentinel`;
  stdout 示例补 `discipline_reminders`/`stage_flow_files`/`stale_fanout`(注明含 merge 分支恒
  存在);真值表 t1 行单元口径 + manifest 短路;`--check` 清单补双向哨兵违例 + t3 审计覆盖;
  `--invalidate-stale` 段按 D8 重写(D9)
- [x] 4.4 `core/contracts/init/step-manifest.md` Step→IO 表纠偏:scout/t1/t3 行 script 改
  `fanout_runner.py`、t2 行改 bash 派发、scout 行补 `extra_invocations`;注记段同步;**merge 行
  不动**(批次 7 拍板项)(D9)
- [x] 4.5 跑 1.8 契约同步断言转绿;`python tools/check_contracts.py` /
  `check_distributed_purity.py` / `check_distributed_prompt_budget.py` /
  `check_plain_language.py`(人类面无新文件,应零变化)全过

## 5. 收尾

- [x] 5.1 定向面全绿确认:`test_resume_state` / `test_list_clusters` / `test_list_steps` /
  `test_list_scout_batches` / `test_zero_deps` / `test_no_compile_warnings`;全量回归**免跑**
  (未触 `core/contracts/hooks`、`install.sh`、hook 接线、跨脚本公共 helper 的跨面语义——
  `init_tier.py` 仅新增无消费者断言不触既有导出;若有异议按 R5.8 全量闸门执行)
- [x] 5.2 实机抽查:按评审同款 fixture(单簇切 2-3 shard 全 touch `.done`)跑
  `py core/scripts/resume_state.py --target <fixture>`,确认 step 收敛越过 t1、`--check` 无孤儿
  误报;再跑一次带 manifest + 残留 `.active` 的 fixture 确认新违例
- [x] 5.3 bump `VERSION`、补 `CHANGELOG.md`;git commit(消息按仓库惯例含发现编号与先红后绿
  计数);归档走 `/opsx:archive`(specs 增量回写主规格)
