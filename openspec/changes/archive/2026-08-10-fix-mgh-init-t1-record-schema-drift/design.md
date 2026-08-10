# fix-mgh-init-t1-record-schema-drift — 设计

## Context

`fix-mgh-init-scout-stranding` 装上后,scout 候选经 fold-in → clusters → T1 归纳**全部落地**,仍不进
`controls_inventory.json`。磁盘真相(`docs/review-mgh-init-t1-record-schema-drift.md`):部分 T1 子代理
(scout 簇)产出**嵌套 `controls[]`** 记录,违反 `init-induct.md:36-47` 的根级
`evidence[]`/`entry_points[]`/`confidence` 形状;T2 synthesis 按契约字段直取,读嵌套结构取不到 →
**静默丢弃**,scout 类别(含 `authorization`)归零,管线却 step=done。同一事故链里,T1 记录由 LLM 子代理
`Write` 产出、**带 UTF-8 BOM**,正是诱发用户跑破坏性「修 BOM」one-liner(D7 触发)的直接诱因。

现状相关事实(源码/磁盘,非推测):
- T2 边界有 `validate_inventory.py`(R5.9,`mgh-init.md:135` 跑);**T1 边界无对等 validator**——形状仅靠
  `init-induct.md:36-47` 提示词,LLM 漂移即畅通进 T2。
- `init_tier.py`(`fix-mgh-init-scout-stranding` 建立)已是 `INIT_CATEGORIES`/`KIND`/`normalize_category`
  单一真相源,被 `validate_inventory`/`discover_controls`/`merge_scout` 兄弟导入——新 validator 复用之,
  零新依赖、零常量漂移。
- `checkpoints/t1/*.json` 一记录一簇(oversize 簇切 `<cluster_id>::shard-<n>`,仍是单记录同形状);
  每记录有 `.done` marker(`<checkpoint_path>.done`),`.failed` 为终态。
- 对照 `write_runconfig.py::_atomic_write_json` 等确定性脚本写 JSON **无 BOM**;BOM 仅出现在 LLM 子代理
  `Write` 产物——写出编码无确定性约束。

## Goals / Non-Goals

**Goals:**
- D5:T1→T2 边界有确定性形状闸门(`validate_t1_records.py`,镜像 `validate_inventory.py`);嵌套 `controls[]`
  漂移 / 缺字段 / 枚举越界 / category→kind 不匹配 → fail-loud 退出码 2;编排器失效违例簇 `.done` 重派,
  **NEVER 带破损记录进 T2**。
- D6:T1 记录写出编码确定性兜底——`--strip-bom` 无损剥离 UTF-8 BOM(idempotent),编排器 T1 fan-out 后
  **始终**先跑;消除 RFC 8259 不合规 + 消除「修 BOM」动机(D7 触发诱因)。
- 全程零运行时依赖(R2)、双壳字节级对等、契约 lint / 回归测覆盖、命令壳分布纯净(R5.10)。

**Non-Goals:**
- 不修 `init-induct.md` 提示词正文(确定性兜底已够;LLM 侧收敛不在本变更)。
- 不做 T2 容错归一(读嵌套结构再折回根级)——形状漂移在 T1 边界拦,不让破损记录到 T2。
- 不改 `run_config.json`/`init_manifest.json` 磁盘 schema、不新增 tier、不改 step 枚举。
- 不校验 prose 字段(`description`/`usage`/`gaps`/`protects`)——只校验结构承重字段(见 Decisions)。
- D7(opencode hook 绑定漏网)不在本变更——另立 `harden-mgh-opencode-hook-binding`(根因待运行时取证)。

## Decisions

### D1 — 独立 validator `validate_t1_records.py`,镜像 `validate_inventory.py`

新增 `core/scripts/validate_t1_records.py`,逐字镜像 `validate_inventory.py` 的形状(stdout 单 JSON 对象、
stderr 诊断、退出码 0/1/2、兄弟导入 `init_tier`、`sys.path` 自定位、任意 cwd 可跑、零依赖 docstring)。
作用于 T1 边界,与 T2 的 `validate_inventory.py` 对偶。

理由〔单一 chokepoint + 可测 + 与既有 T2 模式对偶 + 承 R5.9 各 stage 产出者暴露 `--check`〕。
替代考虑(否决):
- 折进 `list_clusters` post-materialize——`list_clusters` 是**枚举器**(T1 fan-out **前**跑),不在此后;
  且混入校验职责违背单一用途。
- 扩 `resume_state --check`——`resume_state` 是只读探针(契约「read-only leaf」),已承担 step 仲裁/
  scout 闸门/级联失效多职责;形状校验是不同表面,不并入。
- T2 容错归一(review D5.2 候选)——信任 LLM 消费方归一,不防静默丢弃(失败本就静默于 T2);形状漂移
  应在**最早确定性边界**(T1)拦。

### D2 — 形状违反 = fail-loud 重派;BOM = 无损剥离(不 fail-loud)

关键洞见:**形状漂移与 BOM 性质不同,处理不同**。
- **形状漂移**(嵌套 `controls[]`/缺字段/枚举越界)是**语义可疑**(T2 确实吃不下)→ fail-loud 退出码 2 →
  编排器失效违例簇 `.done` 重派子代理。
- **BOM** 是**纯宿主产物**(LLM 未选 BOM,`Write` 工具/宿主写入;RFC 8259 不合规但无损)→ 无损剥离,不
  re-spawn(re-spawn 一个 LLM 簇去修宿主产物是浪费,且不修编码地基)。

`--check` 模式遇 BOM 时**内存内剥离再解析**(否则 `json.loads("﻿…")` 抛 JSONDecodeError,误判为
形状错),记入 stdout `bom[]` 作 advisory(退出码 0,BOM 非 shape violation);`--strip-bom` 模式做**磁盘**
无损重写。编排器**始终**先 `--strip-bom` 再 `--check`,故 `--check` 实跑时不见 BOM;`bom[]` advisory 仅供
手工直调稳健。

理由〔shape 漂移语义可疑须 fail-loud + BOM 无损且为宿主产物须确定性剥离非重派 + 剥离即消 D7 触发〕。
替代考虑(否决):BOM 也 fail-loud——浪费 LLM re-spawn 修宿主产物,且不建立编码地基。

### D3 — `--strip-bom` 并入同脚本(双模式),非独立 normalizer

`validate_t1_records.py` 默认 `--check`(只读,fail-loud on shape)+ `--strip-bom`(无损 idempotent 重写)
双模式。理由〔review D6.1 明示「D5+D6 合并确定性兜底」+ `merge_scout.py` 既有「mutating main + `--check`」
同脚本先例 + 一个边界一个脚本一个契约一个测〕。替代(否决):独立 `normalize_t1_records.py`——为 3 字节
无损剥离另起脚本过度工程。

### D4 — 编排接线点:step 4(T1 fan-out)→ step 5(T2),镜像 T2 的 validate_inventory

双壳 `mgh-init.md` step 4 末(T1 fan-out 波次完成)与 step 5(T2)之间插两行:
`py …/validate_t1_records.py --strip-bom --checkpoints <target>/.mgh-init/checkpoints/t1` 然后
`--check`(同路径)。`--check` 退出码 2 → recipe:对 stdout `violations[]` 每项,`rm <其 file>.done`,
重跑 `list_clusters` 重派该簇(外科式,仅违例簇,非整波重做)。validator stdout 每项 violation SHALL 含
`file`(绝对 checkpoint 路径)+ `cluster_id`(记录可解析时抽取,供编排器映射回簇)。

理由〔`--strip-bom` 始终跑 = 无条件消 D7 触发 + 接线点与 T2 validate_inventory 对偶 + 外科式重派省 LLM〕。
替代(否决):仅检测到 BOM 才跑 `--strip-bom`——检测本身就是一次读 pass,idempotent 始终跑更简且保证地基。

### D5 — `init_tier` 兄弟导入(单一真相源)

`validate_t1_records.py` `sys.path.insert(0, dir-of-__file__)` 后 `from init_tier import INIT_CATEGORIES,
KIND`(承 R5.3a,与 `validate_inventory` 同款)。category 枚举 / category→kind 映射不在 validator 内复刻,
零常量漂移。

### D6 — 空目录 = ok(非违例);missing 目录 = 退出码 1

`--checkpoints` 目录存在但无 `*.json` → `ok:true, records:0, exit 0`(「T1 是否跑过」是 `resume_state`
职责,非形状 validator);目录缺失 → 退出码 1(误用/路径错,非 shape violation)。与 `validate_inventory`
的「missing → 1 / malformed → 1 / violation → 2」分流一致。

## Risks / Trade-offs

- [validator 过严误伤合法变体 T1 记录] → 只断言**结构承重字段**(`cluster_id`/`name`/`category`/`kind`/
  `evidence`/`entry_points`/`confidence`);prose 字段(`description`/`usage`/`gaps`/`protects`)不断言;
  单测覆盖 `init-induct.md:36-47` 的规范形状。
- [新漂移形状不在 `controls[]` 签名里] → validator 断言**正向契约**(根级必填字段在场 + 合法),任何缺
  必填根字段的形状都 fail;`controls[]` 检查是对**已观测**漂移的 defense-in-depth,非唯一防线。
- [违例簇持续漂移 → re-spawn 死循环] → 既有 `.failed` 终态语义已覆盖(crash ≠ 确认失败;持续漂移由编排器
  标 `.failed` 终态、T2 不带该簇、manifest 披露);validator 不自带重试计数(超范围)。
- [`--strip-bom` 重写受 hook 守卫的文件?] → validator 经 Bash 跑(非 Write/Edit),是 `core/scripts` 叶
  脚本,不触 script-write block;其写出目标 `<target>/.mgh-init/checkpoints/t1/*.json` 在 init 受信子树内,
  即便经 Write 亦过 allowlist。无冲突。
- [`--check` 内存剥 BOM 与磁盘 `--strip-bom` 行为偏离] → 两者共用同一「去前导 EF BB BF」逻辑(抽 helper),
  单测断言 `--check` 对 BOM+合规记录判 ok、`--strip-bom` 磁盘去 BOM,行为对齐。

## Migration Plan

1. 建 `core/scripts/validate_t1_records.py`(`init_tier` 导入 + `--check` + `--strip-bom` + 抽 BOM helper)。
2. `tests/test_validate_t1_records.py`:规范记录过 / 嵌套 `controls[]` 退 2 / 缺 evidence 退 2 / category 越界
   退 2 / kind 越界退 2 / category→kind 不匹配退 2 / BOM+合规 `--check` ok 且报 bom[] / `--strip-bom` 去前导
   BOM 且后字节不变 / 无 BOM 文件 byte-identical / 二次 strip idempotent / 空目录 ok / 缺目录退 1 / stdout
   shape + 退出码分流。
3. 双壳 `mgh-init.md` step 4→5 插 `--strip-bom` → `--check` 两行 + 退出码 2 外科式重派 recipe(承 R5.1 逐字
   镜像、承 R5.10 不引研发编号);`core/prompts/fragments/orchestrator-discipline.md` 补 T1 边界 recipe。
4. `core/contracts/init/` 增 validator I/O 契约(stdout 形状 / 退出码 / `--strip-bom` / `bom[]` advisory)。
5. `tools/check_contracts.py` 断言双壳 `validate_t1_records.py --check`/`--strip-bom` flag 在 `--help`。
6. `tests/test_distributed_md_purity.py` + `test_zero_deps.py` + `test_opencode_hook_parity.py` 照跑不退化;
   `VERSION` bump(承 R5.8)。
7. 手工复现:造嵌套 `controls[]` t1 记录 → `--check` 退 2 + recipe;造 BOM 记录 → `--strip-bom` → 再
   `--check` ok。回滚:任一步回归失败则 revert 该脚本 + 版本回退(strip/check 仅影响本轮 T1 记录,不破坏
   源产物)。

## Open Questions

- validator 是否断言 `protects`/`gaps`/`description`/`usage`?**已决(NO)**:prose 变体大,过严误伤;只校验
  结构承重字段。记此为决策,非 open。
- 违例簇 re-spawn 多少次后转 `.failed`?**留给既有 `.failed` 语义**(crash/确认失败终态),不在本变更加
  计数器——validator 不持有重试状态。
