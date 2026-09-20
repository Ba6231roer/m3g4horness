# improve-mgh-sdr-report-source-links

## Why

> **人话序** 现象:`/mgh-sdr` 报告在项目根目录下生成,简报表的调用链列现在已是「类名.
> 方法名」短形(如 `OrderController.submit`,包路径简写形态在上一轮报告结构 change 里已
> 收敛掉),但仍是纯文本——人审报告发现某跳可疑时,要自己按类名去仓库里翻文件,一条链
> 三四跳就要翻三四次。根因:渲染器只把 `fqn_short` 当显示文本输出,节点自带的 `file`
> +`line` 字段(分组期已物化进 grouping.json,零额外查询)在报告里没有任何消费入口;
> 报告恰好写在目标仓根目录,仓内源文件的相对路径天然就是可点击链接。改什么:报告的三处
> 「类名.方法名」呈现点(简报表入口列、调用链列、章节二问题详述的位置)全部渲染为
> markdown 链接,点击直接跳转到对应源文件(带 `#L<行号>` 锚点,不支持锚点的编辑器自动
> 退化为只跳文件)。怎么验证:单测覆盖链接渲染与路径解析(仓外/绝对/找不到文件的降级
> 形态),以示例项目干跑渲染一次,人工在编辑器里点击核对跳转。

- **问题**:调用链短形解决的是「看得清」,没解决「点得动」——从报告定位到源码仍靠人肉
  检索,每次评审几十跳的累计摩擦显著。
- **为何现在**:链节点 `{fqn_short, file, line}` 与 finding 的 `line` 字段在前两个 change
  里已经落进 grouping.json / drafts,数据齐备,纯渲染层增量即可兑现,零上游改动。

## What Changes

- **`render_sdr_report.py` 三处呈现点加 markdown 链接**(行为变化,报告文件内容形态改变;
  报告仍在目标仓根目录,链接为相对报告文件即仓根的相对路径):
  - 章节一简报表**入口列**(standalone/无路由单元的方法定义短形)与**调用链列**的每个
    链节点文本 → `[类名.方法名](相对源文件路径#L行号)`;
  - 章节二问题详述**位置**(`file:line`)→ `[file:line](相对路径#L行号)`;
  - 降级规则:路径无法解析为仓内相对路径(绝对路径在仓外、字段缺失、空值)→ 保持现行
    纯文本,NEVER 产出坏链接;`line` 缺失 → 链接只到文件不带锚点。
- **不变项**(明确划界):维度列维持「纯文本 `P-NN` 编号、无内部锚点」的既定决策(那是
  报告内部锚点,目标编辑器不支持;本 change 是**文件链接**,不同性质);`sdr_manifest.json`
  `rows[]` 的 `entry`/`chain` 字段保持纯文本短形(机器消费面,不掺链接);章节三 mermaid
  图节点标签不变;grouping.json / drafts schema 不变。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `security-design-review`: 「统一问题记录汇总与确定性报告渲染」需求修改——简报表入口/
  调用链列与章节二位置由纯文本短形改为源文件 markdown 链接(含路径解析与降级规则);
  原「SHALL NOT 产出任何 md 内部锚点」约束收窄为仅辖报告内部锚点(维度列 `P-NN`),不辖
  指向仓内源文件的链接。

## Impact

- 受影响实现:`core/scripts/render_sdr_report.py`(节点文本渲染函数、入口列、章节二位置、
  新增路径解析 helper);`tests/test_render_sdr_report.py`(回归测)。
- 不受影响:`diff_group.py`、`sdr_context.py`、fan-out 提示词与契约、manifest 结构、命令壳。
- 下游消费:`/mgh-blst` 等未来消费者读 manifest `rows[]`(纯文本保持不变,无破坏)。
