## Context

工具面（Write/Edit/MultiEdit/NotebookEdit/ApplyPatch/Read/Glob/Grep）已是允许集模型：写 = target 树（init/ut-init 另交受信子树正向清单 ∪ `out_roots[]`），读 = target ∪ 哨兵 `read_roots[]`。Bash 面是唯一的黑名单残留：五张动词枚举表触发路径判定，表外动词漏（proposal「Why」列了可复演形状）。约束：守卫 = 单文件 Python twin（claude/opencode 字节级 parity、stdlib-only、每调用无状态、非激活早退零开销）；opencode `.ts` shim 是纯胶水（`bash` 事件已在 HANDLED，本 change 不动 shim/matcher）。

## Goals / Non-Goals

**Goals:**

- Bash 面获得与动词无关的 fail-closed 路径净网：表外动词携带树外路径从「放行」变「拦 + 可解释 recipe」。
- 读允许集单一化：工具面与 Bash 面同集（target ∪ 哨兵 `read_roots[]` ∪ 项目配置 `read_roots[]`）。
- 外部只读目录获得用户可持久编辑的项目级载体（`.mgh/read-roots.json`），为 sdr 审批流 change 预留确定性写入口。

**Non-Goals:**

- 不做 shell 解析器（别名/变量间接不在覆盖承诺内，与既有全部 Bash 规则同立场）。
- 不动行为纪律规则（`py -c` 内省 token 表、temp 模式、聚合文件名清单）与其 recipe。
- 不给 sast/sra/srr/sdr 写侧升受信子树清单；不动 init/ut-init 既有受信子树集（`.mgh` 不入 init/ut-init 允许集）。
- 不实现 sdr 审批流与配置写脚本（下游 change `add-mgh-sdr-read-root-config`）。

## Decisions

**D1 读允许集三源并集，工具面与 Bash 面同集（推翻「`read_roots[]` 不及 Bash 面」）**
备选「Bash 面仅 target」被否：需要维护两套读规则；且工具面本就可读已声明根，Bash `rg` 同一文件被拦没有安全增益、只有解释成本。反转的前提恰是本 change 的 D3——Bash 面改为直接判路径，不再依赖动词识别，于是「凡允许读的目录，用什么工具读都放行」成为一句话模型。写侧判定集**不变**（target-only），这是读/写不对称的刻意的。

**D2 判定位置：挂在 Bash 分支规则链末尾**
顺序 = 既有链（missing-install → `py -c` 写形 relabel → `py -c` 内省 → temp-I/O → 聚合整读 → file-assoc → file-search → listing → interpreter-exec → redirect）之后追加 catch-all。理由：变异规则先行保证写/删命中浮出**专属 recipe**（含 init/ut-init P1 树内污染判定）；catch-all 兜的是前面全部规则都不认得的形状，只报「路径不在允许集」的通用 recipe。

**D3 token 提取与判定算法（regex-over-string，非 shell 解析）**
对整条命令字符串单遍扫描，复用现有 `_ABS_PATH_TOKEN_RX` 形状并扩三类：`..` 引导相对 token（对守卫 cwd resolve）、`~/` 引导 token（expanduser 后 resolve；裸 `~` 不判）、引号剥离。后置排除含 `://` 的 token（URL scheme，防 `https://…` 的 `s:/…` 片段误判）。逐 token `Path.resolve()` 后对允许集做 `is_relative_to` 包含判定，任一 token 全集外 → 命中。备选「shlex/tokenize 级解析」被否：PowerShell 语法（win32 opencode 全部 Bash 走 `powershell -Command`）无 stdlib 解析器，且与既有规则的可解释性立场不一致。

**D4 配置文件 `<target>/.mgh/read-roots.json`，守卫每调用读取**
备选：`.mgh-sdr/read-roots.json`（否：守卫域中立，sast/sra/srr 未来同样可声明；且 run 目录是运行期产物目录，持久用户配置不应混入）、`.claude/` 或 `.opencode/` 下（否：双宿主不对称，配置必须宿主中立）、env（否：无可编辑持久载体、跨会话不稳）。语义：缺文件 = 零变化；坏 JSON/错型 = 该文件零授权且不影响其他判定（与哨兵「坏 = 视为缺席」同形的容错，但配置坏**不降级激活**——它只做加法不做激活）；条目沿用 `_in_read_root` 同款 fail-closed 包含判定（存在 ∧ 是目录才生效）。守卫非激活早退在先，配置读取只发生在已激活会话，每调用一次 ≤1 JSON 读 + ≤N 次 resolve，量级与既有哨兵读取相同。

**D5 严格度预算：接受的新拦截（原放行 → 现拦）**
① `> /tmp/x` 单写无回读；② `--flag=<树外绝对路径>` 取值；③ `git -C <树外>`；④ 无害提及树外路径（`echo D:\out`）。裁决：全部接受——mgh 会话提及树外路径本身即可疑，recipe 列出允许根自解释；与「未钉 target 才降级」的既有原则不冲突（钉了 target 就有明确的允许边界）。误伤救济 = 把确需只读的根写进配置（用户动作），或非运行会话（守卫不激活）。

**D6 残余边界（显式披露，与 spec 诚实边界同风格）**
① 未知写动词把数据写进**已声明只读根**：token 在读允许集内被放行、变异规则又不认得该动词 → 漏。影响面 = 用户/流程已确认可读的外部树；sdr 审批流 change 落地后声明根全部经用户拍板，风险受控。② 别名/变量间接（`$p='D:\out'; cp x $p`）提取不到裸路径 → 漏（Non-Goal 同款立场）。③ 纯内建无路径命令的行为纪律（如 temp 中介变体）不在本 change 范畴。

**D7 双端 parity 与接线面零改动**
无新工具名 → matcher/HANDLED 不动；twin 文件字节级镜像 + 既有 `tests/test_opencode_hook_parity.py` 守护。备选「opencode 侧独立实现」被否：违反单一判定来源。

## Risks / Trade-offs

- [误伤合法命令（树外提及类）] → recipe 列允许根 + 配置文件救济（D5）；诚实边界披露剩余形状。
- [配置被 agent 未经用户同意自写] → init/ut-init 写允许集**不含** `.mgh`（天然拦）；sast/sra/srr/sdr 域 in-tree 可写 → 由下游 change 的流程纪律治理（用户拍板后经确定性脚本写 + stderr 打印变更），本 change 不加机器闸。
- [regex 提取漏 token（变量间接等）] → 与既有 Bash 规则同立场；动词精化层仍在，catch-all 是网不是解析器（D6②）。
- [配置手写出错] → fail-closed（D4）；下游 change 提供确定性写脚本 + `--check` 后消失。

## Migration Plan

无 schema/数据迁移：配置缺省 = 行为不变；已装项目重跑 `install.sh` 镜像 twin 即升级。回滚 = revert 单文件对（twin 同步 revert）。

## Open Questions

无。已核实潜在冲突：telemetry seam 落盘路径为 `.mgh-receipts/`，与 `.mgh/` 不冲突。
