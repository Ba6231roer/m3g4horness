## ADDED Requirements

### Requirement: core/scripts 叶脚本编译零告警(stderr 纯净)

`core/scripts/` 全部叶脚本 SHALL 在 `py_compile` 编译(即任何 import/直接执行的第一步)下
**零 SyntaxWarning**:模块 docstring 与一切字符串字面量 SHALL NOT 含无效转义序列(如
反斜杠+反引号)——docstring 中的正则/路径示例含反斜杠时 SHALL 用 raw string 或双反斜杠
表达。理由:叶脚本被编排器/re-export 脚本 import 链加载(如 `resume_state.py` →
`list_clusters.collect_canonical_ids`),一处 `SyntaxWarning` 即经 stderr 污染每次调用的
诊断面,弱模型易把告警误读为脚本故障;stderr 与 stdout 的严格分流契约(R5.3b)隐含
「stderr 只含预期诊断,不含编译期噪声」。回归单测 SHALL 全量编译 `core/scripts/*.py` 并
断言捕获不到任何 Warning(fail-loud,退出码非 0)。

#### Scenario: list_clusters docstring 不再触发 SyntaxWarning
- **WHEN** `py_compile.compile("core/scripts/list_clusters.py")` 且 warnings 置为 always
- **THEN** 不捕获任何 SyntaxWarning(现行 `` `\` `` 非法转义已消除)

#### Scenario: import 链的 stderr 纯净
- **WHEN** 子进程执行 `resume_state.py --target <运行目录>`(其 import 链加载
  `list_clusters`)
- **THEN** stderr 不含 `SyntaxWarning: invalid escape sequence`(进度输出正常,不受影响)

#### Scenario: 全量零告警回归测防回归
- **WHEN** 运行零告警回归单测(全量编译 `core/scripts/*.py`)
- **THEN** 任一脚本产生 Warning → 测试 fail-loud 列出脚本名与告警消息
