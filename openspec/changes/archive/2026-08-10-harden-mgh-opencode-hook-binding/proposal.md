## Why

D7:`py -c` 内省 one-liner 在 `/mgh-init --resume` opencode 运行域内由 LLM 自发执行、**未被
`block_adhoc_scripts` 拦截** → 25 个 T1 checkpoint 一次性归零。这正是 R5.2/R5.7 确定性闭环的核心目的,
在 opencode 上失效。

**根因(opencode 1.18.3 实测确认,非推测)**:shim `runGuard` 的 `Bun.spawn({stdin: <string>})` 在 opencode
自带 Bun 上**抛 TypeError**(`stdio must be 'inherit'|'pipe'|'ignore'|Bun.file|number|null`——**拒收字符串
stdin**)→ catch 块 fail-soft-pass(返回 code 0)→ `code === 2` 永不成立 → 守卫在 opencode 上**从未阻断**。
经 in-opencode probe 否决了其余候选:插件自动加载 ✓、`tool.execute.before` 触发 ✓、cwd=项目根 ✓、哨兵在 ✓、
guard 在场 ✓、tool-id `"bash"` + `output.args.command` ✓(与官方文档一致)。Python 守卫(单一决策源)无责——
激活与检测独立可用。

## What Changes

- **fix(已落地、已验证)**:shim `runGuard` 把 `stdin: stdin`(JSON 字符串)改为 `stdin: new Blob([stdin])`
  (opencode 自带 Bun 受收 Blob、拒收裸字符串)+ 承重注释。一行根因修复。
- **回归守卫**:`tests/test_opencode_hook_parity.py` 加源码形态断言(`new Blob([stdin])` 在场)——CI 跑不了 Bun,
  用源码形态锁防回退;运行 delivery 由手工 opencode 复测覆盖(已验证 `py -c` 内省被拦)。
- **VERSION** 0.1.22 → 0.1.23(承 R5.8)。
- **out-of-scope(deferred)**:`MGH_HOOK_DEBUG` 可观测性 + 安装期插件自检——会让本类 fail-soft 静默吞错更快暴露;
  另立变更或后续。**不在本变更**(避免把未实现项写进主 spec)。

## Capabilities

### New Capabilities
(无)

### Modified Capabilities
- `runtime-hook-enforcement`:opencode shim SHALL 以 Bun 兼容形式(`new Blob([payload])`)喂守卫 stdin,
  **NEVER** 裸传字符串(在 opencode 自带 Bun 上抛 TypeError → fail-soft-pass → 守卫静默失效)。

## Impact

| 面 | 文件 | 变化 |
|---|---|---|
| opencode shim | `releases/opencode/plugins/block_adhoc_scripts.ts` | `runGuard` `stdin: stdin`→`stdin: new Blob([stdin])` + 承重注释 |
| 回归测 | `tests/test_opencode_hook_parity.py` | 源码形态回归断言 `test_shim_feeds_stdin_via_blob_not_string`(21/21 绿) |
| 版本 | `VERSION` | 0.1.23(承 R5.8) |

不引入 pip 依赖(承 R2);守卫 `.py`(单一决策源 + 双端字节一致 invariant)不动;不改哨兵 schema。
