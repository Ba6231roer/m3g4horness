## Why

T1 归纳记录(`checkpoints/t1/*.json`)**无确定性边界校验**——形状仅由 `init-induct.md:36-47`
提示词约束。LLM 子代理输出漂移时,部分簇产出**嵌套 `controls[]`** 而非根级
`evidence[]`/`entry_points[]`/`confidence`,违反契约形状。T2 synthesis 只消费契约形状记录 →
读到嵌套结构**静默丢弃** → scout 类别(含 `authorization`)从 inventory 消失,管线却报 step=done
(对照 T2 产物有 `validate_inventory.py`,T1 记录无对等 validator)。同一根因下,T1 记录由 LLM 子代理
用 `Write` 产出,**写出编码无确定性约束** → 带 UTF-8 BOM(RFC 8259 不合规),正是诱发破坏性
「修 BOM」操作的直接诱因。两者同源:**LLM 子代理产物形状/编码仅靠提示词、无确定性兜底**。

## What Changes

- **D5 — T1 记录形状确定性 validator**:新增 `core/scripts/validate_t1_records.py`(逐字镜像
  `validate_inventory.py` 的形状/退出码/stdout-stderr 分流),在 T1→T2 边界断言每条
  `checkpoints/t1/*.json`:根级契约字段(`cluster_id`/`name`/`category`∈规范 8 类/`kind`∈vvah 6-enum/
  `evidence`≥1 非空锚点/`entry_points` 列表/`confidence` 数值)+ **无嵌套 `controls[]` 漂移签名**+
  category→kind 归一映射。违反 → stdout `violations[]` + 退出码 2。编排器 T1 fan-out 后、进 T2 前
  MUST 运行之;失败 fail-loud 回退重跑违例簇,**NEVER 带破损记录进 T2**(承 R5.9,补 T1 边界对等
  `validate_inventory.py` 之于 T2)。
- **D6 — 无损确定性 BOM 剥离**:同一脚本的 `--strip-bom` 模式(idempotent、UTF-8 no-BOM 重写)。
  编排器 T1 fan-out 后**始终**先跑 `--strip-bom`(无损、可重复),再跑 `--check`。确定性消除 RFC 8259
  不合规 + 消除「修 BOM」动机(即 D7 触发诱因),**不**靠提示词。
- **编排接线**:双壳 `mgh-init.md` step 4(T1 fan-out)与 step 5(T2)之间插入 `--strip-bom` → `--check`
  两行(逐字镜像 T2 段既有的 `validate_inventory.py` 调用形状);`--check` 退出码 2 → 按 recipe 失效违例簇
  `.done` 重派。新增 validator 的 I/O 契约写进 `core/contracts/init/`。

## Capabilities

### New Capabilities

- `t1-record-schema-gate`:T1 记录的确定性形状 + 写出编码边界闸门——`validate_t1_records.py`
  断言契约形状(根级字段、无嵌套 `controls[]`、category/kind 枚举与归一)+ `--strip-bom` 无损 BOM 剥离
  + 编排器 T1→T2 fail-loud 接线。独立成 spec:它引入**新的确定性不变量**(LLM 子代理产物在 T1 边界
  MUST 过确定性形状/编码校验,违反 fail-loud 而非被 T2 静默丢弃),与既有「T2 边界 validate_inventory」
  对偶、但作用在更早的 T1 边界,治理的是「LLM 输出漂移被下游静默吞掉」这一类静默全损。

### Modified Capabilities

- `control-discovery`:`/mgh-init` 流水线 T1→T2 边界新增确定性闸门——编排器 T1 fan-out 后、进 T2 前
  SHALL 运行 `validate_t1_records.py --strip-bom` 然后 `--check`;`--check` 退出码 2 时 SHALL 失效违例簇
  `.done` 并重派,NEVER 携带破损 T1 记录进 T2 综合。交叉引用 `t1-record-schema-gate`。

## Impact

| 面 | 文件 | 变化 |
|---|---|---|
| 确定性脚本 | `core/scripts/validate_t1_records.py` | **新增**;镜像 `validate_inventory.py`;`--check`(只读,fail-loud 退出码 2)+ `--strip-bom`(无损 idempotent 重写);兄弟导入 `init_tier`(`INIT_CATEGORIES`/`KIND`)单一来源 |
| 命令壳(双端) | `releases/{claude-code/commands,opencode/command}/mgh-init.md` | step 4→5 间插 `--strip-bom` → `--check` 两行 + 退出码 2 处理 recipe(承 R5.1 逐字镜像;承 R5.10 不引研发编号) |
| 契约 | `core/contracts/init/*.md`(新增 validator I/O 契约) | validator stdout/退出码形状 + `--strip-bom` 契约 |
| 编排纪律 | `core/prompts/fragments/orchestrator-discipline.md` | T1 边界 fail-loud recipe 措辞(非 prohibition) |
| 契约 lint | `tools/check_contracts.py` | 断言双壳新 `validate_t1_records.py --check/--strip-bom` flag 存在 |
| 回归测 | `tests/test_validate_t1_records.py`(新增)+ `test_distributed_md_purity.py`/`test_zero_deps.py`/`test_opencode_hook_parity.py` | 形状校验(规范记录过 / 嵌套 controls[] 退 2 / BOM 剥离 idempotent / 缺字段退 2)+ 纯净 + 零依赖 + hook parity 不退化 |
| 版本 | `VERSION` | bump(承 R5.8) |

不引入 pip 依赖(承 R2,仅标准库 `argparse/json/sys/pathlib`);不改 `run_config.json`/
`init_manifest.json` 磁盘 schema;不新增 tier(仍 discover→scout→t1→t2→t3→t4);不改 T1 子代理
提示词正文(确定性兜底已够,LLM 侧收敛不在本变更)。`--check` 失败的影响域 = 违例簇重派,不破坏既有源产物。
