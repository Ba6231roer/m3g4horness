# opencode fan-out runner:一个 py 脚本并行跑多个 opencode 任务

> **受众**:人类(教学向,看完就能动手)。本文是「怎么回事 + 能不能一个脚本搞定 + 极简可用版」
> 的一站式说明;深度论证见文末索引。

## 0. 一句话结论

**可以。** 在 opencode 里并行跑 N 个子任务,本质上就是**同时启动 N 个 `opencode run` 子进程**,
每个进程的任务消息经 **stdin** 递入。这件事完全不需要 LLM 参与调度——一个只用 Python 标准库的
脚本就能做完「派发 → 收尾 → 断点续跑」的完整循环。双宿主真机已实证(5 个并发 `opencode run`
同仓跑,互不干扰、无 SQLite 锁冲突),并已在 `/mgh-init` scout 层产品化
(`core/scripts/fanout_runner.py`)。

## 1. opencode 派子任务有三条路,为什么选「子进程」

| 路                                                  | 怎么派                | 并行                              | 结论                                                   |
| -------------------------------------------------- | ------------------ | ------------------------------- | ---------------------------------------------------- |
| ① 交互会话里模型发 `task` 工具调用                             | 主 agent(LLM)每回合亲手派 | ✅ 同回合多调用并发                      | ❌ 每波之间必经一次 LLM 回合(看结果→决定下一批),几千批时白烧 token 且弱模型会漂     |
| ② HTTP API / 消息里注入 `subtask` part                  | 外部程序直接喂 prompt     | ❌ **串行**(源码每轮只 pop 一个、逐个 await) | ❌ 并行性直接出局                                            |
| ③ **CLI 子进程:`opencode run --agent <名>`,消息走 stdin** | 任意脚本 spawn 子进程     | ✅ 线程池起 N 个进程                    | ✅ **本方案**。subagent 的创建本就不需要 LLM——「派谁、喂什么消息」可以全部由代码决定 |

路 ③ 的关键事实(均已在本仓 spike 真机实证,源码锚点为本地 `C:\DEV\opencode` checkout v1.18.x):

| # | 事实 | 锚点 |
| --- | --- | --- |
| 1 | `opencode run --agent X` 的 X **必须是 `mode: primary`**;给 `mode: subagent` 的 agent 会打警告并**静默退回默认 agent**(任务照跑,但 agent 定义/权限全丢) | `packages/opencode/src/cli/cmd/run.ts:610-617` |
| 2 | 任务消息可经 **stdin** 递入:stdin 非 TTY 时 `run` 主动读 `Bun.stdin.text()` 当消息 | `run.ts:416` |
| 3 | 默认输出格式下,**stdout 末行 = 最终回传消息**(恰好可当回执解析) | spike 实证 |
| 4 | 5 个并发 `opencode run` 同仓同 cwd:全部 exit=0,无 SQLite 锁死 | spike 实证 |
| 5 | 子进程 cwd 设为目标项目根,则它加载该项目的 agent 定义/插件,与手跑无异 | spike 实证 |

## 2. fan-out runner 的最小闭环 = 四件事

```mermaid
flowchart TB
    D["minifanout.py(纯代码,无 LLM)"] -->|"读 tasks.json"| P["pending 清单<br/>(扫 .done 标记重派生)"]
    P --> W["取下 N 个 → 线程池并发 spawn<br/>opencode run --agent worker<br/>(消息走 stdin, cwd=项目根)"]
    W --> M["子任务自己写产物 + touch .done<br/>末行回执: ok / failed"]
    M -->|"pending 还有剩"| P
    M -->|"pending 空 / 无进展"| S["stdout 打 JSON 摘要,退出"]
```

1. **任务清单从哪来**:一个 JSON 数组,每项 `{id, message}`。哪些还没做完?**扫磁盘标记**——
   `<id>.done` 文件存在 = 完成。清单永远从磁盘重派生,所以脚本被杀再跑就是天然的断点续跑。
2. **怎么并发**:`ThreadPoolExecutor` + `subprocess.run`,一个 worker 一个 `opencode run` 子进程。
3. **怎么算完成**:子任务在消息里被约定「干完活 touch `.done`,最终回复单行回执」。回执解析不出
   来也没关系——**磁盘标记是唯一真相源**,有 `.done` 即完成。
4. **怎么收敛**:一波跑完重扫标记 → 还有 pending 就派下一波;pending 空 = 全部完成;连续一波
   零进展 = 熔断停下(防死循环),剩下的留给下次重跑。

## 3. 四个必踩的坑(Windows / 双宿主真机实证,全部踩过)

| # | 坑 | 现象 | 解法 |
| --- | --- | --- | --- |
| 1 | npm 装的 CLI 在 Windows 是 `.cmd` 转发脚本 | `subprocess.run(["opencode", ...])` 直接 WinError 2 | 用 `shutil.which("opencode")` 解析成绝对路径再 spawn |
| 2 | 多行消息放 argv 会被 `.cmd` 转发脚本截断 | 子任务只收到第一行(实测只收到 `<!--`) | 消息走 **stdin 管道**(`input=...`),两个宿主都支持 |
| 3 | `--agent` 给了 `mode: subagent` 的定义 | 警告后静默换默认 agent,权限/提示词全丢 | 给 fanout 用的 agent 定义写 `mode: primary` |
| 4 | 三层超时嵌套关系错 | 被宿主 Bash 硬杀,在飞的一波全丢,退化成「杀→重派→再杀」循环 | 自内向外:**单进程超时 < 脚本软时限 < 宿主 per-call 超时**,每级留 ≥20% 余量;软时限到了就停发新波、等在飞的跑完、干净退出(下次重派续跑) |

## 4. 极简可用版(标准库,可直接抄跑)

三样东西:① 一个 worker agent 定义(也可以不要,见下);② `tasks.json`;③ `minifanout.py`。

**① worker agent(可选)**:不指定 `--agent` 就用默认 agent,最简演示可以跳过。要专用 worker
就在目标项目 `.opencode/agent/worker.md` 放(`mode: primary` 是硬要求,见坑 3):

```yaml
---
description: fanout worker
mode: primary
---
你是并行子任务执行者:严格按任务消息办事,最终只回一行结论。
```

**② `tasks.json`**(消息里约定好 `.done` 标记与单行回执,这是整个断点续跑机制的根基;
`<项目根>` 是给你抄写时替换成**绝对路径**的——子任务不信任相对路径,任意 cwd 都安全):

```json
[
  {"id": "t1", "message": "任务:数 README.md 里有几个二级标题。完成约定:用 bash 执行 `touch <项目根>/.minifanout/done/t1.done`(路径按此原样),然后最终只回一行:`ok t1 <数量>`。"},
  {"id": "t2", "message": "任务:数 src/ 下有几个 .py 文件。完成约定:用 bash 执行 `touch <项目根>/.minifanout/done/t2.done`(路径按此原样),然后最终只回一行:`ok t2 <数量>`。"}
]
```

**③ `minifanout.py`**——完整闭环 ~50 行,零第三方依赖:

```python
#!/usr/bin/env python3
"""minifanout.py — 极简 opencode 并行派发(纯标准库)。
用法: py minifanout.py tasks.json   (在目标项目根运行)
约定: 子任务完成时自己 touch .minifanout/done/<id>.done(写进任务消息);
      被杀/超时的子任务没有 .done → 下次重跑自动重派。"""
import json, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

WAVE, CALL_TIMEOUT_S = 5, 7200
REPO = Path.cwd()                       # 子进程 cwd = 目标项目根
DONE = REPO / ".minifanout" / "done"

def spawn(task):
    exe = shutil.which("opencode") or "opencode"     # 坑1: Windows .cmd 解析绝对路径
    try:
        r = subprocess.run([exe, "run", "--agent", "worker"],   # 坑3: agent 须 mode: primary
                           input=task["message"],                # 坑2: 消息走 stdin
                           cwd=str(REPO), capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=CALL_TIMEOUT_S)
        last = (r.stdout or "").strip().splitlines()[-1:] or ["<no output>"]
        print(f"[{task['id']}] exit={r.returncode} ack={last[0][:120]}", file=sys.stderr)
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"[{task['id']}] crash/timeout: {e} -> 留 pending, 重跑即重派", file=sys.stderr)

def pending(tasks):
    return [t for t in tasks if not (DONE / f"{t['id']}.done").exists()]

def main():
    tasks = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    DONE.mkdir(parents=True, exist_ok=True)
    while (pend := pending(tasks)):
        print(f"wave: {[t['id'] for t in pend[:WAVE]]}", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=min(WAVE, len(pend))) as pool:
            list(pool.map(spawn, pend[:WAVE]))
        if len(pending(tasks)) == len(pend):          # 零进展熔断,防死循环
            print("no forward progress; stop (剩下的重跑本脚本即续)", file=sys.stderr)
            break
    print(json.dumps({"total": len(tasks), "pending": len(pending(tasks))}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

跑起来:

```bash
py minifanout.py tasks.json        # 进度看 stderr,摘要看 stdout(JSON)
```

中途 Ctrl-C / 超时 / 断电都不丢进度:重跑同一命令,已 `.done` 的自动跳过,剩下的继续派。

## 5. 极简版 → 产品版的差距(为什么 `fanout_runner.py` 有 600 行)

极简版保留了**骨架闭环**(波次循环 / stdin 消息 / 标记断点续跑 / 零进展熔断),产品版
`core/scripts/fanout_runner.py` 在骨架之上补的都是真机跑大仓才暴露的承重件:

| 能力 | 极简版 | 产品版做法 |
| --- | --- | --- |
| 任务消息来源 | 手写 JSON | **固定模板 + 逐字字段替换**(`core/prompts/fragments/fanout/scout-task.md`),路径拼写错误类失败从根上消失 |
| pending 清单来源 | 静态 tasks.json | 消费枚举脚本 `list_scout_batches.py` stdout(分页/预算/物化绝对路径) |
| 路径安全 | 无 | 派发前 `resolve()` 锚树校验,越树单元直接记失败、绝不 spawn(防「输出漂到盘符根」) |
| 失败语义 | 只认 `.done` | `failed` 回执 → 写 `.failed` 终态标记(不重试);crash 无标记 → 留 pending 重派(crash ≠ 确认失败) |
| 软时限 | 无 | `--time-budget-ms` 停发新波、等在飞收敛、退出码 0 + `partial:true` 干净早退(坑 4 的完整解) |
| 可观测 | stderr 行 | 人类面进度 sidecar `fanout_progress.json`(第二终端 `Get-Content -Wait` 盯)+ 每单元审计副本 `<batch_id>.task.md`(复盘「子任务到底收到了什么」) |
| 宿主适配 | 仅 opencode | `--host` 自动探测 opencode/claude(`claude -p --agents <JSON>` 等价映射),都缺则 fail-loud + 回退手派 |
| 回归保障 | 无 | 单测 `tests/test_fanout_runner.py` + 契约 lint + token lint |

## 6. 参考索引

| 材料 | 位置 |
| --- | --- |
| 可行性分析(subagent 创建机制、三路对比、源码锚点) | [`docs/opencode-subagent-fanout-analysis.md`](opencode-subagent-fanout-analysis.md) |
| change 提案 / 设计(含 spike 实证回填) | `openspec/changes/archive/2026-08-18-add-mgh-init-scout-fanout-runner/{proposal,design}.md` |
| 已 sync 的能力规格 | `openspec/specs/fanout-dispatch/spec.md` |
| 产品版调度器 | `core/scripts/fanout_runner.py` |
| fanout 专用 agent 定义(`mode: primary` 克隆) | `releases/opencode/agent/init-scout-fanout.md` |
| 任务消息模板 | `core/prompts/fragments/fanout/scout-task.md` |
| opencode 源码锚点 | `C:\DEV\opencode` `packages/opencode/src/cli/cmd/run.ts:416`(stdin)、`:610-617`(拒 subagent) |
