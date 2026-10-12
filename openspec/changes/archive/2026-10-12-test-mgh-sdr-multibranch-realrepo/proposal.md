> **人话序** 现象：`/mgh-sdr` 的「一条命令串行跑多个分支、每个分支各出一份独立报告」能力（launcher 的 `--multi-branch` 参数）开发完成至今从未在真实仓库上完整跑过一次——目前的信心只来自单元测试和规格场景文字。根因：真实环境里有三类仿真测覆盖不了的因素——宿主 agent 会话真实被拉起并消耗真 LLM 配额、目标仓库根目录残留着历史报告文件（报告识别按「最新修改时间」取，可能误认旧报告）、多个分支连跑之间的状态残留（哨兵文件、run 目录累积）。改什么：把 springBootTemplate（一个真实的 Spring Boot 项目）当作测试床，准备 3 个测试分支（现有 `sdr-dryrun` + 新建 2 个各带不同安全复核形状的分支），分支清单里再塞一个故意不存在的分支名来注入失败；用单条 launcher 命令串行跑完，逐项核对规格承诺的行为。怎么验证：每分支有独立 run 目录 + 独立 HTML 报告 + 数据 JSON；失败分支不阻断后续分支、最终退出码 1 且 stderr 列出失败者；全程逐项记录进问题清单文档，作为后续修复/优化 change 的输入。

## Why

- 多分支 sweep 是规格里已承诺的行为（「多分支串行」场景：串行跑 N 轮完整流程、每分支独立报告、单分支失败记录后继续、退出码 1 + stderr 列失败分支），但该能力**自开发完成起一次都没真仓执行过**。单元测试能覆盖确定性逻辑（清单解析、循环、退出码），覆盖不了真机因素：宿主 CLI 真实 spawn 与 LLM 扇出、真实 git 仓的历史报告文件干扰报告识别、分支间哨兵/run 目录状态残留、真实时长与配额消耗、Windows 真机路径形态。
- 用户（维护者）需要一份**真仓跑出来的问题清单**作为后续 fix/improve change 的输入——本次 change 的交付物就是这份清单，不修任何问题。

## What Changes

- **测试床准备**：在 `C:/DEV/springBootTemplate` 自 `master` 新建 2 个测试分支（加上现有 `sdr-dryrun` 共 3 个），每个分支的 diff 预置差异化的安全复核形状：
  - `sdr-dryrun`（既有，16 文件 +595/−39）：接口聚集 + 多形态调用链（服务/工具/Mapper XML）；
  - `sdr-mb-authz`（新建）：垂直/横向越权 + 输入校验形状（新增管理接口无权限校验、按 ID 直查对象的横向越权、缺校验入参）+ 少量 standalone 文件；
  - `sdr-mb-sql-sensitive`（新建）：SQL 注入形状（Mapper XML `${}` 拼接）+ 敏感信息形状（日志打印手机号/证件号、硬编码密钥）。
- **失败注入探针**：分支清单在第 2 位插入一个不存在的分支名（如 `sdr-mb-nonexistent`），低成本验证「单分支失败记录后继续」与最终退出码 1，镜像规格场景。
- **执行方式**：目标仓安装 opencode 端分发（`install.sh --opencode`；目标仓当前只有 claude 端，opencode 端随本战役首装，顺带消除脚本副本与开发态的版本漂移）→ `--dry-run` 冒烟 → 单条 `py mgh_sdr_launch.py --repo C:/DEV/springBootTemplate --base master --host opencode --multi-branch <清单文件>` 真跑。宿主显式钉死 opencode（维护者拍板的被测宿主）；opencode 并行子会话的已知稳定性问题（数据库锁崩溃前科）从回避项转为一级观测点。
- **观测与断言清单**：串行性（逐分支起止）、每分支独立 run 目录与报告、报告产物完整性（自包含 HTML + `sdr_report_data.json` + manifest）、失败隔离、哨兵生命周期（run 中在、run 后除）、工作树不被 checkout、历史残留报告不被误认为新报告、基线缺失/敏感目录回退默认模板的降级披露、opencode 宿主特有形态（并行子会话数据库锁是否出现、快败冷却/限流截断/零进展熔断的真实表现）。
- **交付物**：问题清单文档落在本 change 目录（`findings.md`）：每分支结果、与预期行为的偏差、问题（现象/复现/影响/初步定位）、观感与优化建议；不修问题、不改 mgh-sdr 任何产品代码。

## Capabilities

### New Capabilities

- `sdr-multibranch-realrepo-validation`：mgh-sdr 多分支 sweep 真仓验证战役的要求——测试床分支夹具、执行与失败注入方式、观测断言清单、问题清单产物的内容与落点。

### Modified Capabilities

<!-- 无。产品行为零改动；真仓发现的问题由后续 fix/improve change 各自承接，届时再修规格。 -->

## Impact

- **产品代码**：零改动（本 change 纯验证战役）。
- **测试床仓**：`C:/DEV/springBootTemplate` 新增 2 个本地分支与其提交；run 产物（`.mgh-sdr/runs/**`）与每分支 HTML 报告落该仓根（与其既有残留共存，不清理不归属本 change）。
- **分发面**：目标仓**首装** opencode 端分发（`.opencode/`，重跑 `install.sh --opencode`），消除脚本副本与开发工作区的版本漂移。
- **成本**：3 次完整 LLM 流水线串行执行（真实 token 消耗与墙钟时长，预计为所有分支中最耗时的一步）；失败注入探针不消耗 LLM（确定性早败）。
- **依赖**：目标仓 opencode 端由本战役安装（现仅装 claude 端）；宿主 CLI `opencode` 在 PATH；`py` ≥3.10（本机已具备）。
