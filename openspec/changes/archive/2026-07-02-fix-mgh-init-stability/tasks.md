# Tasks — fix-mgh-init-stability

> 依赖顺序:契约修正 + 导入硬化(最低风险,先解 1.2/1.4/1.5)→ 单遍性能重写(1.3)→
> 可观测(1.3 前置建议 + 进度)→ 编排器黑盒纪律(1.1)→ 安装自检 + 回归单测 → 端到端验证。
> 每条可独立验收。遵守 AGENTS.md R1–R4(零依赖、文档简练、复用导入不改 expand_scope)。

## 1. 契约修正 + 导入硬化(FD1 / FD2;解 1.2 / 1.4 / 1.5)

- [x] 1.1 `core/scripts/discover_controls.py`:在 `from expand_scope import …`(`discover_controls.py:32`)之前插入 `sys.path.insert(0, str(Path(__file__).resolve().parent))`(复用已 import 的 `sys`/`pathlib.Path`)。
- [x] 1.2 `core/scripts/chunk_sources.py`:同 1.1,在其 `from expand_scope import …`(`chunk_sources.py:26`)之前加同样的 `sys.path` 自定位。
- [x] 1.3 `releases/opencode/command/mgh-init.md`:移除 `discover_controls.py` 调用示例中的 `--format opencode`(编排流 `--scope .. --format opencode` 与确定性调用块 `--format opencode` 两处)。
- [x] 1.4 `releases/claude-code/commands/mgh-init.md`:移除确定性调用块 `discover_controls.py … --format claude`(`mgh-init.md:68`)的 `--format`(其编排流块本就未带 `--format`,核对无误)。
- [x] 1.5 两份 `mgh-init.md` 的「Stage → component map」/参数表确认:`--format` 仅标注在 T3 `init-rulewriter` 行;发现阶段无 `--format`。(grep 复核:`discover_controls.*--format` 已 0 命中。)

## 2. 单遍性能重写(FD3;解 1.3)

- [x] 2.1 `discover_controls.py` 抽出「**物化文件清单一次**」:`walk_sources(repo, …)` 调用一次,产 `[(path, lang, rel), …]`(受 `--max-files` 截断),供 `build_call_graph_bounded` 与 `scan` 共用,消除两次全仓遍历。(落地为 `collect_sources`。)
- [x] 2.2 `discover_controls.py` 「**每文件读一次**」:`index_files` 一次性 `read_text(encoding="utf-8", errors="replace")` 并缓存 `text`/`lines`;`build_call_graph`/`scan_candidates` 共用缓存,删除重复 `read_text`。
- [x] 2.3 `discover_controls.py` 「**每文件一次 splitlines**」:`scan_candidates` 候选 snippet 改用预算 `lines[ln-1]`,删除每候选重复 split。
- [x] 2.4 `discover_controls.py` 「**enclosing 预排序 + 二分**」:`_node_index` 每文件一次性预排序 class/fn 节点(首遇去重保序),`_enclosing_from_index` 按 `bisect` 取最近前驱,取代每候选全文 finditer。
- [x] 2.5 回归确认:既有 `tests/test_init_discover.py` + `test_init_clusters.py` 全绿(候选集合/聚类字段等价);另加 `_QUICK_RX` 预筛选(各类 pattern 的精确并集,零假负,候选集合不变)。
- [x] 2.6 (新增·实施时发现)**预筛选** `_QUICK_RX`:无安全标记的文件跳过 per-category 扫描 + node index;真实仓多数文件无标记 → 扫描段近常数。exact(并集,无假负),候选集合不变。

## 3. 可观测:i0 大仓预检 + stderr 进度(FD4)

- [x] 3.1 `discover_controls.py`:扫描/调用图阶段每 N(默认 1000)文件向 **stderr** 打印进度;stdout 仍只在末尾打印既有 JSON 摘要(契约不变)。`N` 经 `--progress-every` 覆盖。
- [x] 3.2 两份 `mgh-init.md`:i0 自检段加「统计源文件数,超 `--large-repo-threshold`(默认 15000)则前置建议 `--scope`+`--merge`」;参数表加 `--progress-every`/`--large-repo-threshold`。
- [x] 3.3 `discover_controls.py`:`scan` 在扫描前用物化清单计数,超 `--large-repo-threshold`(默认 15000)时向 stderr 打印大仓建议(继续执行,不中止——D11)。

## 4. 编排器黑盒纪律(FD5;解 1.1)

- [x] 4.1 两份 `mgh-init.md`:「You are the orchestrator」段后加显式条款——「确定性脚本是**黑盒**,经 Bash 执行,**禁止 `Read` 进上下文**;仅 subagent 的 `core/prompts/stages/*.md` 按需读取」,对齐 `mgh-sast.md`。
- [x] 4.2 (FD7·实测反馈追加)两份 `mgh-init.md` 正文**最前列**加「角色铁律」:编排器 = 宿主 agent、MUST NOT `Write` 任何 `.py`(具名反例 `mgh_init.py`)、MUST NOT `Read` 叶子 `.py` 源码、合法 `Write` 仅产物;「Implement it」→「Carry it out」。

## 5. 安装自检 + 回归单测(FD6)

- [x] 5.1 `install.sh`:镜像 `core/` 后校验 `<dest>/mgh-core/scripts/` 下 `expand_scope.py`/`discover_controls.py`/`chunk_sources.py` 三者共存,缺一即 `echo ✗ … >&2; exit 1`。(实测 `./install.sh --opencode <tmp>` 自检通过。)
- [x] 5.2 新增 `tests/test_init_runtime.py`:(a) `subprocess` 在**非脚本目录 cwd** 执行两脚本,断言不报 `No module named 'expand_scope'` / 不报 `UnicodeDecodeError`;(b) 子进程跑 `main()` 验证候选类别 + entry_points 反连 + clusters 完整(等价);(c) 单文件 200 候选 enclosing 计时不退化(宽松 <10s)。
- [x] 5.3 零依赖自检:`grep vvaharness` 无输出;AST 扫描两脚本仅 `expand_scope`(本地兄弟,D2 复用)非标准库,无第三方 import;三脚本 `py_compile` 通过。

## 6. 端到端验证

- [x] 6.1 `py tests/test_init_discover.py` + `test_init_clusters.py` + `test_chunk_sources.py` + `test_init_runtime.py` + `test_deterministic.py` 全绿(共 27 测试)。
- [ ] 6.2 `./install.sh --opencode <javarepo>`:自检通过、三脚本就位 **(本机已验证)**;在 **21611 文件 Java 仓**实测 `/mgh-init --format opencode`——<5min 完成、无 import/编码错误、产物齐全、stderr 有进度 **(待用户真机;本机合成 3000–4000 文件仓 <60s,warm 读 21611 外推 ~3s I/O + 秒级 regex)。
- [ ] 6.3 同仓 `--format claude` 复测 **(待用户真机)**;确认 `--format` 仅作用于 T3、发现阶段不再误传 **(本机 grep 复核 0 命中)**。
- [x] 6.4 抽查:从非脚本目录 cwd 直接 `py <path>/discover_controls.py --repo . --out .mgh-init` 成功(FD2);已通过安装后路径 + `test_init_runtime` 子进程用例 + 冒烟三重验证,无需 `python -c exec` 绕行。
- [x] 6.5 回滚演练:改动面 = **5 文件改 + 1 测试新增**(`core/scripts/discover_controls.py`、`core/scripts/chunk_sources.py`、`releases/opencode/command/mgh-init.md`、`releases/claude-code/commands/mgh-init.md`、`install.sh` + `tests/test_init_runtime.py`);无 schema/数据迁移。

> **遗留**:6.2 / 6.3 的「21611 文件真机实测」需在用户的 Java 仓执行(本环境无该仓)。机制侧已由单测 + 合成规模 + 安装自检 + warm-read 外推充分覆盖,预期 <5min;真机复测请用户跑一次 `/mgh-init --format opencode` 与 `--format claude` 确认。
