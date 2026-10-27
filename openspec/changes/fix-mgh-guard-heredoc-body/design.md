# design — fix-mgh-guard-heredoc-body

> 一个预处理函数 + 接线,不改任何判定语义本身。安全方向单向:只消灭误拦,NEVER 制造漏拦。

## D1 剥离的产出与消费者

新增内部函数 `_strip_data_bodies(text) -> (judged_text, stripped_spans)`:输入完整 Bash
命令文本,输出"命令结构文本"(供 token 提取与判定)。消费者恰为四类结构判定:路径净网
(rule m catch-all)、写动词、删除动词、重定向。**不消费**剥离文本的规则:激活判定、
UTF-8 解码、脚本扩展名写拦截、`py -c` 内省拦截、内联解释器拦截(见 D2)、temp-I/O、
文件关联——这些按原文或按 payload 字段工作,与 heredoc 无关。

## D2 解释器喂养的优先级(不松的关键)

既有 requirement "Bash inline interpreter code blocked in all feeding forms (heredoc /
here-string)"(规格 1584 行起)辖域 = heredoc/here-string 喂给**解释器进程**的代码。
实现顺序 SHALL 是:内联解释器检测在**原文**上先行(命中最先退出,exit 2),结构剥离仅
对未命中解释器喂养的文本生效;接收命令按动词表识别解释器调用(`py`/`python`/`python3`/
`node`/`powershell`/`pwsh` 等既有表)。双保险:即使剥离实现有缺陷把解释器 heredoc 剥了,
先行检测已拦——本 change 的失败模式方向仍然单向(多拦,不少拦)。

## D3 识别与匹配规则(bash heredoc)

- 操作符:行内 `<<`(含 `<<-`)后跟定界符 token(引号形态 `<<'EOF'`/`<<"EOF"` 与裸
  `<<EOF` 都认);同一命令多个 heredoc 逐个处理。
- 数据体 = 定界符行之后到"仅含终结定界符的行"(允许行首制表符,`<<-` 语义;引号形态的
  终结符不剥引号)为止;终结行剥离,数据体替换为单空格。
- **未终结**(到文本结束都没等到终结行)→ 该 heredoc 段**不剥离**(整段保留判定)——
  保守方向(D 节总则);真实失败的 heredoc 本就会在 shell 层报错,不值得为其冒险。
- 数据体内部出现与终结定界符相同的行按 shell 语义即终结(这是正确行为,非边界)。

## D4 PowerShell here-string

配对形态 `@"`…`"@` 与 `@'`…`'@`(起始 `@`/引号后到行尾,终结为行首 `"@`/`'@`);数据体
同样替换为单空格;未配对 → 不剥离(保守)。here-string 喂解释器(`Invoke-Expression @"
…"@`)由 D2 动词表覆盖(`Invoke-Expression` 入解释器表)。

## D5 同步与测试策略

- canonical `core/scripts/block_adhoc_scripts.py` 改后 MUST 字节级同步
  `releases/claude-code/hooks/` 与 `releases/opencode/hooks/` 两份副本(parity 测试强制,
  既有机制零新增)。
- 红测试先行(任务 1.1):两个观测形态(yyyy/MM/dd、`>2000`/`$`)今天被拦 → 实现后通过;
  安全保真组(解释器喂养仍拦、命令部分真违规仍拦、未终结保守)同步入测试,删任一分支即红。
- 守卫既有测试面很大(300+ 用例):新增用例收敛进 `test_block_adhoc_scripts.py` 的新
  TestCase,不动既有断言。

## D6 契约与文档

`core/contracts/hooks/runtime-enforcement.md` 的净网/重定向节补一段"数据体剥离"语义与
保守边界;根 `AGENTS.md` 诚实边界守卫段:残余清单移除"heredoc 内容误伤"类(以本 change
为准),补一条"未终结 heredoc 保守判全文"与"非 heredoc 位置的日期形态 token 仍是已知
残余"(不扩词表白名单)。

## D7 明确不做

- 非引号/非 heredoc 位置的 `yyyy/MM/dd` 类 token 白名单(先修结构不猜词表);
- `<<<` here-string(bash 单串喂 stdin):其内容经变量/stdin 而非文件,量级小,留残余
  清单;如后续观测到再立项;
- 任何判定语义(路径阶梯、动词表、允许集)的调整——零触碰。
