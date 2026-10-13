## ADDED Requirements

### Requirement: diff 种子的非 ASCII 路径保真

sast 侧从 `git diff --name-status` 派生扫描种子的确定性脚本(`diff_seed.py`)SHALL 以
`core.quotepath=false` 配置运行该 git 子命令:非 ASCII 路径源文件 SHALL 以原样字符进入
seed 判定,扩展名过滤 SHALL 基于真实文件名,SHALL NOT 因引号转义形态(引号包裹 + 八进制
转义 + 引号尾粘连)导致扩展名匹配失败而把源文件静默排除出 `seed[]`;无法解析的条目 SHALL
显式披露,SHALL NOT 无声消失。`deleted[]` 侧 SHALL 与 `seed[]` 同权适用源码扩展名过滤。

#### Scenario: 中文路径源文件进入扫描种子

- **WHEN** diff 变更集中存在非 ASCII 路径的 `.java` 源文件(默认 git 配置)
- **THEN** 该文件以真实文件名出现在 `seed[]` 中并通过扩展名过滤;输出中不存在带引号尾
  (`…"`)的伪造扩展名条目

#### Scenario: 删除的非 ASCII 源文件按同一过滤口径记录

- **WHEN** diff 含被删除的非 ASCII 路径源文件
- **THEN** `deleted[]` 与 `seed[]` 使用同一源码扩展名闭集过滤,不出现一边收录一边漏记
