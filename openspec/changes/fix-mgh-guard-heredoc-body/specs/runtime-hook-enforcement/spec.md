## ADDED Requirements

### Requirement: heredoc/here-string 数据体从 Bash 命令结构判定中剥离

守卫对 `Bash` 命令做路径净网、写动词、删除、重定向四类结构判定时,SHALL 先做**结构剥离**:
bash heredoc(`<<` 与 `<<-` 操作符,定界符含引号形态)与 PowerShell here-string(`@"…"@`
与 `@'…'@`)的**数据体**(操作符之后、终结定界符之前的内容)**不进入**待判 token 流——
数据体是被写入文件的数据,不是命令结构;重定向**目标**(heredoc 操作符之前的命令部分,
如 `cat > <路径> <<` 的路径)照旧全判。剥离 SHALL 满足:

- **解释器喂养不豁免**:heredoc 的接收命令是解释器调用(`py`/`python`/`python3`/`node`
  等)时,该 heredoc 不剥离,"Bash inline interpreter code blocked in all feeding forms"
  既有 requirement 按原文全拦(NEVER 因剥离弱化);
- **畸形保守**:未终结(有操作符无终结定界符)或结构畸形的 heredoc 段 SHALL 不剥离、按
  原文判定——本语义只允许消灭误拦(fail-closed 方向),NEVER 制造漏拦;
- **`<<-` 制表剥离**:终结定界符的行首制表符按 shell 语义剥离后匹配;
- 剥离只影响上述四类结构判定的输入文本;激活/解码/UTF-8、脚本扩展名写拦截、越树写
  (工具面)等其余规则不受影响。

#### Scenario: 数据体中的日期形态不再误拦(观测形态一)

- **WHEN** `mgh-init` 运行域激活且 `MGH_TARGET` 钉定,模型执行
  `cat > <target>/.mgh-init/checkpoints/scout/scout-338.json <<'EOF'`(数据体某行含
  `"format": "yyyy/MM/dd"`)`EOF`
- **THEN** 守卫通过(退出码 0):数据体被剥离,`yyyy/MM/dd` 不进入路径判定;修复前该形态
  被误解析为越权路径并拦截

#### Scenario: 数据体中的重定向形态不再误拦(观测形态二)

- **WHEN** 同域,模型以同形态写 checkpoint,数据体某行含 `threshold >2000` 与 `$foo`
- **THEN** 守卫通过:数据体被剥离,`>2000` 不进入重定向判定、`$foo` 不进入符号误判;
  修复前连续被拦直至模型改写内容才放行

#### Scenario: 命令部分的真违规仍拦

- **WHEN** 同域,模型执行 `cat > D:/out/tree/f.json <<'EOF' … EOF`(重定向**目标**在
  `MGH_TARGET` 之外)
- **THEN** 守卫拦截(退出码 2 + 越树写 recipe):剥离只作用于数据体,目标路径照旧全判

#### Scenario: 解释器喂养 heredoc 原样全拦

- **WHEN** 同域,模型执行 `py - <<'EOF'`(数据体为 Python 代码)`EOF`
- **THEN** 守卫按既有"内联解释器代码拦截"语义拦截(退出码 2):解释器喂养形态不在剥离
  豁免之列,本 requirement NEVER 弱化该拦截

#### Scenario: 未终结 heredoc 保守不剥离

- **WHEN** 同域,模型执行 `cat > <target>/.mgh-init/x.json <<'EOF'`(命令文本在定界符
  终结前被截断/畸形)
- **THEN** 该段不剥离、按原文判定(数据体 token 参与判定,可能维持误拦,但 NEVER 漏拦)

#### Scenario: PowerShell here-string 同语义

- **WHEN** 同域,模型执行 `Set-Content -Path <target>/.mgh-init/x.json -Value @" …
  yyyy/MM/dd … "@`(here-string 数据体含日期形态)
- **THEN** 守卫通过:here-string 数据体同样剥离;`-Path` 目标照旧判定
