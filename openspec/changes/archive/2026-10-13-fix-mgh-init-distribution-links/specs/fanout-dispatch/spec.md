# fix-mgh-init-distribution-links — fanout-dispatch delta

## ADDED Requirements

### Requirement: fanout/audit agent definitions mirror their stage prompt's operating contract

每个 fanout / 审计 agent 定义(随 install 分发的 per-host 装载壳)SHALL 与其指向的 stage
提示词在**操作契约**上同形——stage 提示词是行为单一真相源,agent 定义是装载壳,两者漂移即
一面立法一面违法:

① **回传 ack 枚举同形**:agent 定义「回传有界 ack」段枚举的 ack 形态 SHALL 逐字镜像其
stage 提示词 Return-to-orchestrator 段定义的取值闭集(stage 未定义的形态——如 scout 面
Return 段只定义 `ok`/`failed` 而 agent 枚举 `oversize`——SHALL 从 agent 删除该行;dispatcher
侧 `_parse_ack` 的 `oversize` 容错解析不变,stage 后续补定义时 agent 再回填)。理由〔弱模型
按 agent 定义枚举回一个 stage 未定义的 ack,编排器/dispatcher 侧的语义闭环对该形态无立法,
行为不可预期〕。
② **权限钉扎与 stage 授权一致**:agent frontmatter 的工具权限钉扎 SHALL NOT 否定其 stage
提示词明确授权的操作——stage 授权「以 `py` launcher 调 `chunk_sources.py` 切片」的 agent
(如 `init-scout-audit`)SHALL NOT 钉 `bash: deny`;钉扎与授权冲突时,以 stage 授权为准修
钉扎(或收窄 stage 授权),NEVER 两面各执一词。**已知待拍板项**:opencode 约 22 个 agent 钉
`edit: deny` 但职责要求 Write 检查点/规则文件,opencode 官方文档称 `edit` 键覆盖
edit/write/patch——是否真拦须 live 验证(本 change 拍板项 A,不阻塞本批其余面);验证前的
本批修复面仅限「stage 授权与钉扎**已证实**冲突」的 init-scout-audit 对(bash 面冲突,实位
证据:stage L50 授权 py 调 chunk_sources、frontmatter 钉 deny)。
③ **Input 契约完备**:agent 定义「Input (from orchestrator)」段 SHALL 携带其 stage 提示词
行为所需的全部编排器透传字段(如 scout-audit 的切片落点 `slice_dir`——stage 授权
`--out <slice_dir>/…` 而字段缺失时该授权不可执行)。

#### Scenario: fanout agent ack enumeration mirrors the stage Return section

- **WHEN** 审阅 `init-scout-fanout` agent 定义的 ack 枚举与 `init-scout` stage 提示词的
  Return-to-orchestrator 段(后者只定义 `ok <绝对 checkpoint_path> <candidate_count>` 与
  `failed <简短原因>`)
- **THEN** agent 定义的枚举与 stage 闭集一致(`oversize` 行删除);`init-scout.md` 的
  「失败时 touch nothing / crash ≠ 确认失败」语义句在 agent 定义中逐字保留;其余 fanout
  agent 各自与其 stage 同形核对(t1/t2/t3/scout-merge/sdr 同法)

#### Scenario: audit agent's bash pin matches its sanctioned chunk_sources invocation

- **WHEN** 审阅 `init-scout-audit.md`:frontmatter 钉 `bash: deny`,其 stage 提示词明确授权
  「仅 `chunk_sources.py` 且仅当需切片大文件」经 `py` launcher 绝对路径调用
- **THEN** 钉扎改为 `bash: allow`(与 stage 授权一致;该 stage 的其余 NEVER 边界照旧约束
  bash 的使用面),stage 的「其余确定性脚本由编排器调用」收窄句保留

#### Scenario: audit agent Input carries the slice destination

- **WHEN** 审阅 `init-scout-audit.md` 的 Input 段(现仅 `audit_targets[]` + repo 根)
- **THEN** Input 增补编排器透传的 `slice_dir`(切片落点,stage 授权的
  `--out <slice_dir>/<safe-stem>.slice.json` 所需);编排器手派路径的透传清单同步
