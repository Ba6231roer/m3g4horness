# 实机笔记 — add-mgh-native-dispatch-core(0.1.84)

机器:维护者本机(Windows,Git Bash;`py` 为损坏的 Store 占位,统一用 `python`)。
日期:2026-10-20。全程零模型调用、零 token 成本(计划物化与自检均为确定性脚本;
唯一子进程 = tier 枚举器 `diff_group.py`)。

## 1. 闸门仓

`C:\DEV\_mgh_native_plan_gate`(scratch 真仓,保留作复现场):Spring 形状迷你项目,
`master`(基线:UserController/OrderController/pom.xml)→ `feat/security-fix`
(修改 UserController 加端点、新增 UserDao、新增 application.properties 含明文口令——
敏感信息维度诱饵)。`git diff --stat master..feat/security-fix` = 3 文件 13 插入。

## 2. 任务 4.1:sdr tier 真仓 --emit 两次 + --check

前置(真实编排器的分组步骤,产 grouping.json 与单元切片):

```
python core/scripts/diff_group.py --repo C:/DEV/_mgh_native_plan_gate \
  --base master --branch feat/security-fix \
  --checkpoints <run>/checkpoints --materialize <run>/inputs
# stdout 摘要: total 3 pending 3 counts {'interface': 2, 'standalone': 1}
```

物化两次 + 逐字节对账 + 自检:

```
python core/scripts/emit_native_plan.py --tier sdr --repo … --base master \
  --branch feat/security-fix --checkpoints <run>/checkpoints \
  --inputs-dir <run>/inputs          # 第一次
sha256sum <run>/native_plan.json <run>/inputs/*.task.md > /tmp/emit1.sha
python core/scripts/emit_native_plan.py …             # 第二次(同参)
sha256sum -c /tmp/emit1.sha
# native_plan.json: OK
# inputs/UserController___api_users.task.md: OK
# inputs/UserController___api_users_{id}_detail.task.md: OK
# inputs/src_main.task.md: OK
python core/scripts/emit_native_plan.py … --check
# [emit_native_plan] --check ok: …\run\native_plan.json (3 unit(s), 1 wave(s))
# stdout: {"tool": "emit_native_plan", …, "units_total": 3, "waves": 1,
#          "wave_size": 3, "wave_size_source": "concurrency", "check": "ok",
#          "violations": []}   退出码 0
```

计划内容抽查:

- 顶层键恰为 `{agent, repo, tier, units_total, v, wave_size, wave_size_source,
  waves}`,无任何时间戳字段;序列化 `indent=2 + sort_keys + 尾换行`。
- 3 单元 1 波(wave_size 3,来源 concurrency);短号 `sdr-wx4a` / `sdr-myes` /
  `sdr-gy76`(字符集无 `0/1/i/l/o`,两两编辑距离 ≥2)。
- 单元条目 = diff_group pending 字段逐字透传(`chain`/`route`/`slimmed`/
  `unit_bytes`/`baseline_path`/…)+ `{id, unit_id, task_file}`,task_file 全绝对。
- task 文件 = 真实 `sdr-task.md` 模板填充,`grep -c "{{"` 全部为 0;与派发器审计
  副本同路径同内容(同一 `_fill_template` 代码路径 + 同一默认模板,构造性一致)。

零派发副作用证据:全仓 `find -name "*.done" -o -name "*.failed" -o -name cred.json
-o -name "fanout_progress*" -o -name "*.pid"` 为空;run 目录仅
grouping.json/checkpoints/inputs/native_plan.json 及切片与 task 文件;两次 emit 各
~1s 完成(无宿主进程启动的时间痕迹)。

## 3. 任务 4.2:缺省零变化抽查

同一项目**不放** `.mgh/env-profile.json`(整个 `.mgh` 目录不存在):

```
python core/scripts/env_profile.py --target C:/DEV/_mgh_native_plan_gate
# {"…", "exists": false, "profile": {"dispatch_mode": "auto",
#   "native_concurrency": 3, "quota": null}}   退出码 0
python core/scripts/diff_group.py --check C:/DEV/_mgh_native_plan_gate/.mgh-sdr-gate/run
# [diff_group] --check ok: 3 pending unit(s) consistent   退出码 0
```

既有 sdr 步骤面(`diff_group --check`)在画像缺席时按既有契约行为不变;`auto`
缺省解析 = 现状派发形态(本变更未接入任何命令壳,行为影响为零由构造保证:两新脚本
仅被本 change 的测试与实机命令调用,任何既有命令路径不 import 它们)。

## 4. 单测与回归摘要(先红后绿)

- `tests/test_env_profile.py`:先红(27 errors,脚本未存在)→ 绿 27 测。
- `tests/test_emit_native_plan.py`:先红(37 errors)→ 绿 37 测(含真 git 仓端到端:
  唯一子进程断言为 diff_group、两次物化逐字节一致、--check 绿、篡改红)。
- `git diff --stat core/scripts/fanout_runner.py` 为空(派发器零改动,任务 2.1 验证)。
- 定向回归:`test_fanout_stale`/`test_zero_deps`/`test_no_compile_warnings` 全绿;
  `test_fanout_runner` 223 测 2 失败(`waves_run` 11≠10 / 3≠2,真计时器波数断言)——
  与 0.1.82 归档记录的 HEAD 存量环境相关失败一致,且本变更对被跟踪的派发器与测试
  文件零改动(git status 仅契约 md 修改 + 新增文件),零交集。
- lint 四件套:`check_contracts` 504 flags/17 壳全声明;`check_distributed_purity`
  336 扫描 0 违例/174 白名单(条目数与基线一致);`check_distributed_prompt_budget`
  17 壳在预算内(无壳改动,零增量);`check_plain_language` exit 0;
  `test_distributed_md_purity` OK(实机笔记归位后复跑,见任务 5.2);
  `openspec validate add-mgh-native-dispatch-core --strict` valid。

## 5. 消费指引(后续 change)

- **sdr 原生接入**(路线第 5 个):壳的扇出步骤改为「emit → --check → 按波次转述」;
  每波前重物化(stale 计划 NEVER 消费);转述句柄用短号,路径从计划 `task_file`/
  `done_marker` 字段逐字复制。
- **看门狗**(第 4 个):以 `native_plan.json` 的波次与短号作观测坐标系;`--check`
  作每波前的健康哨(退出码 2 = 需重物化,非重试原计划)。
- **形态选择**:`env_profile.load(<项目>)` 的 `dispatch_mode` 是单一来源;缺文件 =
  现状(runner)。`auto` 缺省解析已被规格钉死为「现状」,细化须另立变更。
