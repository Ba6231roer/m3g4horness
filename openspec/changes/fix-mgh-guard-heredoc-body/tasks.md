# tasks — fix-mgh-guard-heredoc-body

> 执行约定:先红后绿;守卫 canonical 改后三副本字节级同步;收尾 lint 四件套 + bump。

## 1. 红测试(复现两个观测形态 + 安全保真组)

- [ ] 1.1 扩 `tests/test_block_adhoc_scripts.py` 新 TestCase(红):①`cat > <树内> <<'EOF'`
      数据体含 `yyyy/MM/dd` → 今天被拦(退出码 2),断言"修复后应通过"的目标态先以
      `expectedFailure`/skip 标注并注明本任务号;②数据体含 `threshold >2000` 与 `$foo`
      同形;③数据体含树外绝对路径字符串(纯数据)→ 应通过
- [ ] 1.2 安全保真组(红→应保持拦截):①`py - <<'EOF'` 喂解释器 → 仍拦(既有内联解释器
      requirement);②`python <<'EOF'`/`node <<EOF` 同判;③重定向目标树外
      (`cat > D:/out/f <<'EOF'`)→ 仍拦;④命令部分含树外读 token → 净网仍拦;
      ⑤未终结 heredoc → 按原文判(树外 token 在体内容仍拦)
- [ ] 1.3 PowerShell here-string 用例:`Set-Content -Path <树内> -Value @" … yyyy/MM/dd
      … "@` → 应通过;`Invoke-Expression @" … "@` → 仍拦;`@"` 未配对 → 保守判全文

## 2. 实现(预处理 + 接线,design D1–D4)

- [ ] 2.1 `core/scripts/block_adhoc_scripts.py` 新增 `_strip_data_bodies(text)`:bash
      heredoc(`<<`/`<<-`、引号/裸定界符、`<<-` 制表语义、未终结保守)+ PowerShell
      here-string(`@"`/`@'` 配对、未配对保守);返回命令结构文本
- [ ] 2.2 接线:内联解释器检测按**原文**先行(确保 D2 优先级);路径净网/写动词/删除/
      重定向四类判定改吃命令结构文本;其余规则零触碰
- [ ] 2.3 使 1.1–1.3 全绿(去掉 1.1 的目标态标注)
- [ ] 2.4 三副本字节级同步:`releases/claude-code/hooks/block_adhoc_scripts.py` 与
      `releases/opencode/hooks/block_adhoc_scripts.py`;`test_opencode_hook_parity` /
      `test_dsh_hook_parity` / `test_install_hook` 跑绿

## 3. 契约与文档

- [ ] 3.1 `core/contracts/hooks/runtime-enforcement.md` 净网/重定向节补"数据体剥离"
      语义(含解释器喂养豁免与未终结保守);行号如需 allowlist 重钉则同步
      `tools/check_distributed_purity.py` 白名单
- [ ] 3.2 根 `AGENTS.md` 诚实边界守卫段:残余清单更新(heredoc 内容误伤类移除;补
      "未终结保守判全文"与"非 heredoc 位置日期形态仍是残余")
- [ ] 3.3 评审登记册 #22 处置更新为"已立项 fix-mgh-guard-heredoc-body"(维护者私有
      文档区,随 apply 会话一并改)

## 4. 回归与收口

- [ ] 4.1 定向回归:`test_block_adhoc_scripts`(全量)+ 三端 parity 三件 +
      `test_install_opencode_plugin` + `test_zero_deps` / `test_no_compile_warnings`
- [ ] 4.2 六域冒烟:各域一条 heredoc 写入用例(init 域以真实 checkpoint 形态)过
      `py core/scripts/block_adhoc_scripts.py` 直接调用冒烟
- [ ] 4.3 lint 四件套:`check_contracts` / `check_distributed_purity` /
      `check_distributed_prompt_budget` / `check_plain_language`(存量 exit 2 之外零新增)
- [ ] 4.4 bump VERSION + CHANGELOG;本文件逐项勾选
