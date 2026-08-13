## Why

`/mgh-init` 与 `/mgh-ut-init` 当前**强制** `--format opencode|claude`——缺失即报错 STOP。opencode 是两者
**与上游/host 无关的默认目标结构**(懒性 `AGENTS.md` 索引 + 详述文件),claude 是显式 opt-in。绝大多数 fresh-run
都落在 opencode 形态上,却每次都要手敲 `--format opencode`;这是一个低价值的强制 flag,既不区分用户意图、也
不防误用(没有「第三个非法值」风险,choices 已锁两值)。把它降为默认 = 减少一类用户摩擦,零行为风险。

## What Changes

- `/mgh-init` 的 `--format` 由**必选**改为**可选,默认 `opencode`**;`--format claude` 仍可显式 opt-in。
- `/mgh-ut-init` 同步:`--format` 默认 `opencode`,显式 `--format claude` opt-in(孪生命令对称)。
- 三处 enforcement 点同步松绑(claude + opencode 双壳):
  - shell 参数表措辞 `--format opencode|claude — required (mutex). Missing → error + STOP.` → 改述为默认 `opencode`、可 opt-in `claude`;
  - leaf `write_runconfig.py` / `write_ut_runconfig.py` 的 `--format` 由 `required=True` 改 `default="opencode"`(仍 `choices=["opencode","claude"]`);
  - bootstrap fragment 调用行 `--format <fmt>` → 默认 `--format opencode`(显式传 `claude` 时透传)。
- **resume 路径本就无状态**(已满足「包括 resume」):`--format` 在 step 0 写入 `run_config.json`,`resume_state.py:232` / `resume_ut_init_state.py:146` 已 `cfg.get("format") or "opencode"` 兜底——`--resume` 从不重读 `--format`。本 change 不动 resume 语义,仅收紧 fresh-run 默认。
- **非破坏**:缺失 `--format` 从「STOP」变为「按 opencode 继续」。`--format claude` 行为零变化。退出码、产物 schema、目录布局均不变。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `control-discovery`: `--format` 由必选改为默认 `opencode`;「Missing required --format」scenario 改述为「omit → default opencode」。
- `test-convention-discovery`: 同上(ut-init 的 `--format` 默认 `opencode`)。

## Impact

- **Affected code**:
  - leaf `core/scripts/write_runconfig.py`(`--format required=True → default="opencode"`)、`core/scripts/write_ut_runconfig.py`(同)。
  - 双壳 × 2 命令 = 4 个 md:`releases/{claude-code/commands,opencode/command}/mgh-init.md` + `releases/{claude-code/commands,opencode/command}/mgh-ut-init.md`(参数表措辞 + description 里「required」字样)。
  - bootstrap fragment `core/prompts/fragments/init-stage/bootstrap.md` + ut-init 对应 bootstrap fragment 的 `--format <fmt>` 调用行。
  - 回归测:`tests/test_write_runconfig.py::test_missing_required_exit2`(断言改成「omitted → 默认 opencode」)、ut-init runconfig 测的等价断言。
- **CLI 契约(R5.1)**:`--format` 仍是两 leaf 的声明 flag(`--help` 仍列),`tools/check_contracts.py` 的 `WRITE_RUNCONFIG_REQUIRED_FLAGS` / `WRITE_UT_RUNCONFIG_REQUIRED_FLAGS` 与 shell required-flag 断言**不受影响**——断言的是「flag 存在于 `--help` / 壳正文」,不是「argparse required=True」。需 review 确认无 lint 依赖「required」语义。
- **无**第三方依赖(R2)、**无**数据迁移(`run_config.json::format` 字段不变)、**无**运行时 hook 变更(域/哨兵不动)。
- **文档**:`docs/mgh-init-工作流程详解.md` 与 `README.md` 若含 `--format` 必选措辞需同步。
