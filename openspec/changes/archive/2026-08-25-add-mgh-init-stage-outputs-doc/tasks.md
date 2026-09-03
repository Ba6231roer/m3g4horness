# Tasks: add-mgh-init-stage-outputs-doc

## 1. 前置核对(字段事实来源)

- [x] 1.1 核对 `.mgh-init/` 下真实产物文件清单(以 `core/scripts/*` 产出者为准):`run_config.json`、
  `.active` 哨兵、`controls_candidates.json`、`clusters.json`、`skeleton.json`、`i1_enriched.json`、
  `scout_plan.json`、`checkpoints/scout/*.json`、`scout_candidates.json`、`checkpoints/t1/*.json`、
  `controls_inventory.json`、`checkpoints/t3/*.<fmt>.json`、`init_manifest.json`、`report.md`、
  `fanout_progress.<tier>.json`
- [x] 1.2 逐一确定每个文件的「字段唯一依据」:对应产出者脚本 / `--help` 契约(如 `clusters.json` →
  `discover_controls.py` form_clusters+stdout、T1 记录 → `validate_t1_records.py`+`init-induct.md`,
  inventory → `validate_inventory.py`),无脚本来源的(如 `.active` 哨兵 → `write_runconfig.py` /
  `resume_state.py` rearm)标注其来源

## 2. 撰写 docs/man/mgh-init-artifacts.md

- [x] 2.1 文件头部:受众声明(人类)+ 与 `docs/man/mgh-init.md`(用法)/ `docs/mgh-init-工作流程详解.md`
  (节点流程)的边界说明与互链
- [x] 2.2 控制侧产物章节:`run_config.json`、`.active` 哨兵(wrapper 结构 + 字段表 + 取值)
- [x] 2.3 发现侧产物章节:`controls_candidates.json`(wrapper `{candidates[],source,...}` + 候选字段
  `id/file/line/category/kind/pattern/anchor/snippet/shape/cluster_id/entry_points/big_file/source/confidence`)、
  `clusters.json`(wrapper `{repo,clusters[],truncated}` + 簇字段
  `cluster_id/category/kind/shape/evidence_files/usage_sites/candidate_ids`)、`skeleton.json`
- [x] 2.4 advisory 章节:`i1_enriched.json`(非 T1 输入,缺失不阻断)
- [x] 2.5 scout 章节:`scout_plan.json`、`checkpoints/scout/<batch_id>.json`、`scout_candidates.json`
- [x] 2.6 T1 章节:`checkpoints/t1/<cluster_id>.json`(契约面 `validate_t1_records.py`:根级
  `cluster_id/name/category/kind/evidence/entry_points/confidence` + 无嵌套 `controls[]` 漂移签名;
  含「空 checkpoints/t1 = T1 未开始的正常前置态 + scout 闸门约束」说明)
- [x] 2.7 T2 章节:`controls_inventory.json`(design_controls 兼容;分类 8 枚举)
- [x] 2.8 T3/装配/收尾章节:`checkpoints/t3/*.<fmt>.json`、`init_manifest.json`、`report.md`
- [x] 2.9 运行态披露:`fanout_progress.<tier>.json`(字段 `ts/host/tier/total/done/failed/pending/wave/
  waves_run/wave_done_avg_s/eta_batches/state`,state ∈ running|exited-partial|exited-clean;人读不读、
  agent 不读)
- [x] 2.10 每文件章节含四块:文件作用+wrapper / 字段表 / 枚举取值说明 / 谁消费+缺失影响;
  字段表用表格(R3),不保留长代码块,仅 3–5 行内联结构片段

## 3. 补 docs/glossary.md

- [x] 3.1 增补词条:`centralized` / `distributed`(簇 shape 含义 + 分组键 + 典型例子)、`cluster_id`
  (组成形态 `category::anchor::file::sha` 或 `category::pattern::sha` + 用途)、`wrapper 字典`
  (如 `{repo,clusters[],truncated}` 形态;若缺)

## 4. 自检与人工闸门

- [x] 4.1 校对:文档每个字段与对应产出者脚本逐字段对读,无凭记忆撰写(承 D3)
- [x] 4.2 人类可读性自检:模拟「空 checkpoints/t1 + clusters.json 830 簇」场景,仅凭文档能答出
  「T1 未开始、受 scout 闸门约束、可继续」而不误判
- [x] 4.3 词典自检:文档用到的操作性词(centralized/distributed/cluster_id 等)在 glossary 均有条目
- [x] 4.4 维护者人工闸门:只读人话序 + tasks.md 能复述本 change 在解决什么(字段参考缺失)、改什么
  (新增产物字段参考 + 词典补条)、如何验证(章节与真实产物对应)
