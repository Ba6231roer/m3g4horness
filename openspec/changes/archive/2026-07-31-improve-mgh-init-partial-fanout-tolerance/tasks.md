# Tasks — improve-mgh-init-partial-fanout-tolerance

> 依赖顺序:L1 work-list 脚本(最低风险、纯 additive)→ resume_state(gating/`--check`)→ 契约 →
> 双壳编排器 recipe → stage 提示词微调 → 测试 → 版本号 + lint + 回归。每条可独立验收。
> 遵守 AGENTS.md R1–R5(零依赖、文档简练、复用导入、R5.1 CLI lint、R5.8 回归 + bump 版本号)。
> **不动 CLI flag**(`.failed` 经 glob 读、编排器 `Write` 写 `list_*` stdout 透传的 `failed_marker`
> 绝对路径)→ `tools/check_contracts.py` 不受影响。设计决策见 `design.md`(D1–D7 + Q1–Q3)。

## 1. L1 — work-list 脚本(`core/scripts/list_*.py`,纯 additive、R2 零依赖、R5.3 自包含)

- [x] 1.1 `list_clusters.py`:新增 `_failed_ids(checkpoints_dir)`(镜像 `_done_ids`,`glob("*.json.failed")`,
      从 sibling 记录 `unit` 字段读 id、filename-stem 回退);`done` 集旁并 `failed` 集;`pending` 枚举里
      `cid in failed` 亦 `continue`(终态、不重试);`_paths()` 增返 `failed_marker`(`<base>.failed`);
      `_slim_materialized` / `_lite` 增 `failed_marker` 绝对字段(对齐既有 `done_marker`);stdout 增 `failed`
      整数计数;`done_count` 语义不变(仅 `.done`),`failed` 独立披露。stderr 进度行补 `failed=N`。
- [x] 1.2 `list_scout_batches.py`:同 1.1(`_done` 旁并 `_failed`,`*.json.failed` glob,排除 `merge.json.failed`/
      `audit.json.failed` 与既有 `.done` 排除一致;pending 项增 `failed_marker`;stdout 增 `failed`)。
- [x] 1.3 `list_rule_jobs.py`:同 1.1(`_done` 用 `*.<fmt>.json.done` → `_failed` 用 `*.<fmt>.json.failed`;
      pending 项增 `failed_marker` = `<checkpoints>/<cat>.<fmt>.json.failed`;stdout 增 `failed`)。
- [x] 1.4 三脚本 `--help` docstring 同步:`failed` 计数 + `failed_marker` 字段说明(双壳镜像不涉及 flag,
      `tools/check_contracts.py` 应仍绿)。

## 2. `resume_state.py` — gating / tiers.failed / notes / `--check`

- [x] 2.1 tier gating:t1 `t1_done_count < clusters_total` → `(t1_done_count + t1_failed_count)
      < clusters_total`;t3 同(`t3_done_count + t3_failed_count < t3_total`);scout reader
      `_scout_batch_done_count` → `_scout_batch_terminal_count = done + failed`,`scout_done_count <
      scout_total` 改 `terminal < total`。
- [x] 2.2 `tiers{}`:每 tier 增 `failed` 字段(`_count_done` 旁加 `_count_failed`,或合并为 `_count_terminal`
      返 `(done, failed)`);`scout`/`t1`/`t3` 三 tier 的 `failed` 取自 `.failed` marker 计数(discover/t2/t4
      不适用 → `failed: 0`)。
- [x] 2.3 `notes[]`:任一 tier `failed > 0` → 加披露 note(tier名 + failed/total);`failed > total/2` →
      升级为醒目 advisory(D4,非 gate)。
- [x] 2.4 `--check`(R5.9):增「同 id 既有 `.done` 又有 `.failed`」= ambiguous terminal → 追加 violation、
      exit 2(D5);`.failed` 无 sibling 记录 **不** 报违例(失败可不产记录)。
- [x] 2.5 `--help` docstring:`tiers` shape 增 `failed`;`--check` 段补 both-marker 规则。

## 3. 契约同步(`core/contracts/init/`)

- [x] 3.1 `clusters.md` + `cluster-enumeration.md`:pending 项 shape 增 `failed_marker`(绝对,parallel
      `done_marker`);stdout 增 `failed` 计数;`<checkpoint_path>.failed` 终态语义 + crash 无 marker=仍 pending。
- [x] 3.2 `scout-enumeration.md` + `rule-jobs.md`:同 3.1(rule 用 `*.<fmt>.json.failed`)。
- [x] 3.3 `resume-state.md`:`tiers{<tier>}` shape 增 `failed`;step 判定真值表把 t1/t3/scout 的「完成」从
      `done>=total` 改 `done+failed>=total`;`--check` both-marker 规则 + 缺记录不违例。
- [x] 3.4 `manifest.md`:`init_manifest.json` 增 `failures` 字段(per-tier `{done,failed,total}` 形态)+
      `boundaries[]` 披露「fan-out 单元失败、已跳过、终局需人评」;counts 来源 = `resume_state`/`list_*`
      stdout(磁盘真相,非 agent 记忆)。
- [x] 3.5 `unit-inputs.md`:补一句 `.failed` marker = `<checkpoint_path>.failed`(与 `.done` sibling),
      body `{unit,reason,tier}`(advisory);终态、resume 不重试。

## 4. 编排器双壳(`releases/{claude-code/commands,opencode/command}/mgh-init.md`,**逐字镜像**)

- [x] 4.1 fan-out 段(scout reader / T1 induct / T3 rulewriter):on subagent `failed <reason>` ack →
      编排器 `Write` 该单元 `failed_marker`(body `{unit,reason,tier}`,路径取 `list_*` stdout
      `pending[].failed_marker` 逐字、**NEVER** 自拼);**不重试**该单元、**不阻断**,继续当前波次。
- [x] 4.2 Re-entrancy & compaction 段:增「`.failed` = 终态,`--resume` 不重试(区别于 `.done` 的完成)」;
      crash 无 ack → 无 marker → 仍 pending → 重派(区别语义);escape hatch = 人工 `rm` `.failed` 后 `--resume` 重派。
- [x] 4.3 收尾段(tier 跑完 → 进下一步前):若该 tier `failed > 0` → 据 `resume_state.py` stdout
      `tiers[<tier>].failed`(磁盘真相)写 `init_manifest.json::failures` + `boundaries[]` + `report.md`
      披露;**NEVER** 据对话记忆编造计数。
- [x] 4.4 起步/flag 段:`--resume` 说明从「skip units whose `.done` exists」扩为「skip `.done` **and**
      `.failed` units(均终态)」。

## 5. stage 提示词微调(`core/prompts/stages/init-{induct,scout,rulewriter}.md` + 双壳 agent 定义)

- [x] 5.1 三 stage 的 `Return-to-orchestrator` 段:`failed <简短原因>` ack 已在(承 context-resilience);
      补一句「失败时 **touch nothing**(不 touch `done_marker`)、仅回 `failed` ack;编排器记录 `.failed`」
      (D2,澄清 subagent 失败路径无副作用)。
- [x] 5.2 双壳 `releases/{claude-code/agents,opencode/agent}/init-{induct,scout,rulewriter}.md`
      Hard-constraints 段同步该措辞(双端 parity)。

## 6. 回归测试(`tests/`,R5.8)

- [x] 6.1 `test_init_clusters.py`:`.failed` 单元不出现在 `pending[]`;stdout `failed` 计数正确;
      pending 项含 `failed_marker` 绝对路径;`done`+`failed` 均 terminal 不进 pending。
- [x] 6.2 `test_list_scout_batches.py`:scout reader batch `.failed` 同 6.1(排除 `merge/audit` 干扰一致)。
- [x] 6.3 rule-jobs `.failed` 覆盖(若无 `test_list_rule_jobs.py`,在最近的 rule 枚举测试或新建小文件覆盖):
      `*.<fmt>.json.failed` 排除 + `failed_marker` 字段。
- [x] 6.4 `test_resume_state.py`:tier `done+failed>=total` → step 越过该 tier;`tiers[<tier>].failed` 正确;
      `failed>0` 进 `notes[]`;`--check` 对同 id 既有 `.done` 又 `.failed` → exit 2;`.failed` 缺 sibling 记录
      → 不违例;resume 不重派 `.failed` 单元。
- [x] 6.5 `py tests/test_deterministic.py`(及 `test_init_runtime.py`/`test_opencode_hook_parity.py`)不退化。

## 7. 稳定性守卫 + 收尾(R5)

- [x] 7.1 `py tools/check_contracts.py` 通过(本变更不动 CLI flag,双壳 MD `--flag` ↔ `--help` 镜像不退化)。
- [x] 7.2 `py tools/check_distributed_purity.py` 通过(契约/壳/提示词措辞为操作性内容,不引入 dev-only
      溯源 / 研发铁律编号 / 内部 issue 文件指针)。
- [x] 7.3 bump `VERSION`(0.1.15 → 0.1.16)+ `install.sh` 自检 fail-soft 通过。
- [x] 7.4 `openspec validate improve-mgh-init-partial-fanout-tolerance` 绿;端到端 dry sanity(手造一个
      `.failed` marker 跑 `resume_state.py` 验 gating + disclosure 字段)。
