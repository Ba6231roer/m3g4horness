# Design — fix-mgh-sdr-docs-shell-alignment

> 修复对象:2026-10-13 评审的文档/壳/契约面(M6/M15–M20/L9/L10)+ launcher/describe 健壮性
> (L1/L2/M12/M13/L3)+ 卫生类。主题 = 披露对齐实现事实 + 低成本健壮性收口。
> **执行顺序建议:五个修复 change 的最后一个**(文档披露以代码事实为准,先落代码面修复
> 可避免披露二次返工)。

## D1 — M6 选型:物化文件 + 路径透传(方案 b),否决占位符内嵌(方案 a)

- **选 (b)**:sdr_context 把解析后的敏感目录对象物化为 `<run-dir>/sensitive_catalog.json`;
  任务模板三元组新增该文件只读路径;subagent 按路径只读。
  - 与外部仓结论文件的「路径透传」设计哲学同构(契约既有承诺:subagent 消息携带结论文件
    路径,NEVER 携带原始内容)。
  - **fanout_runner 占位符集零改动**(路径经既有三元组槽位搭载)——方案 (a)(模板加
    `{{sensitive_catalog}}` 占位符)要动派发器占位符集与残留 `{{` 检查,改动面与回归面
    大一个量级。
  - 37 项目录对象内嵌会吃 task 消息 token;路径 + 只读文件按需读取与「惰性加载」纪律一致。
- **L3 随之消解**:launcher `_build_prompt` 不再内嵌目录对象 → `[:4000]` 静默截断逻辑删除,
  「逐字透传」声称恢复成立;launcher/agent 定义措辞同步。
- 物化时机:sdr_context 主流程内与 context.json 同步写出(确定性、单遍);文件位于 run 目录
  = 守卫运行域内,subagent 只读合法。

## D2 — M15:披露,否决 launcher 加 dsh host

- dsh 是交互式 harness(用户 `/mgh-sdr` 显式召唤),无 headless spawn CLI 可被 launcher
  调用;dsh-only 部署的机器上也不存在 opencode/claude CLI——给 launcher 加 `--host dsh`
  没有可用执行体。披露是唯一诚实选项:dsh SKILL 补一句「launcher 仅 spawn opencode/claude
  宿主;dsh-only 部署直接走壳内路径」。
- **token 预算**:dsh SKILL 4994/5000 贴顶——加句子的同段 MUST 精简等量措辞,
  `check_distributed_prompt_budget` 是硬闸门。

## D3 — M16/M17:三面对齐 claude 规范形

- 超时不变式段(M16):opencode/dsh 采用 claude 面的完整规范形(`--call-timeout-s` MUST
  显式传且 < budget×0.8;`--stall-timeout-s`(≥60)MUST < `--call-timeout-s`),宿主具体
  数值留在调用占位符——消除压缩括号注形的绑定歧义,消除非白名单文本漂移。
- agent 判定纪律(M17):三面统一 claude 面的精确散文形;opencode 面删除运行时永不替换的
  `{{ baseline path from the task message }}` 字面形态(静态文件,dispatcher 只对任务模板
  做替换)。

## D4 — M18/L9/M19/M20:契约文档对齐

- M18:`pipeline.md` 的 `--dimensions` 段改写为与壳披露一致(收窄仅闭集校验 + manifest
  记录,不进入任务消息);「真正接线后恢复现文」以任务清单备注形式留存。
- L9(与 M18 同批):三面 agent 定义删除「task message 的检查面 note 会收窄维度」句
  (描述永不触发的机制)。
- M19:`pipeline.md` 三处字段清单补全——pending[] 补 `baseline_path/external_dir/slimmed/chain`;
  stdout 补 `base/branch/pending_approval[]/baseline_truncated_bytes` 与
  `external_repos[]` item 形(slug/diff_files/route_hits/bytes/truncated);manifest counts
  补 `findings/excluded_files`。以脚本实际产出为准逐项核对,不臆造字段。
- M20:`runtime-enforcement.md` 补 sdr 域哨兵生命周期段(实现事实:`--arm-sentinel` 预武装 →
  sdr_context co-write 细化 → `--rearm-sentinel` 确定性重写 → `--check` 中途存在性校验);
  Authoring 行改「两个确定性写入器」(`read_roots_config --add` 与 `sdr_context
  --approve-external`,共享同一原子写实现);target 来源清单补 sdr_context stdout `repo`。

## D5 — L10:壳参数表转发槽位

- opencode 壳参数表已声明的 `--max-standalone-bytes/--max-interface-bytes/--include-excluded`
  在 step 2 调用行与示例块补括号转发槽位;三面同步(镜像纪律),`check_contracts.py`
  对账通过为硬验收。

## D6 — L1:删死代码外壳,不改哨兵生存语义(辨析)

- 现状:空 `try/finally`(异常路径与正常路径行为已一致——哨兵移除只在正常路径执行)。
- **否决「改真 finally 一律清理」**:launcher Ctrl-C/异常时宿主 CLI 子进程可能仍在运行,
  此时移除哨兵会让**运行中的 run 失去运行域守卫**——安全方向错误;残留哨兵的害处(守卫
  常驻后续会话)有自愈出口(resume 面存在性校验给出 re-arm recipe)。
- 修法 = 删除空壳(行为零变化、消灭死代码),残留哨兵的自愈指引由既有恢复工具承担
  (本 change 的 ADDED requirement 已把「残留哨兵可被恢复工具检出」写成行为契约)。

## D7 — L2:上游 stdout 消费防护

- launcher 对 sdr_context stdout 的 `json.loads` 与字段下标访问包
  `try/except (ValueError, KeyError, TypeError)` → 该分支记 FAILED(stderr 原因:上游产物
  不可解析),多分支清单继续后续分支;已写哨兵的清理沿既有失败路径语义。
- 退出码语义不变(任一分支 FAILED → 最终 1)。

## D8 — M12/M13:describe_artifact 健壮性(补最小回归)

- M12:`--field` 索引段守卫从 `lstrip("-").isdigit()` 改为 `try: int(seg) except ValueError:
  优雅报错`——消除 `--5`、`²` 等「守卫放行但 int() 拒收」的 traceback 面。
- M13:补与兄弟脚本相同的 `stream.reconfigure(encoding="utf-8", errors="replace")` 块
  (该脚本是全族唯一例外;`ensure_ascii=False` 的中文输出在 cp936 控制台即崩——维护者
  本机真实环境)。
- 该脚本此前无专属测试文件:补最小回归(畸形 field 路径优雅报错、中文值在受控编码下正常
  输出)。

## D9 — 卫生类(零行为变化)

- `resume_sdr_state.py`:STEPS 死常量、`_resolve_repo` grp 死参数删除。
- `sdr_tier.py`:probe 失败原因如实区分(binary 缺失 vs env 指向陈旧路径),不再统一报
  "no binary" 掩盖诊断。
- `mgh_sdr_launch.py`:函数内重复 `import os` 收敛到模块头。

## 测试与验收口径

- 文档面硬闸门:`python tools/check_contracts.py`(L10 槽位)、
  `python tools/check_distributed_prompt_budget.py`(**dsh SKILL 贴顶,改后必跑**)、
  `python tools/check_distributed_purity.py`、`python tools/check_plain_language.py`。
- 定向回归:`tests/test_distributed_md_purity.py`、`tests/test_dsh_command_surface.py`、
  `tests/test_mgh_sdr_launch.py`、`tests/test_sdr_failure_chain.py`、
  `tests/test_sdr_context.py`(物化文件)+ describe_artifact 新增最小回归;顺手
  `tests/test_zero_deps.py`、`tests/test_no_compile_warnings.py`。
- 三面镜像纪律:改任一面壳 MUST 同查另两面,镜像是逐字的(方言差异仅落白名单五类)。
- 本 change 改分发面 md → 发布前全量回归由维护者按仓库惯例执行。
