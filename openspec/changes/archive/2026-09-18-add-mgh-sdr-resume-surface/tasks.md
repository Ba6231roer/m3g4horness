## 1. 共享 marker 谓词(写入侧与读取侧同源)

- [x] 1.1 新增 `core/scripts/sdr_tier.py`:承载「单元 marker 正向路径计算」与「canonical 单元 id 集上的
      done/failed 集合计算」两个纯函数(零 IO、无 argparse、自定位,承 R5.3a),接口对位既有
      `core/scripts/init_tier.py` 的 `forward_marker_paths`/`forward_done_ids`/`forward_failed_ids`
- [x] 1.2 `core/scripts/diff_group.py` 改为**导入**该模块计算 marker 路径(现有 `_markers` 就地读取改为
      复用共享判定);marker 文件路径必须**逐字不变**(写入侧零行为变化)
- [x] 1.3 新增 `tests/test_sdr_tier.py`:断言共享函数算出的 marker 路径与 `diff_group.py` 实际写出的
      marker 文件路径逐字一致(含含特殊字符的 unit_id 用例)
- [x] 1.4 跑 `py tests/test_diff_group.py`,确认 1.2 的重构零行为变化

## 2. 纪律表按域分表

- [x] 2.1 `core/scripts/discipline_core.py` 的 `get_discipline(step, domain="init")` 加 `domain` 参数,
      默认域 `init` 的返回值**逐字不变**(既有两处调用零改动);域缺省/未知域 → 空结构(shape 稳定)
- [x] 2.2 新增 `domain="sdr"` 纪律表,key 与 sdr step 闭集一致
      (`not-started|group|fanout|render|done`);每步写入:产出者 `--check` 命令 + 退出码 2 语义、
      fan-out 路径配方(`diff_group` stdout `pending[].input_path|draft_path|done_marker|failed_marker`
      绝对逐字透传)、四级超时不变式、快败冷却/`--retry-failed` 配方、`run.log` 证据路径、该步 `NEVER` 硬边界
- [x] 2.3 跑 `py tests/test_resume_state.py` + `py tests/test_list_steps.py`,确认 init 域纪律输出零漂移

## 3. resume_sdr_state.py

- [x] 3.1 新脚本骨架:`--run-dir`(必填)、`--repo`(可省)、`--check`、`--rearm-sentinel`;
      stdout = 单对象 JSON、stderr = 诊断严格分流(R5.3b);退出码 run-dir 不存在 = 1、`--check` 违例 = 2、
      其余 = 0;任意 cwd 可直接 `py`(R5.3a)
- [x] 3.2 磁盘重派生:`repo`/`base`/`branch`(取自 `context.json`,缺则回退 `grouping.json`,两者冲突时
      以 `context.json` 为准并在 `notes[]` 披露);`tiers`(复用 1.1 的共享谓词按 marker 判终态,
      **不采信** `grouping.json::units[].status`);`step` 闭集按短路序派生
      (not-started → group → fanout → render → done)
- [x] 3.3 `next_action`:每步给出确切调用与 `absolute_paths[]`(逐字取自磁盘,零占位符、零相对路径);
      零 diff / 全排除(`empty==true` 或 `total==0 && excluded.count>0`)直接推进到 `render`;
      起始态退化披露(`not-started` 时 `notes[]` 载明「起始态未落盘」+ desc 给出含默认值的重新给参调用;
      推不出 repo 时不猜,要求显式 `--repo`)
- [x] 3.4 `stale_fanout[]`:扫 `<run-dir>/fanout_runner.*.pid`,报 `{tier, pid_file, pid, pid_alive, note}`;
      存活 PID 的 note 携带 `--kill-stale --dry-run` recipe(PID 存活探查用 OS 进程表)
- [x] 3.5 `--check`(R5.9,失败退出码 2):哨兵存在性(仅 `step ∈ {group,fanout,render}` 判违例 +
      re-arm recipe;`not-started` 仅 note;`done` 不违例)、同一单元同时携带 `.done` 与 `.failed`(违例)、
      孤儿 marker(advisory note,不计数)、`grouping.json` 与磁盘 marker 的判定一致性
- [x] 3.6 `--rearm-sentinel`:据 `context.json::repo` 与 `external_repos[].path`(存在且为目录者)
      确定性重写 `<repo>/.mgh-sdr/.active`(`domain="mgh-sdr"`、`out_roots=[]`);原子写、幂等;
      路径由 Python 产出(Windows 原生,NEVER MSYS 形态)
- [x] 3.7 新增 `tests/test_resume_sdr_state.py`,覆盖中间态:空 run 目录 / 仅 `context.json` / 仅至
      `grouping.json` / 部分单元终态 / 全终态未渲染 / 已渲染 / 零 diff / 全排除 / `status` 陈旧 /
      遗留 `run_config.json` 被忽略 / 哨兵缺失的三种步 / re-arm 幂等 / 同一磁盘态两次调用 stdout 逐字一致

## 4. list_sdr_steps.py

- [x] 4.1 新增 `core/scripts/list_sdr_steps.py`:输出
      `{steps:[{step,kind,script,script_abs,invocation,input,output,discipline}]}`(零磁盘前置,
      对位 `list_steps.py`);`--step <id>` 只吃命名 id,未知 → 退出码 2 + stderr 已知 id 清单
- [x] 4.2 新增 `tests/test_list_sdr_steps.py`:断言与 `resume_sdr_state.py` 同 step 的 `discipline`
      逐字一致(单一真相)、未知 id 退出码 2、`script_abs`/`invocation` 可执行且绝对

## 5. 起始态退场 + 哨兵与 run_config 写入脚本化

> 维护者裁决(见 design D2/D3):`run_config.json` **保留**为 codegraph 信号载体(并存 change
> `fix-mgh-sdr-fanout-callface-contract` 已在工作区接通其读取端),退场的是**起始态用途**;
> 写入者从「编排器手执行 `printf`」换成 `sdr_context.py` 脚本副作用。

- [x] 5.1 `core/scripts/sdr_context.py`:① 加 `--no-codegraph` flag;② 基线投影 + 外部仓检索完成后
      **同一副作用位置 co-write 两样**——`<repo>/.mgh-sdr/.active`(`target` = 其 stdout 的 Windows
      原生 `repo`、`read_roots[]` = 实际检索过的根 ∪ 操作者 `--read-root`)与
      `<run-dir>/run_config.json`(`{"no_codegraph": <bool>}`,**只此一个字段**,起始态字段 NEVER 写入);
      两处均原子写 + 幂等;写失败 fail-loud,不静默
- [x] 5.2 `core/scripts/mgh_sdr_launch.py`:`_write_sentinel` 语义改为**幂等刷新**(内容来源与 5.1 同源,
      保留 spawn 前对已确认根的第二次授权复核 + 并入 `--read-root`);`_remove_sentinel` 生命周期不变;
      `_run_context` 透传 `--no-codegraph`(launcher CLI 同步新增该 flag,与壳对等)
- [x] 5.3 删除命令壳里**三处**手执行写配方:step 0 哨兵 `printf`、step 1 的「有 external_repos →
      重写哨兵」步骤、step 2 的 `run_config.json` `printf`;壳改为向 `sdr_context.py` 传
      `--no-codegraph`(自动探测结果只经该 flag 表达)。确认**无起始态写入面残留**
      (`fanout_runner` 对 `run_config.json::no_codegraph` 的读取面**保留**,是本次刻意保住的契约)
- [x] 5.4 扩展 `tests/test_sdr_context.py`:跑完哨兵必在、`read_roots[]` 最小化(只含实际检索过的根)、
      外部根不存在时不写入;`--no-codegraph` 两种取值 → `run_config.json` 载荷正确、**只含**
      `no_codegraph` 一个字段、重复跑内容逐字相同
- [x] 5.5 扩展 `tests/test_mgh_sdr_launch.py`:重复启动只产生一份同内容哨兵(幂等刷新)、
      spawn 前的第二次授权复核仍拦截未批准根、`--dry-run` 后哨兵保留、`--no-codegraph` 透传生效

## 6. 双壳改造(两壳镜像)

- [x] 6.1 `releases/claude-code/commands/mgh-sdr.md` 与 `releases/opencode/command/mgh-sdr.md`:
      删除哨兵 `printf` 配方(两处)与 `run_config.json` `printf` 配方(一处)——两者改由
      `sdr_context.py` 写出,壳只做 `export MGH_SDR_ACTIVE=1` + 建 run 目录 + 把 codegraph
      自动探测结果作为 `--no-codegraph` 传给 `sdr_context.py`
- [x] 6.2 两壳恢复段改指 `resume_sdr_state.py --run-dir <abs>`:载明**必须带同一个 run 目录**、
      按 stdout `next_action`/`discipline_reminders[]` 继续;删除指向 init 域 `resume_state.py` 的调用
      (该脚本在 sdr 下必然失败,是不可执行指引)
- [x] 6.3 两壳诚实边界补两条:① launcher 重跑会新建 run 目录(别宣称「重跑即续跑」);
      ② `--dimensions` 收窄当前只在 `sdr_context` 做闭集校验、**不下发**到评审单元
- [x] 6.4 用 `py tools/measure_prompts.py` 复核两壳 `mid_tokens` 仍 ≤ 5,000(R5.6)。**注**:本次为
      **净增**(新增「中断恢复」段 + 两条诚实边界;删除三处 `printf` 配方不足以抵消),增量相对
      上一 release 基线约 +13%,按 R5.6 的回归语义属**需 review 的增量**而非静默漂移——增量全部
      来自规格要求的新内容(恢复指引接上 + 缺口如实披露),非冗余

## 7. 契约文档 / lint / 安装自检 / 版本

- [x] 7.1 新增 `core/contracts/sdr/resume-state.md`(对位 `core/contracts/init/resume-state.md`):
      记录 stdout 字段契约、step 闭集与判据表、哨兵校验/重写语义、起始态退化披露
- [x] 7.2 更新 `core/contracts/sdr/pipeline.md`:run_config 的起始态用途退场(保留为 codegraph 信号载体,
      由 `sdr_context` 确定性写出)、哨兵同源写出、恢复入口为 `resume_sdr_state.py`
- [x] 7.3 `tools/check_contracts.py` 登记新脚本 flag 断言(`resume_sdr_state.py`:`--run-dir`/`--repo`/
      `--check`/`--rearm-sentinel`;`list_sdr_steps.py`:`--target`/`--step`)与双壳恢复段标记断言
      (对位既有 `RESUME_SCRIPT`/`UT_INIT_SHELLS` 写法,R5.1)
- [x] 7.4 `install.sh` 共定位自检脚本列表加 `resume_sdr_state` / `list_sdr_steps` / `sdr_tier`
- [x] 7.5 跑 `py tools/check_contracts.py`、零依赖 AST 扫描、`py tools/check_distributed_purity.py` 全绿
- [x] 7.6 `CHANGELOG.md` 追加条目、`VERSION` bump(当前 0.1.48)

## 8. 验收

- [x] 8.1 定向回归测(改哪面跑哪面):`test_sdr_tier` `test_diff_group` `test_resume_sdr_state`
      `test_list_sdr_steps` `test_sdr_context` `test_mgh_sdr_launch` `test_render_sdr_report`
      `test_resume_state` `test_list_steps` `test_distributed_md_purity` `test_plain_language`
      `test_zero_deps` `test_no_compile_warnings`
- [x] 8.2 实机演练(真仓库):人工中断一次 sdr run → `resume_sdr_state.py --run-dir <abs>` 报出正确 step 与
      重派命令 → 按 `next_action` 续跑至报告产出,已完成单元零重复消耗
- [x] 8.3 实机演练哨兵闭环:人为删除 `.mgh-sdr/.active` → `--check` 退出码 2 + recipe →
      `--rearm-sentinel` → 再跑 `--check` 退出码 0,且重写内容与删除前逐字一致
- [x] 8.4 维护者私有文档区:命令人话说明新增「中断后如何续跑」一节(现象→原因→改法),术语词典补条目

## 9. 归档时同步

- [x] 9.1 archive 时同步两处基线 Purpose 措辞:恢复面能力现只描述 `/mgh-init`;运行时守卫能力现写「跨五命令」,
      而 sdr 已是第 6 域(该能力本次未改 Purpose,归档时补齐)
