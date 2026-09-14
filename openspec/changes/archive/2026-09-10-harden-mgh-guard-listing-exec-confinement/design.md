## Context

真机 Linux 首跑(mgh-core 只装根 proj、run 在 `independent_sub_project/`)暴露三个守卫缺口与
一个 stderr 缺陷,现场均已核实:

1. **列目录动词不设防**:`block_adhoc_scripts.py` 读侧 Bash 逃生路由 `_FILE_SEARCH_VERBS`
   只含搜索动词(`rg/grep/findstr/find/fd/ag/ack`);`ls /home`、`ls /adhome` 放行。
2. **解释器带外执行不设防**:规则 (e) file-association 只拦**无解释器前缀**的脚本执行;
   `py <树外脚本>` 因「显式解释器前缀 → 显式放行」(`_LAUNCHER_PREFIXES` 分支 `return False`),
   且无任何规则判定所执行脚本的**位置**。
3. **产品自身缺失安装无 recipe**:mgh-core 未装时 shell 报原生 `can't open file`,无任何指引,
   弱模型自然跨目录漫游找脚本/提示词;`t1-task.md` 给了提示词路径但无「唯一位置 + 找不到即
   failed」硬边界,`init-induct.md` 路径锚定段只防「拼错路径」不防「位置不存在就漫游」。
4. **`list_clusters.py:69` SyntaxWarning**:模块 docstring 中 `` `/` `\`` `` 的 `` `\` `` 是
   非法转义;`resume_state.py` import 链加载该模块时每次触发编译告警污染 stderr(退出码不受
   影响——告警属 warnings 体系,非异常)。全仓 `py_compile` 扫描仅此一处。

## Goals / Non-Goals

**Goals**
- 守卫双端(byte-identical)新增三条 Bash 规则:列目录越树、解释器越树执行、mgh-core 缺失
  安装 stop-all——每条都镜像既有规则形态(动词集 + 首位/分隔符锚定 + operand-vs-arg 辨析 +
  degrade-to-pass)。
- fan-out 任务模板 + reader stage 提示词:提示词路径硬钉唯一位置 + not-found 即 failed ack。
- 叶脚本 stderr 编译纯净契约 + 全量零告警回归测。

**Non-Goals**
- 不扩守卫工具面(仍只 Bash 规则;`Read`/`Glob`/`Grep` 工具抽象层已有越树判定,wiring 不动)。
- 不做 Bash 完整解析(管道喂动词、alias、env 注入路径、相对路径列举仍不保证——沿用各规则
  既有的 regex-over-observed-shape 立场,如实披露)。
- 不改 `list_steps.py` 等其他脚本的既有告警面(全仓扫描确认仅 `list_clusters.py` 一处)。
- 不拦截 `py -c` 代码体的位置判定(已有 introspection/write-relabel 规则管辖,recipe 不同)。

## Decisions

### D1 — 列目录规则镜像 file-search 规则,动词集独立

新 `_LISTING_VERBS = ("ls", "dir", "get-childitem", "gci")` + `_LISTING_VERB_RX`(与
`_FILE_SEARCH_VERB_RX` 同形:首 token / `;|&` 分隔符后锚定,`\b` 收尾)。scope 判定复用
`_ABS_PATH_TOKEN_RX` findall + cwd fallback 的既有逻辑,与 `_out_of_tree_file_search` 共用
判定骨架(抽共享 helper 或复制最小形态,见 D5)。
理由:真实失败形状就是 `ls /home`/`ls /adhome`;`find` 已在搜索集,列目录与搜索是同类读侧
枚举行为,recipe 同用 `_read_recipe`。独立动词集而非并入搜索集:`Get-ChildItem`/`gci` 是
pwsh 语义、`dir` 在 cmd/pwsh 是列目录在部分 shell 是搜索,分开便于 recipe 与未来增删。
替代方案:把 `ls` 并入 `_FILE_SEARCH_VERBS` —— 否,`ls` 的参数语法(无 pattern 语义)与
搜索动词不同,合并会让 recipe 与文档失真。

### D2 — 解释器执行规则:判「第一个脚本扩展名位置参数」

新 `_INTERPRETERS = ("py", "py3", "python", "python3", "python2")`;命中 `_PYC_RX` 同形的
解释器首 token(排除 `-c`/`-m` 形态,那两形态已有规则管辖)后,扫描命令内脚本扩展名 token:
取**第一个**非 `--flag` 值位置的脚本路径判树内外。operand-vs-arg 辨析沿用 file-association
规则的保守立场:只认「`--flag <path>` 对是 flag 的值」形态,regex 不解析完整 argv——凡前置
token 以 `--` 开头,其后一个 token 视为其值跳过;首个裸脚本扩展名 token 即被执行脚本的
保守近似。`py -c`(无脚本参数)不进本规则。
理由:`py .claude/mgh-core/scripts/resume_state.py --target .`(in-tree,放行)与
`py /home/x/run.py`(out-of-tree,拦)的真机对比形态正好覆盖位置参数面;误伤面控制在
「解释器 + 树外脚本路径」这一就是要拦的形状。`--flag` 值不判,因为确定性脚本的全部
`--flag <path>` 都是**数据**路径(in-tree 由写侧/读侧规则另判),不是被执行代码。
替代方案:把树外脚本执行并入规则 (e) 的 launcher-exempt 逻辑 —— 否,规则 (e) 的语义是
「文件关联致死锁」,recipe 完全不同;分开规则各自的 stderr 指引才准确。

### D3 — mgh-core 缺失安装 = stop-all 专用规则(非读侧 recipe)

命中条件:命令含 `mgh-core/scripts` 路径段 ∧ 脚本扩展名 token,其解析路径**不存在**
(`Path.exists()` False)**或**在树外 → exit 2 + 专用 stop-all recipe(停止全部任务、要求
用户在当前项目目录 install、NEVER 跨目录搜索)。**规则次序:置于所有其他 Bash 规则之前**
(缺失安装是 terminal 状态,后续规则 recipe 无意义;`py .claude/mgh-core/scripts/...` 同时
命中 D2 时,stop-all recipe 优先——它才是真根因)。
理由:与读侧 recipe(「用 sanctioned 原语」)语义不同——这里没有 sanctioned 出口,唯一
正确动作是**停 + 让人装**;规则 (f2) 叶源码 Read 拦截已覆盖 `Read` 面,Bash 面(解释器
执行引用)由本规则补齐。判定用 `Path.exists()`:mgh-core 装了但路径拼错(段在、盘上无)与
根本没装,对 subagent 都是同一处境(下一步必然 FileNotFoundError),同 recipe 不失真。
树外分支:命令引用了**别的项目**的 mgh-core(「去根 proj 找」的漫游形态)→ 同 stop-all。
替代方案:只在提示词层写「找不到就停」——否,提示词护栏对弱模型不可靠,承 R5.7「能用 hook
确定性闭环的不靠自觉」;hook 拦的是**引用即拦**(引用树外/不存在 mgh-core 脚本的 Bash 命令),
在 FileNotFoundError 发生前就给 recipe。

### D4 — 提示词硬钉:t1/scout/t3 任务模板同位补句 + init-induct 锚定段补句

`t1-task.md` 的行为加载段(现「READ it first and follow it exactly」)追加硬边界句:该路径
是提示词的**唯一位置**;Read 失败 → **立即**回 `failed mgh-core prompts not installed at
<path>`,NEVER 跨目录搜索。`t3-task.md`/`scout-task.md` 同位同句(模板同形)。
`init-induct.md` 路径锚定纪律段追加一句:锚内预期路径不存在 → 毒输入同款处理(failed ack,
不漫游)。
理由:模板是 subagent 唯一必读入口,句放加载指令旁注意力最集中;三个读模板同形同补防漂移。

### D5 — 守卫实现形态:两份 release 副本 byte-identical

`releases/claude-code/hooks/block_adhoc_scripts.py` 与 `releases/opencode/hooks/` 同名文件
字节级同步(既有 parity 测试兜底)——所有规则改动**双写**,不引入单一真源生成步骤(现状
已是双写 + parity 测试,维持)。判定 helper(`_out_of_tree_scope(command, target, cwd)` 形态)
在守卫文件内私有,不与 `core/scripts/` 共享(hook 是分发产物,零依赖自包含)。

### D6 — docstring 修复用 raw string

`list_clusters.py` 模块 docstring 改 `r"""` 开头(raw):docstring 内含 `` `\` ``、Windows
路径反斜杠等示例是合法内容,raw string 一处消除全部转义语义,零内容变更。回归测
`tests/test_no_compile_warnings.py`:`py_compile.compile` + `warnings.simplefilter("always")`
全量扫 `core/scripts/*.py`,捕获任何 Warning 即 fail 列出脚本名。

## Risks / Trade-offs

- [D1 列目录集不含所有 shell 别名/未来动词] → recipe 与 docstring 如实声明
  regex-over-observed-shape 边界(与 file-search 规则同立场);动词集后续可增量补。
- [D2 `--flag <path>` 值跳过的保守 argv 近似会漏 `--flag=<path>=` 连写形态的脚本参数]
  → 确定性脚本契约无一用连写形态(`py x.py --flag=v` 不存在),漏面为空集;如实披露。
- [D3 stop-all 误伤:mgh-core 装在自定义路径(哨兵 out_roots 场景)] → 判定锚是
  「命令引用的路径解析」,自定义 install 路径经命令逐字传入 → 解析存在且(通常)在树内 →
  放行;仅当引用路径真的不存在/在树外才拦,与「装没装」的事实一致。
- [D3 早于其他规则改变既有 recipe 优先级] → 仅当命令同时含 mgh-core 引用缺失才短路,
  其余命令路径行为不变;回归测覆盖「既有规则各自 hit 不受新规则影响」。
- [D4 模板加句增 token] → 每模板 ≤ 2 行,占位符替换机制不变;R5.6 预算余量充足。

## Migration Plan

单 commit 交付:守卫双写 → 双端 parity/单测 → 模板/提示词补句 → docstring raw + 回归测 →
契约 lint(`tools/check_contracts.py`)+ purity lint 全绿 → install.sh 自检无新面(守卫
文件名不变,无接线变更)。回滚 = revert 单 commit;无数据/磁盘格式变更。

## Open Questions

(无——三条规则的边界形态已由真机失败形状钉死;若后续发现新 shell 形态,动词集增量补,
不改 requirement 结构。)
