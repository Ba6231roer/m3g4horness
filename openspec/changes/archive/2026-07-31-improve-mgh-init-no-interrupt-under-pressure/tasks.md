# Tasks — improve-mgh-init-no-interrupt-under-pressure

> 仅提示词措辞变更(orchestrator 对话行为,非 hook、非脚本)。依赖顺序:双壳指令(逐字镜像)→
> 边界澄清(pre-run advisory 保留)→ 稳定性守卫 + 收尾。遵守 AGENTS.md R1–R5(R3 简练、R5.1 不动 CLI flag、
> R5.6 token 预算、R5.7 双壳 parity、R5.8 回归 + bump 版本号、R5.10 分发纯净)。设计决策见 `design.md`
> (D1–D5 + Q1–Q2);规格见 `specs/control-discovery/spec.md`。
>
> **范围铁律**:本任务**只动两份 `mgh-init.md` 命令壳**——**不动**任何 `core/scripts/*.py`、
> **不动** `core/contracts/**`、**不动** runtime hook / `core/prompts/stages/**` / `agents/**`。
> 披露所消费的字段(`init_manifest.json::boundaries[]` / `report.md` / `resume_state.py` `notes[]` /
> `list_*` stdout)均已存在,NEVER 新增 flag 或 schema。

## 1. 编排器双壳 run-to-completion 指令(`releases/{claude-code/commands,opencode/command}/mgh-init.md`,逐字镜像)

- [x] 1.1 claude-code `mgh-init.md`:在 fan-out / Re-entrancy & compaction 区加一条**规范性短行**
      (RFC-2119):fan-out 波次(scout reader / T1 induct / T3 rulewriter)进行中,编排器 **MUST NOT**
      因规模大停下征求用户「拆分/跳过/终止」、**SHALL** 迭代 `list_*` stdout `pending[]` 以 `max_concurrent`
      跑到 `pending` 为空;规模与边界(大 fan-out 计数 / 部分覆盖 / `.failed`/跳过 / 残留盲区)**SHALL** 流入
      既有披露渠道(`init_manifest.json::boundaries[]` + `report.md` + `resume_state.py` `notes[]`),
      **NEVER** 作为运行中阻塞式提问;披露计数取自磁盘 `resume_state.py`/`list_*` stdout(NEVER 对话记忆)。
- [x] 1.2 opencode `mgh-init.md`:**逐字镜像** 1.1(同段同措辞,R5.7 双端 parity)。

## 2. 边界澄清(pre-run advisory 保留——D2)

- [x] 2.1 核实 i0 pre-run `--large-repo-threshold` → 建议 `--scope`+`--merge` 措辞**语义不变**(它在花 token
      之前触发,属合法 R5.4 前置建议);若两壳该处尚未显式区分「pre-token 建议 vs 运行中不打断」,补半句
      把两个时刻的区别点明(不改 advisory 行为,只澄清边界)。

## 3. 稳定性守卫 + 收尾(R5)

- [x] 3.1 `py tools/check_contracts.py` 通过(本变更**不动 CLI flag**,双壳 MD `--flag` ↔ `--help` 镜像不退化)。
- [x] 3.2 `py tools/check_distributed_purity.py` 通过(壳内新增措辞为操作性内容,NEVER 携带研发铁律编号 /
      FDn / Dn / openspec 变更夹名 / 内部 issue 文件指针等 dev-only 溯源——承 R5.10)。
- [x] 3.3 bump `VERSION`(当前 0.1.15 → 0.1.16,或承接 `improve-mgh-init-partial-fanout-tolerance` 之后的
      下一 patch 号;与并行/相邻变更协调避免冲突)+ `install.sh` 自检 fail-soft 通过(R5.8)。
- [x] 3.4 `openspec validate improve-mgh-init-no-interrupt-under-pressure` 绿;手核两壳新增行逐字一致、
      规范性动词(`MUST NOT`/`SHALL`)在位、无长代码块(R3)。
