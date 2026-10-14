# design — add-mgh-sdr-inline-branch-list

> 受众:双受众(维护者拍板 + apply agent 执行)。
> 单一事实源:`core/scripts/mgh_sdr_launch.py`;规格面 = `security-design-review` 新增
> ADDED requirement(见本 change specs delta)。

## D1 — 独立参数,不做 `--multi-branch` 双重语义

逗号在 git 分支名中合法(`git check-ref-format` 的拒绝集不含 `,`),「值含逗号 = 内联
列表、否则 = 文件」会让 `--multi-branch "foo,bar"` 在「两个分支」与「一个含逗号的分支
文件」之间不可判定。独立参数 + 显式互斥(同给退出码 2)让每个输入形态只有一种解读。
备选「`--multi-branch` 智能探测文件是否存在、不存在再当列表」被否:错误输入(拼错的
文件名)会被静默当分支名跑预检,把误用变成一批 branch-not-found FAILED——把 typo 从
退出码 2(立即可见)降级成退出码 1(混在真实失败里),违反 fail-loud 文化。

## D2 — 解析规则:严格拒空项,`strip` 后去重保序

- 切分 `value.split(",")` → 逐项 `strip()` → 空项即误用(退出码 2,报出第几项)——
  `a,,b`/结尾逗号是手滑高发形态,静默跳过会让「少跑一个分支」变成无声覆盖缺口;
  与三枚举器 `--limit <1` 拒识、scope 拼错路径 exit 2 同一 fail-loud 立场。
- 去重保序(首个为准),与 `_read_multi_branch` 的既有去重行为一致——同一分支在清单
  里出现两次只跑一次(run 目录按时间戳命名,重跑同名分支会产生两个难认领的 run 目录)。
- **无注释语法**:文件模式支持 `#` 注释是「给人维护的清单文件」的属性;内联值是机器
  直传的一次性输入,每个逗号项按字面分支名处理(`#` 特判反而制造「这个分支名怎么没跑」
  的隐性行为)。
- 实现为纯函数 `_split_branch_list(value: str) -> list[str]`(误用时 `sys.exit(2)`,
  与 `_read_multi_branch`/`_detect_host` 的既定形态一致),可被单测直调。

## D3 — 互斥语义与优先级

- `--branch-list` ∧ `--multi-branch` → `sys.exit(2)` + recipe(在 `main()` 参数检查段,
  先于任何 gate/分支执行);NEVER 定静默优先级。
- `--branch-list` 压过 `--branch`(同形于现行 `--multi_branch` 压过 `--branch`):
  `branches = _split_branch_list(args.branch_list) if args.branch_list else
  (_read_multi_branch(...) if args.multi_branch else [args.branch or _current_branch(repo)])`。
  `--branch` 是「单分支」语义,两多分支喂法都视作对其的展开,不构成歧义,不做互斥。

## D4 — 流程同源:清单归一后零分叉

三种喂法在 `main()` 汇成同一个 `branches: list[str]` 后,**逐分支循环、`_run_one`、
失败汇总、退出码全部复用现有代码,零新分支逻辑**。`--branch-list` 不改变每分支的
run 目录命名(`_safe_name` 清洗)、报告认领、哨兵生命周期、host-error 证据提取
(0.1.75)等任何行为。

## D5 — 契约与文档面

- `--help` 是唯一契约面(R5.1):argparse `help=` 写清格式与互斥;`check_contracts.py`
  对壳内 `*.py --flag` 断言超集兼容,零壳改动即零风险(三面壳只把 launcher 当优选入口
  指认,不展 flag 表——维持现状,`--branch-list` 是人/cron 入口参数,宿主会话无感知)。
- README `/mgh-sdr` 多分支段补第三种喂法一行示例 + 互斥/拒识说明;launcher 头注
  usage 行同步补 `[--branch-list <b1,b2,...>]`。
- 规格走 **ADDED requirement**(不改写既有 launcher 要求块):主规格上尚有未归档的同
  能力 delta(`fix-mgh-sdr-host-error-capture`)改写该要求块,MODIFIED 会双 delta 叠写;
  ADDED 独立要求与归档顺序无关,两 change 任意顺序归档结果一致。

## D6 — 测试策略(先红后绿)

- 纯函数直测:`_split_branch_list` 正常切分/去空白/去重保序/空项退出 2(报序号)/
  空串退出 2。
- 集成(`_FakeHostMixin` + 临时仓两分支):`--branch-list "feature-pay, feature-b2"`
  串行两轮完整流程、退出码 0、两份报告;互斥同给退出码 2 零 spawn;`--branch` 被内联
  清单忽略。
- `--help` 真子进程断言含 `--branch-list`(镜像既有 `test_help_documents_model_flag`)。
