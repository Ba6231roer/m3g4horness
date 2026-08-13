## Context

`/mgh-init` 与 `/mgh-ut-init` 是孪生命令,共享同一 `--format opencode|claude` **必选** flag 的三处 enforcement:

| 层 | init | ut-init |
| --- | --- | --- |
| shell 参数表 | `mgh-init.md`(claude + opencode 双壳)`--format … — required (mutex). Missing → error + STOP.` | `mgh-ut-init.md`(双壳)同 |
| leaf argparse | `write_runconfig.py` `--format required=True, choices=["opencode","claude"]` | `write_ut_runconfig.py` 同 |
| bootstrap 调用行 | `init-stage/bootstrap.md` `write_runconfig.py … --format <fmt>` | ut-init bootstrap fragment 同 |

**Resume 路径已无状态**:`--format` 在 step 0 原子写入 `run_config.json`(`write_runconfig.py`),`resume_state.py:232`
与 `resume_ut_init_state.py:146` 已 `fmt = cfg.get("format") or "opencode"` 兜底。`--resume` 从不重读 `--format`,
故「包括 resume」**已被现行实现满足**——本 change 不动 resume 语义,只把 fresh-run 默认收紧到 opencode。

**R5.1 契约 lint** (`tools/check_contracts.py`) 断言的是「flag 出现在 `--help` / 壳正文」(presence),**非** argparse
`required=True` 语义。已核:`WRITE_RUNCONFIG_REQUIRED_FLAGS` / `WRITE_UT_RUNCONFIG_REQUIRED_FLAGS` 与两壳
required-flag 断言仅查存在性,设默认值不破契约(基线 `✓ 254 flag(s) … all declared in --help`)。

## Goals / Non-Goals

**Goals:**
- `/mgh-init` 与 `/mgh-ut-init` 的 `--format` 默认 `opencode`;`--format claude` 显式 opt-in 行为零变化。
- 三处 enforcement 点 + 回归测 + 文档措辞同步。
- 保持 R5.1 契约 lint、R5.9 `--check`、resume 无状态语义、退出码、产物 schema 不变。

**Non-Goals:**
- 不改 `run_config.json::format` 字段、不改 resume 派生逻辑(resume 已无状态,无需改)。
- 不改 `assemble_rules.py` / `assemble_test_rules.py` 的 `--format`(T3/assemble 仍由编排器从 `run_config` 透传,
  非 user-facing 默认;它们的 `--format` 保持必选 = 编排器必须显式传,不引入「叶子默认」歧义)。
- 不动 runtime hook 域 / 哨兵 / 受信子树。
- 不为其它命令(sast/sra/srr)设 `--format`(它们无 `--format` 概念)。

## Decisions

### D1 — 默认值落在 leaf,不在 shell「解析层」
`write_runconfig.py` / `write_ut_runconfig.py` 的 `--format` 由 `required=True` 改 `default="opencode"`
(保留 `choices=["opencode","claude"]`)。理由:default 是**单一真相源**——bootstrap fragment 透传时省略 `--format`
即得 opencode,显式传 `claude` 透传;shell 描述「default opencode」与之镜像。避免「shell 推断默认 + leaf 又默认」
双源漂移。

### D2 — bootstrap 调用行省略 `--format`,显式 claude 时透传
`init-stage/bootstrap.md`(与 ut-init bootstrap fragment)的 `write_runconfig.py … --format <fmt>` 调用行改为
默认不带 `--format`(= opencode),仅在编排器收到用户 `--format claude` 时透传 `--format claude`。承 R5.5① recipe:
调用示例逐字镜像 leaf 契约。

### D3 — shell 参数表措辞:default + opt-in,删「required/Missing → error」
双壳 × 2 命令的参数表行 `--format opencode|claude — **required** (mutex). Missing → error + STOP.` 改述为
`--format opencode|claude` (default `opencode`; pass `claude` for `.claude/rules/*.md`)。`description:` 字段里
`--format claude|opencode required` 同步删「required」。`--out` 默认行本就按 format 分述,不动。

### D4 — 回归测:断言从「missing → exit 2」翻转为「omitted → opencode」
`tests/test_write_runconfig.py::test_missing_required_exit2` 当前用 `--format opencode`(无 `--target`)测**靶** missing;
改后 `--format` 本身可省 → 该测保持(它测的是无 `--target`,与 `--format` 无关),新增 `test_format_defaults_opencode`:
`_run("--target", t)` 不传 `--format` → exit 0 + `cfg["format"]=="opencode"`。ut-init runconfig 测加等价断言。
`test_run_root_explicit_default_byte_equivalent` 等历史测都显式传了 `--format opencode`,不受影响。

## Risks / Trade-offs

- **行为变化(可接受)**:omit `--format` 从「STOP」变「opencode 继续」。显式 `claude` 用户零影响。这是本 change 的目的,非回归。
- **文档/示例遗漏漂移**:若某处文档仍写「`--format` 必选」,agent 读之会困惑。缓解:tasks 显式列出 `docs/` + `README` 排查项;`check_distributed_purity.py` 不覆盖措辞,需人工 + 提示词护栏。
- **T3/assemble `--format` 维持必选**:编排器从 `run_config.format` 透传给 `assemble_rules.py --format <fmt>`,该叶子保持 `required`——避免「叶子默认 opencode」与「run_config 已定 claude」打架(双默认源)。本 change 边界 = 仅 user-facing runconfig 入口。
