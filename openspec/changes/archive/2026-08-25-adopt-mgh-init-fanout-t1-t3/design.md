# Design: adopt-mgh-init-fanout-t1-t3

## Context

`add-mgh-init-scout-fanout-runner` + `improve-mgh-init-fanout-longrun-timeout-visibility` 两轮
落地后,scout 层的 dispatcher 形态已真机稳定(见 proposal Why 表——机制清单全部实证)。
`fanout_runner.py` 现状是 **scout 专用**:hard-code `list_scout_batches.py` 调用
(`_list_pending`)、`tier="scout"`(`_write_failed_marker`)、scout 占位符集
(`PLACEHOLDERS`)、scout 模板路径(`_TEMPLATE_REL`)、agent 名 `init-scout-fanout`
(`_spawn_cmd`)、`--scout-plan/--checkpoints/--inputs-dir` 三 flag 即 scout 语义。原 change
design Non-Goals 明确「泛化入口 `--tier` 留接口不实现,后续 change」——本 change 即该后续。

T1/T3 现状派发形态(手派)与 scout 引入 dispatcher 前完全同构:

| | scout | t1 | t3 |
| --- | --- | --- | --- |
| 枚举脚本 | `list_scout_batches.py` | `list_clusters.py` | `list_rule_jobs.py` |
| stdout `repo` 锚 | ✅ | ✅ | ❌(缺,须补) |
| pending 路径字段 | input/checkpoint/done/failed/slice_dir | 同 scout | input/**rule_path**/done/failed |
| subagent | init-scout | init-induct | init-rulewriter |
| 后置闸门 | merge_scout `--check` | `validate_t1_records --check`(T1→T2) | assemble(后续步) |
| 特殊前置 | — | **scout 闸门**(list 退出码 2) | 需 `--format`/`--rules-dir` |

## Goals / Non-Goals

**Goals**

- `fanout_runner.py` 一套脚本三 tier 复用:tier 差异全部收敛进单点映射表,波次循环/ack 状态机/
  超时/sidecar/审计副本零分叉。
- t1/t3 编排器步达成与 scout 同等的 token/稳定性收益(1 次 Bash + 重派,零逐波 LLM 回合;
  任务消息构造固定)。
- 既有 scout 调用面**零变化**(`--tier` 缺省 = scout;三 flag 不改名)——已安装项目的 fragment
  调用行不破。

**Non-Goals**

- 不改 marker/resume/翻页契约与 T1→T2 validate、T3 assemble 等后续步骤语义(闸门留在编排器)。
- 不泛化到 mgh-sra a3 augment、mgh-ut-init(同构但非 mgh-init 域,后续 change);scout-merge
  shard 扇出(聚合节点)不在列。
- 不引入 pip 依赖;不做 dispatcher 内置 oversize 处置(枚举脚本已标 `oversize`,处置纪律在
  fragment)。

## Decisions

### D1: tier 映射表单点(`TIERS` dict),循环体零分叉

```python
TIERS = {
  "scout": {list_script, list_args(fn), template, placeholders, path_fields,
            agent, marker_tier},
  "t1": {...}, "t3": {...},
}
```

- `--tier` 缺省 `scout`;`--scout-plan/--checkpoints/--inputs-dir` 保持 scout 语义;t1 需
  `--clusters`/`--candidates`,t3 需 `--inventory`/`--format`/`--rules-dir`(闭集校验:缺
  必需 flag → 退出码 2)。
- 波次循环、`_fill_template`、`_anchor_check`、`_write_failed_marker`、ack 解析、sidecar、
  审计副本全部从映射表取参,无 per-tier if 分支散落。
- **备选弃**:三份独立 runner 脚本——弃,状态机/超时/sidecar 逻辑三处维护必漂移(scout 两轮
  修的 bug 要打三遍);泛化正是原 change 预留的路径。

### D2: 占位符集按 tier 参数化;T3 用 `rule_path`

scout/t1 共用 `{input_path, checkpoint_path, done_marker, failed_marker, slice_dir, <id>,
chunk_sources_abs, repo, codegraph}`;t3 用 `{input_path, rule_path, done_marker,
failed_marker, category, format, repo}`(无 checkpoint/slice/chunk_sources——rulewriter 直接写
rule 文件,无大文件切片需求)。填充后残留 `{{` 断言与锚树校验逻辑复用,仅字段集参数化
(`PATH_FIELDS` → `path_fields(tier)`)。t3 `rule_path` 双格式(claude `.claude/rules/` /
opencode `docs/security-controls/`)同在 repo 树内,`_in_tree` 单判覆盖,无需 per-format 分支。

### D3: T3 `repo` 锚补齐 = `list_rule_jobs.py` stdout 顶层增 `repo` 字段

取 `--target` 的 `Path.resolve()` 绝对值(与 `list_clusters` 同式),一行改动。既有消费方
(编排器手派)不读该字段,零影响。**理由**:dispatcher 的锚树校验与子进程 cwd 都锚 `repo`;
枚举 stdout 是单一真相源(NEVER 在 dispatcher 里从 flag 重推锚——`--target` 相对值 + 任意
cwd = 盘符根漂移的老失败形状)。

### D4: T1 scout 闸门 = 退出码 2 透传,NEVER 吞成 crash

`list_clusters.py` 的 scout-incomplete-gate 以退出码 2 + stderr recipe 拒识。dispatcher 的
`_list_pending` 现状把 list 非零退出一律 `sys.exit(1)`——对 t1 会把「闸门拒识」(应回退/先做
scout)错报成「通用错」重派空转。改法:`_list_pending` 对退出码 2 透传(`sys.exit(2)` +
原样转发 stderr),退出码 1 保持现状。fragment 侧 t1 派发段注明:退出码 2 → 看 stderr——
宿主 CLI 不可用 → 手派回退;scout-incomplete-gate → 先完成 scout 层(两形态都是「不进
t1 派发」,recipe 已在 stderr)。

### D5: opencode fanout agent 克隆 + claude inline JSON 参数化

- opencode:新增 `.opencode/agent/init-induct-fanout.md` / `init-rulewriter-fanout.md`
  (`mode: primary`,正文 = 既有 init-induct/init-rulewriter 逐字克隆,同 init-scout-fanout
  先例)。**理由**:opencode `run` 拒绝 `mode: subagent` 作 primary 并静默降级(spike 实证),
  克隆是已验证路径。
- claude:`_spawn_cmd` 的 inline JSON 按 tier 参数化(agent 名 + description + tools 白名单
  = induct/rulewriter 各自交互面),无新增落位文件。

### D6: sidecar 按 tier 命名 `fanout_progress.<tier>.json`

scout 由 `fanout_progress.json` 改为 `fanout_progress.scout.json`。**理由**:t1/t3 与 scout
可交错长跑(resume 场景),单文件互相覆盖会让第二终端看到假进度回跳;per-tier 文件天然隔离。
旧名残留无害(运行态披露件,非契约产物,不参与 resume 派生);install 不清理。man page 与
fragment 同步改名。

### D7: t1/t3 fragment 改写模板 = scout.md 已验证结构逐 tier 复制

scout.md 16–27 行的派发段结构(plan → dispatcher 主路径 + 超时接线 + partial 重派 + 退出码 2
回退 + 宿主外直跑 + 手派回退原文)逐字复制到 t1.md/t3.md,仅换枚举脚本调用行与 tier 名。
T1 的 4b validate 闸门、T3 的后续 assemble 引用保持段内原位不动。

### D8: `--resume` 语义不变 + `run_config.json` 零变更

tier 状态全部由磁盘 marker 派生(list 脚本重扫),dispatcher 无新增持久态;`resume_state.py`
步骤图不感知 dispatcher(t1/t3 步的 `next_action` 仍是「跑完该 tier fan-out」)。无 schema
变更,`init_manifest.json` 不动。

## Risks / Trade-offs

- [泛化改坏 scout 稳态(回归风险)] → 既有 21 个 test_fanout_runner 用例全部保持绿(scout
  路径参数化后语义等价);新增 tier 用例参数化覆盖;真机冒烟 scout+t1+t3 各一轮。
- [T3 `--format` 与宿主格式失配(opencode run 上 claude 格式 rule_path)] → dispatcher 透传
  枚举 stdout 的 `format` 进任务消息;格式来源仍是 `run_config.json` 单一真相源,list 脚本
  已按 format 算 `rule_path`,dispatcher 不重算、逐字搬运。
- [T1 簇数百 × 单批分钟级 = 长跑倍增] → 三级超时/软时限/sidecar/宿主外直跑全部随泛化继承,
  无需新机制;冒烟任务在大仓验证 t1 波次推进。
- [sidecar 改名破坏既有使用习惯] → 一次性、文档同步(man page + fragment);旧文件残留无
  害;CHANGELOG 标注。
- [agent 克隆与原定义内容漂移(两处维护)] → 克隆正文 = 原定义逐字 + 仅改
  `mode`/`description` 的 fanout 标注;回归测断言克隆正文与非-fanout 定义正文一致(同
  init-scout-fanout 先例——若已有同形断言则扩展,无则新增)。

## Migration Plan

1. 实现(任务 §1–§4):runner 泛化 → 模板/agent → fragment/契约面 → lint/install。
2. 回归:全量测试 + 契约 lint + 纯净性 lint + 双壳 token lint。
3. 真机冒烟:spike 仓或小目标仓,t1/t3 各双宿主一轮(与手派路径产物等价);大仓由维护者
   复跑验证长跑面。
4. 回滚 = git revert 单 commit;泛化后 scout 调用面不变,已安装项目不受损(重跑 install
   得新模板/agent)。

## Open Questions

(无——泛化路径在首 change design 已预留,机制面无新未知数;t1/t3 特殊面(闸门/format)已
在 D3/D4/D5 定夺。)
