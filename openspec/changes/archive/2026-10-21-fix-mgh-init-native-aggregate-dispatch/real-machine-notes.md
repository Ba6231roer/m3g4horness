# 实机笔记 — mgh-init 聚合四层 opencode 缺省原生派发(2026-10-21,本机)

本文件记录本 change 的本机闸门结果(任务 5.1–5.4)、过程发现的宿主/环境事实,以及企业内网
2.0.32 的交接清单(5.5,不阻塞归档)。任务编号对应 `tasks.md` 第 5 节。

## 环境

| 项 | 值 |
|---|---|
| 宿主 OS | Windows 10.0.26200(Git Bash;opencode shell 工具 = PowerShell) |
| opencode | 2.1.0(npm 全局安装,PATH 首位;前次笔记的 `%LOCALAPPDATA%\opencode2\opencode` 已不在,以 `opencode --version` 为准) |
| Python | 3.14.6(`python`;维护者 Git Bash 的 `py` 是 Store 占位——闸门用了 `/tmp` 垫片,真会话内模型自适应改用裸 `python`,见 §5) |
| 闸门仓 A(5.1 全链真会话) | `C:\DEV\_mgh_agg_gate_e2e`:3 个控制特征 Java 文件(2 候选/2 簇),`install.sh --opencode` 真装,无画像(`--no-scout --skip-consistency` 起跑,parked at t1) |
| 闸门仓 B(5.2 中规模通道 B) | `C:\DEV/_mgh_agg_gate_med`:120 个中性 Validator 文件(120 簇),真装 + 无画像;pack `--pack-bytes 16384 --pack-max 8` |
| 闸门仓 C(5.3 故障面) | `C:\DEV\_mgh_agg_gate_fault`(单簇失败注入)+ `C:\DEV\_mgh_agg_gate_sm`(scout-merge 8 分片超预算夹具)+ med 仓(中断续跑、越树写) |
| 规模对照夹具(5.2 对照腿) | `C:\DEV\_mgh_agg_gate_scale`:5 类 × 120 文件 = 240 簇,确定性页循环(无 LLM) |

## 1. 小仓全链原生 smoke(任务 5.1;闸门仓 A,两次真会话)

第一会话:t1 原生通道 B 一次 `mgh_dispatch` 调用 2 单元 1 波全 done(磁盘 2 `.done` 零
`.failed`),重物化 `units_total==0` 收敛,T1→T2 形状闸门过,t2 闸门 `needs_reduce=false`
(3291B ≤ 98304B)→ **零派发**(物化器不产计划、stdout note 即信号)→ 单上下文
`init-synthesis` spawn 时**撞宿主 5 小时用量限额中断**(见 §5 限额事实)。

第二会话(resume,额度重置后):`resume_state.py` 从磁盘重派生 `step=t2`、t1 2/2 零重做 →
t2 单上下文完成(2 controls,`synthesis.json.done` + `validate_inventory` 0 violations)→
t3 原生物化(`native_plan_t3.json`,2 单元 1 波)+ `--check` 过 → 通道 B 一次调用 2/2 done
→ 重物化 `units_total==0` → `assemble_rules.py` 写 AGENTS.md 惰性索引块 + 2 个详述文件,
`--check` 0 violations。**全链四层产物与子进程形态同构**(同一校验器把关)。

关键证据:
- 计划文件按 tier 命名实测:`native_plan_t1.json` / `native_plan_t3.json` 各归各层,
  scout 既有 `native_plan.json` 未被触碰(仓内无 scout run)。
- t2 零派发实证:闸门 `needs_reduce=false` 后编排器**没有**调物化器产计划
  (`.mgh-init/` 无 `native_plan_t2.json`),直接单上下文 subagent——「装得下不派」在
  真会话保持。
- 看门狗:第一会话拉起(pid 54804),t1 落定后 `exit_reason: settled` **自退**;第二会话按
  fragment §0 用裸 `python` + PowerShell `Start-Process -PassThru` 重拉(pid 59920)。
- 通道 B 摘要与磁盘对账:工具摘要 done/failed/no-marker 计数与 `checkpoints/t1|t3/` 标记
  逐一相符;编排器回复零文件内容(有界 ack 纪律)。

## 2. 中规模 t1 走派发工具 + pack(任务 5.2;闸门仓 B + 规模对照夹具)

- **真会话腿(闸门仓 B)**:120 簇 → pack 后页 1 = 11 包(4 波);通道 B 一次调用跑完,
  摘要 `10 done, 1 no-marker`(`t1-zggd`,工具内零重派)→ 重物化即重枚举回待派(自愈);
  页 2 = 2 包(同 `no-marker` 形态)→ 再重物化 `units_total==0` 收敛;磁盘真相
  **120/120 成员 `.done`、0 `.failed`**。编排器回合数 = 页数 + 少量管理回合,**不随
  120 簇线性涨**。看门狗整场驻留(§0 拉起,流水线继续不收)。
- **真会话腿暴露的共享面错位(如实记录,非本 change 回归)**:页 1 有 2/11 个 pack 会话
  违共享任务模板(Form B 明示成员记录写成员路径、包级 checkpoint 仅占位)写了 2 个
  pack 级账本 JSON → 既有 `validate_t1_records`(glob `*.json`)把账本误读为记录,
  报 13 violations;移除 2 个账本后闸门绿(85 记录 0 违例)。该错位在子进程形态的同一
  模板下同等存在,两形态失败终态等价;记 hardening 候选(validator 忽略 pack 账本形状 /
  模板强化包级占位说明)。另一处 35 簇「marker 有、记录无」是**本闸门预置污染**(§3 ③
  腿的 touch-only 合法终态形态,validator 按设计不报),非运行产物缺口。
- **确定性对照腿(240 簇夹具,无 LLM)**:pack 打包 → 30 包单元、3 页
  (页单元序列 `[12, 11, 7, 0]`,页尾补位语义可见)→ **通道 B = 3 次工具调用**;
  通道 A 等价 ~10 波次回合;不打包子进程对照 = 240 单元 = 80 回合。
  即聚合规模在通道 B 下被压平为「页数」,不再是编排器回合的放大器。

## 3. 故障面(任务 5.3;①②④ 确定性腿 + ③ 真会话腿,四项全过)

- **① 单元失败 → 至多一轮重派 → 缺口披露**(闸门仓 C,确定性):`.failed`(429 特征)
  在场时无 `--retry-failed` 重物化 `units_total=0`(失败 = 终态不回 pending);装 opencode
  面后 `resume_state` 给 `failed=1` + 「AT MOST ONE more」+「quota window」两条原生 note
  (t1 专属行);重派轮 = 删旧 `.failed` + `--retry-failed` → 恰好 1 单元、短号跨轮稳定
  (`t1-a43k`);再败 → 接受缺口(终态),`resume_state` 仍推进且 failures 披露面可读。
- **② scout-merge 缺 shard 不 rollup**(sm 仓,确定性):8 分片超预算夹具,7 done +
  1 自写 `.failed` → 重列 `pending=0`(失败分片终态出局)→ **无 rollup**(缺该分片摘要 =
  静默丢候选,缺口由 fragment/boundaries 承载披露);rollup manifest 消费面
  (`rollup_manifest.json` 路径先行)在 gate stdout 原样可见。
- **③ 中断续跑已完成零重做**(med 仓,真会话 + 确定性双证):会话 A 限额中断后 resume
  会话 t1 2/2 零重做直接进 t2(§1);确定性腿完成 5/12 包(成员级 marker)后重物化
  `units_total=11`(页补位),已完成包不回 pending,同 `unit_id` 跨轮短号不变,
  `resume_state` 报 t1 done=35/120 + 原生派发相位。
- **④ rulewriter 越树写被守卫拦**(med 仓,真会话):真 spawn `init-rulewriter-native`
  令其写 `D:\_mgh_oott_test\probe.md` → 守卫退出码 2 逐字拒绝
  (「blocked: Write/Edit outside the sanctioned init subtrees…」+ 完整 recipe),子代理
  不重试、文件未落地、宿主自证无该路径——**唯一带写权限的孪生被既有写侧约束收口**。

## 4. 回退与形态抽查(任务 5.4;med 仓/claude 真装)

| # | 形态 | 结果 |
|---|---|---|
| ① | opencode 无画像 `list_steps --step t1` | `dispatch.form=native, source=host-default`;t1 步 = `emit_native_plan.py` + arc `[materialize, dispatch, gate]`;`aggregate_agents` 四层齐 |
| ② | 画像显式 `runner` | 无 `dispatch` 字段;t1 步 = `fanout_runner.py`,无 `native_arc`;resume 同(子进程 next_action 逐字) |
| ②b | 画像显式 `native`(opencode) | `form=native, source=profile` |
| ③ | claude 面真装(dsh 布局同构) | 无 `dispatch`,t1 步 = 子进程(与画像无关) |
| ④ | claude 面 + 画像显式 `native` | **退出码 2** + recipe「only on the opencode face」 |
| ⑤ | 删聚合孪生 `init-induct-native.md`(解析 native) | **退出码 2** + recipe 指名缺该文件;还原后恢复 native;资产门按 init surface 查 7 资产 |

企业如需暂时回退:项目画像写 `{"dispatch_mode":"runner"}`(零代码改动,整条流水线回子进程,
产物互通)。

## 5. 环境事实(过程中发现,已记录)

- **维护者 Git Bash 的 `py` 是 Store 占位**,而 PowerShell(opencode shell 工具)里连
  `/tmp` 垫片都不可见(路径解析不同)——真会话内模型按 fragment 的解释器探测自适应改用
  PATH 裸 `python`,全链无阻。分发壳 step 0 的既有探测(py/python/python3)覆盖此形态。
- **5 小时用量限额中断是 resume 路径的真实验证场景**:中断发生在 t2 单上下文 subagent
  spawn 中途,磁盘零脏产物(t1 标记齐、无半写 inventory),resume 从 `step=t2` 干净接上。
- 看门狗在 `opencode run` 直跑形态仍无 `OPENCODE_SESSION_ID` 注入(承前一 change 笔记),
  以 `--root` 缺省阈值运行、落定自退;真 TUI/服务形态不受此限。
- pack 页补位语义实测:5 包出局后页尾补位(12→11),`units_total` 恒为页级数。

## 6. 企业内网 2.0.32 交接清单(任务 5.5;不阻塞归档,循前例保持未勾)

前置:目标机 `install.sh --opencode <仓>`(自检 ✓ 行须含五只 `init-*-native` 孪生与
`init-aggregate-native-dispatch.md` fragment);opencode 2.0.32 在 PATH(注意 1.x 同名
二进制前置覆盖);`python`/`py` 任一可用。

1. **解析**:任意项目根 `python .opencode/mgh-core/scripts/env_profile.py --target <abs>
   --consumer init` → 预期 `form=native, source=host-default, host_face=opencode`;
   `--consumer generic` → `runner`。
2. **步骤清单**:`list_steps.py --target <abs> --step t1` → `dispatch.form=native` +
   `emit_native_plan.py` 入口 + arc `[materialize, dispatch, gate]` + `aggregate_agents`;
   `resume_state.py --target <abs>` → 顶层 `dispatch`(含 `aggregate_plan_present`)。
3. **真会话小链**:`/mgh-init --no-scout` 至 t1,预期看门狗先行 → 物化
   `native_plan_t1.json` → 一次 `mgh_dispatch` 调用跑完本页波次 → 重物化 `units_total==0`
   → 形状闸门;t2 小仓预期 `needs_reduce=false` 零派发单上下文。
4. **回退抽查**:画像 `{"dispatch_mode":"runner"}` → 四层全回 `fanout_runner.py` 行、
   无 `dispatch` 字段。
5. **差异回填**:2.0.32 的插件加载面(`mgh_dispatch` 工具注册 + 令牌展开钩子)、
   `tool.execute.before` 双插件并存、权限闸门对聚合孪生 spawn 的行为,回填
   `core/contracts/fanout/runtime.md` 版本矩阵与本文件。
