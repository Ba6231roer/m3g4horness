> **人话序** 现象：`/mgh-sdr` 的命令壳把一批参数和几个开关交给通用派发器，但其中几样派发器根本不认。命令壳导出的 `MGH_SDR_CODEGRAPH` 环境变量没有任何脚本读取；壳按自己的指引写进运行目录的 `run_config.json` 没人读；派发器内部对 sdr 直接写死"关闭"，其源码注释自承"在接通之前 sdr 一律关"。后果是 `--no-codegraph` 成了空开关，而且每个复核子代理拿到的任务里 codegraph 永远显示 off——哪怕这个仓库已经有现成的代码索引可用，分组阶段也确实用上了它。根因是写入端齐备、读取端从未接通，停在半截契约上。第二件事：命令壳里一条排障指引让编排器去跑 `resume_state.py --check`，而这个脚本只去 `.mgh-init` 找状态，在 sdr 运行目录里必然报"找不到"并退出，该指引在 sdr 场景百分之百失败。顺带更正一条先前的判断：曾以为壳里硬编码的 `--stall-timeout-s 300` 低于标定下限、应改回默认值，核对源码后发现这是误读——900 秒是"宿主外手动直跑"的默认值，硬性拒绝下限是 60 秒，而 300 正是 `/mgh-init` 各阶段与 `/mgh-sdr` 共同使用、并被规格明确许可的取值；把它改成不传会取到默认 900，触发"失活窗口必须小于单次超时"的启动校验，以退出码 2 拒绝启动。本 change 因此不改超时，只把这个容易混淆的口径写进规格，防止后人重蹈。改什么：接通 codegraph 信号（派发器改读运行目录的 `run_config.json`，与 init 同形）；把不可执行的恢复指引换成本域可用的检查。怎么验证：派发器生成的每个单元任务里 `codegraph` 占位符随开关变化；修正后的检查命令在真实 sdr 运行目录返回 0。

## Why

- **契约半截（三样写入物，零消费者）**。命令壳与启动器写下三样东西，Python 侧没有任何一方读：`MGH_SDR_CODEGRAPH` 环境变量（仅出现在两个命令壳里）、`<run-dir>/run_config.json` 的 `no_codegraph` 字段（壳用 `printf` 写，无人读）、壳内声明的 `--no-codegraph` 开关。`core/scripts/fanout_runner.py::_codegraph_signal()` 对 `tier == "sdr"` 直接早返回 `"off"`，docstring 自承 "until then sdr = off in the dispatcher"。可直接观测的后果是 sdr 任务模板里的 `codegraph={{codegraph}}` 占位符恒为 `off`——而 `core/scripts/diff_group.py::_codegraph_available()` 自己却会探测 `<repo>/.codegraph/` 与 PATH 上的 `codegraph` 用于分组，同一 run 内两侧判断互相矛盾：分组按调用链合并了单元，复核子代理却被告知"本单元可能在接口边界被切开"，判断依据与事实相反。
- **恢复指引跨域引用（100% 不可执行）**。`mgh-sdr` 命令壳的"快败风暴三层"第 ① 层让编排器跑 `resume_state.py --check` 作为"磁盘无异常"的依据；而该脚本的运行目录解析是 `--init-dir` > `<target>/<--run-root>`（默认 `.mgh-init`），在 sdr 运行目录下必然以 `init-dir not found` 退出码 1 结束。`tools/check_contracts.py` 只断言 flag 存在于 `--help`，不断言该 flag 在调用域内可执行，因此这条坏指引能通过 lint。
- **超时口径易被误读（已核实：无需改代码，但需写死口径）**。`core/scripts/fanout_runner.py` 里有两个不同的数：`STALL_TIMEOUT_FLOOR_S = 60` 是**硬性拒绝下限**（`1..59` 退出码 2），`DEFAULT_STALL_TIMEOUT_S = 900` 是**仅适用于宿主外手动直跑的默认值**。`/mgh-init` 的四个阶段片段与 `/mgh-sdr` 均显式传 `300`，规格的合规示例也写作 `720000/540/300` 与 `480000/360/300`。曾经的判断把 900 当成了"下限"并主张改为不传——那会让 sdr 取到 900，而宿主演进调用面传的 `--call-timeout-s` 是 360/540，`stall >= call` 触发 spawn 前校验，sdr 以退出码 2 完全无法启动。此处**不改行为**，改为把两个数的分工与"宿主演进调用 MUST 显式传、NEVER 依赖默认值"写进规格。
- **分发副本滞后**：开发仓内已安装的 `.claude/commands/mgh-sdr.md` 与 `.opencode/command/mgh-sdr.md` 为 151 行，缺 release 版（155 行）的"快败风暴三层"块。

## What Changes

- **codegraph 信号接通（已定：接通，不删除）**。`fanout_runner._codegraph_signal()` 取消 `tier == "sdr"` 早返回，与 init 同形读 `<plan-dir>/run_config.json` 的 `no_codegraph` 字段——sdr 的 plan 锚点已是 `<run-dir>/grouping.json`，其父目录即运行目录，零路径改动即可命中。`MGH_SDR_CODEGRAPH` 环境变量**删除**（它没有任何消费者，保留等于再造一个死契约）；命令壳的自动探测结果改为只经 `run_config.json` 单一载体传递，`--no-codegraph` 由此成为有效开关。缺失/不可解析 `run_config.json` → `off`（沿用 legacy 语义，逐字不变）。
- **恢复指引换域**。`mgh-sdr.md` "快败风暴三层"第 ① 层的 `resume_state.py --check` 改为 sdr 域内可执行的 `diff_group.py --check <run-dir>`（校验 grouping.json + slices + markers，fail-loud 退出码 2），并删除对 `resume_state.py` 的引用。完整的 sdr 恢复面由后续 change `add-mgh-sdr-resume-surface` 提供，本 change 只负责消除不可执行指引。
- **超时口径写死（零行为改动）**。sdr 与 init 的 `--stall-timeout-s 300` 保持不变；在 `fanout-dispatch` 增一条规格，写明 `0` / `1..59` / `60..` / 默认值 `900` 四段的语义分工、默认值仅限宿主外手动直跑、宿主演进调用 MUST 显式传 `--stall-timeout-s < --call-timeout-s` 且 NEVER 依赖默认值。
- **分发副本刷新**：重跑 `install.sh` 使开发仓内安装副本与 release 版一致；核对 release 版不含指向维护者私有文档区的指针。**注意**：该步骤会把守卫钩子写入开发仓 `.claude/settings.json`（当前为空对象），与仓库现有"开发仓不接种自身守卫"的约定冲突，见 `design.md` 风险节的做法。
- **非目标**：不新建 sdr 恢复面（见 `add-mgh-sdr-resume-surface`）；不改 `fanout_runner` 的派发/失活/冷却/熔断机制；不改 `diff_group` 的分组与预算逻辑；不改任何超时取值。

## Capabilities

### New Capabilities

<!-- 无。两项均为 security-design-review 与 fanout-dispatch 既有要求的契约对齐。 -->

### Modified Capabilities

- `fanout-dispatch`：「sdr tier dispatches diff-review units through the shared wave machine」——`codegraph` 占位符 MUST 有确定性消费者（读运行目录的 `run_config.json`），NEVER 恒为 `off`。
- `fanout-dispatch`：新增「宿主演进调用的 `--stall-timeout-s` 取值口径」——`--help` 契约面已定义默认值与非默认取值，本要求把"调用方必须显式传"与"默认值仅限宿主外"写成规范性约束。
- `security-design-review`：「sdr 运行域守卫激活与幂等 resume」——命令壳的恢复/排障指引 MUST 只引用 sdr 运行域内可执行的脚本。

## Impact

- **代码**：`core/scripts/fanout_runner.py`（`_codegraph_signal` 取消 sdr 早返回）；`releases/claude-code/commands/mgh-sdr.md` 与 `releases/opencode/command/mgh-sdr.md`（删除 `MGH_SDR_CODEGRAPH` 行、改写 run_config 传递说明、恢复指引换域）。
- **契约/lint**：`tools/check_contracts.py` 增断言——sdr 壳不再出现 `MGH_SDR_CODEGRAPH`，且壳内引用的检查脚本均在 sdr 域内可执行。
- **测试**：`test_fanout_runner`（tier sdr 的 codegraph 信号分支：run_config 存在/缺失/`no_codegraph` 三态）、`test_distributed_md_purity`（分发副本纯净性）、`test_mgh_sdr_launch`（提示文件内容）。
- **文档**：维护者私有文档区里 `/mgh-sdr` 的命令人话说明需同步 codegraph 与恢复指引两节；CHANGELOG/VERSION bump。
- **协调**：`add-mgh-sdr-resume-surface` 承接完整恢复面，本 change 只做"消除不可执行指引"的最小改动；两者对 `mgh-sdr.md` 的同一段落有先后依赖，建议本 change 先落地。
