# Tasks — fix-mgh-sdr-docs-shell-alignment

> 主面 = 分发面文档(三面镜像纪律:改任一面 MUST 同查另两面)+ launcher/describe 健壮性。
> **建议最后执行**(其余四个代码面修复 change 落地后,披露一次对齐到位)。
> 改任一分发面文档后必跑:`check_contracts` + `check_distributed_prompt_budget` +
> `check_distributed_purity`。

## 1. M6 + L3 — 敏感目录物化与路径透传

- [x] 1.1 `sdr_context.py`:解析后目录对象物化为 `<run-dir>/sensitive_catalog.json`(与 context.json 同步、确定性单遍)
- [x] 1.2 `core/prompts/fragments/fanout/sdr-task.md`:三元组新增该文件只读路径(fanout_runner 占位符集零改动)
- [x] 1.3 `mgh_sdr_launch.py` `_build_prompt`:删除目录对象内嵌与 `[:4000]` 截断,改路径指认;launcher 措辞同步
- [x] 1.4 三面 agent 定义与 launcher 相关措辞同步;回归:run 产物含物化文件、任务消息含路径(修复前:六维拿不到目录且无披露)

## 2. M18 + L9 — dimensions 披露对齐

- [x] 2.1 `core/contracts/sdr/pipeline.md` `--dimensions` 段改写为与壳披露一致(收窄不下发;接线后恢复现文的备注留存)
- [x] 2.2 三面 agent 定义删「note 收窄维度」句
- [x] 2.3 对照验收:契约与三面壳口径一致,无矛盾表述

## 3. M15 — dsh SKILL launcher 披露

- [x] 3.1 dsh SKILL 补「launcher 仅 spawn opencode/claude;dsh-only 部署走壳内路径」,同段精简等量措辞
- [x] 3.2 `python tools/check_distributed_prompt_budget.py` 通过(SKILL 4994/5000 贴顶,硬闸门)

## 4. M16/M17 — 三面措辞对齐

- [x] 4.1 opencode/dsh 壳超时不变式段对齐 claude 完整规范形(budget/call/stall 三层逐条可辨)
- [x] 4.2 三面 agent 判定纪律统一 claude 精确形;opencode 面删 `{{ }}` 字面占位符
- [x] 4.3 对照验收:三面同段语义一致、无字面占位符残留

## 5. M19/M20 — 契约文档补全

- [x] 5.1 `pipeline.md` 三处字段清单补全(pending[]/stdout/manifest;以脚本实际产出逐项核对)
- [x] 5.2 `runtime-enforcement.md` 补 sdr 哨兵生命周期段(预武装 → co-write → rearm → check)+ Authoring 行改两个确定性写入器 + target 来源清单补 sdr_context `repo`

## 6. L10 — 壳参数表转发槽位

- [x] 6.1 opencode 壳参数表三 flag(--max-standalone-bytes/--max-interface-bytes/--include-excluded)在 step 2 调用行与示例块补槽位;三面同步
- [x] 6.2 `python tools/check_contracts.py` 通过

## 7. launcher 健壮性(L1/L2)

- [x] 7.1 删除空 try/finally 死代码外壳(行为零变化;NEVER 改成异常路径一律移除哨兵——运行中 run 会失守,见 design D6)
- [x] 7.2 sdr_context stdout 消费包 try/except → per-branch FAILED(后续分支继续,退出码语义不变)
- [x] 7.3 回归:模拟 stdout 错形 → 分支 FAILED 非 traceback;残留哨兵经恢复入口可检出

## 8. describe_artifact(M12/M13,补最小回归)

- [x] 8.1 `--field` 索引守卫改 try-int(畸形段优雅报错,非 traceback)
- [x] 8.2 补控制台 utf-8 reconfigure 块(与兄弟脚本同形)
- [x] 8.3 新增最小回归:畸形 field 路径、中文值输出

## 9. 卫生(零行为变化)

- [x] 9.1 `resume_sdr_state.py` STEPS 死常量、`_resolve_repo` grp 死参删除
- [x] 9.2 `sdr_tier.py` probe 失败原因如实区分(binary 缺失 vs env 指向陈旧)
- [x] 9.3 `mgh_sdr_launch.py` 函数内重复 import 收敛模块头

## 10. 收口

- [x] 10.1 定向回归:`tests/test_distributed_md_purity.py`、`tests/test_dsh_command_surface.py`、`tests/test_mgh_sdr_launch.py`、`tests/test_sdr_failure_chain.py`、`tests/test_sdr_context.py`、describe 新增回归;顺手 `tests/test_zero_deps.py`、`tests/test_no_compile_warnings.py`
- [x] 10.2 四个 lint:`check_contracts`、`check_distributed_prompt_budget`、`check_distributed_purity`、`check_plain_language`
- [x] 10.3 `CHANGELOG.md` + `VERSION` bump;分发面 md 改动 → 提示维护者发布前跑全量回归
