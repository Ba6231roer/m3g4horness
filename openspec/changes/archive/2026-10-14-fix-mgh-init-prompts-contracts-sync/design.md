# fix-mgh-init-prompts-contracts-sync — Design

> 收官批:以对齐实况为主(提示词/契约文档),唯一行为新增 = H11(b) 的 `--merge` 显式拒绝。
> 全部裁决按「规格已钉的语义优先;文档对代码错则改文档;规格对文档错则改代码并回写规格」。

## D1 — H11 选 (b):`--merge` 显式拒绝(对比陈述见 proposal)

**拒绝点位 = `write_runconfig.py`(step 0)**:argparse 保留 `--merge` 声明(可发现性:传之得
针对性 recipe 而非 argparse 泛化的 unrecognized),main 里遇之 → 退出码 2 + stderr recipe
(指认「--merge 无确定性实现;多次分模块运行产物各自独立落盘,跨模块对照人工完成」)。run_config
payload 删 `mode`/`merge_partials_dir` 两字段(不再有第二形态)。**连带清理**(死引用全链):
- resume_state:删 `mode == "merge"` 短路分支(~521-545);步词表去 `merge`(docstring ×2 +
  返回结构);`--check` 的步词表同步。
- list_steps:删 merge 行(~174-176,`merge_inventories.py` 死引用所在)。
- fragment `init-stage/merge.md`:删除;`resume_state._FRAGMENT_STEPS`/stage_flow_files 若点名
  merge 则同步删。
- 三面壳 ×3:flag 表 `--merge <partials-dir>` 行删;frontmatter description 句
  「Supports --scope/--resume/--merge」去 `--merge`;stage 流程清单去 `merge`(--merge 模式) 步;
  正文「`--scope`/`--merge` 回退」类 advice 措辞 → 「`--scope`(多次局部运行产物独立)」。
- 契约:step-manifest.md 词表(2 处)+ merge 行(92)+ merge 注记(101-102 改述保留
  scout-merge 澄清);resume-state.md 词表(58)。
- 规格:delta 8 MODIFIED(生成引擎产出,场景名保留、内容改述)。

**被否的替代 (a)**:实现 `merge_inventories.py`——大工作量 + 无真实诉求背书 + 新增面需闸门/去重/
`--check` 全套;真需求出现时独立立项。(b) 的核心收益 = 把「声明了但走不通」变成「显式拒绝 +
诚实 recipe」,符合全仓 fail-loud 文化。

## D2 — ack 枚举收口(三.15)

Base agent 六面的回传行删 `oversize <绝对路径>`(与批次 4 克隆侧同判:stage Return 段从未定义
oversize ack 的行为——何时 touch marker、是否写产物均未规定,枚举它 = 文档教 agent 发一个无语义
信号)。规格 bounded-ack requirement 同步把 oversize 移出取值枚举(附「枚举器 oversize 标注 +
recipe 处置、dispatcher 容错」的归属说明)。`TestAgentCloneParity` 随 base 面删除转绿。
**不动**:dispatcher `_parse_ack`(历史容错)、T3 枚举器的 `oversize:true` 标注(那是输入侧
处置,与 ack 无关)。

## D3 — 提示词七修(P1-P7)

- **P1 中文化排除**(init-scout.md:136 + init-resolve 同形段):「面向人读的非代码内容用简体中文」
  的对象枚举中删 `evidence_snippet`(它 SHALL 逐字源码行——契约「单行安全子串」的同义强约束;
  翻译代码行破坏证据锚定)。
- **P2 init-induct**:①增加 Form B(pack 形态)指引——unit id = `cluster_id` 行的值在 pack 形态
  为 pack id、按 `members[]` 逐成员处理、检查点/(marker 写 pack 级,member 级 done 跳过),
  与 t1-task.md 模板字段(pack_id/members[])对齐;②输出 schema 段补 canonical 8 类清单
  (input-validation/authentication/authorization/data-masking/crypto/rate-limiting/csrf/
  audit-logging)+ 「自造类名会被闸门拒」一句。
- **P3 init-survey**:第 1 步两文件路径改绝对(与全家族「绝对路径 verbatim」纪律同);读侧白名单
  补列第 1 步要求读的 candidates/clusters 两文件(消互斥)。
- **P4 init-rulewriter**:补读侧三件套段(锚 repo 根 / NEVER 越界 / Bash 搜索同禁)——镜像
  init-survey 的 Sanctioned tools 段形态。
- **P5 init-rules-consistency**:「opencode: every managed block」→「opencode: `<rules-dir>/<cat>.md`
  详述文件」(与 Task-4/预算段同源)。
- **P6 rules-format ×2**:「fails loud on any leak」→ 如实枚举 FORBIDDEN_TOKENS 覆盖面
  (工具内部 token/inventory schema 字段/YAML 围栏/特征过程短语;裸 tier 词与
  category:/source:/evidence: 前缀有意不拦)。
- **P7 init-scout**:删 `regex_known[]` 幽灵输入字段引用(全链路无 producer;「Do not re-report」
  无从执行;regex 已命中文件本就不进 scout 目标集)。

## D4 — 契约九修(C1-C9,以源码为准)

- **C1 clusters.md**:cluster_id 公式改实况——读 `discover_controls.form_clusters` 的真实拼接
  (4 段含 file 槽位;判别尾 sha1 前 12 hex)后改写 25/37 两行; sha8 字样全消。
- **C2 scout-plan.md**:`--scout-batch-bytes`/`--scout-batch-cap` → 真名 `--batch-bytes`/
  `--batch-cap`(plan_scout argparse 实名);补「plan 顶层自描述 batch_bytes/batch_cap,
  --check 优先 plan 记录值」(批次 5 已实现的实况)。
- **C3 candidates.md**:source 枚举删 `regex+scout`(全仓无产出者)。
- **C4 unit-inputs.md**:「done 检测读 unit 字段」→ forward marker 路径判定(批次 5 实况);
  bytes/oversize 语义按 tier 分列(scout = 批声明字节,t1/t3 = 物化文件字节——批次 5 后 t1/t3
  已回填 st_size,scout 保持声明值)。
- **C5 manifest.md**:删「unit record」幻影形状(无产出者);resolve 行注记「subagent 写、
  optional/codegraph-gated、非确定性产出者」。
- **C6 三枚举器契约**(cluster-enumeration/scout-enumeration/rule-jobs):CLI flag 清单补
  `--materialize/--offset/--limit/--orch-budget-bytes/--max-unit-bytes/--include-failed`(各按
  脚本 argparse 实况);stdout 补分页四字段(offset/limit/effective_limit/shrunk);
  `total == done+failed+len(pending)` 恒等式改述(分页/收紧下对 pending 页成立);pack 模式
  补记(cluster-enumeration:`--pack-bytes/--pack-max`/members[]/cluster_total/cluster_done)。
- **C7 resolved.md**:补「additive 并入无确定性出口」披露(resolve 为 optional/codegraph-gated,
  富化实质值依赖 subagent 写回,非机械通道)。
- **C8 step-manifest.md**:词表去 merge;92 行 merge 行删;101-102 注记保留 scout-merge 澄清、
  去「merge 是 --merge 模式专用步骤」句。
- **C9 resume-state.md**:词表去 merge。

## D5 — 笔误与孤儿订正

t2.md `openmode`→`opencode`;controls-context.md `中和`→ 中文措辞(如「缓解」按上下文)。
孤儿 fragment 三件:**保留**(sast-deepdive 分发面引用实存,评审「无加载者」结论不成立)——
交接文档订正记录,零文件改动。

## D6 — 测试与面纪律

- 红绿:merge 拒绝(write_runconfig exit 2 + recipe;run_config 无 mode 字段;resume_state 词表
  无 merge 且对遗留 mode=merge 的旧 run 正常派生;list_steps 无 merge 行);parity 转绿
  (TestAgentCloneParity 现红即红测)。
- 面纪律:壳改动 → 三面镜像 diff + `check_distributed_prompt_budget` + `check_contracts`
  (init 壳参数表对账会断言壳与脚本 --help 并集——壳删 --merge 而 write_runconfig 保留,子集
  方向成立);提示词/契约改动 → `check_distributed_purity`(第 10 类 core/ 前缀盯防)+
  `test_distributed_md_purity`;fragment 删除 → install 自检 inventory 断言核对(不点名
  merge.md 则零影响)。
- 存量噪音:plain_language exit 2 不涉;TestRateLimitStorm 不追查。

## D7 — 批次边界

批次 4 拍板项 A(edit: deny live 验证)与 B(第 10 类基线全家族扫尾)留维护者,本批不动;
交付本批后战役七批全清,交接文档进入「战役完结」态。
