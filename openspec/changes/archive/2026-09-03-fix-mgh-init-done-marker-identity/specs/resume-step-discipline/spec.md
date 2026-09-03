# resume-step-discipline Specification [MODIFIED]

## MODIFIED Requirements

### Requirement: 计数口径披露与自洽校验

`resume_state.py` 的 done 口径 SHALL 为「canonical 单元 id 的正向 marker 存在性」——与
`list_clusters.py`/`list_scout_batches.py` 的判定同源(同一编码函数正向计算 marker 路径),
而非裸 glob 文件计数。`--help`/docstring SHALL 注明各消费方口径:
1. `resume_state.py` 的 tier done = canonical id 集上正向判定 done 的单元数(与枚举脚本
   `pending[]` 语义一致:pending 恒可推导为 `total - done - failed`);
2. `ls checkpoints/<tier>/` 目录条目数 = done marker + `.failed` marker + 记录体 `.json`
   + tier 级 merge/audit marker,含孤儿产物 → 与口径 1 可不等;
3. 两数差非数据丢失(口径不同);**孤儿 marker** (不对应任何 canonical id 的磁盘 marker)
   由枚举脚本 stderr 审计告警、由 `resume_state.py --check` 列出(不计入任何 tier 计数,
   fail-soft 提示,不阻断)。

`--check` 自洽校验 SHALL 覆盖:某 canonical 单元同时携带 `.done` 与 `.failed`(歧义终态,
violation);canonical 单元判 pending 但其 marker 文件已存在(判定不一致 = 枚举脚本与磁盘
真相漂移的确定性信号,violation);孤儿 marker(advisory note,非 violation)。
理由〔口径披露是给「人比对文件数与 stdout 数字」的场景;判定不一致从「静默口径差」升级为
「--check 可检 violation」后,身份漂移类缺陷(mgh-init 实测:超长 id 簇 done 判定漂移致
无限重派)在边界即 fail-loud,不再依赖 fan-out 运行时暴露〕。

#### Scenario: 用户比对 stdout 与目录条目数
- **WHEN** 用户比对 stdout `tiers.t1.done` 与 `checkpoints/t1/` 下文件数
- **THEN** `resume_state.py` docstring/--help 注明口径差异:done = canonical id 正向判定,
  目录条目数含孤儿与记录体;两数差非数据丢失

#### Scenario: 判定不一致是 --check violation
- **WHEN** 某 canonical 单元无 `.done`/`.failed` marker(按正向路径计算判 pending),但其
  checkpoint 目录存在编码后与该单元 marker 路径相同的文件(判定与磁盘真相矛盾)
- **THEN** `resume_state.py --check` 退出码 2,violations 列出该单元 id + 磁盘 marker 路径
  + 修复 recipe;stdout `pending` 语义不变

#### Scenario: 孤儿 marker 是 advisory note
- **WHEN** checkpoint 目录存在不对应任何 canonical id 的 `.done`/`.failed` marker
  (遗留 run 产物)
- **THEN** `resume_state.py --check` 将其列入 notes[](advisory),不 violation、不阻断;
  tier 计数不含孤儿
