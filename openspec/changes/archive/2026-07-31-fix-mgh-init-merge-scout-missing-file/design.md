## Context

`merge_scout.py::_normalize` 把 scout candidate 子集补齐到 `form_clusters` 期望的完整 Candidate
shape。当前 `category` 字段已是容错模式(`.get` + 缺字段 `return None`,由调用方 skip + 向 stderr
打 warn),而 `file` 是函数内**唯一残留的直索引**(`c["file"]`)——缺 `file` 即抛 `KeyError: "file"`
中止整次 merge。正常流程下 `merge_scout.py --check` 已挡缺字段候选(退出码 2 回退重跑);本设计补
**归一路径侧**的 defense-in-depth:即便 `--check` 被绕行(编排器上下文压力下跳过 merge 闸门、或
畸形 `scout_candidates.json`),脚本也不该以原始 `KeyError` 崩。

## Goals / Non-Goals

**Goals:**
- `file` 对齐 `category` 的容错范式(缺字段 → `return None` → 调用方 skip + warn)。
- skip 的 warn 如实指出**缺哪个**必填字段(`category` / `file` / 两者)。
- 确认 `_normalize` 内无其它直索引必填字段残留。

**Non-Goals:**
- 不改 `merge_scout.py --check` 行为(它已正确挡缺 `file`/`category`,退出码 2)。
- 不为缺字段**补造**值(`file` 是下游 cluster id 派生与 evidence 锚点的依据,捏造会污染身份;缺即 skip)。
- 不改 `merge_scout.py` 的 CLI I/O 契约(stdout JSON / stderr 诊断 / 退出码 `0|1|2` 全不变)。
- 不治「`--check` 被绕行」的根因(那是编排纪律 / 上下文韧性范畴,本仓 `harden-mgh-init-context-resilience`
  已覆盖磁盘化 resume;本变更只补脚本侧鲁棒性)。

## Decisions

**D1 — 缺 `file` 复用 `category` 的同一 `None`-return 守卫**(而非新增独立分支)。**
合并为 `if not c.get("category") or not c.get("file"): return None`。
- *Why*:`category` 与 `file` 在归一语义上同构——都是下游必需、都不可补造、都应 skip + warn;合并守卫 =
  单点真相、零分支膨胀。
- *Alt*:单独 `if not c.get("file"): return None` 分支 → 重复模式且 warn 措辞需两处维护;否决。

**D2 — warn 措辞泛化为「missing required field (<which>)」**,据实际缺失字段填 `category` / `file` / `both`。**
- *Why*:如实披露缺哪个字段 > 笼统报 "missing category";调用方 warn 已带 candidate `index` 与可得
  `file:line` 定位,泛化后定位信息不丢。
- *Alt*:保留原措辞仅加 file 分支 → 缺 `file` 却报 "missing category",误导排查;否决。

**D3 — `file` 取值由 `c["file"]` 改 `c.get("file")`**(守卫已保证非空,取值等价但形式统一)。**
- *Why*:函数内其余字段已全 `.get`;消除「唯一直索引」这一特殊点,风格一致,顺手防回归。

## Risks / Trade-offs

- **[Risk] 缺 `file` 的 candidate 被 drop 而未被察觉 → 静默数据丢失。**
  Mitigation:stderr warn(含 index + 可得 `file:line` 定位)+ 正常流程的 `--check` 闸门先挡;warn 非 silent,
  且 merge 末尾既有 `scout_merged` 计数可对账。
- **[Risk] 容错掩盖「`--check` 被绕行」这一更深的编排问题。**
  Mitigation:本变更**不**假装绕行正常——warn 文案如实披露字段缺失;绕行根因由 context-resilience 的磁盘化
  resume 与编排纪律治,不在本变更范围(见 Non-Goals)。

## Migration Plan

单脚本改动,无数据 / 契约迁移。`install.sh` 镜像 `core/scripts/merge_scout.py` 到目标项目的
`.claude/mgh-core/scripts/` 与 opencode 对应位置即生效。回滚 = 还原 `_normalize` 中 `file` 行为直索引。

## Open Questions

无。
