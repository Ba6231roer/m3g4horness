## Why

`/mgh-init` 在大仓上 T1 fan-out 时把 `clusters.json` 的簇数数错(`len(c)`=3,实际
`len(c["clusters"])`=360),进而怀疑可选的 init-survey 没产 `i1_enriched.json` 并陷入
调试。根因是**确定性规约缺口**,每次大仓运行都会复现,不是随机稳定性抖动:

1. `clusters.json` 是 `{repo, clusters[], truncated}` **包装字典**,但 `core/contracts/init/`
   只有 `candidates.md`/`inventory.md`/`manifest.md`,**无 clusters 契约** → agent 只能盲猜
   结构,数到顶层 3 个 key。
2. `discover_controls.py` 已把 `{"clusters": M}` 打到 stdout,但命令壳没告诉编排器以此
   为簇数真相源 → agent 手搓 `py -c "import json..."` 重新推算,违反 R5.2(确定性脚本经
   Bash,禁手搓内省)。
3. `i1_enriched.json` **孤立**:init-survey 产出它,但 T1(`init-induct`)直接读
   `clusters.json`,无任何消费者 → agent 把「没产出」误判为致命错误并偏题调试。

## What Changes

- **新增** `core/contracts/init/clusters.md`:落定 `clusters.json` 包装结构
  (`{repo, clusters[], truncated}`)+ Cluster 记录 schema(`cluster_id`/`category`/`kind`/
  `shape`/`evidence_files[]`/`usage_sites[]`/`candidate_ids[]`,源 `discover_controls.py:409`)。
- **新增** 确定性叶脚本 `core/scripts/list_clusters.py`:读 `clusters.json` + 扫
  `checkpoints/t1/*.done`,stdout 输出权威 T1 工作清单
  `{repo,total,done,pending[],truncated}`;stderr 走进度;退出码 `0/1/2`。零依赖、自包含、
  任意 cwd 可跑(R5.3)。取代编排器一切手搓 JSON 内省。
- **收紧** 双发行壳 `releases/{claude-code/commands,opencode/command}/mgh-init.md`:
  - 步骤 4 fan-out 改为调用 `list_clusters.py` 取 `pending[]`;显式声明 clusters.json 是包装
    字典,**禁止 `len()` 顶层**;簇数真相源 = discover stdout `clusters` 字段 /
    `list_clusters` stdout `total`。
  - 步骤 3 init-survey 标注 **optional + advisory + non-fatal**:产出当前仅作审计/T2 参考,
    非 T1 输入;缺失不阻断;`total` 过大时跳过(单 subagent 装不下整仓簇)。
  - Stage→组件表补 `list_clusters.py` 行;契约引用补 `clusters.md`。
- **回归** `tests/` 增 `list_clusters` 用例(包装解包 / pending·done 切分 / 空 / truncated);
  AST 零依赖扫描 + `tools/check_contracts.py` CLI lint 须含新脚本 flag;按 R5.8 bump 版本号。

## Capabilities

### New Capabilities

_(无。`list_clusters.py` 是 `control-discovery` 内部确定性叶脚本,不构成新对外能力。)_

### Modified Capabilities

- `control-discovery`:簇枚举行为规约化——编排器必须经确定性 `list_clusters.py` 取 T1
  工作清单,不得手搓 `clusters.json` 内省;`clusters.json` 取得正式 I/O 契约;init-survey
  定为 optional/advisory/non-fatal。

## Impact

- **代码**:`core/scripts/list_clusters.py`(新)、`core/contracts/init/clusters.md`(新)。
- **命令壳**:`releases/claude-code/commands/mgh-init.md`、`releases/opencode/command/mgh-init.md`
  (双壳逐字镜像,承 R5.1)。
- **测试/工具**:`tests/`(增用例)、`tools/check_contracts.py`(新脚本 flag 断言)、版本号。
- **依赖**:零新增运行时依赖(承 R2;新脚本仅 `argparse/json/pathlib/sys`,stdlib)。
- **下游**:`/mgh-sra`、`/mgh-blst`、未来 mgh-sast 控制摄入不受影响(消费 `controls_inventory.json`,
  本变更不动 T2 及之后)。
- **非目标**:不把 `i1_enriched.json` 接入 T1(留作 advisory);不引入 tree-sitter 调用链;不改
  cluster 成簇算法。
