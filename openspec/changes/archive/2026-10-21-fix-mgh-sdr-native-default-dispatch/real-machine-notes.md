# 实机笔记 — opencode 缺省原生派发(2026-10-21,本机)

本文件记录本 change 的本机闸门结果、过程中发现的宿主差异,以及企业内网 2.0.32 的交接
清单。内网执行结果回填后归档,不阻塞本机结论(沿用前例)。

## 环境

| 项 | 值 |
|---|---|
| 宿主 OS | Windows 10.0.26100(Git Bash / PowerShell shell 工具) |
| opencode | 2.1.0(`%LOCALAPPDATA%\opencode2\opencode`);PATH 默认的 `opencode` 是 1.19.3,闸门需把 2.1.0 目录前置 |
| Python | 3.13.2(`py`);`python` 是本机 Store 占位 |
| 目标仓 | 临时 git 仓:base 分支 `master`,feature 分支 `feature-native`(1 个接口文件 + 1 个独立文件),项目无 `.mgh/env-profile.json` |
| 安装面 | `./install.sh --opencode <仓>`;`.opencode/`、`.mgh-sdr/`、`.mgh/` 在 `.gitignore` 内,不进入 diff |

## 闸门结果

### 1. step 0 解析(无画像,安装树内脚本)

```
py .opencode/mgh-core/scripts/env_profile.py --target . --consumer sdr
→ form=native, source=host-default, host_face=opencode, profile raw=auto

py .opencode/mgh-core/scripts/list_sdr_steps.py --target . --step fanout
→ dispatch.form=native; fanout step = emit_native_plan.py; invocation 无子进程派发器
```

### 2. launcher 提示词(无画像,`--dry-run`)

```
py .opencode/mgh-core/scripts/mgh_sdr_launch.py --repo . --branch feature-native --host opencode --dry-run
→ [launch] dispatch form=native (source=host-default, host_face=opencode, consumer=sdr)
```

生成的 `orchestrator_prompt.md`:第 3 步只有原生动作(看门狗 → `emit_native_plan.py`
物化 + `--check` → 同消息 `sdr-review-native` 令牌派发 → 重枚举),含
`sdr-native-dispatch.md` 绝对路径;正文零子进程派发调用。`--dry-run` 不 spawn 宿主。

### 3. 真跑全链(opencode 2.1.0,无画像)

```
PATH="<opencode2 目录>:$PATH" py .opencode/mgh-core/scripts/mgh_sdr_launch.py --repo . --branch feature-native --host opencode
→ branch ok → mgh-sdr-feature-native-20261021_145442.html
```

运行产物与对账:

| 证据 | 结果 |
|---|---|
| `native_plan.json` | 在场;每轮重物化即重枚举(首轮 2 单元,波次 1,wave_size=3) |
| `watchdog/state.json` | 驻留 25 个巡检周期,sessions=4,`exit_reason` 空(宿主退出后自退) |
| 单元标记 | `markers/PayController___pay_detail.done` + `markers/src.done`,无 `.failed` |
| drafts | 2 个 JSON,全部可解析 |
| 报告/manifest/数据文件 | `dispatch.form=native`、`source=host-default`、`profile_exists=false`、证据串「native_plan.json + opencode host default (no env profile)」;counts units=2 / findings=3 / failed_units=0 |
| 子进程派发器 | 全程零调用(日志仅在脚本目录罗列时出现文件名);run 目录无 `fanout_runner.*.pid` |
| 哨兵 | 完成态由 step 5 移除(launcher 另有兜底移除) |

### 4. 显式 runner 回退对照

```
项目写 {"v":1,"dispatch_mode":"runner"} →
  list_sdr_steps: 无 dispatch 字段;fanout step = fanout_runner.py
  launcher: dispatch form=runner (source=profile);提示词含子进程调用、无原生动作
```

### 5. 宿主不支持显式 native 时 fail-closed

```
项目写 {"v":1,"dispatch_mode":"native"} + --host claude →
exit 2;stderr:「native dispatch exists only on the opencode face」+ 改用 opencode / runner 的 recipe
```

不在 spawn 前写提示词、不 spawn 宿主。

### 6. 中断恢复(磁盘态)

原生 run 物化计划后,给一个单元写 `.done`,再跑恢复查询:

```
step=fanout; dispatch.form=native / source=host-default / plan_present=true;
next_action.kind=subagent;desc 指原生重物化 + 同消息派发;done=1/2;无子进程派发提示
```

重物化把已完成单元自动剔出 pending(2 → 1),零重做。

### 7. claude / dsh 面不变

| 面 | 结果 |
|---|---|
| claude(`.claude/mgh-core/scripts`) | 无画像:`fanout` step = `fanout_runner.py`,无 `dispatch` 字段;恢复 `next_action` 含子进程调用 |
| dsh(`<target>/mgh-core/scripts`,宿主面 other) | 无画像:同上,子进程形态 |

### 8. 特殊授权可选入口(真仓)

`<仓>/.mgh/special-auth.md` 在场 → launcher 提示词恰有一句「特殊授权说明在场(<abs>):
先 Read 该说明,按其鉴权说明执行」,`mgh_credentials.py`/`cred_source.json`/凭证注入参数/
`credential_expired` 零出现;移除后提示词零特殊授权字节。install 对旧安装树副本的删除与
迁移提示由 `test_install_special_auth` 实跑覆盖。

## 过程中发现的宿主差异(已处置 / 记录)

1. **opencode v1 与 v2 的 `--log-level` 拼写不同**:launcher 原先固定 `ERROR`,2.1.0 直接
   拒绝启动(`Invalid value for flag --log-level: "ERROR"`)。已改为按 `--version` 探测:
   v2 用 `error`,v1 保留 `ERROR`。修复前 2.1.0 的 launcher 路径完全不可用。
2. **PATH 默认 `opencode` 是 1.19.3**:v1 的 `run` 不提供可轮询的宿主 service,看门狗
   两次拉起均 `root_missing` 退出;编排器按纪律扣留第一波并 fail-loud(未派发、未渲染、
   保留哨兵),进程表零残留。v2.1.0 的 `run` 走后台 service,看门狗驻留正常。
   教训:本 change 的闸门必须显式用 2.1.0 二进制。
3. **一个单元的首份 draft 带 UTF-8 BOM**(PowerShell 写入形态):渲染器把它计为 failed
   unit,编排器按「至多一轮重派」删标记重派,第二份 draft 无 BOM(首三字节 `7B 22 75`),
   最终 0 failed。与前一 change 记录的 hardening 候选同源;本 change 不扩大范围处理,
   留给后续 native 写入面加固。

## 企业内网 2.0.32 交接清单(结果回填,不阻塞归档)

1. 在目标仓执行 `install.sh --opencode <仓>`;确认 `.opencode/agent/sdr-review-native.md`
   与 `.opencode/mgh-core/prompts/fragments/sdr-native-dispatch.md` 在场。
2. 不写 `.mgh/env-profile.json`,以 `mgh_sdr_launch.py --repo <仓> --branch <分支> --host opencode`
   (或宿主会话内 `/mgh-sdr`)跑一次;预期:step 0 `form=native`、第 3 步只有
   `emit_native_plan.py` + `sdr-review-native`、磁盘有 `native_plan.json` +
   `watchdog/state.json`、报告/manifest 披露 `dispatch.form=native`,
   运行期间进程表零 `fanout_runner` 命中。
3. 写 `{"v":1,"dispatch_mode":"runner"}` 重跑一次;预期:步骤清单与 launcher 提示词回到
   子进程调用行,原生计划与看门狗不启用。
4. 记录两项宿主前提是否满足:宿主会话注入 `OPENCODE_SESSION_ID`(看门狗零参自挂)、
   宿主提供可轮询的 loopback service。任一缺失时原生形态按纪律 fail-loud(不派发),
   回退开关 = 显式 `runner` 画像。
5. 需要特殊授权的部署方:把有效说明放在 `<仓>/.mgh/special-auth.md`;流程只承诺
   「存在则先读」,不预设凭证命令。
