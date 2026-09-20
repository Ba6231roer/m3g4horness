# tasks — fix-mgh-sdr-fanout-callface-contract

> 契约与措辞以 `specs/fanout-dispatch/spec.md` 与 `specs/security-design-review/spec.md` 为准;
> 技术选型与替代案见 `design.md` D1–D5。本 change **零超时行为改动**(见 D4),第 3 组只是文案
> 与口径固化。
>
> **对接说明(实施中发现并已采纳)**:原 D1 设想「命令壳自己写 `run_config.json`」被同期落地的
> sdr 恢复面 change 取代——写入端下沉到 `sdr_context.py`(launcher 与宿主壳**都必经**的那一步),
> 壳只透传 `--no-codegraph`。该做法严格更优(单写入端、原子、fail-loud、两条入口同源),故本
> change 按之对齐;第 2 组按此改写。由此又暴露一条同形缺陷(launcher 不探测,恒发 `on`),按用户
> 拍板由本 change 一并收口,见第 8 组。

## 1. codegraph 信号接通(派发器侧,D1+D2)

- [x] 1.1 `core/scripts/fanout_runner.py` 的 `_codegraph_signal()`:删除 `tier_key == "sdr"`
  的早返回分支,使 sdr 落入与 init 逐字相同的读取路径(`plan_path.parent / "run_config.json"`
  的 `no_codegraph` 字段)。保留 `tier_key` 形参以免触碰调用方
- [x] 1.2 同步该函数 docstring:移除 "until then sdr = off in the dispatcher" 段落,改写为
  "sdr 与 init 同源——plan 锚点 `<run-dir>/grouping.json` 的父目录即运行目录"
- [x] 1.3 降级语义逐字不变:文件缺失 / 不可解析 / `no_codegraph` 为真 → `off`;三种情形
  NEVER 抛异常、NEVER 写 stderr 噪声

## 2. 命令壳改造(codegraph 载体 + 恢复指引,两壳镜像)

- [x] 2.1 两个命令壳删除 `export MGH_SDR_CODEGRAPH=on|off` 整行及其说明;载体写入端下沉到
  `sdr_context.py`(脚本副作用),壳不再自行写 `run_config.json`(见文件头对接说明)
- [x] 2.2 改写传播说明句:明确 dispatcher 读该文件 `no_codegraph` 派生 `codegraph=on|off` 并填入
  单元任务消息的 `{{codegraph}}` 占位符;删除"信号经环境变量"的表述
- [x] 2.3 "快败风暴三层"第 ① 层:把 `resume_state.py --check` 换成
  `diff_group.py --check <run-dir>`(域内可执行,退出码 0/2);删除该段对 `resume_state.py`
  的全部引用
- [x] 2.4 在同一层就近加一句语义披露:`diff_group --check` 校验的是分组产物完整性(非运行
  进度自洽性)
- [x] 2.5 两壳(claude / opencode)改动逐字镜像;壳体积复核 ~3.1K tok,未触 5,000 tok 上限
- [x] 2.6 核对两壳不含指向维护者私有文档区的指针(纯分发产物要求)

## 3. 超时口径固化(零行为改动,D4)

- [x] 3.1 `core/scripts/fanout_runner.py` 的 `--stall-timeout-s` `--help` 文案:把
  `{STALL_TIMEOUT_FLOOR_S}`(=60)显式标注为**硬性拒绝下限**,把
  `{DEFAULT_STALL_TIMEOUT_S}`(=900)显式标注为**宿主外手动直跑的默认值**;二者 NEVER 混称
  "下限"
- [x] 3.2 同一文案补一句调用方约束:宿主演进调用(传 `--time-budget-ms`)MUST 显式传
  `--stall-timeout-s` 且 `< --call-timeout-s`,NEVER 依赖默认值
- [x] 3.3 断言**未改任何取值**:`STALL_TIMEOUT_FLOOR_S` / `DEFAULT_STALL_TIMEOUT_S` 两常量
  不动,spawn 前校验逻辑不动,`/mgh-init` 与 `/mgh-sdr` 命令壳的 `--stall-timeout-s 300` 不动

## 4. 契约 lint(`tools/check_contracts.py`)

- [x] 4.1 增断言:sdr 两壳 SHALL NOT 出现 `MGH_SDR_CODEGRAPH`(防死契约回流)
- [x] 4.2 增断言:sdr 两壳引用的每个检查/恢复脚本参数形态在 sdr 运行域内可执行——不得出现
  `resume_state.py`,且 `diff_group.py --check` 在册
- [x] 4.3 断言两壳的 `--no-codegraph` 声明与派发器消费路径同时存在(开关不再是空开关):
  另断言派发器的 sdr 早返回不得复现
- [x] 4.4 (新增)断言 codegraph 探测**单一来源**:`sdr_tier.py` 持有
  `codegraph_available()`,`diff_group.py` 与 `sdr_context.py` 都导入它,任一方
  re-inline 裸探测即 fail

## 5. 回归测试

- [x] 5.1 `tests/test_fanout_runner.py` 增用例:sdr tier 的 `_codegraph_signal` 三态
- [x] 5.2 增用例:sdr 单元任务消息的 `{{codegraph}}` 占位符被填为真实信号;断言用的是
  `<run-dir>/grouping.json` 的父目录,证明零路径改动即命中
- [x] 5.3 增用例(防回流):scout/t1/t2/t3 四 tier 的 `_codegraph_signal` 行为逐字不变
- [x] 5.4 增用例:宿主演进调用省略 `--stall-timeout-s` 取默认 900 时以退出码 2 拒绝,recipe
  含"显式传 + 合规示例 + 关闭态"三要素
- [x] 5.5 `tests/test_distributed_md_purity.py` 覆盖两壳改动后的纯净性
- [x] 5.6 `tests/test_mgh_sdr_launch.py`:launcher 提示文件不含 codegraph / 恢复指引文本,
  无需同步(已核对);launcher 自身的信号用例见第 8 组
- [x] 5.7 (新增)`tests/test_sdr_tier.py` 覆盖共享探测:两个条件缺一即 off、"无二进制"分支
  确定性构造、探测原因文案、以及两侧都导入同一谓词(源码级)
- [x] 5.8 (新增)`tests/test_sdr_context.py` / `tests/test_mgh_sdr_launch.py`:信号由仓库
  探测派生而非回显 flag——未索引仓 → `off`;索引仓 + 可解析二进制 → `on`(两条入口同值)

## 6. 分发副本刷新(D5,勿整跑 install)

- [x] 6.1 按 D5 最小搬运刷新开发仓内 `.claude/commands/mgh-sdr.md` 与
  `.opencode/command/mgh-sdr.md`,与 release 版逐字一致
- [x] 6.2 **验收(必做)**:核对 `.claude/settings.json` 的 `hooks` 仍为 `{}`(开发仓刻意不接种
  自身守卫)、`.opencode/plugins/block_adhoc_scripts.ts` 未被改动
- [x] 6.3 未采用整跑 `install.sh` 的路径(按 D5 最小搬运),故无条件成立

## 7. 全量校验与真机验收

- [x] 7.1 `py tests/test_fanout_runner.py`(139)· `py tests/test_fanout_stale.py`(18)全绿
- [x] 7.2 `py tools/check_contracts.py`(314 flag)· `py tools/check_distributed_purity.py`
  (280 文件 clean)· `py tools/check_plain_language.py`(本 change 无新增告警;退出码 2 来自
  仓库内 4 个**其它** change 缺人话序,见交付说明)
- [x] 7.3 `test_distributed_md_purity`(30)· `test_zero_deps`(13)· `tools/measure_prompts.py`
  壳体积复核
- [x] 7.4 `CHANGELOG.md` 记录;`VERSION` = 0.1.49(与同期 sdr 恢复面 change 同版)
- [x] 7.5 维护者私有文档区的 `/mgh-sdr` 命令人话说明:新增 codegraph 段;排障段补"重派前先确认
  产物没坏,且该步只答产物完整性、不答进度"的披露
- [ ] 7.6 真机:**确定性一半已完成**——在本仓(真 `.codegraph/` 索引 + PATH 有 `codegraph`)
  跑通 `sdr_context → diff_group → fanout_runner --pending-file`,实测 `diff_group.codegraph=true`
  与 6 个单元任务消息 `codegraph=on` 两侧一致;带 `--no-codegraph` 重跑落 `off`。
  **未完成的一半(已拍板不跑)**:「draft 能引用 slice 内链上下游证据」需要真实 LLM 扇出。
  该半测的是「子代理拿到 `on` 之后怎么写 draft」= 模型行为,不是本 change 的契约面;且本仓是
  Python/markdown 仓,没有 Java 接口链可看,证据面薄。**如实标注为未验证**,不假称跑过
- [x] 7.7 真机:在真实 sdr 运行目录逐字执行壳内恢复指引命令——`diff_group.py --check <run-dir>`
  退出码 0、`resume_sdr_state.py --run-dir <run-dir>` 退出码 0,均非 1

## 8. codegraph 探测下沉(实施中发现的同形缺陷,用户拍板扩入)

> 现象:launcher 的 `--no-codegraph` 是 `store_true`(默认 False = on),而该路径**无人探测**
> repo,于是无索引仓上 `run_config.json` 恒 `{"no_codegraph": false}` → 任务书恒 `codegraph=on`,
> 而 `diff_group` 已退化为 `false`/空链——子代理被指示「切片已装整条链,别去别处找」,而链并不在。
> 这正是本 change 要消除的「两侧打架」,只是换到了 launcher 入口。

- [x] 8.1 探测下沉到 `sdr_context.py`(两条入口必经的一步):
  `no_codegraph = 用户 `--no-codegraph` 强制关 OR 探测不可用`
- [x] 8.2 探测谓词单一来源:上提到 `core/scripts/sdr_tier.py` 的 `codegraph_available()` /
  `codegraph_bin()` / `codegraph_probe_reason()`;`diff_group.py` 改为导入(消除第二份实现)
- [x] 8.3 launcher:`--no-codegraph` 帮助文案由"default = on"改为**强制关**语义(信号否则自动探测)
- [x] 8.4 两壳 step 0 删除第三份探测(壳不做探测、不写信号),仅用户显式要求时透传 `--no-codegraph`
- [x] 8.5 stderr 披露信号来源(`forced by --no-codegraph` / `probe: <reason|available>`),
  使取值可观测
- [x] 8.6 回归测试:探测两条件、探测原因、两侧导入同一谓词(源码级);launcher 与壳两条入口
  在索引/未索引仓上取值一致
- [x] 8.7 契约 lint:探测单一来源断言(见 4.4)
- [x] 8.8 `--no-codegraph` 只翻转**信号**、不改变**分组**(`diff_group.py` 无该 flag,恒自行
  探测)。实测:强制关时 `diff_group.codegraph=true` 而任务书 `codegraph=off`——方向保守,
  刻意如此。**用户拍板:改文案而非改行为**(守本 change 非目标「不改 diff_group 的分组与预算
  逻辑」)。已改:两壳参数表 + step 0、`sdr_context.py` / `mgh_sdr_launch.py` 的 `--help`、
  人话说明 codegraph 段,均写明「只改信号、不改分组」;原「零 codegraph 调用、行为等价」的
  不实表述已删;规格增一条如实披露该刻意不一致的 scenario。「让 flag 真能关掉分组」留作独立
  change(它改的是分组行为,应走自己的规格与验证)
