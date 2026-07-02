# m3g4h⊿rness — agentic security harness for Claude Code + opencode

**m3g4h⊿rness**（读作 *megahorn-ness*；双重语义：宝可梦招式「超级角击 / Megahorn」，
隐喻渗透测试的角击；亦是 *mega-harness* 之意）是一套面向 AI 编程 Agent 的安全工作流
工具族。所有命令共享前缀 **`mgh-`**，确定性脚本零第三方依赖（仅 Python ≥3.10 标准库）。

## Tools

| 命令 | 状态 | 用途 |
|---|---|---|
| `/mgh-sast` | ✅ 可用 | 9 阶段 agentic SAST（survey → threat-model → decompose → deep-dive → prefilter → verify → dedup → chain → SARIF）。零运行时依赖地复刻 vvaharness 流水线。 |
| `/mgh-init` | ✅ 可用 | 发现存量安全控制（输入校验/脱敏/鉴权/加密等）→ 生成 Agent rules（Claude Code `.claude/rules/` 或 opencode `AGENTS.md`，二选一不混用）。隔离优先三层流水线；产出 `controls_inventory.json`（与 vvah `design_controls` schema 兼容）。 |
| `/mgh-sra` | 🚧 TODO | 在 openspec `propose` 后辅助补充 specs/tasks 的安全设计内容，并引导读取 mgh-init 产出的 rules。 |
| `/mgh-blst` | 🚧 TODO | 结合业务接口逻辑与 mgh-init 的 rules，设计与业务强耦合的安全测试案例（如换账户/auth 检验越权）。 |

> 本 README 余下内容聚焦 **`/mgh-sast`** 与 **`/mgh-init`** 两个已可用命令。`/mgh-sra`、
> `/mgh-blst` 仍为空骨架，功能定义见 [`task.260630.md`](task.260630.md)。

## `/mgh-sast` — 9-stage agentic SAST

A self-contained, **zero-runtime-dependency** reimplementation of the vvaharness
9-stage LLM SAST pipeline as a native agent command. It surveys a codebase,
threat-models it, decomposes it, deep-dives each chunk, adversarially verifies
findings, deduplicates, builds exploit chains, and emits a Markdown report +
SARIF 2.1.0.

> **Faithful to the original.** Prompts and workflow are ported from
> `vvaharness/` (Visa / Project Glasswing, Apache-2.0) — see
> `core/docs/prompt-provenance.md` and `core/docs/NOTICE`. This package does
> **not** import or call any `vvaharness/` code. 功能实现/提示词与原项目的逐项对应关系见
> [`docs/upstream-index.md`](docs/upstream-index.md)（非必要不改，便于上游更新同步）。

## Layout

```
m3g4horness/
├── AGENTS.md                 # 研发规则 + mgh-sast 与原项目关系(必读)
├── core/                     # platform-neutral, single source of truth
│   ├── prompts/              # stage system prompts + fragments + lenses + baselines (ported)
│   ├── scripts/              # diff_seed / expand_scope / prefilter / dedup / emit_sarif
│   ├── profiles/             # default / cli / full
│   ├── contracts/            # stage I/O JSON schemas
│   └── docs/                 # prompt-provenance, NOTICE
├── releases/claude-code/     # Claude Code shell → mirrors into .claude/
│   └── commands/{mgh-sast,mgh-init,mgh-sra,mgh-blst}.md
├── releases/opencode/        # opencode shell → mirrors into .opencode/
│   └── command/{mgh-sast,mgh-init,mgh-sra,mgh-blst}.md
├── docs/                     # 分发指南 + upstream-index(原项目引用)
└── tools/                    # 构建期工具(extract_prompts / gen_*)，不随安装分发
```

## Install

**工具包与目标仓分离**：`m3g4horness/` 是独立工具包（放在自己的路径）；install.sh 把
运行时载荷**注入到你的业务仓**的 `.claude/` 或 `.opencode/`，不会把整个工具包拷进业务仓。

```bash
# 在「业务仓根目录」里执行，把 m3g4horness 指过去（默认 Claude Code）：
bash /PATH/TO/m3g4horness/install.sh --claude .        # → 本仓/.claude/
bash /PATH/TO/m3g4horness/install.sh --opencode .      # → 本仓/.opencode/
# Windows PowerShell：
.\PATH\TO\m3g4horness\install.ps1 -Platform claude -Target .
```

install.sh 会：(1) 自检零运行时依赖（不 import `vvaharness`）；(2) 把所选 shell + `core/`
拷进目标仓的 `.claude/` 或 `.opencode/`（`core/` 以 `mgh-core/` 名义；**不**拷 `tools/`、
`tests/`、`openspec/`、`docs/`）。多个业务仓可共用同一个工具包，各自安装、互不污染。

> **企业内网分发？** 多业务系统、Claude Code 与 opencode 混用环境的完整安装/使用/分发说明见
> [`docs/分发与使用指南.md`](docs/分发与使用指南.md)。

## Dependencies（无需 pip）

**确定性脚本零第三方依赖**——全部只用 Python ≥3.10 标准库（`argparse / ast /
collections / datetime / json / math / pathlib / re / subprocess / sys`）。
经 AST 扫描与单测双重验证，**不需要 `pip install` 任何包**，因此：

- 内网**无需访问 PyPI / 无需联网**装依赖；
- 同事只需本机有 Python ≥3.10（Win 用 `py`，Mac/Linux 用 `python3`）即可。

> 唯一的"依赖"是你自己的 AI 编程 Agent（Claude Code 或 opencode）——LLM 阶段由它执行。
> 若未来接入可选的 tree-sitter 调用链后端以提精度，届时再新增 `requirements.txt`
>（当前未接入，故无此需求）。

## Usage

```
/mgh-sast --repo <path>                                 # full-repo scan
/mgh-sast --repo . --diff origin/main                   # incremental (git diff) + call chain
/mgh-sast --repo . --path src/payment                   # directory scope + call chain
/mgh-sast --repo . --package com.bank.payment           # package scope + call chain
/mgh-sast --repo-file repos.csv --group-by-app          # batch, one report per app
/mgh-sast --repo . --estimate                           # scope/cost preview (no LLM spend)
```

### Flags

| Flag | Effect |
|---|---|
| `--repo <path>` | Single local target (mutex with `--repo-file`). |
| `--repo-file <f>` | Batch: `.csv` (`AppId,RepoName[,Path]`) or `.txt`. |
| `--workspace <dir>` | Where batch repos are cloned (default `./batch-workspace`). |
| `--group-by-app` | Batch: one scan per AppId (one report per application). |
| `--keep-clones` | Keep cloned repos after scanning (batch). |
| `--diff <ref>` | Incremental: seed = changed files vs `ref`, expanded by call chain. |
| `--path <dir>` | Scope: seed = files under `dir`, expanded by call chain. |
| `--package <pkg>` | Scope: seed = files of `pkg`, expanded by call chain. |
| `--config <profile>` | `default` / `cli` / `full`. |
| `--application-id <id>` | Asset id → SARIF `run.properties.applicationId`. |
| `--stop-after <stage>` | Stop after `s1`…`s9` (debug/cost). |
| `--budget <usd>` | Per-stage budget cap. |
| `--scope-depth <N>` | Call-chain expansion depth (default 2). |
| `--scope-direction` | `callers` / `callees` / `both` (default `both`). |
| `--models role=id` | Override one role's model. |
| `--resume` | Reuse checkpoints. |
| `--estimate` | Scope/cost preview, no LLM spend. |

## Honest limitations

- **Findings are LLM-generated triage candidates, not confirmed vulnerabilities.**
  Human review is required. Runs are non-deterministic.
- **Call graph is textual/AST-level.** It misses dynamic dispatch, reflection,
  DI, and **framework routing** (Spring `@RequestMapping`, Feign clients, AOP
  aspects, `@Autowired`/constructor injection, JPA/Spring Data). A framework
  allowlist conservatively includes route handlers / Feign clients / advised
  beans; unresolved calls are listed in the report for manual follow-up.
- Token-hungry. Use `--estimate` and `--stop-after`.

See `core/docs/` for configuration, pipeline, output, and prompt provenance.
