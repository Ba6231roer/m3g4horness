# mgh-init scout 吞吐:诊断结论与实验交接

> **受众:人类(操作者 + 接手的新会话 AI 助手)。**
> 这是一份**自包含交接文档**:读它就能接着干,不需要翻前面的对话。
> 目的分两段:① 记录已确诊的缺陷与修复计划;② 给出修复后要跑的吞吐判别实验(A/B/C)与判读表。

**当前状态一句话**:`/mgh-init` 在 Linux 上跑 scout 长跑**必然在约 10 分钟处猝死**,已定位为两个代码缺陷;实验尚未取得有效数据,等缺陷修复后重跑。

---

## 0. 新会话开工指引

如果你是接手的新会话,按这个顺序读:

| 顺序 | 读什么 | 为什么 |
|---|---|---|
| 1 | 本文件 §1–§3 | 原始问题 + 已确诊的缺陷 + 修复计划 |
| 2 | 本文件 §4–§7 | 要做的实验、命令、判读表 |
| 3 | `core/scripts/fanout_runner.py` 的 `_kill_tree`(约 1103 行)、`_run_unit`(约 750 行)、`_tail_stream`(约 709 行) | 缺陷现场 |
| 4 | `openspec/changes/fix-mgh-fanout-posix-stall-containment/` | 本次缺陷的修复记录 |

**不要**凭本文件的印象直接改代码,先读实际源码核对行号。

---

## 1. 原始问题

`/mgh-init`(存量安全控制发现工具)的 **scout(探查)阶段**在大仓上跑不动。实测数据:

| 项 | 值 |
|---|---|
| 规划出的 LLM 单元批数 | **1052** 批 |
| 覆盖文件数 | 12707 个 |
| 单批实际耗时 | 5–8 分钟 |
| 实测吞吐 | 约 **1 单元/分钟** |
| 外推全量耗时 | 约 **16 小时** |
| 实际中断点 | 跑到 **8/1052** 时停下 |
| 交互式续派 | 每次宿主只能推进 5–8 个单元,约需 **150+ 轮** |

已完成的那 8 个 scout 单元**质量良好**,不是质量问题,是速度/稳定性问题。

**运行环境**:企业内网部署的大模型网关,限流 **每 10 分钟 100 次调用**。
**宿主环境**:Linux 终端(nohup 直跑)。上一次(1052 批那次)是在 Windows 上跑的。

**用户目标**(按优先级):**尽可能快、全量、稳定**。全量是硬要求,不能用 `--scope`/`--budget` 截断换速度。

---

## 2. 已确立的诊断

### 2.1 现象里混着两个独立瓶颈

```
瓶颈 A:单元太多 × 每单元固定开销大  → 受「并发 × 单单元耗时」或「配额」约束
瓶颈 B:每轮只能推进 5–8 个单元      → 受「宿主单次调用超时」约束
```

**瓶颈 B 的解释**(已确立):派发器 `fanout_runner.py` 按设计在「软时限」到点后正常返回,不是崩溃。软时限取「宿主单次调用超时 × 0.8」;claude 的 Bash 单次上限 600 秒 → 软时限 480 秒 = 8 分钟 → 8 分钟 × 1 单元/分钟 ≈ 8 个单元,1052 ÷ 8 ≈ 131 轮。与你观测的「5–8 单元 / 150+ 轮」吻合。
**解法**:换到不受宿主超时钳制的终端跑,131 轮塌缩成 1 轮。

**瓶颈 A 的解释**(两条假设,尚未判别):

| | 假设甲:慢在模型 | 假设乙:慢在配额 |
|---|---|---|
| 通俗说法 | 模型一次要算 5–8 分钟,同时只跑 5 个 | 网关每 10 分钟只准 100 次调用,一次单元烧约 9 次 |
| 算术 | 5 并发 ÷ 6.5 分钟 ≈ 0.77/分钟 | 10 次/分钟 ÷ 9 次/单元 ≈ 1.1/分钟 |
| 与实测 1/分钟 | 吻合 | 也吻合 |
| 提速办法 | 调大 `--wave` | 调大 `--scout-batch-bytes`(批变大 → 单元数变少,摊薄固定开销) |
| 估算收益 | wave 10 → 约 8–9 小时 | 96KB→288KB:约 16h→10h |

**判别器就是实验一**:调大 `--wave`,完成数翻倍 → 假设甲;不动或冒限流信号 → 假设乙。

### 2.2 已确诊的两个代码缺陷(本次猝死的直接原因)

三次运行全部死在**约 10 分钟**处,日志时间戳分别是 `+00:09:38`、`+00:09:40`、journalctl `15:29 → 15:39`,且都是:侧车 `fanout_progress.scout.json` 停在 `"running"`、**没有 stdout 汇总 JSON**、`--kill-stale` 返回 `killed:[]`(无孤儿)。这是「被强杀、未走正常退出»的典型形状。

**缺陷 1 — POSIX 下 stall 杀会连带杀死派发器自己**

- 子进程在 `fanout_runner.py:774` 用 `subprocess.Popen(...)` 启动,**没有 `start_new_session=True`** → 子进程与派发器**同进程组**
- 杀掉失活单元时调 `_kill_tree`(`fanout_runner.py:1103`),POSIX 分支是:
  `os.killpg(os.getpgid(pid), signal.SIGTERM)` —— 杀**整个进程组**,包含派发器自身
- 结果:第一次 stall 杀 → 派发器 SIGTERM 自杀,当场死。**连 stall 日志都来不及写**(kill 在打日志之前)
- **Windows 不受影响**:那边走 `taskkill /pid <pid> /T /F`,是树范围,不碰派发器

**缺陷 2 — 失活判据取错方向,健康单元被误判**

- 两个输出流的 sink 在 `fanout_runner.py:787-788` 都初始化为 `ts = t_start`(spawn 时刻)
- `_tail_stream`(`:709`)只在**读到字节**时才更新 `ts`
- 失活判据在 `:819` 取两者中**较旧**的:`last_out = min(out_sink["ts"], err_sink["ts"])`
- 所以**只要有一条流自始至终没输出**,它的 `ts` 永远停在 spawn 时刻 → 健康单元也在 `spawn + stall_timeout_s` 被判失活
- `--help` 对该阈值的原文是「no stdout/stderr bytes for this long」= **没有任何一路有字节才算静默**,即语义应为 `max`
- 同样的 `min` 还出现在心跳披露行 `:2124`(只影响给人看的 `idle` 数值)

**为什么这次才暴露**:`--stall-timeout-s` 是 600 秒 = 正好 10 分钟。之前在 Windows 上每轮只有约 8 分钟(宿主截断),**从来没跑到过这个阈值**。现在换成长跑,第一次就踩中。

**只修缺陷 1 不够**:缺陷 2 还在的话,单元每 600 秒被误杀一次 → 重派 → 再被误杀 → 最终零推进熔断退出,实验照样跑不完。

### 2.3 参数层面绕不过去

派发器启动自检强制不变式:

```
--stall-timeout-s  <  --call-timeout-s  <  --time-budget-ms ÷ 1000 × 0.8
```

即 **stall 阈值必然早于轮次结束**。所以只要有一个健康单元在飞够久(且缺陷 2 存在),派发器就会自杀。**没有任何参数组合能保证跑满。**

---

## 3. 修复计划(三处)

| # | 位置 | 改动 | 不修会怎样 |
|---|---|---|---|
| 1 | `fanout_runner.py:774` 的 `Popen` | 加 `start_new_session=(os.name != "nt")` | 任何 stall/超时杀都会连带杀死派发器自己 |
| 2 | `fanout_runner.py:819` | `min` → `max` | 健康单元每 `stall_timeout` 秒被误杀一次,收敛不了 |
| 3 | `fanout_runner.py:2124` 心跳行 | `min` → `max` | 只影响给人看的 `idle` 数值,与 #2 同源,顺手对齐 |

**副作用(要知情)**:`start_new_session=True` 后,在终端里按 Ctrl-C **不再连带杀掉子进程**(它们自成会话,会变成孤儿)。孤儿会被登记在 `<init-dir>/fanout_runner.<tier>.pid` 的 `children[]` 里,下一次派发前的 `--kill-stale` 能清掉。**用 nohup 挂后台跑则完全不受影响**(本来就是推荐跑法)。

**仓库规矩**(`AGENTS.md` R5.8):脚本改动必须 bump `VERSION`;需补回归测试并跑 `tools/check_contracts.py`。

---

## 4. 实验设计:三个方案与判别逻辑

```
┌──────────────────────────────────────────────────────────────┐
│  方案 A  调 --wave(并发上限)                                 │
│    验:慢在模型并发 还是 配额已满                              │
│    判别:wave 5→10,完成数翻倍 = 假设甲;不动/冒限流 = 假设乙     │
├──────────────────────────────────────────────────────────────┤
│  方案 B  调 --scout-batch-bytes(批字节上限)                  │
│    验:把 1052 个批并成更少的大批,摊薄每单元的固定调用开销       │
│    离线可算:批数 = 单元数,直接重算三种取值下的批数即可         │
├──────────────────────────────────────────────────────────────┤
│  方案 C  换到独立终端 / nohup 长跑                            │
│    验:能否摆脱「宿主单次调用超时」的钳制                        │
│    注:本项在修复前已证伪 —— 独立终端里同样在 10 分钟死,        │
│        那是 §2.2 的代码缺陷,不是宿主超时。修复后重验。          │
└──────────────────────────────────────────────────────────────┘
```

**关键约束**:B 方案**不能覆盖正在跑的 `scout_plan.json`**。批号(`scout-001`…)按切批结果重新编号,覆盖后磁盘上已有的 `.done` 标记会张冠李戴 → **静默丢覆盖**。所有重算必须写到 `_scratch_` 开头的临时文件。

---

## 5. 执行步骤(修复并重新分发安装之后)

### 变量准备

**Linux / bash**

```bash
TARGET=/path/to/your/project
MGH="$TARGET/.claude/mgh-core"          # opencode 安装改成 $TARGET/.opencode/mgh-core
INIT="$TARGET/.mgh-init"
SCOUT="$INIT/checkpoints/scout"
INPUTS="$INIT/inputs/scout"
PLAN="$INIT/scout_plan.json"
```

**Windows / cmd**

```cmd
set "TARGET=D:\path\to\your\project"
set "MGH=%TARGET%\.claude\mgh-core"
set "INIT=%TARGET%\.mgh-init"
set "SCOUT=%INIT%\checkpoints\scout"
set "INPUTS=%INIT%\inputs\scout"
set "PLAN=%INIT%\scout_plan.json"
```

### 第 0 步:安全准备 + 记基准

```bash
cp -r "$SCOUT" "$INIT/_bak_scout_checkpoints"
ls -1 "$SCOUT"/*.json.done | wc -l
```

```cmd
xcopy /E /I /Y "%SCOUT%" "%INIT%\_bak_scout_checkpoints"
dir /b "%SCOUT%\*.json.done" | find /c /v ""
```

> `.done` 文件计数 = 完成的单元数,但会混进 2 个**层级标记**(`merge.json.done`、`audit.json.done`,scout 汇总阶段的标记,不是某个批),记数时减掉。
> **记下基准 `done` 数 = ______**

### 第 1 步:清孤儿(每次派发前必做)

```bash
python3 "$MGH/scripts/fanout_runner.py" --tier scout --kill-stale --dry-run \
  --scout-plan "$PLAN" --checkpoints "$SCOUT" --inputs-dir "$INPUTS"
```

```cmd
py "%MGH%\scripts\fanout_runner.py" --tier scout --kill-stale --dry-run ^
  --scout-plan "%PLAN%" --checkpoints "%SCOUT%" --inputs-dir "%INPUTS%"
```

`killed` 为空 → 跳过。非空 → 去掉 `--dry-run` 再跑一次真杀。

### 第 2 步(方案 C):nohup 独立终端长跑,跑满 25 分钟

```bash
nohup python3 "$MGH/scripts/fanout_runner.py" --tier scout \
  --scout-plan "$PLAN" --checkpoints "$SCOUT" --inputs-dir "$INPUTS" \
  --wave 5 --time-budget-ms 1500000 --call-timeout-s 900 --stall-timeout-s 600 \
  --hb-interval-s 60 > "$INIT/_scout_run.log" 2>&1 &
echo $! > "$INIT/_scout_run.pid"
```

```cmd
py "%MGH%\scripts\fanout_runner.py" --tier scout ^
  --scout-plan "%PLAN%" --checkpoints "%SCOUT%" --inputs-dir "%INPUTS%" ^
  --wave 5 --time-budget-ms 1500000 --call-timeout-s 900 --stall-timeout-s 600 ^
  --hb-interval-s 60 > "%INIT%\_scout_run.log" 2>&1
```

参数含义:`--time-budget-ms` **单位是毫秒**,1500000 ms = 1500 s = 25 分钟,到点停止派新单元、把在飞的收完、**退出码 0** 并打印汇总。
不变式校验:`600 < 900 < 1500 × 0.8 = 1200` ✓

**怎么判断这一轮是正常结束还是又被打死**:

```bash
tail -20 "$INIT/_scout_run.log"
grep -o '"state": *"[^"]*"' "$INIT/fanout_progress.scout.json"
```

| 现象 | 含义 |
|---|---|
| 末尾有 `{"runner": "fanout_runner", ...}` 汇总行 + `state` 为 `exited-partial`/`exited-clean` | **正常退出**,量具可用 |
| 最后一行是心跳行、无汇总、`state` 仍是 `running` | 又被外力杀了,缺陷未修干净,回 §2.2 |

### 第 3 步(方案 A):`--wave 5` → `10` → `16` 三轮各 25 分钟

只改 `--wave`,其余逐字不动。每轮开跑前回到第 1 步清孤儿,跑完记 `done` 增量。

### 第 4 步(方案 B):离线重算批数

**全部输出到 `_scratch_` 开头文件,绝不覆盖 `$PLAN`。**

```bash
python3 "$MGH/scripts/plan_scout.py" --skeleton "$INIT/skeleton.json" \
  --candidates "$INIT/controls_candidates.json" --out "$INIT/_scratch_96k.json" \
  --batch-bytes 98304 --batch-cap 40
python3 "$MGH/scripts/plan_scout.py" --skeleton "$INIT/skeleton.json" \
  --candidates "$INIT/controls_candidates.json" --out "$INIT/_scratch_288k.json" \
  --batch-bytes 294912 --batch-cap 40
python3 "$MGH/scripts/plan_scout.py" --skeleton "$INIT/skeleton.json" \
  --candidates "$INIT/controls_candidates.json" --out "$INIT/_scratch_576k.json" \
  --batch-bytes 589824 --batch-cap 40
```

```cmd
py "%MGH%\scripts\plan_scout.py" --skeleton "%INIT%\skeleton.json" ^
  --candidates "%INIT%\controls_candidates.json" --out "%INIT%\_scratch_96k.json" ^
  --batch-bytes 98304 --batch-cap 40
py "%MGH%\scripts\plan_scout.py" --skeleton "%INIT%\skeleton.json" ^
  --candidates "%INIT%\controls_candidates.json" --out "%INIT%\_scratch_288k.json" ^
  --batch-bytes 294912 --batch-cap 40
py "%MGH%\scripts\plan_scout.py" --skeleton "%INIT%\skeleton.json" ^
  --candidates "%INIT%\controls_candidates.json" --out "%INIT%\_scratch_576k.json" ^
  --batch-bytes 589824 --batch-cap 40
```

看 stderr 末行 `[plan_scout] N targets -> M batches`,**M 就是批数 = 单元数**。
跑完删除临时文件(Linux `rm "$INIT"/_scratch_*.json`;cmd `del "%INIT%\_scratch_*.json"`)。

> 注意:`list_scout_batches.py` 的 `DEFAULT_MAX_UNIT_BYTES` 是 192KB。`--batch-bytes` 一旦超过它,每批会被标 `oversize`(仅告警,不切分,不致命),需同时调 `--max-unit-bytes`。

### 第 5 步(方案 C 实战):过夜长跑

把第 2 步的 `--time-budget-ms` 改成 43200000(12 小时),`--wave` 用实验一得出的最优值,其余不变。不变式:`600 < 900 < 43200 × 0.8 = 34560` ✓
跑完回宿主会话 `/mgh-init --resume` 接续(磁盘标记是唯一真相源)。

**注意**:实验三已被证伪过一次(独立终端同样 10 分钟死)。修复后若仍在约 10 分钟死,说明缺陷不止 §2.2 那两个,回到诊断。

---

## 6. 观察项(填这些就够)

```
基准 done = ______

C1  第 2 步能否跑满 25 分钟
A1  wave 5  时的限流信号
A2  wave 10 完成数 vs wave 5
A3  wave 10 时的限流信号
A4  心跳里的单单元静默时长(idle=字段)
B1  96KB / 288KB / 576KB 的批数 = ___ / ___ / ___
B2  批数降幅
C2  过夜长跑结果
```

**C1 —— 独立终端里这条命令实际跑了多久?**

- **A.** 跑满接近 25 分钟(瓶颈 B 的宿主超时解释成立,且缺陷已修净)
- **B.** 8–10 分钟就自己停了(**缺陷未修净,回 §2.2**)
- **C.** 1–2 分钟退出,打印了 `rate_limited:true` 或 `stalled:true`
- **D.** 命令报错没跑起来

**A1 / A3 —— 那一轮 stderr 里出现过哪些字样?**

- **A.** 完全没有 `cooldown` / `429` / `rate limit` / `quota`,心跳一路正常
- **B.** 出现过 `cooldown #1 …pausing NEW dispatch`,但无限流特征字样
- **C.** 出现过 `429` / `rate limit` / `quota`(可能在 stderr,也可能在 `*.run.log`)
- **D.** 直接以 `rate_limited:true` 提前退出

**A2 —— wave 10 的完成数相比 wave 5:**

- **A.** 约翻倍或更多(≥1.8 倍)
- **B.** 有增加但不到 1.5 倍
- **C.** 基本持平(0.8–1.2 倍)
- **D.** 反而变少

**A4 —— 心跳行 `inflight=5 unit=scout-003 idle=120s done=42/1052` 里的 `idle`:**

- **A.** 大多数时候在 60 秒以内(稳定输出,是「算得慢」不是「卡住」)
- **B.** 经常冲到 300 秒以上但最终完成(慢但健康)
- **C.** 冲到 600 秒并被杀(留下 `.run.log`)
- **D.** 心跳打不出来 / 数字不动

**B2 —— 从 96KB 提到 288KB,批数降到:**

- **A.** 约 1/3(约 350 批) · **B.** 约 1/2(约 525 批) · **C.** 几乎没变 · **D.** 降得更多

**C2 —— 过夜长跑:**

- **A.** 顺利跑完/跑到很后面(如 800+),无中断
- **B.** 中途 `rate_limited:true` 退出 · **C.** 中途 `stalled:true` 退出
- **D.** 别的原因(附 stdout 末段 JSON) · **E.** 早上还在跑,进度正常

---

## 7. 判读表

| C1 | A1 / A3 | A2 | 结论 | 建议动作 |
|---|---|---|---|---|
| A | A / A | A(翻倍) | **假设甲成立**:慢在模型并发 | 把 `--wave` 提到最优值直接长跑;调大批尺寸无收益 |
| A | A / A | B 或 C | 混合瓶颈:并发加到一定程度不涨了 | 找拐点 wave;同时做实验二 |
| A | A / B 或 C | 任意 | **接近配额临界**:并发一到就碰限流 | `--wave` 小幅上调 + 做实验二;考虑申请更高配额 |
| A | B 或 C / B 或 C | C 或 D | **假设乙成立**:配额已占满 | 唯一杠杆是减少调用总数 → 走实验二;并考虑做「派发器自适应限速」 |
| A | D | — | 配额已彻底打满 | 先确认网关配额可调;不可调则必须做自适应限速 |
| B | — | — | **缺陷未修净** | 回 §2.2 重新诊断,别再跑实验 |
| C | — | — | 每次都是配额风暴 | 走实验二 + 自适应限速 |
| D | — | — | 命令本身跑不起来 | 贴报错 |

**若 B2 选 A(批数降到约 1/3)**:无论 A 组结果如何,实验二都值得做。按当前算术,96KB→288KB 约能把 16 小时压到 10 小时,576KB 压到 8–9 小时(下限由「读文件本身的调用」决定,省不掉)。

---

## 8. 已知的未决问题

1. **企业网关侧的真实调用数**。文档里「每单元约 9 次调用」是从 16 小时这个总量**反推**的,不是实测。若能从网关管理后台按时间窗看调用计数,那是最直接的证据,能把实验一直接省掉。
2. **模型的上下文上限**。它决定 `--scout-batch-bytes` 能推到多大(96KB ≈ 2.5 万 token,576KB ≈ 15 万 token)。上限不明时建议止步 288KB,且只在新开的干净 run 上试。
3. **限流特征字样是否准确**。派发器靠输出里的 `429` / `rate limit` / `quota` 等字样判限流;网关若用别的措辞会判成「未知」而不触发截断(冷却仍兜底)。所以「没看到字样」≠「没发生限流」,要结合 A2 的完成数一起看。
4. **`--wave` 未暴露到命令壳**。`mgh-init` 的 flag 表里没有 `--wave`,只能走独立终端手传。要不要上壳待定。
5. **派发器自适应限速(token-bucket)**。长期贴着配额跑的网关,最理想形态是派发器自己按配额匀速放行,永不触发风暴、永不退出。该能力在前一份规格里被明确列为「非目标」,理由是「冷却已覆盖风暴形态」——那是在「有人守着、失败就 resume」的前提下。是否推翻该裁定待定。

---

## 9. 变更记录

| 日期 | 事件 |
|---|---|
| 2026-09-15 | 首轮实验:Linux 终端直跑,三次均在约 10 分钟猝死(`+9:38` / `+9:40` / `15:29→15:39`),无汇总 JSON、侧车停在 `running`、无孤儿 → 定位 §2.2 两个缺陷 |
| 2026-09-15 | 开出 `fix-mgh-fanout-posix-stall-containment` 记录修复 |
| _(待填)_ | 缺陷修复 + 重新分发安装后,按 §5 重跑实验一,填 §6 观察项到本节 |
