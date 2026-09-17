# 缺陷分析:mgh-init scout 层产物搁浅(stranded scout output)

> 分析文档,供「分析与设计修复」任务消费。本文只做**根因 / 影响 / 证据 / 候选方向**,不给实现。
> 日期:2026-08-07 · 触发场景:全仓 `/mgh-init` run(scout 开启,`no_scout:false`)

## TL;DR

一次全仓 `/mgh-init` 只产出 input-validation + data-masking 两类规则,疑似漏权限控制。排查确认:**scout reader 跑了 413/415 批(LLM 召回层已工作),但其汇总产物 `scout_candidates.json` 从未生成**,scout 发现全部搁浅在 `checkpoints/scout/` 里、**从未并入 inventory**;pipeline 实质跑成 **regex-only**。T1-T4 却全部 `.done`——即**编排器越过未完成的 scout 层直奔下游**。权限控制(access-control/auth)一直在 scout checkpoint 里,只是没被合并/综合。

- **主缺陷 D1**:tier 顺序仅靠提示词强制,无确定性闸门 → 编排器可越过未完成 scout 跑 T1。
- **次缺陷 D2**:tier 间无数据依赖不变量 → scout 补完后 plain `--resume` 仍跳过 T1-T4,必须手工删 marker。
- **D3**:scout 类别漂移(`access-control`/`auth`),防御位置过晚(T2 validator 才拦)。
- **D4**:无「scout 跑了但贡献 0」一致性检查,搁浅不自报。

## 一、现象与已确认事实(磁盘真相,非推测)

| 项 | 值 | 来源 |
|---|---|---|
| `no_scout` | `false`(scout 开启) | `<target>/.mgh-init/run_config.json` |
| scout readers | 413 done / 5 failed(of 415) | `resume_state.py` tiers |
| `scout_candidates.json`(init-scout-merge 产物) | **缺失** | 文件 + `resume_state step=scout` |
| T1 / T2 / T3 / T4 | 全 `.done`(9/9 · 1/1 · 2/2 · 1/1) | `resume_state.py` tiers |
| `init_manifest.json` | **缺失**(run 未到 step 8) | 文件 |
| inventory 类别 | 仅 input-validation + data-masking | `controls_inventory.json` |
| scout checkpoint 实际内容 | 含 `access-control` / `auth` / `input-validation` 等大量发现 | `rg checkpoints/scout/*.json` |

## 二、缺陷分层

### D1(主)— tier 顺序无确定性强制:编排器越过未完成 scout 直奔 T1

- **现象**:T1-T4 `.done` 而 scout-merge(更早 tier)未完成 → 编排器越过 `init-scout-merge` + `merge_scout.py` fold-in,直接用 discover 的 regex 簇跑了 T1-T4。
- **根因**:tier 顺序当前**仅由命令壳提示词强制**(`mgh-init.md`「NEVER skip to T1 / merge_scout.py」、`resume_state.py:374` 的 note)。`resume_state.py` 能正确**报告** `step=scout`,但**不阻止**编排器越过它跑 T1——无确定性闸门。违 R5.7 哲学(能确定性闭环的不靠 agent 自觉)。
- **影响**:**静默召回全损**。scout 是非 Spring/自研框架控制的唯一召回层(`discover_controls.py:98-104` 的 authorization pattern 几乎全是 Java/Spring 词,跨框架 0 命中),搁浅即归零;且 inventory 看起来「正常」(2 类、有 evidence),用户无从察觉。
- **严重度**:高。

### D2 — tier 间无数据依赖不变量 / 无级联失效

- **现象**:scout 补完后,plain `--resume` 会正确跑 scout-merge + fold-in,但**仍跳过 T1-T4**(它们已 `.done`)→ scout 候选永不被综合;必须**手工删 t2/t3/t4 `.done`** 才能恢复。
- **根因**:`resume_state.py` 把各 tier 当**独立 done 计数**,缺「上游 tier 变更 → 下游 `.done` 失效」的数据依赖。T2 的 `.done` 实为「基于 regex-only 输入」的过期凭证,却被当有效。
- **影响**:恢复非自动;plain `--resume` 给「完成」假象(inventory 不变)。对不熟悉内部者不可发现。
- **严重度**:中高。

### D3 — scout 类别漂移(部分防御,位置过晚)

- **事实**:scout reader 批次产出非规范类名 `access-control` / `auth`(规范 8 类为 `authorization` / `authentication`)。
- **防御现状**:
  - scout 提示词**确实**钉死 8 类(`core/prompts/stages/init-scout.md:55,82`:「category MUST be one of the 8 enums」)→ 靠 prompt,LLM 不遵守即漂移(已发生)。
  - `merge_scout.py::_normalize` **不校验**类名是否规范(只查非空)→ 漂移畅通进 clusters / T1。
  - `validate_inventory.py:84` **才**校验(`category ... not in init 8` → fail-loud 退出码 2)→ 防御在 T2 边界,**最晚**。
- **影响**:要么 T2 被 validator 阻断(恢复卡),要么 T2 综合 LLM 静默丢非规范类 → 又一次静默损失。规范化正确位置应**前移**(init-scout-merge 汇总时 / merge_scout fold-in 时),让 T2 看到干净规范类。
- **严重度**:中(有 fail-loud 兜底,但位置晚 + 依赖 LLM 综合)。
- **待验证**:`init-scout-merge` 汇总时是否归一(若归一,D3 在恢复时不触发;若不归一,恢复会在 T2 报违例)。

### D4 — 可观测性缺口:无「scout 跑了但贡献 0」一致性检查

- **现象**:`controls_candidates.json::provenance.scout_merged`(`merge_scout.py` fold-in 写入)是「scout 实际并入数」信号,但**无检查**把它与「scout 是否开启 / 跑了几批」交叉校验。413 批跑了、`scout_merged` 却缺失 → 明显异常,无人报。
- **影响**:搁浅不自报,靠用户怀疑「结果不全」才发现。
- **严重度**:中。

## 三、pipeline 状态为何不一致(触发链推测)

```
discover ──► scout readers(413/415) ──✕ init-scout-merge 未产 scout_candidates.json
                                          │
                                          └──(编排器越过)──► T1(regex 簇)──► T2 ──► T3 ──► T4
                                                                          └── manifest 未写(step 8 未达)
```

正常顺序应为 discover → scout readers → **init-scout-merge → merge_scout fold-in** → T1 → …。磁盘上 T1-T4 已终态、scout-merge 未完成,只能是编排器在某次推进(很可能某次 `--resume`)越过 scout-merge 直奔 T1。**待查**:`core/prompts/fragments/orchestrator-discipline.md` + `resume_state.py` 步骤仲裁,确认编排器为何越过(是编排器误读 step,还是 resume 仲裁本身给了歧义 next_action)。

推测诱因:run 中断(上下文溢出 / crash / 手动停)于 scout readers 完成、init-scout-merge 之前;续跑时编排器越过该步。

## 四、当前可用恢复路径(workaround,佐证 D2)

手工删下游 marker,再 `--resume` 让 scout-merge + fold-in + 重综合跑通:

```cmd
del "<target>\.mgh-init\checkpoints\t2\*.done"
del "<target>\.mgh-init\checkpoints\t3\*.done"
del "<target>\.mgh-init\checkpoints\t4\*.done"
```
(t1 的 `.done` 保留:regex 簇归纳复用,scout 簇会被新归纳。)然后在 opencode 从目标项目根 `/mgh-init --resume`。

**该 workaround 的手工 marker 删除本身就是 D2 的证据**——确定性 resume 本应自动级联失效下游,而非依赖用户知道删哪个。

## 五、修复方向(候选,留给设计任务,不展开)

- **D1/D2**:确定性 tier gate——`list_clusters.py`(T1 枚举)在 scout 启用且未完成时 refuse / fail-loud;或 `resume_state.py` 检测「上游未完成 + 下游 `.done` 存在」→ **自动级联失效**下游 marker(免手工删)。
- **D3**:类别归一**前移**到 init-scout-merge 汇总或 `merge_scout.py` fold-in(确定性映射表 `access-control→authorization` 等),而非靠 T2 validator 兜底。
- **D4**:`resume_state.py` / `init_manifest.json` 加 scout 一致性 health check(`enabled && batches>0 && scout_merged 缺失/0` → fail-loud / 醒目披露)。

## 六、可复现证据

- `py <target>/.opencode/mgh-core/scripts/resume_state.py --target <target>` → `step=scout`,`next_action=spawn init-scout-merge`,tiers `{discover:1/1, scout:413/415(5 failed), t1:9/9, t2:1/1, t3:2/2, t4:1/1}`。
- `<target>/.mgh-init/scout_candidates.json` 缺失;`controls_candidates.json::provenance.scout_merged` 缺失。
- `rg -o "category[^a-z-]+[a-z-]+" checkpoints/scout/*.json` → 命中 `access-control` / `auth` / `input-validation` 等大量内容。
- `<target>/.mgh-init/controls_inventory.json` 仅 2 类。

## 七、相关文件索引

| 角色 | 文件 |
|---|---|
| tier 顺序提示词(被越过) | `releases/{claude-code/commands,opencode/command}/mgh-init.md`、`core/prompts/fragments/orchestrator-discipline.md` |
| resume 步骤仲裁 | `core/scripts/resume_state.py`(`_scout_complete:333` / `_scout_step:348` / `_foldin_done:135`) |
| scout merge 子代理 | `core/prompts/stages/init-scout-merge.md` |
| fold-in(写 `provenance.scout_merged`) | `core/scripts/merge_scout.py` |
| 类别规范源 + T2 校验 | `core/prompts/stages/init-scout.md:55,82`、`core/scripts/validate_inventory.py:84` |
| authorization regex(Spring 偏置) | `core/scripts/discover_controls.py:98-104` |
| 候选 source 字段 | `core/contracts/init/candidates.md:38-39` |
