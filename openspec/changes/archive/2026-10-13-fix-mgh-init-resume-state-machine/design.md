# design — fix-mgh-init-resume-state-machine

## Context

评审基线(VERSION 0.1.60)之后仅有 mgh-sdr 域的 5 个修复 change 落地,本批涉及文件
(`resume_state.py`/`list_clusters.py`/`list_steps.py`/`core/contracts/init/**`/`init-stage/**`)
经 git diff 核实零改动。关键现状(均已实读核实):

- `resume_state.py:517` 以 `collect_canonical_ids(cl["clusters"], {}, 0, None)` 退化入参取 t1 id 集;
  `:508-510` 的整簇赋值被其无条件覆盖(死代码 + 二次读盘);`:610` t1 闸门按簇总数判收敛;
  `:530-531` t3 计数裸 glob;`:459-472` merge 短路分支缺 `stale_fanout`;`:912-932`
  `--invalidate-stale` 无前置判定、unlink 失败 exit 0、先于 `--check`/`--rearm-sentinel` 短路;
  `:598-649` step 派生从不产出 survey/resolve/t4,manifest 检查排在全部 tier 闸门之后。
- `list_clusters.py` 的 `_shard_plan`(分片计划单一来源,枚举与 canonical id 收集共享)**无整装
  守卫**:docstring 声称「簇整装时返回 []」但代码对任何含候选簇都产出 ≥1 个 `::shard-<n>`——
  本机实测(2026-10-13):两个远小于预算的簇 + 真实候选 + 默认预算,`collect_canonical_ids`
  返回 `[c1, c1::shard-0, c2, c2::shard-0]`。物化路径 `_resolve_units` 有自己的整装短路
  (`_byte_len(full) <= max_unit_bytes → 整簇单元`),故幽灵 id 从不对应输入文件、永无 marker。
- `fanout_runner.py`(六域共用)不向枚举器透传 `--max-unit-bytes` → 派发路径上枚举/物化实际恒用
  默认预算;`write_runconfig.py` 记录的 `budgets.max_unit_bytes` 主路径无消费者(评审批次 5 的
  已知 medium)。
- `init_tier.orphan_markers` 已豁免 `pack__` 前缀(pack 级 marker 不误报孤儿);pack 模式成员级
  marker 是唯一真相源,复算口径对 pack run 天然成立。
- 三面壳的 resume recipe 是通用「读 stdout `step` → `list_steps --step` → **Read
  `stage_flow_files[0]`**」——把 done 加入 `_FRAGMENT_STEPS` 后壳文本**零改动**即恢复 done.md
  可达性;`list_rule_jobs.py` 的 t3 marker 公式 = `<category>.<fmt>.json.done`(category 经 8 类
  canonical 枚举,`safe_unit_filename` 对其恒等)。

## Goals / Non-Goals

**Goals:**

- t1/t3 计数与 step 派生对「分片簇」「孤儿 marker」「完成态 run」三类磁盘状态给出收敛且诚实的判定。
- done 步收尾纪律(哨兵移除、manifest 收尾)经 per-step 机制可达;`--check` 能检出完成态哨兵残留。
- 三个 fragment 头注/配方与加载机制如实对齐;t2 步闸门对 resume 直落不豁免。
- 两份契约(resume-state / step-manifest)与实现对齐,且有机械化防再漂移防线。

**Non-Goals(边界,均有独立去向):**

- `--merge` 模式的确定性出口(实现 `merge_inventories.py` vs 三面拒绝)——批次 7 拍板项,
  step-manifest 的 merge 行本批不动。
- runner 向枚举器透传 `--max-unit-bytes`(批次 5;本批以「共享默认预算」为口径锚,见 D1 耦合注记)。
- `list_clusters` stdout 的簇级计数三分(批次 5 H4)、`plan_aggregate` 物化字节口径(批次 5 H8)。
- 守卫域(H2/H3/H13,批次 2)、fanout_runner 剩余 medium(批次 3)、Form B pack 形态的 stage
  prompt 覆盖(批次 7;pack 模式 marker 落点当前依赖任务模板,复算口径已按成员级成立)。
- t3 枚举器 `list_rule_jobs.py` 自身的正向化改造(批次 5)——本批只让它**导出** id 公式,零行为变化。

## Decisions

### D1 — t1 id 集:生产者侧共享函数「真复算」,预算锚 = 共享默认常量

`list_clusters.py` 新增生产者侧组合函数(读 `clusters.json` + `controls_candidates.json` →
`_load_candidates` + `collect_canonical_ids`,预算取模块级 `DEFAULT_MAX_UNIT_BYTES`),
`resume_state.py` 导入之(单一真相,NEVER 第二份拼装)。`resume_state.py:500-517` 的两次读盘 /
死赋值收敛为单次。

**预算为何锚默认常量而非 `run_config.budgets.max_unit_bytes`**:派发路径上枚举/物化**实际恒用
默认预算**(runner 不透传,批次 5 已知 medium)——复算用 run_config 自定义值会与磁盘上已物化的
分片计划错位,恰在「自定义预算 + 超预算簇」的 run 上延续死锁;复算用默认则与物化口径今日严格
一致。耦合注记写入两处代码注释:批次 5 落地转发时,**物化口径与复算口径必须同一 change 内同步
切到 run_config 值**(锁步不变量)。

被否方案:(a)「整簇 marker OR 全部分片终态」的簇级兜底口径——「全部分片」仍需分片计划,不复算
就退回簇级残差公式,与 H4 纠缠且引入第二套判定;(b) 读物化 input 文件反推单元集——文件名 → id
是明令禁止的反向推导(stem 截断不可逆)。

### D2 — `_shard_plan` 补整装守卫(判据与物化同度量)

守卫放在 `_shard_plan` 顶部:绝对化后的整装体(header + 全部候选命中)`_byte_len` ≤ 预算 →
返回 `[]`。判据必须与 `_resolve_units` 的整装短路**同一度量**(候选命中绝对化后的整装字节),
否则「判据说切、物化说整装」或反向漂移。成本:整装体在超预算路径被计算两次(纯内存、每簇一次,
可忽略);不重构签名,`_resolve_units`/`_enumerate_packed` 调用面零变化。效果:收集器返回集与
物化可写集逐簇一致,幽灵 `::shard-0` 消失——这是 D1 的承重前提(否则真复算给每个含候选簇引入
一个永无 marker 的单元,单元口径闸门永假,死锁更彻底)。既有枚举行为不受扰:枚举器 pending[]
 emission 走 `_resolve_units`,幽灵 id 此前仅惰性存在于 done/failed 判定集。

被否方案:在 `collect_canonical_ids` 里过滤 `::shard-0`——按序号特判会误杀真超预算单分片簇
(超预算簇贪心切分可能恰产 1 片),且守卫语义属分片计划本身。

### D3 — `tiers.t1` 单元口径 + 闸门/契约同步

`tiers.t1 = {done, failed, total = len(canonical ids)}`(含分片),闸门 `done + failed < total`。
「全部单元终态 ⟺ 全部簇终态」(整装簇 1 单元;分片簇全片终态),与 scout(batches)/t3(categories)
的「tiers 计可派发单元」口径一致。`resume-state.md` 契约 t1 行同步(原「全部簇 .done 或 .failed」
改「全部 canonical 单元(整簇 + 分片)终态」);stderr 摘要行 `t1:done/total` 语义随之,壳只透传
不解析。兼容披露:无分片 run 的 total 数值不变(整装簇 id 集不变)。

### D4 — manifest 短路提到全部 tier 闸门之前

`init_manifest.json` 在 → 直接 `step=done`(承「manifest 作终态」的既有定位),tier 计数照实
输出但不再驱动 step。消除「完成态 run 因计数口径历史漂移被拉回执行态」的整类波及。被否方案:
维持闸门优先 + 修好口径——任何未来口径缺陷仍会把 done run 拉回重派,终态凭证应一票定局;
`--check` 的既有自洽违例(如 t2 marker 缺)仍在,破损产物照常 fail-loud,不因短路掩盖。

### D5 — t3 前向口径:id 公式由 `list_rule_jobs.py` 导出

`list_rule_jobs.py` 新增纯函数 `rule_unit_ids(categories, fmt) -> [f"{cat}.{fmt}"]` 并在其
marker 路径处改为消费它(逐字节等价);`resume_state.py` 导入,以 inventory categories(既有
`t3_total` 提取逻辑)× `cfg format` 构造 id 集,`forward_done_ids`/`forward_failed_ids` 判定,
孤儿/判定审计(`orphan_markers`/`check_init_markers`)扩到 t3 目录。canonical 8 类 category 均
为 ASCII 小写连字符,`safe_unit_filename` 恒等,与磁盘 `<cat>.<fmt>.json.done` 命名吻合;
若出现非规范 category(id 编码后 ≠ 磁盘名),判定一致性审计会把「判 pending 但 marker 在」暴露为
violation,fail-loud 而非静默。

### D6 — done 步可达性走机制(`_FRAGMENT_STEPS`),非壳配方

`_FRAGMENT_STEPS` 增 `"done"`(+脚本 docstring/注释同步:done 的收尾纪律**有**后续加载),
step=done(含 finalize 分支)→ `stage_flow_files[] = [done.md]`。三面壳 recipe 通用,零改动;
`orchestration-substrate` 规格 MODIFIED 同步。`--check` 新增完成态哨兵残留违例(manifest 在 +
`.active` 在 → exit 2 + 移除 recipe),与既有「进行中缺哨兵」违例构成哨兵生命周期双向闭环。
被否方案:壳写 done.md 固定路径加载 recipe——三面壳各改一处(违反单点机制),且 fresh-run 与
resume 两路径都要照顾;机制入口一处搞定。

### D7 — survey/resolve/t4:头注如实化 + assemble 尾部配方,不派生新 step

survey/resolve 是 optional/non-fatal(规格明文「从不阻塞」),把它们路由进阻塞序列会改变流水线
语义;t4 并入 assemble 分支是既有设计(assemble 无磁盘凭证,拆分需新增 marker + 检查规则 +
stale 清单联动,收益低——assemble_rules 幂等,压缩后重跑即正)。故:survey/resolve/t4 头注改
为如实可达性陈述(编排器决定执行该阶段时 fixed-path Read);`assemble.md` 尾部加一行「进入 T4 前
Read `init-stage/t4.md`」配方(与同文件既有调用行风格一致);t2.md 头部加无条件前置闸门行
(`validate_t1_records --strip-bom` + `--check`,幂等,exit 2 → 按 orchestrator-discipline 的
外科式重派配方处理),堵「resume 直落 t2 跳闸门」。全部是 fragment 正文改动,经 install 分发,
purity/budget lint 复跑。

### D8 — `--invalidate-stale` 三点收口

前置判定复用 `no_scout` falsy ∧ `not scout_complete(init_dir)`(与 `--check` 的 stale-credential
违例同判据,init_tier 单一来源):不满足 → stdout `removed:[]` + stderr 提示 + exit 0(幂等空转,
删零文件);满足 → 既有 dry-run/实删行为,unlink 失败收集后 exit 2(stderr 列失败路径)。
互斥:`--invalidate-stale` 与 `--check`/`--rearm-sentinel` argparse 互斥组(误用 exit 2),
`--dry-run` 仅在前者存在时有效(单独传 `--dry-run` 亦 exit 2,闭集拒歧义)。

### D9 — 契约同步 + 机械化防再漂移

`resume-state.md`:CLI 段补 `--run-root`/`--rearm-sentinel`;stdout 示例补
`discipline_reminders`/`stage_flow_files`/`stale_fanout`(注明 merge 分支恒存在);真值表 t1 行
单元口径 + manifest 短路行;`--check` 清单补「进行中缺哨兵」(实装已有)与「完成态哨兵残留」
(新)两违例 + t3 审计覆盖;`--invalidate-stale` 段按 D8 重写。`step-manifest.md`:Step→IO 表
scout/t1/t2/t3 四行按 `list_steps.py` 实态纠偏(fanout_runner 派发优先、t2 bash、scout
extra_invocations),注记段同步;merge 行不动(去向见 Non-Goals)。防再漂移:
`tests/test_list_steps.py` 新增断言——解析 step-manifest 表的 bash 步 script/kind 与
`list_steps.py` stdout 对应字段一致(评审实证该表曾失同步 7 周横跨 4 次架构演进)。

## Risks / Trade-offs

- [D1 复算依赖 `controls_candidates.json` 与 `clusters.json` 的一致性] → 二者均为原子写产物且
  fold-in 先于 T1 派发;若外因致两文件与已物化分片错位,判定一致性审计(`--check`)把「判
  pending 但 marker 在」升级为 violation + do-not-re-dispatch recipe,fail-loud 而非静默死锁。
- [D2 守卫改变 `collect_canonical_ids` 输出(减幽灵 id)] → 枚举器 pending[]/done 判定本就不经
  幽灵 id(emission 走 `_resolve_units`),行为面零变化;`tests/test_list_clusters.py` 既有断言
  如有逐 id 比对需同步翻转(apply 时先跑定向面确认)。
- [D3 `tiers.t1.total` 语义变化(簇数 → 单元数)] → 无分片 run 数值不变;有分片 run 本就处于
  死锁不可用态,不存在「既有正确消费方」受扰;契约同步披露语义。
- [D6 done 步多加载一个 15 行 fragment] → token 成本可忽略(仅收尾态一次);换取哨兵移除纪律
  可达,消除「run 完成后目标项目被写锁定」这一更贵故障。
- [D7 fragment 措辞属 agent 面,弱模型遵循度] → 均为 recipe 形(「该做什么」),非 prohibition;
  t2 闸门行与 orchestrator-discipline 既有闸门措辞逐字对齐;R5.7 段 A 的完整 A/B 评估对本批
  1-2 行级改动按既有惯例以定向回归 + 实机抽查代替。
- [回滚] → 全部为代码/文档/提示词改动,单 commit revert 即回滚;磁盘产物 schema 零变化
  (不新增/不删除任何 marker 形态),旧 run 无需迁移。

## Migration Plan

1. 先写回归测试(先红):分片死锁三态(全 done / 部分 / 含 failed)、幽灵分片守卫、t3 孤儿不
   抬高、manifest 短路、done 可达 + 哨兵残留违例、invalidate-stale 三点。
2. 实现 D1-D9;定向面测试转绿:`test_resume_state` / `test_list_clusters` / `test_list_steps` /
   `test_list_scout_batches`(口径相邻)/ `test_zero_deps` / `test_no_compile_warnings`。
3. lint:`check_contracts`(resume_state 的 --help 面变化)/ `check_distributed_purity`(fragment
   改动)/ `check_distributed_prompt_budget`(未触壳,应零变化)/ `check_plain_language`。
4. bump VERSION、CHANGELOG;实机抽查一次含分片簇的 fixture run(评审复现脚本同款)确认
   step 收敛。归档时 specs 增量回写主规格。

## Open Questions

(无——`--merge` 出口与预算转发两个真悬置项已显式划归批次 7 / 批次 5,不阻塞本批。)
