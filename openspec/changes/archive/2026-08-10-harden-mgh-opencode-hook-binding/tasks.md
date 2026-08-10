# harden-mgh-opencode-hook-binding — Tasks

> 根因经 opencode 1.18.3 in-opencode probe 实测确认:shim `Bun.spawn({stdin: <string>})` 抛 TypeError →
> fail-soft-pass → 守卫从未阻断。fix 已落地、已验证。以下为最终确定的修复点(完成项标 [x];未做的显式列为
> out-of-scope,NEVER 伪翻 done)。

## 1. 根因取证(opencode 1.18.3 in-opencode probe)

- [x] 1.1 probe v1(module-load / 函数注册 / `tool.execute.before` 三 marker 全出):确认插件自动加载 +
      hook 触发 → 否决「插件未加载」「加载期抛错」「tool-id」「cwd」。
- [x] 1.2 probe v2(复用 shim `Bun.spawn` + 记 cwd/guard_exists/sentinel/exit/stderr):`spawn=THREW
      TypeError: stdio must be 'inherit'|'pipe'|'ignore'|Bun.file|number|null` → **根因坐实**;`plugin_cwd=项目根`/
      `guard_exists=true`/`sentinel_at_cwd=true` → 否决 cwd/guard 安装/哨兵。
- [x] 1.3 probe v3(测 fix 候选):`stdin: "pipe"`+write 与 `stdin: new Blob([payload])` **均 code=2**(全 recipe
      命中)→ fix delivery 验证,采 Blob。

## 2. fix(已落地)

- [x] 2.1 `releases/opencode/plugins/block_adhoc_scripts.ts::runGuard`:`stdin: stdin` → `stdin: new Blob([stdin])`
      + 承重注释(根因 + probe 复现说明)。
- [x] 2.2 `tests/test_opencode_hook_parity.py`:加源码形态回归断言 `test_shim_feeds_stdin_via_blob_not_string`
      (`new Blob([stdin])` 在场);CI 跑不了 Bun,源码形态锁防回退。全量 parity 21/21 绿。
- [x] 2.3 `VERSION` 0.1.22 → 0.1.23(承 R5.8)。

## 3. 验证(真实 opencode shim)

- [x] 3.1 重新部署 fix 到目标项目 → 写哨兵 → 重启 opencode → 跑 `py -c "import json; json.load(open('x.json'))"`
      → **被拦**(exit 2 + `blocked: ad-hoc 'py -c' introspection in mgh-init run-domain` recipe)✓。

## 4. out-of-scope(deferred —— 不在本变更,避免把未实现项写进主 spec)

- `MGH_HOOK_DEBUG` 可观测性(shim fail-soft 路径打日志)+ 安装期插件自检——会让本类 fail-soft 静默吞错更快暴露。
  另立变更或后续。见 `design.md` Resolution + 记忆 `opencode-plugin-runtime-gotchas`。
