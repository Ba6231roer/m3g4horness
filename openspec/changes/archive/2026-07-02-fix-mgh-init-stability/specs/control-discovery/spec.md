## ADDED Requirements

### Requirement: Standalone script invocation robustness

`discover_controls.py` 与 `chunk_sources.py` SHALL 在 `from expand_scope import …` 之前,把
**本脚本所在目录**显式插入 `sys.path`(`sys.path.insert(0, str(Path(__file__).resolve().parent))`),
使其在**任意工作目录**、经**宿主 agent 的任意调用方式**(直接 `py`/`python` 执行)下都能定位同目录
的 `expand_scope.py`。两脚本 MUST NOT 仅依赖「运行时自动把脚本目录加入 `sys.path[0]`」这一隐式行为
来保障兄弟导入,MUST NOT 要求用户以 `python -c "exec(…)"` 方式绕行(该方式在 Windows 中文 locale
下会触发 gbk 解码错误)。

#### Scenario: Runs from a different working directory
- **WHEN** 宿主 agent 从目标仓根目录(非脚本所在目录)执行 `py <path>/discover_controls.py --repo . --out ./.mgh-init`
- **THEN** 脚本成功 import `expand_scope`,不报 `No module named 'expand_scope'`,正常产出 candidates/clusters

#### Scenario: Direct execution needs no python -c workaround
- **WHEN** 用户按文档以 `py`/`python` 直接执行 `chunk_sources.py` / `discover_controls.py`
- **THEN** 无需借助 `python -c "exec(open(...).read())"` 即可运行,从而不触发 Windows gbk 编码错误

### Requirement: Bounded single-pass scan performance on large repos

`discover_controls.py` SHALL 对每个源文件**至多读一次磁盘**(读入后缓存文本,供调用图两遍与候选
扫描共用);`walk_sources(repo)` 在单次运行中**只遍历一次**仓库并物化文件清单,供调用图构建与候选
扫描复用;每文件**仅调用一次 `splitlines()`**;候选的 enclosing 锚点 SHALL 通过**每文件预排序的
结构节点列表 + 按行二分**求解,而非「每候选对全文反复 `finditer`」。系统 SHALL 在扫描期间向
**stderr** 周期输出进度(每 N 个文件),stdout 仅在末尾输出既有 JSON 摘要(契约不变)。在 i0 阶段
SHALL 以低成本统计源文件数,命中大仓阈值时**在开始全量扫描前**主动建议 `--scope` 分模块 + `--merge`。

#### Scenario: Large repo finishes within the host timeout
- **WHEN** 对一个约两万个源文件的目标仓运行 `/mgh-init`(默认 `--max-files`)
- **THEN** `discover_controls.py` 在 5 分钟内完成,不被宿主 300s 超时强杀

#### Scenario: Each source file read at most once
- **WHEN** 对任意目标仓运行发现脚本
- **THEN** 每个源文件的磁盘读取次数为 1(调用图两遍与候选扫描共用同一缓存文本)

#### Scenario: Progress emitted to stderr only
- **WHEN** 扫描持续进行且尚未完成
- **THEN** stderr 周期性打印已扫描文件数;stdout 不在中途打印非 JSON 内容,末尾 JSON 摘要契约不变

#### Scenario: Large repo advised to scope before scanning
- **WHEN** i0 阶段统计的源文件数超过阈值
- **THEN** 系统在开始全量扫描前提示建议 `--scope` 分模块 + `--merge`,而非静默跑到超时

### Requirement: Deterministic scripts are orchestrator black boxes

`/mgh-init` 的编排器是宿主 agent 本身(按 `mgh-init.md` 用自身工具跑流水线,非写代码)。命令壳 SHALL 在正文最前列声明:确定性逻辑封装在 `discover_controls.py` / `chunk_sources.py`,直接 `Bash` 调用;agent MUST NOT `Write` 任何 `.py`(编排器/包装器/重实现),MUST NOT `Read` 叶子脚本 `.py` 源码进上下文(报错看 stderr),`Write`/`Edit` 仅用于产物;调用示例 SHALL 只传脚本声明的 flag——`--format` 由 T3 `init-rulewriter` 消费,`discover_controls.py` 不接受 `--format`。

#### Scenario: No orchestrator script is created
- **WHEN** 宿主 agent 执行 `/mgh-init`
- **THEN** agent 不 `Write` 任何 `.py`,而是用自身工具按提示词编排;命令壳正文最前列声明此角色定位

#### Scenario: Discover script not passed --format
- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-init.md` 中 `discover_controls.py` 的调用示例
- **THEN** 这些示例不含 `--format`;`--format` 仅出现在 T3 `init-rulewriter` 阶段的描述中

#### Scenario: Scripts invoked, not read, by the orchestrator
- **WHEN** 编排器执行 i1 发现阶段
- **THEN** `discover_controls.py` / `chunk_sources.py` / `expand_scope.py` 经 Bash 执行,其源码不被 `Read` 进编排上下文

#### Scenario: Discover accepts its documented flags
- **WHEN** 以 `discover_controls.py --repo . --out ./.mgh-init`(不带 `--format`)执行
- **THEN** argparse 不报「unrecognized argument」,脚本正常进入扫描
