# design — fix-mgh-guard-enforcement-integrity

## Context

批次 1 已归档(VERSION 0.1.68);本批涉及文件(`block_adhoc_scripts.py` 1518 行 /
`discipline_core.py` / 双 `.ts` shim / `orchestrator-discipline.md`)经 git diff 核实自评审基线
(0.1.60)以来零改动,仅 `runtime-enforcement.md` 被 sdr 批次挪过 28 行(H13 段落现位于 ~146-148,
语义未变)。13 项发现全部在当前代码逐行核实:

- **H2**:`_redirect_in_sanctioned`(:1129-1139)对无 allowlist 域 `return True`;redirect 越树分支
  (:1358-1360)`continue` → 四域整体放行。该函数被用在语义相反的两个调用点(树内 P1 白名单查询 vs
  树外拦截豁免)是根因。
- **out_roots 三入口翻转**:`_out_of_tree_mutation` 返回 `oot=True` 后 main(:1257-1259)无条件拦——
  init 域写动词到哨兵 `out_roots` 内的目的地被拦,而同一目的地 Write/Edit 工具面
  (`_allowlist_write_blocked` 咨询 out_roots)与 redirect 面放行;`_emit_bash_write_block` 的
  `out_roots` 形参从未被读(想接线未接的痕迹)。
- **H3**:main 入口 `json.load(sys.stdin)`(:1200)解码随控制台代码页;判定 cwd 用 `Path.cwd()`
  (:1203)而哨兵锚用 payload `cwd`(:1204-1209)——双源。
- 其余:`_INTERPRETER_RX` 负向前瞻 `(?!-(?:c|m)\b)`(:318-320)只排除粘连形;`_PYC_RX`/
  `_PY_INLINE_RX` 版本段 `[0-9]*`(:224/:244);`_mgh_core_missing_install` 全 token 无差别判引号内
  搜索模式(:704-719);`_PATH_TOKEN_RX` 左边界类 `[\s;&|("'=]`(:339-342)缺 `<`/`>`;
  `_is_leaf_script_read` 的 `parts[i] == "mgh-core"`(:583-585)大小写敏感;docstring 规则 (m) 段
  (:145-179)整段两遍;双 shim(`releases/opencode/plugins/block_adhoc_scripts.ts` :139-142、
  `releases/dsh/plugins/mgh-guard.ts` :168-172)把 code===2 一律当 deny;`get_discipline`
  (`discipline_core.py` :391-398)返回共享表引用(`table.get(step)` 直返 + `dict(_EMPTY)` 浅拷贝)。
- **镜像面**:canonical `core/scripts/block_adhoc_scripts.py` + `releases/{claude-code,opencode}/hooks/
  block_adhoc_scripts.py` 两份字节级镜像(parity 测试强制);`.ts` shim 各自为分发源。

## Goals / Non-Goals

**Goals:**

- 三个写入口(Write/Edit 工具面 / Bash 写动词 / redirect)对同一目的地**同判**(按域镜像工具面),
  「声明只读根永不可写」在所有写面成立;守卫在 GBK 控制台代码页下正常激活与判定。
- 误拦面收敛(`-m`/`-c` 尾参、grep 模式)、绕过面收敛(带点版本、大小写变体、无空格重定向)。
- 双 shim 的 fail-soft 契约「守卫不在 → PASS」真正成立;纪律表不可被消费方污染;H13 两处文档讲真话。

**Non-Goals:**

- `cat`/`Get-Content` 读叶脚本源码的 Bash 面缺口(评审未列;f2 只覆盖 Read 工具面)——另立。
- 净网的别名/变量间接、glob 展开结果判定等既有披露残余(诚实边界已记录,非本批回归)。
- opencode 插件 normalize 构造 `cwd` 字段(其插件进程 cwd 即最佳可得信号,单源化后无错根面)。
- 四域 Write 工具面是否咨询 `out_roots`(维持不咨询——见 D1 被否方案)。
- install.sh 分发拷贝 `__pycache__` 的卫生问题(批次 4)。

## Decisions

### D1 — 统一写目的地谓词,按域镜像工具面(治 H2 + 三入口翻转)

新增单一谓词 `_bash_write_dest_blocked(dest, domain, target, out_roots)`:

- **allowlist 域(init/ut-init)**:`_allowlist_write_blocked(dest, target, out_roots, subtrees)`——
  树内须落受信子树/AGENTS.md(P1),树外须落哨兵 `out_roots`(与 Write/Edit 工具面**同一查询函数**);
- **四域(sast/sra/srr/sdr)**:`_is_out_of_tree(dest, target)`——树外即拦、树内放行(其工具面同样
  不咨询 out_roots,逐字镜像)。

三个调用点统一走它:mutation 分支(替换 `mut_oot` 无条件拦 + P1 双段)、redirect 循环(替换
`_redirect_in_sanctioned`,`<cwd>` 目的地以判定 cwd 代入)、`py -c` 写形态重标记(随 mutation 分支)。
`_redirect_in_sanctioned` 删除;`_emit_bash_write_block` 死参 `out_roots` 移除(调用点同步)。规则
次序不变(mutation/redirect 仍先于兜底净网,写侧 recipe 优先浮出——净网 requirement 的既有场景保持)。
**`read_roots` 在谓词内不出现**(任何写面永不豁免只读根)。

被否方案:(a) 按评审字面「四域树外 + 授权根内放行」让 Bash 面咨询 `out_roots`——四域的 Write 工具面
不咨询,会造成新的「工具面拦、Bash 面放行」翻转,只是方向反过来;(b) 同时扩展四域工具面咨询
`out_roots`——四域 run 实际不声明 out_roots(写产物全在树内),为零收益改工具面拦截语义。镜像工具面
是零新分歧的最小正确解;四域将来真需要树外写目的地时,走 out_roots + 同步扩两面(锁步,注记在代码)。

### D2 — stdin 强制 UTF-8(H3)

`payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))`,异常面不变
(`OSError`/`ValueError` → return 0 fail-soft)。测试替身兼容:in-process 测试的 `sys.stdin` 若为
`StringIO`(无 `.buffer`)则回退 `sys.stdin.read()`(getattr 探测,一行);TextIOWrapper 替身有
`.buffer`,主路径可测。`replace` 降级仅发生在 payload 本身非 UTF-8 的病态输入(锚点或失效 → 休眠,
如实披露,优于按错误代码页静默错解)。

### D3 — 解释器规则的 `-c`/`-m` 排除交由 token 流(删负向前瞻死代码)

`_out_of_tree_interpreter_exec` 的 token 走查中:遇 `tok in ("-c", "-m")` → `return False`(非执行
脚本形态,内省/写重标记规则拥有该 body);`_INTERPRETER_RX` 的 `(?!-(?:c|m)\b)` 前瞻删除(粘连形
与空格形统一由走查排除)。效果:`py -m pytest <路径>` / `py -c "…" <路径>` 的尾随参数不再被误当
执行脚本。**次级效应如实记录**:该命令若路径 token 越出统一读允许集,兜底净网仍会以**读侧** recipe
拦(读策略使然,非执行脚本误判)——这是既有读面语义,不是本规则的责任面。

### D4 — 带点版本段:`[0-9]*` → `[0-9.]*`

`_PYC_RX` 与 `_PY_INLINE_RX` 的版本段改 `[0-9.]*`(两处同改,单一提交)。安全性:匹配仍需后随
`\s+-c`/`- <<`,裸 `py.`/`pypy` 形不满足(左边界 + 后缀约束);`_INTERPRETERS`(规则 k)不需改
——`python3` 前缀经 `\b` 已在 `python3.11` 内命中,token 走查照常。

### D5 — 规则 l 的搜索模式操作数豁免(读动词不豁免)

`_mgh_core_missing_install` 从「全局 replace 后走全部 token」改为按简单命令分段
(`re.split(r'[;|&]', …)`):段首 token(小写)∈ `_FILE_SEARCH_VERBS` 时,跳过该段**首个非旗标
操作数**(搜索模式);其余 token 照判。读动词(cat/type/Get-Content/gc)操作数是磁盘路径,**不
豁免**(stop-all 面不缩;`cat <缺失安装的 mgh-core 脚本>` 仍拦)。豁免按**位置**不按引号——
`grep -n mgh-core/scripts/run.py notes.md` 的裸模式同豁免。

### D6 — 判定 cwd 与哨兵锚单源

main 中锚解析后 `判定 cwd := anchor`(payload `cwd` 可解析时;否则维持进程 cwd)。落地为:计算
anchor 后将其同时用于 `_resolve_domain` 与全部判定调用(相对 `..` 解析、listing/mutation cwd 缺省、
Glob/Grep 无 `path` 锚)。变量收拢为单一 `judge_cwd`,注释注明语义与回退。

### D7 — 双 shim:存在性预检 + 「can't open file」签名兜底

opencode 插件与 dsh shim 同修:spawn 循环前 `existsSync(guardPath())`(node:fs;Bun 兼容)为假 →
放行 + 一条诊断(不 spawn);code===2 且 stderr 匹配 python「can't open file … .py」签名 → 按
fail-soft 放行 + 诊断(预检的兜底,覆盖 TOCTOU 与非常规缺失形态)。deny 判定收窄为「code===2 且
非签名形态」。parity 测试的源形态断言同步加 `existsSync` 要求。

### D8 — `get_discipline` 深拷贝

`return copy.deepcopy(table.get(step, _EMPTY) if table is not None else _EMPTY)`——未知步/域的
`dict(_EMPTY)` 浅拷贝形态一并消灭(`_EMPTY` 的嵌套列表同为共享引用)。两脚本逐字一致不变量不受
影响(值相等);调用频次下的深拷贝成本可忽略(每 resume/list_steps 调用一次,结构 ~几十项)。

### D9 — 净网左边界补 `<`/`>`;f2 大小写不敏感;docstring 去重

`_PATH_TOKEN_RX` 左边界类改 `[\s;&|("<>'=]`(`<`、`>` 入类;token 体仍须路径锚,`->b` 类中缀不
误触)。`_is_leaf_script_read` 段比较改 `.lower()`(与规则 l 的 `_MGH_CORE_SEG_RX` IGNORECASE 对齐,
Windows 大小写不敏感文件系统)。docstring 规则 (m) 第二份粘贴段删除(纯卫生)。

### D10 — H13 文档按域讲真话 + 回归锚

`orchestrator-discipline.md`(:51 括注)与 `runtime-enforcement.md`(:146-148 completion 段)改述:
残留哨兵按其域激活**完整守卫面**——init/ut-init = 受信子树外一切写(任何扩展名)+ 树外读拦
(≈ 日常开发写锁定);sast/sra/srr/sdr = 脚本写 + 越树写 + 树外读拦(树内非脚本写放行)。两处均
指向处置路径:尽快 `rm` / resume 重写覆盖;init 域完成态残留已被 `resume_state --check` 作为违例
检出(批次 1 落地)。回归测:构造 init 哨兵激活 fixture,断言受信子树外 `.md`/`.json` Write 被
拦(exit 2)——把文档语义钉在测试上。

## Risks / Trade-offs

- [四域 redirect 越树从放行变拦(拦截面只增)] → 检查四域合法流:sdr/sast/sra/srr 的产物路径全部
  在 MGH_TARGET 树内(报告/run 目录/规则文件),无树外 redirect 合法形态;真需要树外写目的地的
  将来形态走 out_roots 声明(D1 锁步注记)。定向测试 + 三域 fixture 回归兜底。
- [`-c`/`-m` 排除后该规则少拦] → 这些 body 本就归内省/写重标记/净网所有;净网对越树 token 的读侧
  拦截保留(D3 次级效应注记),无裸放行面。
- [grep 模式豁免可能放过「真在找 mgh-core 脚本」的搜索] → 搜索模式不是磁盘引用(不执行、不解析),
  stop-all 的对象是「要运行/引用不存在的安装」;wandring 形态(`ls`/`py` 引用)不受豁免影响。
- [判定 cwd 切到 payload cwd 改变 claude 面判定结果] → 正是修复目标(相对路径按发起上下文解析);
  opencode/dsh 无 payload cwd 的路径行为零变化(单源回退同值)。
- [shim 预检引入 fs 依赖] → node:fs `existsSync` 是两宿主运行时标配(Bun 兼容 node:fs);parity
  源形态断言防回退。
- [回滚] → 代码/文档/提示词改动,单 commit revert 即回滚;无磁盘 schema、无 CLI 面、无产物形态变化。

## Migration Plan

1. 先红:13 项各配回归(见 tasks 1.x;GBK 管道用 `TextIOWrapper(BytesIO(utf8), encoding="gbk")`
   替身,修复前 exit 0 / 修复后 exit 2)。
2. 实现 D1-D10;canonical + 两份 `.py` 镜像同步(parity 测试强制),双 `.ts` shim 更新。
3. 定向面:`test_block_adhoc_scripts` / `test_opencode_hook_parity` / `test_dsh_hook_parity` /
   `test_install_hook` / `test_install_opencode_plugin` / `test_install_dsh` / `test_resume_state` /
   `test_list_steps` / `test_zero_deps` / `test_no_compile_warnings`。
4. lint:`check_distributed_purity`(orchestrator-discipline.md 改述)/ `check_contracts`(守卫无
   CLI 面,应零变化)/ `check_distributed_prompt_budget`(未触壳,应零变化)。
5. bump VERSION、CHANGELOG;归档走 `/opsx:archive`(specs 增量回写三面主规格)。

## Open Questions

(无——四域 out_roots 语义取舍已在 D1 裁定并留锁步注记;H11 拍板项属批次 7。)
