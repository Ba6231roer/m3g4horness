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
      "output": {"artifact": "<name>", "shape": "<shape>", "path_pattern": "<pattern>"}
    }
  ]
}
```

- `step` ∈ `not-started|discover|survey|scout|resolve|t1|t2|t3|assemble|t4|merge|done`
  (与 `resume_state.py` step 枚举一致)
- `kind` = `bash`(确定性叶脚本) 或 `subagent`(LLM stage,无 leaf script)
- `script_abs` = **绝对路径**(Windows 原生盘符);`null` for subagent steps
- `invocation` = 逐字可执行 Bash 调用行(占位符 `<target>`/`<init-dir>`/`<fmt>`/
  `<rules-dir>` 供编排器替换);`null` for subagent steps
- `input{}input`/`output` = 该步消费/产出的**逻辑 artifact**(非物理路径;
  物理路径见各 tier 的 `list_*` stdout `checkpoint_path`/`rule_path`/`done_marker`,
  扇出路径契约)

## Step→IO 表

| step | kind | script(相对 `core/scripts/`) | 输入产物 + shape | 产物路径 + shape |
|---|---|---|---|---|
| `not-started` | bash | `discover_controls.py` | — | `controls_candidates.json` {candidates[],source} |
| `discover` | bash | `discover_controls.py` | — | `controls_candidates.json` {candidates[],source} |
| `survey` | subagent | — | `controls_candidates.json` {candidates[]} | `i1_enriched.json` {summary[]} |
| `scout` | bash | `list_scout_batches.py` | `scout_plan.json` {batches[]} | `scout_candidates.json` {candidates[],source} |
| `resolve` | subagent | — | `controls_candidates.json::unresolved` [unresolved[]] | `resolved.json` {resolved[],unresolved_residual[]} |
| `t1` | bash | `list_clusters.py` | `clusters.json` {repo,clusters[]} | `checkpoints/t1/*.json` [checkpoint per cluster] |
| `t2` | subagent | — | `checkpoints/t1/*.json` [T1 records] | `controls_inventory.json` {controls[],category} |
| `t3` | bash | `list_rule_jobs.py` | `controls_inventory.json` {controls[]} | `checkpoints/t3/*.<fmt>.json` [checkpoint per category] |
| `assemble` | bash | `assemble_rules.py` | `checkpoints/t3/*.<fmt>.json` [T3 records] | `rules` (claude: `.claude/rules/security-*.md` / opencode: `docs/security-controls/*.md`) |
| `t4` | subagent | — | `rules` (rule files) | `checkpoints/t4/consistency.json.done` (marker) |
| `merge` | bash | `merge_inventories.py` | `<partials-dir>` [partial inventory JSONs] | `controls_inventory.json` {controls[],merged[]} |
| `done` | bash | — | — | `init_manifest.json` {version,counts,boundaries[]} |

> 注:`scout` 行的 `list_scout_batches.py` 是**枚举器脚本**,扇出 reader subagents;
> 真正的 scout-merge 脚本是 `merge_scout.py`(见 `resume_state.py` scout 子状态)。
> `merge` 是 `--merge` 模式的专用步骤(常规 pipeline 不经过)。

## Pattern portability

本 manifest 为 `/mgh-init` 专用;对称 `list_steps`-style 出口可后置移植到
其它 mgh-* 命令(sast/sra/srr 各有独立 stage→脚本映射,结构一致)。
