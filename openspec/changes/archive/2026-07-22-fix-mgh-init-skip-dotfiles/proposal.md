## Why

`/mgh-init` 默认全仓扫描目标项目,但目标项目根下常有大量**非业务代码**的点前缀目录/文件——
本工具自身安装落地的 `.opencode/`(hooks/plugins)、`.claude/`(commands/agents/hooks)、
`.codegraph/`(索引),以及 `.github/`、`.husky/`、`.idea/`、`.vscode/` 等。当前 `walk_sources`
的 `EXCLUDE_DIR` 只枚举了部分点目录(`.git/.hg/.svn/.venv/.idea/.vscode/.gradle`),**漏掉了**
`.opencode/.claude/.codegraph` 等,导致这些工具脚本被当作业务安全控制分析——实测会把本工具的
`block_adhoc_scripts.py`(运行时纪律守卫)归纳成一条「权限管控」控制,污染 inventory 与生成的
rules,同时浪费 scout/induct 的 token 预算去深读生成态工具代码。

Unix 惯例下「`.` 开头的文件/目录」= 非一方业务代码(config / tooling / VCS / build / IDE / 索引),
这给了一个低误报、无需逐一枚举的默认剪枝规则。

## What Changes

- **默认跳过任何路径分量以 `.` 开头的条目**:`expand_scope.walk_sources` / `collect_dir` /
  `build_call_graph` 在既有 `EXCLUDE_DIR` 精确匹配之外,**新增**「任一路径分量以 `.` 开头即跳过」
  的通用规则(覆盖 `.opencode/.claude/.codegraph/.github/.husky` 及未来新工具目录,无需维护清单)。
  该规则是文件枚举层的属性,`/mgh-init`(发现 + 调用图)与 `/mgh-sast`(scope 扩展,复用同引擎)
  同时受益。
- **`--include-dotfiles` 逃生口**:`discover_controls.py` 新增该 flag(默认关),`mgh-init` 双壳
  (claude/opencode)镜像透传;传该 flag 时回退到旧行为(扫描点目录)。非 BREAKING——旧行为可经
  flag 完整恢复。
- **诚实边界披露**:`report.md` / `init_manifest.json` 的 `boundaries[]` 增列「点前缀路径默认不扫描,
  若控制定义点在 `.xxx` 内须传 `--include-dotfiles`」。
- **契约 + 测试**:`core/contracts/init/` 落定跳过语义;`tests/test_init_discover.py` 增断言:
  `.opencode`/`.claude` 下含控制特征的源文件默认不被发现、`--include-dotfiles` 下重新纳入。

## Capabilities

### New Capabilities
<!-- 无新能力 -->
_(无)_

### Modified Capabilities
- `control-discovery`:
  - 「Parse arguments…」增 `--include-dotfiles` 到接受的 flag 集。
  - 「Discover security control candidates deterministically」增 MUST:扫描跳过任一以 `.` 开头的
    路径分量,`--include-dotfiles` 覆盖。
  - 「Disclose honesty boundaries in artifacts」增第 4 条边界:点前缀路径默认不扫描。

## Impact

- **代码**:`core/scripts/expand_scope.py`(`walk_sources`/`collect_dir`/`build_call_graph` 加点前缀跳过,
  共享默认,SAST scope 扩展一并受益)、`core/scripts/discover_controls.py`(加 `--include-dotfiles` 并
  穿入调用图/枚举)。
- **分发壳**:`releases/claude-code/commands/mgh-init.md` + `releases/opencode/command/mgh-init.md`
  (镜像 flag + 边界披露行;R5.1 契约 lint 自动覆盖新 flag)。
- **契约/测试**:`core/contracts/init/candidates.md`(或 skeleton.md)落定跳过语义;
  `tests/test_init_discover.py` 增点目录用例;改动 md/脚本按 R5.8 bump 版本号。
- **SAST 连带**:`/mgh-sast` 复用 `expand_scope`,默认不再扫描工具目录(更正确,非回归——无 SAST
  spec 承诺扫描 `.claude`/`.opencode`,实施时核验)。
- **零依赖**:仅标准库 `pathlib`(`p.parts`/`str.startswith`),承 R2。
