## Context

基础层 change `harden-mgh-bash-path-allowlist` 建立了统一读允许集（target ∪ 哨兵 `read_roots[]` ∪ `<target>/.mgh/read-roots.json`）并把 Bash 面反转为路径允许集判定；配置文件在该层只有**读侧**（守卫每调用读取、手编可用）。本 change 回答「谁写、何时写」：sdr 是唯一的外部只读消费者，授权门必须做在 sdr 侧——launcher 进程内的检索**不经过守卫**，核对只能发生在检索之前。现状：存量设计声明 → `sdr_context.py` 检出 → launcher 自动写入哨兵 `read_roots[]`，隐式授权、每 run 失效。

## Goals / Non-Goals

**Goals:**

- 一次用户拍板 → 项目级持久授权；未配置仓在 launcher/sdr_context 两侧都零读取。
- 配置写入走确定性叶脚本（幂等、原子、审计），编排器只做「问 + 调脚本」，不手拼 JSON。

**Non-Goals:**

- 不动守卫判定与配置 schema（基础层已定）；不做 TTY/配置 UI；不把 `.mgh` 写入收窄为仅脚本可写（后续可选加固）；不改 launcher 退出码语义与 multi-branch 串行语义。

## Decisions

**D1 问询放宿主会话，不放 launcher**
launcher 承 R5.3 禁交互 TTY（人/cron 双入口）；宿主会话是本流程既有的人机交互面（a2 批量澄清问答同款）。launcher 的职责止于「核对 + 跳过 + 披露 `pending_approval[]`」。

**D2 授权核对单点在 launcher/sdr_context 侧（检索前），守卫不承担此职**
守卫只辖 agent 工具面/Bash 面；launcher 进程读外部仓不经守卫。故「未配置 → 不检索」必须内建于检索发起方，两处（sdr_context 与 launcher 各自核对）以同一判定函数语义实现（存在 ∧ 是目录 ∧ 在配置列表中），避免一处核对一处漏。

**D3 独立叶脚本而非 sdr_context 子命令**
`read_roots_config.py` 独立成脚本：配置管理是通用能力（未来其他命令/人工直接用），不背 sdr 的检索上下文；R5.1 契约面单一（`--help` 即契约），R5.3 I/O 契约（stdout JSON / stderr 审计 / 0/1/2 / 幂等 / `--check`）独立可测。

**D4 同意后「重跑 launcher 同参数」而非热继续**
第一轮 launcher 已跳过未配置仓并正常走完准备；配置生效后重跑即完成检索——launcher 本就幂等可续（run 目录 resume 语义），零新增状态机。备选「launcher 挂起等 stdin 批准」违反 D1；备选「编排器进程内替 launcher 补检索」把跨树读挪进宿主会话，正是该架构要避免的。

**D5 哨兵 `read_roots[]` 保留（仅含已配置仓）**
守卫并集语义下冗余但无害；保留的理由：本 run 实际放行根的显式回显（审计）+ 对未升级守卫的旧装项目向后兼容。launcher 不再写入未配置仓（语义反转点）。

**D6 壳预算（R5.6）**
两壳的「外部仓授权」步以最短 recipe 表达（读 `pending_approval` → 问 → `--add` → 重跑 / 拒绝 → 继续+披露）；若壳超 5K tok 上限，把 recipe 细节 shard 进按需 fragment（lazy `Read`），NEVER 硬塞。

## Risks / Trade-offs

- [新项目首跑多一轮问询 + 重跑] → 每仓仅一次；配置可预置（提交 VCS / 模板分发）；重跑走既有 resume 幂等，成本低。
- [编排器不问直接写配置] → 流程纪律（NEVER 未经同意写）+ 脚本 stderr 变更审计留痕；机器闸（`.mgh` 仅脚本可写）列为后续加固。
- [配置条目失效（目录被移走）] → 守卫侧 fail-closed 零授权（基础层语义）；launcher 侧视为未配置 → 重新进 `pending_approval`，自愈路径 = 重新问询或 `--remove` 清理；`read_roots_config.py --check` 使失效显式可见。
- [存量设计声明的路径与配置大小写/分隔符不一致（Windows）] → 核对统一 `Path.resolve()` 后比较，与守卫同款语义，避免 `D:/x` vs `D:\x` 双记。

## Migration Plan

无破坏迁移：未配置 = 未授权 = 既有「声明不可达」同款降级，报告如实披露。已装项目升级顺序 = 基础层先落地（守卫认配置）→ 本 change（流程写配置）。回滚 = revert 两 change 各自文件集，配置文件残留无害（无人读即零效果）。

## Open Questions

无。
