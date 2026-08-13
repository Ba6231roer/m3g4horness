# Tasks — default-mgh-format-opencode

## 1. leaf 默认值(mgh-init)

- [x] 1.1 `core/scripts/write_runconfig.py`:`ap.add_argument("--format", …)` 由 `required=True` 改 `default="opencode"`(保留 `choices=["opencode","claude"]`);更新 docstring「Exit codes」行去掉「missing --format」、`--help` 用法行示例。
- [x] 1.2 `tests/test_write_runconfig.py`:新增 `test_format_defaults_opencode`(无 `--format` → exit 0 + `cfg["format"]=="opencode"`);保留 `test_missing_required_exit2`(它测无 `--target`,与 `--format` 无关);确认历史测未依赖「省略 `--format` → exit 2」。

## 2. leaf 默认值(mgh-ut-init)

- [x] 2.1 `core/scripts/write_ut_runconfig.py`:`--format` 由 `required=True` 改 `default="opencode"`;docstring 同步。
- [x] 2.2 ut-init runconfig 回归测加 `--format` 默认 opencode 断言(等价 init 的 1.2)。新增 `tests/test_write_ut_runconfig.py`(此前无 ut runconfig 专用测)。

## 3. shell 措辞(mgh-init 双壳)

- [x] 3.1 `releases/claude-code/commands/mgh-init.md`:参数表行 `--format opencode|claude — **required** (mutex). Missing → error + STOP.` → `(default opencode; pass claude for .claude/rules/*.md)`。
- [x] 3.2 同文件 `description:` 字段删 `--format claude|opencode required` 里的「required」。
- [x] 3.3 `releases/opencode/command/mgh-init.md`:3.1 + 3.2 镜像(opencode 壳)。

## 4. shell 措辞(mgh-ut-init 双壳)

- [x] 4.1 `releases/claude-code/commands/mgh-ut-init.md`:参数表 `--format … — **required** …` → 默认 opencode 措辞;`description:` 删 required。
- [x] 4.2 `releases/opencode/command/mgh-ut-init.md`:镜像 4.1。

## 5. bootstrap 调用行

- [x] 5.1 `core/prompts/fragments/init-stage/bootstrap.md`:`write_runconfig.py … --format <fmt>` 调用行改述为「默认不带 `--format`(= opencode);用户传 `--format claude` 时透传」。
- [x] 5.2 ut-init bootstrap fragment(定位 ut-init 的 fresh-run bootstrap):同 5.1。ut-init 无独立 fragment 文件,bootstrap step-0 内联于双壳 `mgh-ut-init.md`(claude/opencode),两处 `write_ut_runconfig.py … --format <fmt>` 调用行已改。

## 6. 校验 + 文档

- [x] 6.1 跑 `py tools/check_contracts.py` → 仍 `✓ … all declared in --help`(`--format` 仍在 `--help`/壳正文,默认值不破 R5.1)。实测 `✓ 254 flag(s) across 10 shell(s)`。
- [x] 6.2 跑 `py tests/test_write_runconfig.py` + ut-init runconfig 测 + `py tests/test_deterministic.py`(零回归)。另跑 `test_resume_ut_init_state`/`test_init_ack_contract`/`test_ut_init_ack_contract`/`test_distributed_md_purity`/`test_init_discover`/`test_mgh_init_codegraph_parity` 全绿。
- [x] 6.3 `bump` 版本号:任何受影响 `.md`/脚本的 version 字段(承 R5.8)。`VERSION` 0.1.27 → 0.1.28(单真相源;runconfig leaf 无自有版本字段)。
- [x] 6.4 文档排查:`docs/mgh-init-工作流程详解.md`、`README.md` 若含 `--format` 必选措辞 → 同步为默认 opencode(R3 简练)。两文件 i0 行 + 参数表/prose 已同步。基线 specs(`openspec/specs/**`)由 delta `## MODIFIED` 在 archive/sync 时落地,非本次实现态文档。
- [x] 6.5 `openspec validate default-mgh-format-opencode --strict` 通过;`/opsx:apply` 前 final review。实测 `Change 'default-mgh-format-opencode' is valid`。
