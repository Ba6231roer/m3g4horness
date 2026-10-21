# Contract: `list_steps.py` stdout — per-step invocation manifest

Producer: `core/scripts/list_steps.py` (read-only leaf). Consumer: the
`/mgh-init` orchestrator — the canonical source for "what is the exact
invocation line for each step". Complements `resume_state.py` (disk-derived
"which step am I / what's next"): `resume_state` yields current step,
`list_steps.py --step <id>` yields the exact invocation line for that step.

> Zero disk preconditions: does NOT read run_config.json, does NOT scan
> `.mgh-init/`, does NOT depend on any run-state artifacts. Queryable pre-run,
> during compaction recovery, or for pure documentation review.

## Host prefix derivation

每步的 `script_abs` 是经 `Path(__file__).resolve().parent` 派生的**绝对路径**
(本脚本所在 `scripts/` 目录的同族文件)。宿主前缀(`.claude/mgh-core/` vs
`.opencode/mgh-core/`)由脚本实际安装位置决定,**NEVER** 硬编码、**NEVER**
经提示词传递。claude install 下 emit `<target>/.claude/mgh-core/scripts/<x>.py`;
opencode install 下 emit `<target>/.opencode/mgh-core/scripts/<x>.py`。模型逐字直抄
该绝对路径,**NEVER** 猜 `scripts/` vs `mgh-core/scripts/`、**NEVER** 漏宿主前缀。

## Complementarity with `resume_state.py`

- `resume_state.py` 答「我在哪 / 下一步干啥」(磁盘真相,需 run_config 存在)
- `list_steps.py` 答「这一步的确切调用行 / 全量 step→IO map」(静态契约,零前置)
- 配套用:`--resume` 或压缩后 → `resume_state` 给 `step` → `list_steps --step <id>` 给确切调用行

## CLI

```
py list_steps.py [--target <dir>] [--step <id>]
```

`--target` 接受但不使用(未来扩展锚点)。`--step <id>` 打单步(闭集,未知 id → exit 2)。
`--step` **只接受命名枚举 id**(与 `resume_state.py` step 枚举一致:
`not-started|discover|survey|scout|resolve|t1|t2|t3|assemble|t4|done`);数字索引
(如 `--step 0`)→ exit 2(闭集拒歧义)+ stderr 附**可操作 hint**(id 是命名枚举、读
`resume_state.py` stdout `step` 或 `list_steps.py` 不带 `--step` 列全表;numeric indices
NOT accepted)。

**bootstrap 可达性**:`not-started`(bootstrap)不在 `stage_flow_files[]`(`resume_state.py` 对
not-started 返回空数组、run_config 前 exit 1)——fresh-run 的 bootstrap 正文由壳 **fixed-path
Read** `<mgh-core>/prompts/fragments/init-stage/bootstrap.md` 加载,NEVER 对 bootstrap 调
`list_steps --step <数字>`。

## stdout shape

```json
{
  "steps": [
    {
      "step": "<id>",
      "kind": "bash|subagent",
      "script": "<name>.py | null",
      "script_abs": "<abs path> | null",
      "invocation": "py <script_abs> <args> | null",
      "input": {"artifact": "<name> | null", "shape": "<shape> | null"},
      "output": {"artifact": "<name>", "shape": "<shape>", "path_pattern": "<pattern>"},
      "discipline": {"gates": [{id,desc,command,fail_exit}], "path_recipes": [{id,desc,source}], "nevers": ["<NEVER ...>"]}
    }
  ]
  [, "dispatch": {"form": "native", "source": "profile|host-default",
                  "profile_exists": bool, "host_face": "opencode", "consumer": "init",
                  "profile_path": "<abs>", "plan_present": bool,
                  "native_agent": "init-scout-native", "discipline_fragment": "<abs>"}]
}
```

- `step` ∈ `not-started|discover|survey|scout|resolve|t1|t2|t3|assemble|t4|done`
  (与 `resume_state.py` step 枚举一致)
- `kind` = `bash`(确定性叶脚本) 或 `subagent`(LLM stage,无 leaf script)
- `script_abs` = **绝对路径**(Windows 原生盘符);`null` for subagent steps
- `invocation` = 逐字可执行 Bash 调用行(占位符 `<target>`/`<init-dir>`/`<fmt>`/
  `<rules-dir>` 供编排器替换);`null` for subagent steps
- `input{}input`/`output` = 该步消费/产出的**逻辑 artifact**(非物理路径;
  物理路径见各 tier 的 `list_*` stdout `checkpoint_path`/`rule_path`/`done_marker`,
  扇出路径契约)
- `discipline` = 该步纪律子集(gate 闸门形状 `--check` 命令 + 退出码 2 / fan-out 路径配方 /
  适用 NEVER),与 `resume_state.py` stdout 同 step 的 `discipline_reminders[]` **逐字一致**
  (共享静态表 `core/scripts/discipline_core.py`,单一真相;`done`/`not-started`/未知 → 空结构)
- `dispatch` = **仅原生形态在场**(解析形态 native ∧ `host_face=="opencode"`;scout 读者批 +
  聚合四层 map 段的派发形态,经 `env_profile.resolve(<target>, consumer="init")` 单源解析)。
  除既有八键外,**聚合扩展键**(additive):`aggregate_fragment`(聚合纪律 fragment 绝对路径)、
  `aggregate_agents`({t1: init-induct-native, t2: init-synthesis-native, t3:
  init-rulewriter-native, scout-merge: init-scout-merge-native})、`aggregate_plan_present`
  (各层 `native_plan_<tier>.json` 在场佐证)。子进程形态(显式 `dispatch_mode:"runner"`、
  `consumer=generic`、claude/dsh/other 面)**不出现该字段**,stdout 逐字节回到既有形状——读者以
  「字段缺席 = 子进程」解释。fail-closed 面:坏画像 / native+非 opencode 面 / 缺 init 原生资产
  (五只 `init-*-native` 孪生或两个纪律 fragment 任一缺席)→ 退出码 2 + recipe,NEVER 静默回退。

## Step→IO 表

| step | kind | script(相对 `core/scripts/`) | 输入产物 + shape | 产物路径 + shape |
|---|---|---|---|---|
| `not-started` | bash | `discover_controls.py` | — | `controls_candidates.json` {candidates[],source} |
| `discover` | bash | `discover_controls.py` | — | `controls_candidates.json` {candidates[],source} |
| `survey` | subagent | — | `controls_candidates.json` {candidates[]} | `i1_enriched.json` {summary[]} |
| `scout` | bash | `fanout_runner.py` | `scout_plan.json` {batches[]} | `scout_candidates.json` {candidates[],source} |
| `resolve` | subagent | — | `controls_candidates.json::unresolved` [unresolved[]] | `resolved.json` {resolved[],unresolved_residual[]} |
| `t1` | bash | `fanout_runner.py` | `clusters.json` {repo,clusters[]} | `checkpoints/t1/*.json` [checkpoint per cluster] |
| `t2` | bash | `fanout_runner.py` | `checkpoints/t1/*.json` [T1 records] | `controls_inventory.json` {controls[],category} |
| `t3` | bash | `fanout_runner.py` | `controls_inventory.json` {controls[]} | `checkpoints/t3/*.<fmt>.json` [checkpoint per category] |
| `assemble` | bash | `assemble_rules.py` | `checkpoints/t3/*.<fmt>.json` [T3 records] | `rules` (claude: `.claude/rules/security-*.md` / opencode: `docs/security-controls/*.md`) |
| `t4` | subagent | — | `rules` (rule files) | `checkpoints/t4/consistency.json.done` (marker) |
| `done` | bash | — | — | `init_manifest.json` {version,counts,boundaries[]} |

> **dispatcher-first 扇出步**:scout/t1/t2/t3 四行的 script = `fanout_runner.py`(确定性派发器,
> 与 `list_steps.py` stdout `script` 字段一致,回归测同步把守)——各扇出 tier 的枚举/物化脚本
> (`list_scout_batches.py` / `list_clusters.py` / `list_rule_jobs.py` / `plan_aggregate.py`)
> 由 runner 的 tier 配置**内部调用**,NEVER 编排器直调。t2 行的 bash = map 段派发
> (`fanout_runner.py --tier t2`);小仓(needs_reduce=false)single-context `init-synthesis`
> 子代理分支见 t2 fragment。scout 步另载 `extra_invocations`(scout-merge map 段驱动:
> `fanout_runner.py --tier scout-merge`)。`merge` 是 `--merge` 模式的专用步骤(常规 pipeline
> 不经过);真正的 scout-merge 聚合脚本是 `merge_scout.py`(见 `resume_state.py` scout 子状态)。

### scout 原生步形(`dispatch` 字段在场时;子进程表不受影响)

解析形态为 native 时,scout 行**整体替换**为计划物化入口(确定性脚本仍是 stdout 契约面,
派发本身是编排纪律,由 `native_arc` 相位承载):

| 字段 | 值 |
|---|---|
| `script` / `script_abs` | `emit_native_plan.py`(绝对) |
| `invocation` | `py <emit_abs> --tier scout --scout-plan <init-dir>/scout_plan.json --checkpoints <init-dir>/checkpoints/scout --inputs-dir <init-dir>/inputs/scout --profile <target>` |
| `input` | `scout_plan.json` {batches[]}(发现本体不变:批规划仍由 `plan_scout.py` 产出 + `--check` 校验) |
| `output` | `<init-dir>/native_plan.json` + `<init-dir>/inputs/scout/<batch_id>.task.md`(页界波次拆分 + 每批任务文件;终态标记由子代理自写) |
| `native_arc` | `[{phase:"materialize", kind:"bash", script, invocation, note}, {phase:"waves", kind:"subagent", agent:"init-scout-native", discipline_fragment, note}, {phase:"merge", kind:"bash", step_ref:"scout-merge", note}]` |
| `extra_invocations` | **换为** scout-merge map 段的原生驱动行(`emit_native_plan.py --tier scout-merge`,聚合步形见下;子进程形态仍为 `fanout_runner.py`) |
| `discipline` | `get_discipline("scout", domain="init", form="native")`(与 `resume_state.py` 同 step 同 form 逐字一致) |

- **页语义**:一次物化只覆盖枚举器当前 pending 页(编排预算收紧页,stdout `units_total`
  = 本页单元数);派完当前页**重物化**取下一页,循环直到 `units_total == 0` 才进
  scout-merge——NEVER 假设一次计划覆盖全部批、NEVER 手工翻 `scout_plan.json`。
- **波次派发**(waves 相位,编排纪律):同一条 assistant 消息并发派当前波全部单元
  (agent `init-scout-native`,`mode: subagent`;`description`=计划短号逐字,任务体=单行
  令牌 `mgh-dispatch: plan=<plan_path> unit=<短号>`,派发插件 `mgh_dispatch.ts` 的令牌展开
  钩子在子代理启动前展开为任务文件全文;展开钩子缺席的旧版安装回退=固定句+task_file
  绝对路径逐字透传)。标记唯一写者是子代理自身(成功 touch `.done`;失败自写 `.failed`,
  内容 `{unit_id, reason}`——该指令仅住原生 agent 定义,共享任务模板零改动);失败批至多
  一轮重派,限流特征按画像配额等窗;看门狗先行(`native_watchdog.py --run-dir <init-dir>`,
  阈值缺省,run 落定自退)。
- **plan 工件探针**:`dispatch.plan_present` = `<target>/.mgh-init/native_plan.json`
  在场(佐证信号,解析形态才是绑定决策)。**计划文件按 tier 命名**:scout 与 sdr 用未带
  后缀的 `native_plan.json`(既有约定);四个聚合 tier 各用 `native_plan_<tier>.json`
  (`native_plan_t1.json` / `native_plan_t2.json` / `native_plan_t3.json` /
  `native_plan_scout-merge.json`)——共享同一 init 目录的各层互不覆写对方的计划工件
  (`dispatch.aggregate_plan_present` 逐层佐证)。

### 聚合层原生步形(t1/t2/t3;`dispatch` 字段在场时;子进程表不受影响)

解析形态为 native 时,t1/t2/t3 三行**整体替换**为各自的原生面(确定性入口 = 计划物化器;
各层既有语义一个不动,细则住 `init-aggregate-native-dispatch.md` 纪律 fragment):

| 字段 | t1 | t2 | t3 |
|---|---|---|---|
| `script` 字段 | `emit_native_plan.py --tier t1`(可透传 `--pack-bytes/--pack-max` 打包) | `emit_native_plan.py --tier t2` | `emit_native_plan.py --tier t3` |
| `native_arc` 相位 | `materialize → dispatch → gate` | `gate → materialize → dispatch → rollup` | `materialize → dispatch → gate` |
| `dispatch` 相位 | `kind:"tool", tool:"mgh_dispatch", agent:"init-induct-native"`(**默认通道 B**:一次工具调用跑完本页全部波次,输入只带计划引用;工具缺席回退通道 A 同消息波次) | 同形,`agent:"init-synthesis-native"` | 同形,`agent:"init-rulewriter-native"` |
| 收口相位 | T1→T2 形状闸门(`validate_t1_records --strip-bom + --check`,两形态共用) | `gate` 相位 = 聚合预算闸门先行(`plan_aggregate --node t2`;`needs_reduce=false` **零派发**:物化器不产计划、不建会话,single-context `init-synthesis` 照旧);`rollup` 相位 = manifest 消费(`rollup.summary_paths` 清单路径)不变 | 规则纯净 lint(`assemble_rules.py --check`,两形态同一校验器);done/failed 正向判定 / 孤儿审计不变 |
| 计划文件 | `native_plan_t1.json` | `native_plan_t2.json`(仅 `needs_reduce=true` 才产) | `native_plan_t3.json` |
| `discipline` 字段 | `get_discipline("t1", domain="init", form="native")` | `get_discipline("t2", …, form="native")` | `get_discipline("t3", …, form="native")` |

- **页语义与 scout 同构**:一次物化只覆盖枚举器当前 pending 页;通道 B 一次调用跑完的是
  **本页**的全部波次;`units_total == 0` 才离开该层循环。
- **各层不变量**(逐项保持):t1 pack 打包摊薄(成员级 `.done` 唯一真相源)+ scout 完成
  闸门透传;t2 `needs_reduce=false` 零派发 + rollup manifest 消费面;t3 唯一带写权限孪生
  `init-rulewriter-native`(写面只开规则产物,越树写被运行域守卫拦)。
- scout-merge 的 map 分片派发在原生形态经 scout 步的 `extra_invocations`(物化驱动行)+
  聚合纪律 fragment 承载;其单上下文 / rollup / audit / fold-in 段不变。

## Pattern portability

本 manifest 为 `/mgh-init` 专用;对称 `list_steps`-style 出口可后置移植到
其它 mgh-* 命令(sast/sra/srr 各有独立 stage→脚本映射,结构一致)。
