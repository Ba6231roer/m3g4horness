# tasks — fix-mgh-guard-enforcement-integrity

> 约定:回归测试一律**先红后绿**;`block_adhoc_scripts.py` 的 canonical 副本改后 MUST 同步
> `releases/{claude-code,opencode}/hooks/` 两份字节级镜像(parity 测试强制);`py` 为本机解释器。

## 1. 先红:回归测试(修复前确认失败形态)

- [ ] 1.1 `tests/test_block_adhoc_scripts.py` 新增「写目的地统一」组:(a) sdr 域(带哨兵
  `read_roots`)+ `echo x > <readroot>/f` → 断言 exit 2 + 写侧 recipe(修复前全链路 exit 0);
  (b) sast/sra/srr 任一域 + `echo x > D:\out\f` → exit 2(修复前 redirect 分支放行);(c) init 域 +
  哨兵 `out_roots` + `Copy-Item x <out_root>\x.json` → exit 0(修复前写动词面拦);(d) init 域 +
  `Copy-Item x <readroot>\x.js` → exit 2(只读根永不可写)
- [ ] 1.2 同文件新增「stdin 编码」组:monkeypatch `sys.stdin` 为
  `io.TextIOWrapper(io.BytesIO(utf8_payload), encoding="gbk")`(payload `cwd` 含中文路径 +
  哨兵链命中 + 越树 Write)→ 断言 exit 2(修复前按 cp936 错解 → exit 0 放行);另断言
  空/非 JSON 管道维持 exit 0 fail-soft
- [ ] 1.3 同文件新增「解释器规则」组:`py -m pytest <树外 test_x.py>` 与
  `py -c "import x" <树外 helper.py>` → 断言**不**以「执行越树脚本」recipe 拦(修复前误拦);
  `python3.11 -c "import json; …"` → 断言以内省 recipe 拦(修复前绕过);
  `python3.12 - <<'EOF'` heredoc 形 → 断言以 inline 形 recipe 拦(修复前绕过)
- [ ] 1.4 同文件新增「规则 l 模式豁免」组:`grep -n "mgh-core/scripts/run.py" notes.md`(notes.md
  在树内)→ 断言不触发 stop-all(修复前误拦);`cat .claude/mgh-core/scripts/不存在.py` → 断言
  stop-all 仍拦(读动词不豁免)
- [ ] 1.5 同文件新增「单一 cwd 源」组:payload `cwd=<target 子目录>`(进程 cwd 在别处)+
  `type ..\..\secret.txt` → 断言按 payload cwd 解析后 exit 2(修复前按进程 cwd 解析误判)
- [ ] 1.6 同文件新增「净网边界 + f2 大小写」组:`echo x >D:/out/f`(无空格重定向)→ 断言净网
  exit 2(修复前 token 提取不到);`Read file_path=<target>\.CLAUDE\Mgh-Core\Scripts\x.py` →
  断言叶源码拦截 exit 2(修复前大小写变体绕过)
- [ ] 1.7 同文件新增「H13 语义锚」:init 哨兵激活 fixture → 受信子树外 `.md` 与 `.json` 的
  Write/Edit → 断言 exit 2(把「残留哨兵 = 全面写锁」钉在测试上)
- [ ] 1.8 `tests/test_opencode_hook_parity.py` / `tests/test_dsh_hook_parity.py`:源形态断言各加
  「守卫文件存在性预检(`existsSync`)存在」与「`can't open file` 签名 fail-soft 分支存在」
  (修复前无此形态 → 红)
- [ ] 1.9 纪律表污染回归(就近纪律面测试文件,`test_resume_state.py` 或 `test_list_steps.py`):
  `get_discipline("t1")` 返回值 append 后再次调用 → 断言共享表未被污染、两脚本输出仍逐字一致
  (修复前永久污染 → 红)

## 2. 统一写目的地判定(D1,H2 + out_roots 三入口翻转)

- [ ] 2.1 新增 `_bash_write_dest_blocked(dest, domain, target, out_roots)`:allowlist 域走
  `_allowlist_write_blocked`(树内 P1 + 树外 out_roots,与 Write/Edit 工具面同查询);四域走
  `_is_out_of_tree`;`read_roots` 不入谓词
- [ ] 2.2 mutation 分支(含 `py -c` 写形态重标记)与 redirect 循环改走该谓词;`<cwd>` 目的地以
  判定 cwd 代入;删除 `_redirect_in_sanctioned`;移除 `_emit_bash_write_block` 死参 `out_roots`
  (调用点同步);四域 out_roots 锁步注记落代码注释
- [ ] 2.3 canonical `core/scripts/block_adhoc_scripts.py` + `releases/claude-code/hooks/` +
  `releases/opencode/hooks/` 三份同步(字节一致);跑 1.1 转绿 + `test_block_adhoc_scripts` 既有
  用例零回归

## 3. 解码与单源(D2/D6,H3 + cwd 双源)

- [ ] 3.1 main 入口改 `json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))`
  (`StringIO` 测试替身 getattr 回退 `.read()`);异常面 fail-soft 不变;跑 1.2 转绿
- [ ] 3.2 判定 cwd 与哨兵锚单源(payload `cwd` 优先、回退进程 cwd;`judge_cwd` 收拢 + 注释);
  跑 1.5 转绿;三份镜像同步

## 4. 正则与规则收口(D3/D4/D5/D9)

- [ ] 4.1 `_out_of_tree_interpreter_exec` token 走查遇 `-c`/`-m` → return False;删
  `_INTERPRETER_RX` 负向前瞻死代码;跑 1.3 前半转绿
- [ ] 4.2 `_PYC_RX` / `_PY_INLINE_RX` 版本段 `[0-9]*` → `[0-9.]*`(两处同改);跑 1.3 后半转绿
- [ ] 4.3 `_mgh_core_missing_install` 改按简单命令分段:搜索动词段的首个非旗标操作数(模式)豁免,
  读动词不豁免;跑 1.4 转绿
- [ ] 4.4 `_PATH_TOKEN_RX` 左边界类补 `<` `>`;`_is_leaf_script_read` 段比较 `.lower()`;docstring
  规则 (m) 重复段删除;跑 1.6 转绿;三份镜像同步

## 5. 双 shim fail-soft 与纪律表深拷贝(D7/D8)

- [ ] 5.1 `releases/opencode/plugins/block_adhoc_scripts.ts`:spawn 前 `existsSync`(node:fs)
  预检 → 缺失放行 + 诊断;code===2 且 stderr 匹配「can't open file」签名 → fail-soft 放行 + 诊断
- [ ] 5.2 `releases/dsh/plugins/mgh-guard.ts` 同修(node:fs `existsSync` 同款);跑 1.8 双 parity
  转绿 + `test_install_opencode_plugin` / `test_install_dsh` 分发镜像过
- [ ] 5.3 `discipline_core.py` `get_discipline` 改 `copy.deepcopy` 返回(未知步/域的浅拷贝形态
  一并消灭);跑 1.9 转绿 + `test_resume_state` / `test_list_steps` 既有用例零回归

## 6. H13 文档与收尾(D10)

- [ ] 6.1 `core/prompts/fragments/orchestrator-discipline.md`(:51 括注)与
  `core/contracts/hooks/runtime-enforcement.md`(completion 段)按域改述残留哨兵真实语义
  (init/ut-init = 受信子树外全面写锁 + 树外读拦;四域 = 脚本写/越树写/树外读拦)+ 处置路径
  (rm / resume 重写;init 完成态残留已被 `resume_state --check` 检出);跑 1.7 转绿(语义锚测试)
- [ ] 6.2 定向面全绿确认:`test_block_adhoc_scripts` / `test_opencode_hook_parity` /
  `test_dsh_hook_parity` / `test_install_hook` / `test_install_opencode_plugin` / `test_install_dsh` /
  `test_resume_state` / `test_list_steps` / `test_zero_deps` / `test_no_compile_warnings`;
  **全量回归免跑**(未触 `core/contracts/` 既有 requirement 语义之外的分发脚本行为——hook 三端接线
  面零改动,仅 shim 内部 fail-soft 分支;若有异议按 R5.8 全量闸门执行)
- [ ] 6.3 lint:`python tools/check_distributed_purity.py`(fragment 改述)/
  `check_contracts.py`(守卫无 CLI 面,应零变化)/ `check_distributed_prompt_budget.py`(未触壳)
  / `check_plain_language.py`(人类面无新文件)
- [ ] 6.4 实机抽查:GBK 控制台会话(或 `chcp 936` 子进程)下以中文路径 cwd 喂 UTF-8 payload →
  拦截生效;四域 fixture 上重放评审 H2 实测命令(`echo x > <readroot>/f`)→ exit 2
- [ ] 6.5 bump `VERSION`、补 `CHANGELOG.md`;git commit(发现编号 + 先红后绿计数);归档走
  `/opsx:archive`(specs 增量回写三面主规格)
