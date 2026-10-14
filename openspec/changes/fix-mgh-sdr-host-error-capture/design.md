# design — fix-mgh-sdr-host-error-capture

> 受众:双受众(维护者拍板 + apply agent 执行)。
> 背景:findings 定位与建议方向见本 change proposal「Why」;本文件只记**怎么改**的决策与
> 备选取舍。单一事实源:`core/scripts/mgh_sdr_launch.py`(launcher,随 install 分发)。

## D1 — 修法取「下游捕获」,不动 flags、不追上游

opencode 子会话日志只落全局文件属上游(opencode)行为,本仓不可修(原 findings 已注明)。
三个候选方向:

| 方向 | 内容 | 取舍 |
| --- | --- | --- |
| ① 纯 recipe | 失败时 stderr 提示去翻全局日志 | 成本最低,但排障仍要脱离 run 目录人肉 grep,且「被重试吸收的瞬时错误」(成功分支)永远无人看见 |
| ② 时间窗提取落盘 | launcher 宿主退出后提取全局日志窗内 ERROR 行 → `<run-dir>/host_error.log` | run 目录自包含;成功分支同治则瞬时断连也留痕(实测价值:2026-10-13 run1 的 2 次断连被重试吸收,当时只能事后人肉翻全局日志才发现) |
| ③ 换日志通道 | 给编排器换 `opencode --print-logs` 之外的日志面 | 无此面;上游不支持 |

**拍板:①+② 组合**。② 为主(证据落盘),① 收编为 ② 的零捕获 fallback(证据文件只有头注时,
失败 recipe 才改指全局日志路径)。flags(`--print-logs --log-level ERROR`)**保留**——它们对
父进程自身错误(如 stdin 断、任务投递失败)仍是唯一就地披露面,且无副作用;但其承诺面在
docstring/spec 双处收窄为「父进程尽力」,NEVER 再声称覆盖扇出子会话。

## D2 — 提取时机:每次宿主退出后都提取(成功分支同治),不是「仅失败时」

备选「仅宿主非零退出时提取」被否:launcher 能观测的失败只有「宿主非零退出 / 无报告」两形,
而扇出单元级失败(冷却/限流/熔断)常以 **partial:true → 编排器披露缺口 → 报告照常渲染 →
宿主退出 0** 收场——仅失败提取会在最需要证据的形态上缺席;且被重试吸收的瞬时错误(本轮
N4 实测形态)只有同治才能留痕。成本:每分支一次全局日志全文行扫(单文件、一次性,百 MB 级
也 ~1s),人/cron 入口可接受。`--dry-run` 分支零 spawn,天然零提取。

## D3 — 窗口与解析语义(纯函数,可单测)

- **记窗**:`_spawn_host` 以 `datetime.now(timezone.utc)` 记 spawn 起;提取时刻记止。窗 = 
  `[spawn_start_utc, extract_utc)`。两侧由 launcher 自记,无时钟偏移补偿需求(全局日志时间
  戳经实测为 UTC:`2026-10-13T09:40:5x` ↔ 本地 17:40,+8)。
- **解析**:逐行匹配 `timestamp=<token>` 与 `level=<TOKEN>` 两个键(regex-over-string,与本仓
  守卫 Bash 面同立场);时间戳经 `datetime.fromisoformat` 解析,尾缀 `Z` 归一为 `+00:00`,
  naive 值按 UTC 释义。非 ERROR 行、无时间戳行、时间戳不可解析行 → 跳过(不保守收入,避免
  证据文件被噪声稀释;收入面收窄由「零捕获 → recipe 指全局日志」兜底)。
- **落盘**:`<run-dir>/host_error.log`,头两行注记(`# source: <全局日志绝对路径>`、
  `# window: <start> .. <end> (UTC)`),正文 = 窗内 ERROR 行**逐字**(grep `level=ERROR`
  对头注行天然惰性,`#` 注记不污染匹配)。
- **三态**(spec 已定):文件缺席 = 未提取(claude 宿主 / 全局日志缺失或不可读);仅头注 =
  提取过、零捕获;有正文 = 窗内 ERROR。「没跑提取」与「跑了零错误」可区分。

## D4 — 全局日志路径:本机实测形态硬编码 + fail-soft 自我暴露

`~/.local/share/opencode/log/opencode.log`(2026-10-13 实测,win32 + opencode 1.18.31;
`Path.home()` 拼接)。备选「探测 `OPENCODE_*` env / XDG 变量」被否:无上游文档证据支持该
覆盖面,猜错比不猜更危险。路径以**独立小函数**单点持有(测试 monkeypatch 注入假路径);
文件缺失/不可读/不可解析 → stderr note 注明**假定的路径**——opencode 未来若改路由,note
本身就是失配的自暴露信号。诚实边界(spec 与代码注释双处):同机并发 opencode 会话窗内
ERROR 行可能混入,提取是诊断近似非精确归属(按 session id 过滤不做——子会话 id 提前不可知,
且捕获侧过度智能不如原文留证)。

## D5 — 失败原因拼装:证据指针进信封与汇总,不进退出码语义

`_run_one` 现返回 `(ok, outcome, pending)`;失败 outcome 为一句信封(如
`host CLI exited 1 for <branch>`)。接线点在宿主退出之后、信封拼装之前:提取已发生,把证据
状态并进 outcome 文案——有正文 → 追加 `(host error evidence: <host_error.log 绝对路径>)`;
仅头注 → 追加 recipe 句(指认全局日志路径);缺席(claude/日志缺失)→ 不追加(extraction
skip 的 stderr note 已覆盖)。`FAILED BRANCHES` 汇总复用同一 outcome 字符串,零额外拼装。
退出码语义(0/1/2)与分支判定**一字不动**——可诊断性增强 NEVER 变成新失败源(fail-soft
是 spec 级要求)。

## D6 — 测试策略:纯函数直测 + 假宿主/假全局日志集成,零真 spawn

- 纯函数直测(不 spawn):窗内/窗外边界行、非 ERROR 行、无/坏时间戳行、`Z` 尾缀与 naive
  时间戳、逐字保真(含中文与多字节)、头注两行、零捕获仅头注、全局日志缺失返回缺席态。
- 集成(复用 `test_mgh_sdr_launch.py` 既有 `_FakeHostMixin` 假宿主机制 + monkeypatch 全局
  日志路径函数):成功分支同治落盘 + stderr 计数;失败分支 outcome/汇总携指针;零捕获 recipe
  句;claude 宿主零提取零文件;日志缺失时退出码语义不变。
- 既有 `test_opencode_carries_log_flags_claude_does_not` 保留不动(flags 不删,断言仍真)。

## D7 — 规格与文档对齐面

- 主规格 `security-design-review` launcher 要求第 ⑧ 项经本 change delta 改述(已随 specs
  工件产出);spec 语言只写可观测行为(窗/三态/fail-soft/指针),NEVER 写内部函数名。
- launcher 头注与 `_spawn_host` docstring 同步改述真实机制(它们当前声称「provider 形失败在
  launcher stderr 可定位」——失实陈述按分发纯净纪律必须修正)。
- 三面命令壳、命令的维护者 man 通俗说明(维护者私有文档区)、契约文件均**不含**该
  flag/诊断面描述(apply 期以 grep 复核一次即可),零触碰。
