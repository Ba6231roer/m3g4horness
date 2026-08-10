## Why

`mgh-init`(claude + opencode 两壳)各内联 ~7KB 近乎逐字相同的**编排纪律正文**(orchestrator = 宿主
agent、三条 `NEVER` 硬边界、fan-out 刚性三元组、resume recipe、`.failed` 终态、长跑 Bash 超时纪律)。
这部分正文是**宿主无关的通用纪律**,但当前 (a) 在两壳间重复、(b) 没有任何 spec 把它捕获为规约、
(c) 即将到来的 `mgh-ut-init` / `mgh-ut`(见 `task.260805.md` P1/P2)若照搬会再复制两份 → 纪律正文 drift。

同时 `resume_state.py` / `write_runconfig.py` 把运行目录名**硬编码**为 `.mgh-init`,ut 族需要
`.mgh-ut-init` / `.mgh-ut`。本变更(P0,`task.260805.md` 第六节)**行为保持**地抽出共享基座,为
P1/P2 铺路,本身不交付任何新用户特性。

## What Changes

- **新增共享 fragment** `core/prompts/fragments/orchestrator-discipline.md`:把 mgh-init 两壳里
  **宿主无关**的编排纪律正文(三条 `NEVER` 硬边界 / fan-out 刚性三元组 / implementation-intention
  recipe / resume-from-disk recipe / `.failed` 终态 / 长跑 Bash per-call `timeout` 纪律)抽出为单一来源。
- **两壳改引用**:`mgh-init.md`(claude + opencode)删除内联纪律正文,改用 R5.6 认可的
  `REQUIRED SUB-SKILL: Use orchestrator-discipline` 标记引用上述 fragment;init 专属内容
  (stage 流 / 具体 `list_*` 脚本 / 产物清单 / 边界披露)留在壳内不动。
- **`--run-root` 参数**:`resume_state.py` + `write_runconfig.py` 新增 `--run-root <name>`
  (默认 `.mgh-init`),解耦运行目录名与脚本;取值优先级 `--init-dir`(全路径)> `--run-root`
  → `<target>/<name>` > 默认 `<target>/.mgh-init`。默认值 = 既有行为字节级一致。
- **版本号 bump** + 既有回归测全绿 + 契约 lint / 分发纯净 lint / 零依赖 AST 扫描覆盖新 fragment。
- **明确非目标**:`resume_state.py` 的 tier 逻辑(discover/scout/t1–t4、产物名)仍 init 专属,
  `--run-root` 仅泛化目录名;ut 族 resume 脚本是 copy 还是 generalize 留给 P1 决策 C3-lite。sast
  命令**不在本变更范围**(其纪律已由 `sast-orchestration-discipline` spec 治理)。

## Capabilities

### New Capabilities

- `orchestration-substrate`: 宿主无关的共享编排纪律基座——抽取出的 fragment 内容契约(三条 `NEVER`
  硬边界、fan-out 刚性三元组、resume recipe、`.failed` 终态、长跑 Bash 超时纪律)+ 壳经
  `REQUIRED SUB-SKILL` 引用它的规约 + `resume_state.py`/`write_runconfig.py` 的 `--run-root` 参数契约。
  mgh-init 是首个消费方;P1/P2 的 ut 族将同引此 fragment。

### Modified Capabilities

(无。本变更是行为保持的抽取 + 参数化,不改任何既有 spec 的 requirement 语义。`sast-orchestration-discipline`
不受影响——其 requirement 是 sast 专属脚本的规约,本变更不触 sast。)

## Impact

- **代码**:`core/scripts/resume_state.py`、`core/scripts/write_runconfig.py`(各加 `--run-root` flag +
  优先级解析,~10 行/脚本)。
- **提示词/壳**:新增 `core/prompts/fragments/orchestrator-discipline.md`;改 `releases/claude-code/
  commands/mgh-init.md` + `releases/opencode/command/mgh-init.md`(删内联纪律正文、加 `REQUIRED SUB-SKILL`
  引用、stage 流不动)。
- **测试/工具**:`tests/test_resume_state.py`、`tests/test_write_runconfig.py` 扩 `--run-root` 用例
  (默认 = 旧行为、`--run-root` 命名目录、`--init-dir` 仍优先);`tools/check_contracts.py` 自然覆盖
  新 flag(`--help` 即契约);`tools/check_distributed_purity.py` 扫描集已含 `core/prompts/fragments/`,
  新 fragment 需纯净(无 R5.x/FDn/Dn/变更夹名等 dev-meta)。
- **依赖**:零(承 R2,纯标准库改动)。
- **分发**:`install.sh` 镜像 `core/` → `.claude/mgh-core/` 自动带上新 fragment;版本号 bump 触发
  install 自检(fail-soft)+ CI 必 fail(承 R5.8)。
- **行为保持验收**:既有全部回归测绿;mgh-init 流水线产物 / 退出码 / 产物路径字节级一致。
