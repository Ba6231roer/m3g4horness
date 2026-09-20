# Contract: `resume_sdr_state.py` stdout — re-entrant orchestrator resume state

Producer: `core/scripts/resume_sdr_state.py` (read-only leaf). Consumer: the `/mgh-sdr`
orchestrator — the **single sanctioned outlet** for "which step am I on / what do I do
next". Called as the FIRST action after a crash, after any host context compaction, or in
a fresh session that must pick up an interrupted run.

> 进度真相源 = 磁盘(`<run-dir>/` 的 `context.json` / `grouping.json` / `markers/*` /
> `sdr_manifest.json`),**不是对话记忆**。crash / compact / 新 session 三态坍缩为同一恢复路径:
> 「读磁盘状态 → 继续」——`step` / `next_action` / 纪律全部由磁盘重派生,故「压缩是否丢掉编排
> 纪律提示词」无关紧要(新 session 重灌命令壳 = 完整提示词)。

## CLI

```
py resume_sdr_state.py --run-dir <abs> [--repo <abs>] [--check]
py resume_sdr_state.py --run-dir <abs> [--repo <abs>] --rearm-sentinel
```

`--run-dir` **必填**:sdr 没有唯一缺省运行目录(launcher 每次按时刻新建
`<repo>/.mgh-sdr/runs/<ts>-<branch>/`)。目录不存在 → 退出码 `1` + recipe。
`--repo` 可省:`context.json::repo` > `--repo` > 运行目录布局(`<repo>/.mgh-sdr/runs/<…>`);
三者皆不可得 → `repo` 为空串 + `notes[]` 要求显式传参(**NEVER 编造仓库根**)。

## Run 目录布局假设

`run-dir` 有两条产生路径(launcher 的时间戳目录、命令壳的 `--run-dir`),脚本对两者一视同仁,
**只吃一个运行目录**,不对目录命名做任何假设。仅 `--repo` 的**布局回退**会读
`<repo>/.mgh-sdr/runs/<name>` 这一形态。

## stdout shape

```json
{
  "repo": "<abs, Windows-native>",
  "run_dir": "<abs>",
  "base": "<ref>",
  "branch": "<ref>",
  "step": "<enum>",
  "resumable": true,
  "tiers": {"done": 2, "failed": 1, "total": 5},
  "next_action": {"kind": "bash|subagent|done", "desc": "...", "absolute_paths": ["<abs>"]},
  "notes": ["..."],
  "discipline_reminders": {"gates": [], "path_recipes": [], "nevers": []},
  "stale_fanout": [{"tier": "sdr", "pid_file": "<abs>", "pid": 1234,
                    "pid_alive": false, "note": "..."}]
}
```

- `step` ∈ `not-started|group|fanout|render|done`,语义 = **当前待办步**(说「下一步做什么」,
  而非「上一步做完了什么」)。`resumable` = `step != "done"`。
- `base`/`branch` 从 `context.json` 重派生,缺则回退 `grouping.json`;两处冲突以 `context.json`
  为准并在 `notes[]` 披露。
- `next_action.absolute_paths` = `Path.resolve()` 绝对值,逐字取自磁盘,**无占位符、无相对路径**;
  命令行为 `py <script_abs> ...`,脚本路径由 `__file__` 自定位(宿主前缀无关)。
- `discipline_reminders` 字段**恒存在**:`{gates[], path_recipes[], nevers[]}`;`done` /
  `not-started` 与未知步返回**三键皆空**的结构(shape 稳定)。内容与 `list_sdr_steps.py --step`
  的 `discipline` 逐字一致(同一静态表,两个消费者)。
- `stale_fanout[]` 字段**恒存在**:扫 `<run-dir>/fanout_runner.*.pid` 残留存活文件,报
  `{tier, pid_file, pid, pid_alive, note}`;PID 存活时 note 携带 `--kill-stale --dry-run` recipe。
- `--run-dir` 内 `context.json` / `grouping.json` **存在但不可解析** → 退出码 `2` + recipe
  (**NEVER** 从不完整产物猜步骤图)。

## step 判定真值表(按序短路,判据全是磁盘存在性)

| `step` | 判据 | `next_action` |
|---|---|---|
| `not-started` | `context.json` 不存在 | `sdr_context.py --repo <abs> --run-dir <abs>`(该步同时写出哨兵与运行目录的 codegraph 信号) |
| `group` | `context.json` 在、`grouping.json` 缺 | `diff_group.py --repo --base --branch --checkpoints <run>/markers --materialize <run>/slices` |
| `fanout` | `grouping.json` 在,单元未全终态 | `fanout_runner.py --tier sdr ...`(带四级超时三参数) |
| `render` | 单元全终态、`sdr_manifest.json` 缺 | `render_sdr_report.py --run-dir <abs> --repo <abs>` |
| `done` | `sdr_manifest.json` 在 | 无(`resumable=false`) |

- **终止凭证** = `<run-dir>/sdr_manifest.json`;该文件不存在 ⇒ run 未收尾(渲染器先写报告
  再写 manifest,故 manifest 在 ⟹ 报告已产出)。
- **单元终态判据** = `done + failed >= total`,其中 done/failed 是「canonical 单元 id 的
  **正向 marker 路径**存在性」判定(`markers/<unit_id>.{done,failed}`)。MUST NOT 采信
  `grouping.json::units[].status`(枚举时点快照,fan-out 后即陈旧),MUST NOT 由 glob 文件数
  或文件名 stem 反推。marker 路径拼接规则与写入方 `diff_group.py` **共享同一模块**
  (`sdr_tier.py`),口径不可能分叉。
- `.failed` = **终态**(确认失败,`--resume` 不重试、不阻塞),任一 `failed>0` 进 `notes[]` 披露。
- **零 diff / 全排除**:`empty == true`,或 `total == 0` 而 `excluded.count > 0` ⇒ `0 >= 0`
  视为 fan-out 已完成,`step` 直接推进到 `render`,**NEVER** 停在 fan-out 空转;`notes[]` 区分
  两种成因(零变更 diff ≠ 全被排除)。
- **孤儿 marker**(文件名不对应任何 canonical 单元 id)进 `notes[]` advisory,**不计入**任何
  done/failed 计数。

## 起始态不可重派生的显式退化披露

`not-started` 步 `context.json` 尚未写出,起始态(尤其 `--base`/`--branch`)在磁盘上
**无可判定产物**。此时 `notes[]` 载明「起始态未落盘,需重新给定」,`next_action.desc` 给出含
默认值提示的可执行调用(`--base master`;`--branch` 为当前分支)。脚本**不跑 git 猜分支**——
中断期间若用户切了分支,默认值会与实际 run 的分支不符,冒用他人分支做 diff 的代价高于多打一个参数。

该退化**不是数据丢失**:这一步恰是零已完成工作的步(run 目录刚建立),重新给参重跑即完整恢复。
运行目录里的 `run_config.json` 之所以**不**承载起始态,正由这一条支撑——它只承载 codegraph
信号(见 [`pipeline.md`](pipeline.md));本脚本**不读**该文件。

## `--check`(自洽校验)

不自洽 → 退出码 `2` + `violations[]`;自洽 → 退出码 `0`。stdout 另含 `notes[]`(advisory,非 gate)。

| 检查项 | 判定 |
|---|---|
| 哨兵缺失 | `step ∈ {group, fanout, render}`(已有工作产物)而 `<repo>/.mgh-sdr/.active` 不存在 → **违例**(守卫休眠 = 只读/子树限定静默失效)+ re-arm recipe;`not-started` 仅 advisory;`done` 不违例(守卫本就应休眠) |
| 歧义终态 | 同一单元同时携带 `.done` 与 `.failed` → **违例** |
| work-list 一致性 | `grouping.json::pending[]` 出现 `units[]` 里不存在的 unit_id → **违例** |
| 孤儿 marker | 不与任何 canonical 单元 id 对应 → **advisory**(不计入计数) |
| 残留存活文件 | `stale_fanout[]` 非空 → **advisory** |

repo 不可推导时哨兵检查降级为 advisory(位置无法解析),并在 `notes[]` 明说「本检查未生效,
传 `--repo <abs>` 使其生效」——**NEVER** 静默跳过。

## `--rearm-sentinel`(确定性重写哨兵)

据磁盘重写 `<repo>/.mgh-sdr/.active`:`target` = `context.json::repo`,`read_roots[]` =
`context.json::external_repos[].path` 中**仍存在且为目录**者(**失效路径被剔除**,fail-closed
方向不放宽授权),`domain` 恒 `mgh-sdr`,`out_roots` 为 `[]`。原子写(`.tmp` + `os.replace`)、
**幂等**(同一磁盘状态 → 逐字相同文件)。路径由 Python 产出(Windows 原生),**NEVER** shell 的
MSYS 形态(`/c/…`)。`context.json` 缺失或 repo 不可得 → 退出码 `2` + recipe。

> 哨兵的正常写入者是 `sdr_context.py`(本步是 launcher 与宿主会话两条入口都必经的第一步),
> 本命令是其**缺失时的确定性补写**入口,内容同源。
