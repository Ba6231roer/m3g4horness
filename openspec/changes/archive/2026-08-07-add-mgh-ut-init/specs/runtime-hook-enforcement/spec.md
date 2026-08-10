## Purpose

跨五命令(`/mgh-init`|`/mgh-sast`|`/mgh-sra`|`/mgh-srr`|`/mgh-ut-init`)共享的运行时纪律守卫契约——激活
模型(env 或磁盘哨兵)、运行域脚本只读、脚本扩展名集、写入受信子树限定。取代此前分散在各命令 spec、
措辞漂移的重复 hook 要求,作为 `block_adhoc_scripts` 守卫(双端 byte-identical)的单一真相源。本能力由
change `harden-mgh-opencode-hook-enforcement` 建立、`add-mgh-ut-init` 扩到第 5 域 `mgh-ut-init`。

## MODIFIED Requirements

### Requirement: Run-domain activation via env or disk sentinel

The `block_adhoc_scripts` guard SHALL activate inside an mgh run-domain when **EITHER** (a) env
`MGH_{INIT,SAST,SRA,SRR,UT_INIT}_ACTIVE=1` is set, **OR** (b) a disk sentinel `<run-root>/.active` exists relative to
the guard's cwd, where `<run-root>` is the domain's run directory: `mgh-init`→`.mgh-init/`, `mgh-sast`→
`security-scan/`, `mgh-sra`→`.mgh-sra/`, `mgh-srr`→`.mgh-srr/`, `mgh-ut-init`→`.mgh-ut-init/`. The sentinel SHALL be JSON
`{"domain":"mgh-<d>","target":"<abs target>","out_roots":["<abs>..."],"v":1}`, written by the orchestrator at
step 0 via `Bash` and removed at run completion / clean-stop. `MGH_TARGET` for the subtree check SHALL resolve
with precedence **env `MGH_TARGET` > sentinel.`target` > degrade** — when neither pins a target the subtree
(out-of-tree) check SHALL pass (cwd is the implicit run root for cwd-relative sentinel discovery but is **not**
used as a hard block target, to avoid over-blocking when no target was pinned); the script-extension write block
and `py -c` introspection block still fire whenever the guard is active. Outside all run-domains (neither env nor
sentinel present) the guard SHALL exit 0 silently (zero day-to-day noise). The disk-sentinel activation path
exists because the opencode `.ts` plugin process does not inherit mid-session bash-exported env; env-only
activation left the opencode guard dormant for an entire run (the prior fail-soft reliability boundary is now
closed by the sentinel, host-neutral and parity-preserving on both claude and opencode).

#### Scenario: opencode activates via sentinel when env is unset

- **WHEN** opencode 触发 `tool.execute.before`,且 `MGH_INIT_ACTIVE` env 未设、但 `<cwd>/.mgh-init/.active` 哨兵存在
- **THEN** 守卫激活(等效于 env 已设),`py -c` 内省/越权脚本写/越树写均按运行域规则 fail-loud;哨兵经磁盘对 opencode 插件进程可见,绕开 mid-session env 不继承

#### Scenario: claude activates via env (sentinel optional)

- **WHEN** claude `PreToolUse` 触发,且 `MGH_INIT_ACTIVE=1`(哨兵在或不在)
- **THEN** 守卫激活;env 仍是 claude 端的有效激活源,哨兵为兜底

#### Scenario: Non-run-domain session is silent

- **WHEN** 既无任何 `MGH_*_ACTIVE` env、各域 `<run-root>/.active` 哨兵亦不存在
- **THEN** 守卫退出码 0 放行,零日常噪声

#### Scenario: Sentinel carries target so the subtree check fires without env

- **WHEN** opencode 下 `MGH_TARGET` env 未设,但哨兵 `.active` 携 `target=<abs>`,编排器 `Write` 一个落在该 target 子树外的路径(如 `D:/raw.json`)
- **THEN** 守卫以退出码 2 拦截越树写;`MGH_TARGET` 取自哨兵,子树判定在 opencode 上可靠

#### Scenario: Active domain with no pinned target degrades the subtree check

- **WHEN** 守卫激活(env `MGH_*_ACTIVE=1` 或哨兵在),但 `MGH_TARGET` env 未设且哨兵无 `target`
- **THEN** 脚本扩展名写 / `py -c` 内省仍 fail-loud(退出码 2);越树写子树检查**降级放行**(NEVER 用 cwd 硬拦,避 over-block)

#### Scenario: Orchestrator writes sentinel at step 0 and removes on completion

- **WHEN** 审阅 `mgh-*.md` 编排流起步与完成态
- **THEN** step 0 含写 `<target>/.mgh-<domain>/.active` 的 Bash 步;run 完成 / 干净停止含移除该哨兵的步

#### Scenario: mgh-ut-init activates via env or sentinel as the fifth domain

- **WHEN** `MGH_UT_INIT_ACTIVE=1` env 已设,**或** `<cwd>/.mgh-ut-init/.active` 哨兵存在
- **THEN** 守卫在 `mgh-ut-init` 运行域激活(第 5 域,与既有 4 域同机制:`py -c` 内省/脚本扩展名写/越权子树写均 fail-loud);哨兵 `domain:"mgh-ut-init"`、run-root `.mgh-ut-init`

### Requirement: Write confinement to sanctioned locations

When active, the guard SHALL block any `Write`/`Edit` whose resolved target falls **outside** the resolved
`MGH_TARGET` tree (e.g. a drive root, `%LocalAppData%\Temp`, another project dir) — for all five run-domains.
For the `mgh-init` and `mgh-ut-init` domains, the guard SHALL **additionally** require the target to fall **inside**
a sanctioned subtree (positive allowlist): for `mgh-init` — `<target>/.mgh-init/**`,
`<target>/.claude/rules/**`, `<target>/docs/security-controls/**`, `<target>/AGENTS.md`; for `mgh-ut-init` —
`<target>/.mgh-ut-init/**`, `<target>/.claude/rules/**`, `<target>/docs/test-conventions/**`, `<target>/AGENTS.md`;
plus any absolute root the orchestrator recorded in the sentinel's `out_roots[]` (for customized `--out`/`--rules-dir`).
A write inside `MGH_TARGET` but outside the sanctioned subtrees (e.g. project-root `temp_clusters*.json`) SHALL
fail-loud (exit 2) + recipe pointing at the producer stdout `checkpoint_path`/`rule_path`. `mgh-sast`/`mgh-sra`/
`mgh-srr` retain the out-of-tree check **without** the positive allowlist (no root-pollution reported for those
domains; their output paths are already narrowed to `security-scan/`, `.mgh-sra/`, `.mgh-srr/`).

#### Scenario: Out-of-tree write is blocked in every domain

- **WHEN** 任一运行域内编排器 `Write`/`Edit` `D:/raw.json` 或 `%LocalAppData%\Temp\x.json`
- **THEN** 守卫以退出码 2 拦截,recipe 指向 producer stdout 的绝对产物路径字段

#### Scenario: init root-level pollution is blocked

- **WHEN** `mgh-init` 运行域内编排器 `Write` `<target>/temp_clusters1.json`(在 `MGH_TARGET` 内、但不在受信子树)
- **THEN** 守卫以退出码 2 拦截(既有 `_is_out_of_tree` 只挡树外、放行了树内根污染——即 temp_clusters 失守形状)

#### Scenario: init sanctioned-subtree writes pass

- **WHEN** `mgh-init` 运行域内写 `<target>/.mgh-init/inputs/t1/u.input.json`、`<target>/.claude/rules/x.md`、`<target>/docs/security-controls/auth.md`、或 `<target>/AGENTS.md`
- **THEN** 守卫放行(落入受信子树)

#### Scenario: init custom output root recorded in sentinel passes

- **WHEN** 编排器以 `--out <custom>` 启动、把解析后的绝对根写入哨兵 `out_roots[]`,运行域内 `Write` `<custom>/x.json`
- **THEN** 守卫放行(`out_roots[]` 承载自定义产物根,防 over-block)

#### Scenario: mgh-ut-init sanctioned-subtree writes pass

- **WHEN** `mgh-ut-init` 运行域内写 `<target>/.mgh-ut-init/inputs/t1/u.input.json`、`<target>/.claude/rules/test-junit5.md`、`<target>/docs/test-conventions/mockito.md`、或 `<target>/AGENTS.md`
- **THEN** 守卫放行(落入 ut-init 受信子树;ut-init 与 init 同形写 rules,共用 `.claude/rules` + `AGENTS.md`)

#### Scenario: mgh-ut-init root-level pollution is blocked

- **WHEN** `mgh-ut-init` 运行域内编排器 `Write` `<target>/temp_clusters1.json`(在 `MGH_TARGET` 内、但不在 ut-init 受信子树)
- **THEN** 守卫以退出码 2 拦截(ut-init 与 init 同形状根污染风险,同正向允许清单治理)
