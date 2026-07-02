## Why

`add-mgh-init` 实现已归档上线,但在**真实大仓**(opencode 对一个 21611 个 Java 文件的
目标仓)首次实战 `/mgh-init` 时,连续踩 5 个稳定性/可用性问题(详见 `mgh-init-issues.md`),
任务被迫中止:

1. 编排器把 `discover_controls.py` / `chunk_sources.py` / `expand_scope.py` 等 `.py`
   **读进上下文**(本应黑盒执行);
2. 命令壳指示运行 `discover_controls.py --format opencode`,而该脚本**根本不接受 `--format`**
   → argparse 报错;
3. 调整参数后 `discover_controls.py` 在大仓上 **300s 超时**被强杀;
4. 改用 `--max-files 5000` 报 `No module named 'expand_scope'`;
5. 又改用 `python -c "exec(读脚本)"` 绕过 → Windows gbk 编码错误。

根因集中在三处:**命令壳↔脚本的契约不一致**、**兄弟导入依赖隐式 `sys.path[0]` 经不起非规范
调用**、**确定性发现脚本的 I/O 与每候选计算在大仓上呈近 3 倍冗余 + 拟线性爆炸**。这是实现完成
后的**运行时硬化缺口**,不补则 `/mgh-init` 在任何中大型仓都不可用。

## What Changes

- **修契约 bug(1.2)**:从 `releases/{claude-code/commands,opencode/command}/mgh-init.md` 中
  `discover_controls.py` 的调用示例里**移除 `--format`**(该 flag 只属于 T3 `init-rulewriter`;
  发现脚本是 format 无关的,产 `controls_candidates.json` + `clusters.json`)。
- **硬化兄弟导入(1.4 / 1.5)**:`discover_controls.py` 与 `chunk_sources.py` 在 `from expand_scope
  import …` **之前**,显式 `sys.path.insert(0, 本脚本所在目录)`,使任意 cwd / 包装器 / 宿主
  agent 调用方式下都能定位同目录的 `expand_scope.py`,消除 `No module named 'expand_scope'` 与
  `python -c exec` 绕行(后者正是 gbk 错误的来源)。
- **大仓性能(1.3)**:重写 `discover_controls.py` 的扫描主循环为**单遍**——每文件**读一次、缓存
  文本**,调用图两遍 + 候选扫描共用同一缓存;`walk_sources(repo)` **只遍历一次**并物化文件清单
  供调用图与扫描复用;每文件**仅一次 `splitlines()`**;`_enclosing` 改为**每文件预排序结构节点 +
  按行二分**,取代「每候选对全文 finditer」的拟线性爆炸。目标:21611 文件从 >300s 降到分钟内。
- **大仓可观测 + 前置建议(1.3)**:扫描期向 **stderr** 周期打印进度(每 N 文件),stdout 仍只在
  末尾输出 JSON 摘要(契约不变);i0 阶段**廉价统计源文件数**,命中大仓阈值时**在扫描前**主动
  建议 `--scope` 分模块 + `--merge`(取代「先跑 5 分钟再超时」)。
- **编排器黑盒纪律(1.1)**:在 `mgh-init.md`(双壳)显式写明「**确定性脚本是黑盒,经 Bash 执行,
  禁止 `Read` 进上下文**;仅 subagent 的 stages/*.md 提示词按需读取」,对齐 `mgh-sast.md` 的范式。
- **安装自检**:`install.sh` 在镜像 `core/` 后**校验三脚本同目录共存**
  (`expand_scope.py` / `discover_controls.py` / `chunk_sources.py`),缺一即报错(防御部分/陈旧
  安装;虽然 `cp -r core/.` 已覆盖,显式校验更稳、可读)。
- **回归单测**:新增 `tests/test_init_runtime.py` 覆盖——(a) 两脚本在**非脚本目录的 cwd** 下作为
  子进程仍能 import 成功;(b) `discover_controls.py` 单遍语义与旧实现**候选集合等价**(无回归);
  (c) 大文件多候选时 `_enclosing` 与单遍 splitlines 的**性能不退化**(简单计时断言)。

## Capabilities

### New Capabilities
<!-- 无新增能力。本次为运行时硬化,不引入新功能面。 -->

### Modified Capabilities
- `control-discovery`: 既有「确定性发现」要求补充**运行时契约**——(1) `discover_controls.py` 必须可
  作为独立脚本在任意 cwd 下被宿主 agent 直接执行(兄弟导入自定位,不依赖隐式 `sys.path[0]`,不要求
  `python -c exec` 绕行);(2) 发现脚本**不接受 `--format`**,`--format` 仅由 T3 `init-rulewriter`
  消费(命令壳的调用示例须与此一致);(3) 大仓(数万源文件)上的扫描须**单遍 I/O、每候选常数级
  enclosing**,并在超时前以进度与大仓建议给出可观测性。`rules-emission` 的既有要求本身正确
  (`--format` 已正确限定在 T3),**本次不改**;仅命令壳对 T1 发现阶段的 flag 误用需修正。

## Impact

- **改动代码**:
  - `core/scripts/discover_controls.py`(导入硬化 + 单遍重写 + 进度 + 大仓预检);
  - `core/scripts/chunk_sources.py`(导入硬化);
  - `releases/claude-code/commands/mgh-init.md` + `releases/opencode/command/mgh-init.md`
    (移除 discover 上的 `--format`;加黑盒纪律;加大仓预检/进度说明);
  - `install.sh`(三脚本共存自检)。
- **新增代码**:`tests/test_init_runtime.py`(导入鲁棒性 + 单遍等价性 + 性能不退化)。
- **依赖**:**零新增运行时依赖**(R2)。仅用标准库 `sys/pathlib` 等;不引入多进程/并发框架
  (Windows + opencode 子进程约束下风险高,列为 Non-Goal)。
- **契约兼容**:`controls_candidates.json` / `clusters.json` 的**字段与语义不变**(单遍重写为内部
  实现,候选集合等价);stdout 末尾 JSON 摘要不变(进度走 stderr)。
- **无 BREAKING**:不改变产物 schema、不改变 CLI 合法参数集(仅移除文档对一个不存在 flag 的误用)。
- **受益场景**:任何中大型目标仓的 `/mgh-init` 首跑;opencode 与 claude-code 双壳。
