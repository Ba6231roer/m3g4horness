## ADDED Requirements

### Requirement: Skip dot-prefixed paths during discovery

确定性文件遍历(`expand_scope.walk_sources` / `collect_dir` / `build_call_graph`)SHALL 在既有
`EXCLUDE_DIR` 精确匹配之外,**额外跳过**任何「相对 repo 的路径中存在以 `.` 开头的分量」的文件
(即点前缀目录与点前缀文件,如 `.opencode/`、`.claude/`、`.codegraph/`、`.github/`、`.husky/`、
`.env`)。该跳过 SHALL 作为文件枚举层的属性,统一作用于 regex 候选、`skeleton.json`、调用图与
scout 目标集(单一 chokepoint,承「Bounded single-pass scan」与「Extract lossless source skeleton」
的单遍复用语义),使全部下游阶段一致地不见点前缀路径,而非仅 regex 一路。

`discover_controls.py` SHALL 提供 `--include-dotfiles` flag(默认关);传该 flag 时 SHALL 回退到
引入本要求前的行为(纳入点前缀路径)。理由:点前缀条目按 Unix 惯例为非一方业务代码(tooling /
VCS / IDE / build / config / 索引);默认扫描它们会把工具自身脚本(如运行时纪律守卫
`block_adhoc_scripts.py`)诱导成伪业务控制,污染 inventory 与生成的 rules 并浪费 LLM 预算。
既有 `EXCLUDE_DIR` 集合**保持不变**(通用点规则吸收其点成员,非点构建/缓存目录如 `node_modules`/
`target`/`build`/`vendor` 仍由其精确匹配负责)。本要求仅用 Python 标准库(`pathlib.Parts` /
`str.startswith`),承 R2 零运行时依赖。

#### Scenario: Installed tooling under a dot-prefixed dir is not discovered by default
- **WHEN** 目标项目根下 `.opencode/plugins/` 与 `.claude/hooks/` 各含一个匹配控制特征(如鉴权/校验
  关键字)的 `.py`/`.ts` 源文件,且未传 `--include-dotfiles`
- **THEN** 这些文件不出现在 `controls_candidates.json`、`skeleton.json`、调用图、scout 目标集中;
  它们诱导出的工具脚本(如 `block_adhoc_scripts.py`)**不**作为安全控制进入 inventory / 生成的 rules

#### Scenario: --include-dotfiles re-includes dot-prefixed paths
- **WHEN** 运行 `discover_controls.py --repo . --out .mgh-init --include-dotfiles`,且 `.opencode/` 下
  含一个匹配控制特征的源文件
- **THEN** 该文件被纳入候选/skeleton/调用图(行为等价于引入本要求前),不被点前缀规则跳过

#### Scenario: Dot-prefix skip is consistent across all downstream stages
- **WHEN** 默认运行 `discover_controls.py`,且 `.codegraph/` 与 `.claude/` 下各有一个源文件
- **THEN** `skeleton.json`、调用图(`build_call_graph` 产出)、`plan_scout.py` 的 scout 目标集三者
  **均不含**这些点前缀路径(单一 chokepoint,非仅 regex 候选一路排除)

#### Scenario: Non-dot build/cache dirs remain excluded (regression guard)
- **WHEN** 默认运行发现,且 `node_modules/`、`target/`、`build/` 下各有一个源文件
- **THEN** 这些文件仍被既有 `EXCLUDE_DIR` 精确匹配跳过(通用点规则不弱化既有构建目录剪枝)

#### Scenario: Windows drive root is not mis-excluded
- **WHEN** 在 Windows 上对 `C:\DEV\<repo>` 运行发现
- **THEN** 盘符根分量(`C:\`)不以 `.` 开头,不触发点前缀跳过;repo 下正常源文件照常被发现

## MODIFIED Requirements

### Requirement: Parse arguments and guard zero-token no-op

`/mgh-init` SHALL accept `--target <dir>`(默认 `.`)、`--format opencode|claude`
(**必选**)、`--out <path>`、`--scope <dir|package>`、`--language <lang>`、
`--config <profile>`、`--include-dotfiles`(默认关;传则回退到扫描点前缀路径,见「Skip
dot-prefixed paths during discovery」)。当无 actionable 参数或传 `--help` 时,系统 MUST 仅打印参数表
与指向 `task.260630.md` 的说明后**停止,不消耗 token、不做任何分析**。

#### Scenario: Missing required --format
- **WHEN** 用户运行 `mgh-init --target ./svc` 未提供 `--format`
- **THEN** 系统打印「`--format` 必选」错误 + 参数表并停止,不扫描代码

#### Scenario: Help / no actionable args
- **WHEN** 用户运行 `mgh-init --help` 或不带任何参数
- **THEN** 系统打印参数表后停止,零 LLM 调用、零代码扫描

#### Scenario: --include-dotfiles is a recognized flag
- **WHEN** 用户运行 `mgh-init --target . --format claude --include-dotfiles`
- **THEN** `--include-dotfiles` 被 `discover_controls.py` 接受(argparse 不报 unrecognized),
  发现阶段纳入点前缀路径;该 flag 出现在 `--help` 参数表(承 R5.1,`--help` 即契约面)

### Requirement: Disclose honesty boundaries in artifacts

`report.md` 与 `init_manifest.json` MUST 明示四条边界:(1) 控制为「**存在**」非「**有效**」
(引用 CVE-2025-41248:参数化类型上 `@PreAuthorize` 可绕过);(2) 调用图为文本/AST 级,
漏 AOP/反射/DI/框架路由,未解析项见 `unresolved[]`;(3) 归纳结果为 LLM 候选,**需人工复核**;
(4) **点前缀路径(tooling/VCS/IDE/build/config/索引,如 `.opencode`/`.claude`/`.codegraph`/
`.github`)默认不扫描**——若目标项目的安全控制定义点落在 `.xxx` 内,默认不会被发现,须传
`--include-dotfiles` 才纳入。

#### Scenario: Manifest carries all four disclaimers
- **WHEN** 一次运行完成
- **THEN** `init_manifest.json` 含上述四条边界声明的可识别字段

#### Scenario: Dot-prefix skip boundary is disclosed
- **WHEN** 审阅默认运行产出的 `report.md` / `init_manifest.json::boundaries[]`
- **THEN** 其中明示「点前缀路径默认不扫描,控制定义点在 `.xxx` 内须传 `--include-dotfiles`」,
  并指向该 flag
