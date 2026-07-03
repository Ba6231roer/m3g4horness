## Context

`/mgh-init` 在大仓 T1 fan-out 误数簇数,根因是规约缺口而非随机失败(详见 `proposal.md`)。
当前确定性事实:

- `discover_controls.py:489` 写出的 `clusters.json` 是 `{repo, clusters[], truncated}` **包装字典**
  (顶层 3 key);`clusters[]` 每条由 `form_clusters`(`discover_controls.py:409`)产出,字段
  `cluster_id/category/kind/shape/evidence_files[]/usage_sites[]/candidate_ids[]`(簇级**无**
  `entry_points`——它在 candidate 上,仅 distributed shape 被 set)。
- `discover_controls.py:493` 已把 `{"clusters": M, ...}` 打到 stdout。
- T1(`init-induct`)直接消费 `clusters.json`;`i1_enriched.json`(init-survey 产出)**无任何消费者**(grep 确认)。
- 编排器壳 `mgh-init.md`(claude/opencode 双壳)步骤 4 只写「for each cluster in clusters.json」,
  未声明包装结构、未指定权威计数源。

约束:R2 零运行时依赖;R5.2 编排器=宿主 agent、确定性叶脚本经 Bash、禁手搓 `.py`/禁 Read 源码;
R5.3 叶脚本自包含 + stdout=JSON/stderr=进度 + 退出码 `0/1/2`;R5.1 双壳 flag 逐字镜像且 `--help` 即契约;
R5.8 任一 `.md`/脚本改动 bump 版本号 + 回归。

## Goals / Non-Goals

**Goals:**
- 让编排器**永不手搓** `clusters.json` 内省:簇数与 T1 工作清单由确定性脚本产出。
- 给 `clusters.json` 正式 I/O 契约(包装结构 + Cluster 记录)。
- 把 init-survey 明确为 optional/advisory/non-fatal,缺失不阻断流水线。
- 全程零新增运行时依赖;双壳镜像;回归测 + CLI lint 通过。

**Non-Goals:**
- 不把 `i1_enriched.json` 接入 T1(留 advisory;wiring 列为已考虑但暂缓)。
- 不改 cluster 成簇算法、不动 T2 及之后、不引入 tree-sitter。
- 不改 `clusters.json` 的磁盘结构(纯加契约,不改产出格式)。

## Decisions

### D1 — 新增 `core/contracts/init/clusters.md`(而非仅壳内一行注释)
**选择**:独立契约文件,落包装结构 + Cluster 记录字段表。
**理由**:R5.3 I/O 契约单一真相源;包装字典反直觉(顶层 3 key),仅靠壳内散文 agent 仍会
`len()` 顶层;契约文件供 init-survey/init-induct/subagent 共享索引。
**备选(否决)**:只在 `mgh-init.md` 加一行「注意是包装字典」——不可索引、易随壳改版漂移、
subagent 看不到。

### D2 — 新增确定性叶脚本 `core/scripts/list_clusters.py`(而非仅收紧散文)
**选择**:脚本读 `clusters.json` + 扫 `checkpoints/t1/*.done`,stdout 输出权威工作清单
`{repo,total,done,pending[],truncated}`;`pending[]` 每项
`{cluster_id,category,kind,shape,evidence_files[],candidate_count}`。
**理由**:R5.2——编排器禁手搓内省;叶脚本 `--help` 即契约(R5.1)、stdout 结构化/stderr 进度/
退出码 `0/1/2`(R5.3);同时充当 `--resume` 的 pending·done 闸门(R5.4 廉价计数);cluster 结构
日后漂移由脚本吸收,而非每轮 agent 重新发现。
**备选(否决)**:仅文档化包装结构、信任 agent 手写 `py -c`——正是本次事故根因,且违反 R5.2。

### D3 — init-survey 标 optional/advisory/non-fatal/bounded(而非把 i1_enriched 接入 T1)
**选择**:壳步骤 3 显式声明——产出仅作审计/T2 参考、非 T1 输入;缺失非致命;`total` 过大时跳过。
**理由**:`i1_enriched.json` 当前**孤立**(无消费者);接入 T1 增分支但增益边际(T2 仍做最终裁定)。
标 non-fatal 直接消除本次事故(把「没产出」误判为致命)。
**备选(暂缓)**:T1 读 `i1_enriched.json`(若存在)否则回退 `clusters.json`——行为变更更大,留作后续。

### D4 — `list_clusters.py` 契约镜像既有叶脚本纪律
stdout=结构化 JSON、stderr=诊断/进度**严格分流**;退出码 `0/1/2`;`sys.path.insert(0, dir-of-__file__)`
自定位(utf-8 读入、任意 cwd 可 `py`);零依赖(仅 `argparse/json/pathlib/sys`);幂等只读;
`--help` 列全 flag。与 `discover_controls.py` 及 spec「Standalone script invocation robustness」一致。

## Risks / Trade-offs

- **[list_clusters 读到陈旧 clusters.json]** → discover 已被 `--resume`/`--rebuild-cache` 闸门;
  list_clusters 纯只读,新鲜度归编排器(壳内注明先跑 discover 再跑 list_clusters)。
- **[新增脚本扩大 install 足迹 / CLI lint 面]** → stdlib、小;`tools/check_contracts.py` 增几个 flag
  断言;R5.8 回归(AST 零依赖扫描 + CLI lint + bump 版本)覆盖。
- **[init-survey 降为 advisory 削弱其价值]** → 可接受(本就孤立);壳内显式标注 advisory 角色,
  保留步骤供审计/未来 wiring。
- **[Cluster 记录文档与 init-induct 输入描述的 `entry_points[]` 不符]** → 文档实际形态(簇级无
  entry_points,在 candidate 上);顺带修该 doc drift。

## Migration Plan

- **纯增量**:新增 `clusters.md` 契约 + `list_clusters.py` 脚本 + 双壳措辞收紧;`clusters.json`
  磁盘结构**不变**,既有产物与在跑流水线不受影响,无需数据迁移。
- **回滚**:删脚本/契约 + 还原壳措辞;无副作用。
- **install 同步**:`core/{contracts,scripts}` 经 `install.sh` 镜像到目标 `.claude/mgh-core/`,
  新脚本随之分发;`tools/check_contracts.py` 加入新 flag 断言。

## Open Questions

- **版本号位置**(R5.8 bump):仓库未见顶层 `VERSION`/`install.sh` 内 version 字段(grep 无命中);
  apply 时确认版本载体(疑似 `init_manifest.json` 运行时字段或既有约定),并 bump。
- **是否在 discover stdout 摘要顺带暴露 `pending` 计数**:非必需(list_clusters 已提供);暂不做。
