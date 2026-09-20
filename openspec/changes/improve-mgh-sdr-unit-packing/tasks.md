> **本任务清单含一个硬停闸门。** 第 0 组的裁决若为 DROP,任务 1 及其后**一律不执行**,change
> 直接归档。裁决为 PASS 才继续。判据与取值口径见 `design.md` D1,不得就地放宽。

## 0. 先决闸门:量化与裁决(硬停)

> 本组的取数**不在开发侧可完成**:`U`/`T` 是网关侧事实。面向数据采集人的实验协议
> (含安装、跑 run、取 `grouping.json`、捞网关记录、交付清单)见本 change 目录
> [`experiment.md`](experiment.md)——该文档面向零背景人类读者,算术留待开发侧执行。

- [ ] 0.1 采集 **≥3 次真实业务仓真实分支**的 sdr 运行,从各次 `grouping.json` 取
      `counts.interface` 记 `M`(中位数),并留下逐单元 `unit_bytes` 分布(仿真/构造 diff 不计入)
- [ ] 0.2 经网关侧计数取 `U`(单个单元的固定开销调用数:会话启动 + 读任务 + 读输入 + 写 draft +
      回执,取中位数)与 `T`(该次 run 的网关侧总调用数)
- [ ] 0.3 对**最接近 `M` 的那次 run** 的逐单元 `unit_bytes`,按 `design.md` D3 的排序键与贪心
      规则**离线复算**包数 `P`(建议取值 `--pack-bytes 16384 --pack-max 8`);不接受估值
- [ ] 0.4 按 `(M − P) × U / T ≥ 0.20` 裁决:
      - PASS → 记录算式与取值,继续第 1 组,并以本组数据定下命令壳的建议取值
      - DROP → 只写结论记录(样本描述、`M/P/U/T`、算式、结论)到本 change 目录,任务 1..9 不执行

## 1. 打包分区与包标识(`core/scripts/diff_group.py`)

- [ ] 1.1 新增 `--pack-bytes`(默认 `0` = 关闭)与 `--pack-max`(默认 `8`);`--pack-max` 单独
      传入而 `--pack-bytes` 为 0 → 退出码 2 + recipe;`--help` 写明打包语义与关闭路径不变量
- [ ] 1.2 实现候选集过滤(`kind=interface` ∧ 非 `(part N)` ∧ 未超 `--max-interface-bytes`)
- [ ] 1.3 实现家族键派生(单元标识 `::` 之前的宿主文件段)与同家族内
      `(unit_bytes 升序, unit_id 字典序)` 排序 + 贪心装包
- [ ] 1.4 实现包标识 `pack::<家族键>::<sha8(成员标识排序拼接)>`,断言与枚举顺序无关
- [ ] 1.5 `--pack-bytes 0` 时打包逻辑零执行,stdout 与 `grouping.json` 逐字节等同于改动前

## 2. 合并 slice 与 pending 包条目

- [ ] 2.1 物化合并 slice:首部确定性成员清单(`unit_id`/`route`/`draft_path`/`done_marker`/
      `failed_marker` 绝对路径)+ 依序拼接各成员切片;文件名经既有消毒(`/ \ :` → `_`)
- [ ] 2.2 `pending[]` 产包条目:与普通条目同形(同字段集)仅多 `members[]`;`unit_id` 载包标识、
      `kind=interface`、`route` = 成员路由去重排序 `;` 连接、`unit_bytes` = 合并文件落盘字节数
- [ ] 2.3 包级 marker 落在 `<checkpoints>/packs/` 独立命名空间(成员 marker 路径不变)
- [ ] 2.4 包 pending 判据 = 「≥1 成员 `.done` 不存在」,包级 `.done` 存在不使包消失
- [ ] 2.5 `grouping.json` 的 `units[]` 仍逐成员一条、`total`/`done`/`failed`/`counts` 仍成员级;
      包数经**新增字段**披露,既有字段语义与取值零变
- [ ] 2.6 `--check` 追加打包自洽断言(包标识纯函数派生、成员非空且绝对、无跨家族、无
      `(part N)`/超预算成员、`unit_bytes` = 合并文件落盘字节数),失败退出码 2
- [ ] 2.7 物化失败隔离语义照旧:单成员失败写成员级 `.failed` 并继续批次;整包失败则不进
      `pending[]` + stderr 告警,退出码不变

## 3. 成员级 marker 与步骤派生隔离

- [ ] 3.1 审计 `core/scripts/sdr_tier.py` / `resume_sdr_state.py` / `list_sdr_steps.py` 的 marker
      枚举点,确认包级目录不被任何单元级计数或孤儿审计收入
- [ ] 3.2 打包开启的 run 上验证步骤派生:部分成员完成 → 步骤仍判为 fanout 进行中,不因包级
      回执提前跳步

## 4. 派发模板双形态(`core/prompts/fragments/fanout/sdr-task.md`)

- [ ] 4.1 新增打包形态:以「合并 slice 首部有无成员清单块」为唯一判据;逐成员读该成员切片、
      逐成员写成员 `draft_path`(`unit` = 成员标识)、逐成员 touch 成员 `done_marker`
- [ ] 4.2 打包形态的失败纪律:某成员失败先完成其余成员,末行 ack `failed <成员标识列表>:<原因>`
- [ ] 4.3 单单元形态**逐字不变**(与 `git diff` 对拍确认该段落未被改写)
- [ ] 4.4 模板 SHALL NOT 新增任何 `{{...}}` 占位符(残留 `{{` 会 fail-loud),改后跑
      `fanout_runner --tier sdr` 冒烟确认无残留

## 5. 报告与 manifest 披露

- [ ] 5.1 `core/scripts/render_sdr_report.py` 读 `grouping.json` 的包归属;**仅当本次 run 存在
      打包单元**时,在诚实边界节列出包数与被合并的成员单元标识
- [ ] 5.2 `sdr_manifest.json` 以新增字段承载同一事实;**无打包单元时该字段不出现**
- [ ] 5.3 关闭打包路径下报告与 manifest**逐字节**等同于改动前(拿改动前产物直接对拍)

## 6. 纪律表、命令壳与契约 lint

- [ ] 6.1 `core/scripts/discipline_core.py`:新增包级 `.failed` 人工恢复 recipe(删包级回执 →
      重新枚举 → 仅缺失成员重跑);调用行加打包 flag 建议取值
- [ ] 6.2 双壳 `releases/claude-code/commands/mgh-sdr.md` 与
      `releases/opencode/command/mgh-sdr.md` 的 `diff_group.py` 调用行同步;fan-out 路径配方与
      纪律表对同一步的输出保持同构
- [ ] 6.3 跑 `py tools/check_contracts.py`,确认新 flag 被逐字断言(双壳 MD 与脚本 `--help` 一致)

## 7. 回归测试

- [ ] 7.1 `tests/test_diff_group.py`:分区确定性(同输入同分区、两种枚举顺序同包标识)、家族
      不混包、`(part N)`/超预算/standalone 不入包、包 pending 由成员 marker 派生、
      `--pack-bytes 0` 逐字节回归、无效 flag 组合退出码 2、`--check` 拦截不自洽包
- [ ] 7.2 `tests/test_render_sdr_report.py`:有打包时披露节出现、无打包时报告逐字节不变
- [ ] 7.3 `tests/test_resume_state.py` / `tests/test_list_steps.py`(sdr 域):包级 marker 不
      污染单元级步骤派生
- [ ] 7.4 `tests/test_fanout_runner.py` 冒烟:包条目的 `--tier sdr` 派发无残留占位符、ack 写
      包级 marker;in-process harness 显式传 `--cooldown-s 0`
- [ ] 7.5 `tests/test_zero_deps.py` / `tests/test_no_compile_warnings.py`(新增代码零依赖)
- [ ] 7.6 跨面改动收口:命令壳 / 分发产物面跑 `test_distributed_md_purity`、`test_plain_language`
      与 `test_mgh_sdr_*_codegraph_parity`

## 8. 文档与版本

- [ ] 8.1 维护者私有文档区的 `/mgh-sdr` 命令人话说明补打包一节(开关语义、建议取值、调用次数
      算术、包级失败恢复指引、诚实边界);术语词典补「包」条目
- [ ] 8.2 `CHANGELOG.md` 与 `VERSION` bump
- [ ] 8.3 全量回归(`tests/` 全量,跨面改动触发)

## 9. 真机验收

- [ ] 9.1 同一份真实 diff 在打包**关/开**两种配置下各跑一次完整 run,核对报告章节一的**行集合
      逐行一致**(行 = 成员单元)、成员级 `.done` marker 可逐一核对
- [ ] 9.2 从网关侧对比两次 run 的实际调用数,回收实测节省比例,与第 0 组的预测对账
- [ ] 9.3 至少一次 crash 重派实证:中断一个包后重派,确认已完成成员不被重跑
