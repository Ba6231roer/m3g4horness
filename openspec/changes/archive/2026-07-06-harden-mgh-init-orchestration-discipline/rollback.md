# Rollback rehearsal — harden-mgh-init-orchestration-discipline

> 回滚演练(§10.5)。改动面清单 + 可逆性确认。无 schema/数据迁移;全部 additive。

## 改动面清单

| 层 | 新增 | 修改 |
|---|---|---|
| `core/scripts/` | `list_scout_batches.py`、`list_rule_jobs.py`、`describe_artifact.py`、`validate_inventory.py` | `plan_scout.py`(`regex_known_count` + `--check`)、`discover_controls.py`(`--check` + stdout `big_files`/`unresolved_count` + `--repo/--out` 可选)、`merge_scout.py`(`--check`) |
| hook | `releases/claude-code/hooks/block_adhoc_scripts.py` | — |
| 构建期工具 | `tools/install_hook.py` | `install.sh`(`--no-enforce-hook`、镜像 `hooks/`、hook 注入、opencode 降级、自检扩面) |
| 命令壳 ×2 | — | `releases/{claude-code/commands,opencode/command}/mgh-init.md`(纪律段、fan-out 三元组、`--check` 步骤、hook 声明、新调用、map 行) |
| stage prompt ×8 | — | `core/prompts/stages/init-*.md`(Sanctioned tools 段;`init-scout`「Use tools freely」→ 受限) |
| agent 壳 ×16 | — | `releases/{claude-code/agents,opencode/agent}/init-*.md`(NEVER `Write .py`/`py -c`) |
| `AGENTS.md` | — | R5.2(三条明线)、R5.3(b)(扇出即脚本枚举)、R5.7(交付物)、新增 R5.9 |
| 契约 | `scout-enumeration.md`、`rule-jobs.md`、`describe.md` | `scout-plan.md`、`candidates.md`(`regex_known_count` 等) |
| 测试 | `test_list_scout_batches`、`test_describe_artifact`、`test_stage_check`、`test_block_adhoc_scripts`、`test_install_hook` | `test_init_runtime`、`test_zero_deps`(扩面) |

## 迁移

**无 schema / 数据迁移**。既有产物磁盘格式不变(`controls_candidates.json` / `clusters.json` /
`controls_inventory.json` / `scout_plan.json` 全 additive:新 stdout 字段、新 `--check`、新脚本、
新 hook)。下游 `/mgh-sra` / `/mgh-blst` / mgh-sast 消费的 `controls_inventory.json` 不变。

## 逐层回退

1. **hook 层(最大侵入面,可独立回退)**:`install.sh --no-enforce-hook` 完全不注入;或对已装仓
   `py tools/install_hook.py --settings <target>/.claude/settings.json --remove` 取出 matcher。回退后
   纪律仍由 L1(壳明线)+ L2(合法原语)+ L4(subagent 白名单)+ L5(AGENTS.md)+ R5.9(边界校验)兜底。
2. **新脚本 / `--check`**:additive;移除仅丢失「合法瞄一眼 / 工作清单 / 边界校验」能力,不破坏既有产物。
   (注:壳已声明 `list_scout_batches`/`list_rule_jobs` 为扇出必经,故脚本与壳须成对回退。)
3. **AGENTS.md R5.x**:仅收紧(加明线 + R5.7 升交付物 + 新增 R5.9),**不放松**任何既有约束;
   回退无回归风险。
4. **整体**:`git revert` 本变更提交即可,双向无数据迁移。

## 验证状态

- §10.1 测试/契约/AST:14 文件 101 测试绿;`check_contracts` 63 flag 0 违例;零依赖 grep 干净 ✓(本机)
- §10.2 双壳 install 自检:claude(opencode 降级 / `--no-enforce-hook` opt-out)脚本就位 + hook 注入幂等 ✓(本机)
- §10.3 合成仓确定性 spine:discover/plan_scout/merge_scout `--check` + validate_inventory 全 exit 0;hook 对 5 条合法叶子调用零误伤 ✓(本机)
- §10.4 真机大仓(Java,opencode):**(待用户真机)** —— 非确定性 LLM 段的残留方差由 hook + prompt 白名单治理,需真机首跑回灌
- §10.5 本文档 ✓
