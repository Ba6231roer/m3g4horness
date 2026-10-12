## 1. 前置检查

- [x] 1.1 确认执行条件:宿主 CLI `opencode` 在 PATH、`py --version` ≥ 3.10、本仓 `install.sh` 可用;任一不满足则停止并报告
- [x] 1.2 记录测试床起始态:`C:/DEV/springBootTemplate` 当前分支、`git status --short` 快照、根目录既有 `mgh-sdr-*.html` 残留文件清单及各自修改时间(供「不误认历史报告」断言比对)

## 2. 测试床分支夹具

- [x] 2.1 自 `master` 新建 `sdr-mb-authz` 并提交,预置形状:管理接口无权限校验(垂直越权)、按 ID 直查资源不校验属主(横向越权)、入参不校验(负数/超长/类型混淆)、外加 1–2 个非接口 standalone 文件改动(util/config);提交信息写明预置形状;只留本地不推远端
- [x] 2.2 自 `master` 新建 `sdr-mb-sql-sensitive` 并提交,预置形状:Mapper XML 用 `${}` 拼接排序字段或查询条件(SQL 注入)、日志明文打印手机号/证件号(敏感信息)、硬编码密钥或密码常量;提交信息写明预置形状;只留本地不推远端
- [x] 2.3 断言夹具就绪:`git branch` 含 3 个测试分支(sdr-dryrun / sdr-mb-authz / sdr-mb-sql-sensitive)、各分支 `git diff --stat master..<branch>` 非空、`master` 零新提交;完成后测试床切回 `sdr-dryrun`

## 3. 重装与冒烟

- [x] 3.1 本仓根执行 `bash install.sh --opencode C:/DEV/springBootTemplate`(目标仓 opencode 端**首装**):核对 `.opencode/` 落地(command / agent / plugins / mgh-core),抽查已装 launcher `py C:/DEV/springBootTemplate/.opencode/mgh-core/scripts/mgh_sdr_launch.py --help` 含 `--multi-branch`、`.opencode/plugins/` 下 hook 插件在位
- [x] 3.2 写分支清单文件(4 行,顺序固定:`sdr-dryrun`、`sdr-mb-nonexistent`、`sdr-mb-authz`、`sdr-mb-sql-sensitive`;`#` 注释标明第 2 行是故意不存在的失败探针)落本 change 目录
- [x] 3.3 dry-run 冒烟:用已装 opencode 副本(`.opencode/mgh-core/scripts/mgh_sdr_launch.py`)同清单加 `--dry-run` 跑一遍,核对 4 个分支逐个产 run 目录(含 `orchestrator_prompt.md`)且零宿主 spawn、零 LLM 消耗;如实记录 dry-run 的哨兵保留行为与文案

## 4. 真跑 sweep

- [x] 4.1 后台启动真跑(输出重定向到落盘文件,避免前台单次调用时长上限截断):`py C:/DEV/springBootTemplate/.opencode/mgh-core/scripts/mgh_sdr_launch.py --repo C:/DEV/springBootTemplate --base master --host opencode --multi-branch <清单绝对路径>`;期间逐分支观察 `[launch] === branch <名> ===` 分段、哨兵 `<repo>/.mgh-sdr/.active` 随分支生灭、任一时刻至多一个宿主会话
- [x] 4.2 探针分支断言:`sdr-mb-nonexistent` 确定性早败(无宿主 spawn、无 LLM 消耗、FAILED 原因是上下文失败),其后 `sdr-mb-authz` 与 `sdr-mb-sql-sensitive` 照常完整执行
- [x] 4.3 收尾断言:launcher 退出码为 1,stderr 有 FAILED BRANCHES 汇总且含探针分支及原因,逐分支 ok/FAILED 行可与清单一一对应;记录真跑的完整输出文件路径
- [x] 4.4 opencode 宿主特有形态记录:并行子会话稳定性(「database is locked」崩溃是否出现)、快败冷却/限流截断/零进展熔断是否触发及表现;若某分支扇出无法收敛,按 design 风险条目补救(同一 run 目录换 claude 宿主 resume 补收尾)并完整记录 opencode 侧证据

## 5. 产物清点与逐项断言

- [x] 5.1 独立产物:3 份自包含 HTML 报告(文件名含各自分支名)+ 各分支独立 run 目录 + 同源 `sdr_report_data.json` + `sdr_manifest.json` 全部存在
- [x] 5.2 报告对应性:逐份核对报告单元/文件可追溯到该分支自身 diff 与预置形状(sdr-dryrun=接口聚集与调用链;authz=越权与输入校验;sql-sensitive=SQL 注入与敏感信息)
- [x] 5.3 历史残留不误认:每份被认领报告的修改时间晚于其分支 run 起始时刻,与 1.2 记录的残留清单比对,无把旧报告记为新产物的情况
- [x] 5.4 运行域终态:`.mgh-sdr/.active` 不存在;测试床当前分支与工作树同 1.2 起始态一致(sweep 未 checkout、未改动工作树)
- [x] 5.5 降级披露:manifest 记 `sensitive_catalog_source` 为默认模板回退、基线缺失降级形态在 manifest 或报告可见、报告含「LLM 候选非已确认漏洞」诚实边界声明

## 6. findings 交付

- [x] 6.1 写本 change 目录 `findings.md`:① 每分支结果与关键指标(起止时刻、单元数、失败计数、耗时);② 规格场景逐条「符合/偏差」结论;③ 问题清单,每条含现象/复现方式/影响/初步定位线索;④ 观感与优化建议(非缺陷类);⑤ 局限披露(失败探针只覆盖上下文早败形态,不覆盖扇出中途失败);⑥ opencode 宿主特有形态结论(并行子会话数据库锁是否出现、冷却/截断/熔断的真实表现)
- [x] 6.2 向维护者汇报 findings 摘要,并列出建议的后续 fix/improve change 候选清单
