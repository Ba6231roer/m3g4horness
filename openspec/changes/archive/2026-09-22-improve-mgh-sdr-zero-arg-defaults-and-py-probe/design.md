# design — improve-mgh-sdr-zero-arg-defaults-and-py-probe

## Context

动机见 proposal.md - Why。现状约束:

- **默认值已在脚本层存在**:`sdr_context.py` / `diff_group.py` / `fanout_runner.py` /
  `mgh_sdr_launch.py` 的 argparse 均为 `--base` 默认 `master`、`--branch` 空串时经
  `git rev-parse --abbrev-ref HEAD` 取当前分支,并把**已解析**的 `base`/`branch` 写进
  stdout JSON(`sdr_context.py:651-652`)。缺的只是壳层「无参 STOP」把零参路径挡住。
- **壳层 bash 立场已确立**:双壳现有文本用 `export MGH_SDR_ACTIVE=1`、`rm`、
  `mkdir -p` 等 bash 语法(claude/opencode 在 Windows 上宿主 Bash 均为 Git Bash),
  探测配方可沿用同一立场,无需兼容裸 cmd/PowerShell 语法。
- **解释器试错的真实形态**(本机实测):Windows 上 `python`/`python3` 常解析为
  Microsoft Store 占位 stub——`--version` 无输出、退出码 49;`py` 缺席的环境在
  Linux/macOS 上则是 shell 直接报 `command not found`。两种失败形状不同,探测判据
  必须按「退出码 0 **且**版本 ≥3.10」双条件,而非「命令名存在」。
- **家族纪律 R5.6**:`AGENTS.md` 现文为「`--help`/无参 → 打印 flag 表并 STOP」,
  全部 6 个 mgh-* 壳逐字镜像此句;单独改 mgh-sdr 壳会与手册冲突(维护者已拍板:
  修订 R5.6 允许壳声明安全默认集,见 Decisions D2)。
- **token 预算**:编排器壳硬上限 ≤5,000 tok(R5.6),lint 由 `tools/measure_prompts.py`
  + 预算检查强制;mgh-sdr 壳现值需实测后确认余量。

## Goals / Non-Goals

**Goals:**
- 零参 `/mgh-sdr` = 完整流水线跑通(base=master / 当前分支 / 全 6 维),`--help` 行为不变。
- 双壳 step 0 单条探测命令定型解释器,消灭「逐命令换名试错」;压缩/新会话可廉价重建。
- R5.6 手册措辞与壳行为一致,例外条件写成机器可核对的形式(参数表须逐项标注默认)。

**Non-Goals:**
- 不给其余 5 个 mgh-* 壳开零参默认(各自默认集是否安全由后续 change 逐个拍板)。
- 不动脚本 argparse、产物 schema、`run_config.json`/哨兵 schema(探测结果不落盘)。
- 不引入 `detect_python.py` 之类新分发脚本(鸡生蛋:探测本身需要解释器)。
- 不改 launcher `mgh_sdr_launch.py`(人/cron 入口,调用者自知解释器;其默认值已存在)。

## Decisions

### D1 — 探测配方:单条 `;` 链 + 逐候选标签输出,判据 = rc 0 且 ≥3.10

采用(写进双壳 step 0,bash 单调用):

```bash
for c in py python python3; do "$c" --version >/dev/null 2>&1 && echo "PYPROBE $c OK $("$c" --version 2>&1)" || echo "PYPROBE $c UNAVAILABLE"; done
```

- 为什么不用 `||` 短路链:`py --version || python --version || …` 在第一个成功处短路,
  看不到其余候选的版本(维护者明确要求「分别什么版本」);且 Store stub(rc 49)与
  2.x 环境(版本达标性)需要全部版本可见才能按 ≥3.10 判。
- 为什么 `for` 而非三段平铺:宿主 Bash 已统一 Git Bash(见 Context),`for` 紧凑且
  标签机器可读;平铺三段同样可行,取标签统一收益。
- 选中规则:输出行中第一个 `OK` 且版本 ≥3.10 者为解释器;全部不达标 → 早停披露 +
  移除已武装哨兵(与其他 step 1 前干净停止同构)。
- 备选否决:`command -v` 只判存在不判可运行(Store stub 恰好骗过它);`--version` 双跑
  的开销可忽略(每候选毫秒级)。

### D2 — 零参语义与 R5.6 例外形态

壳内把 STOP 句改为两分支:「`--help` → 打印参数表并 STOP;**无任何参数** → 按参数表
声明的默认集直接进入编排流(零参 = 显式传默认值的等价路径)」。R5.6 手册措辞同步:
「`--help`/无参 → 打印 flag 表并 STOP」放宽为「`--help` 或无参 → STOP;仅当命令在
参数表**逐项标注默认值**并显式声明零参执行时,无参 = 按默认集执行(mgh-sdr 首用)」,
原 `理由〔花 token 前先校验〕` 括号保留。机器可核对性 = 「参数表逐项标注默认」这一
声明条件,防例外被无声扩大到其它壳。

### D3 — `py` 保持规范 token,替换纪律集中一处

不改写 ~30 处示例为 `<PY>` 占位符(违反 R5.5 ④「命令行示例逐字可执行」,且
`tools/check_contracts.py` 按示例提取 flag 镜像,占位符化会牵动 lint 面)。改为在
 Orchestrator discipline 段加一条全局纪律:「本壳所有示例中的 `py` = step 0 探测选定
 的解释器,实际执行时逐字替换;选中非 `py` 时 NEVER 再混用 `py`」。恢复章节同样受该
纪律覆盖,另在「中断恢复」加一句:选中解释器不确定 → 重跑探测命令(单条廉价),
NEVER 逐命令试错。

### D4 — 零参路径下壳不猜分支名

run 目录命名 `<ts>` 不含分支(step 0 用 `date +%Y%m%d_%H%M%S` 即可),报告文件名与
`--branch` 消费 step 1 stdout 已解析的 `branch` 字段(`sdr_context.py` 既有输出,
零脚本改动)。否决备选「step 0 加 `git rev-parse --abbrev-ref HEAD`」:与「默认值由
脚本兜底、编排器 NEVER 自行猜」的既有分工冲突,且引入一条守卫可读性的裸 git 调用。

## Risks / Trade-offs

- [零参跑的是完整流水线,误触发的代价从「一次打印参数表」升到「一次 fan-out」] →
  缓解:Always disclose 段与参数表都明示默认集;真实诉求恰是「敲 `/mgh-sdr` 就跑」,
  误触发概率低于每次补参的成本;`--dry-run` 已是既有的低成本试跑出口。
- [`py` 规范 token 与全局替换纪律可能被弱模型忽略,照抄 `py`] → 缓解:step 0 探测
  输出即第一手证据(哪行 OK 用哪个),纪律放在 Orchestrator discipline 顶部而非脚注;
  残余风险接受(照抄 `py` 失败一次后 stderr 自纠错,不再是无界试错)。
- [双壳文本再次分叉(claude/opencode 只改一份)] → 缓解:tasks 列双壳同改清单 +
  `tools/check_contracts.py` 与既有双壳 parity 测兜底。
- [壳 token 超 5,000 预算] → 缓解:实现时先 `tools/measure_prompts.py` 实测余量,
  超限按保真度优先裁剪(优先删既有重复措辞,NEVER 删承重防线)。
- [Store stub 环境 `python --version` 有stderr杂讯] → 缓解:配方 `>/dev/null 2>&1`
  吞杂讯,只输出统一 `PYPROBE` 标签行。

## Migration Plan

纯文本改动,无数据迁移:双壳 + AGENTS.md 一并提交即生效;回滚 = revert 该提交。
已存在的进行中 run 不受影响(恢复章节向后兼容:探测是新 step 0 子项,旧 run 目录
无新字段可读)。
