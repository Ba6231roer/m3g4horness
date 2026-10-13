# fix-mgh-init-distribution-links — control-discovery delta

## MODIFIED Requirements

### Requirement: Parse arguments and guard zero-token no-op

`/mgh-init` SHALL accept `--target <dir>`(默认 `.`)、`--format opencode|claude`(默认 `opencode`;显式传
`claude` 渲染 `.claude/rules/*.md`)、`--scope <dir|package>`、`--language <lang>`、
`--rules-dir <dir>`(T3 规则产物目录;opencode 面 assemble_rules 消费)、
`--include-dotfiles`(默认关;传则回退到扫描点前缀路径,见「Skip dot-prefixed paths
during discovery」)、`--include-tests`(默认关;传则回退到扫描测试源码树,见「Skip test source directories
during discovery」)。当无 actionable 参数或传 `--help` 时,系统 MUST 仅打印参数表后**停止,不消耗
token、不做任何分析**。**参数表闭集对账消费点**:命令级参数表 SHALL NOT 列出任何无消费者
的条目——每个列出的 flag SHALL 能指出其消费点(`write_runconfig.py` / `discover_controls.py`
等的 `--help` 中存在);反 Marathon:实现侧新增消费点而三面壳漏列(如 `--rules-dir` 在
claude 面缺行)同为违例。flag 表中**对实现机制的描述句 SHALL 与实现一致**(如 call-graph
缓存语义:缓存跨 run 复用、按源 mtime/size 失效,`--rebuild-cache` 强制重建——「每 run 必
重建」类陈述与缓存机制互斥,SHALL NOT 出现);同一机制句在三面壳 SHALL 同文(非白名单方言
差异)。

#### Scenario: Omitted --format defaults to opencode

- **WHEN** 用户运行 `mgh-init --target ./svc` 未提供 `--format`
- **THEN** 系统按 `--format opencode` 继续(`<target>/AGENTS.md` 惰性索引 + `docs/security-controls/<cat>.md`),
  不报错、不停止;`run_config.json::format == "opencode"`

#### Scenario: Explicit --format claude overrides default

- **WHEN** 用户运行 `mgh-init --target ./svc --format claude`
- **THEN** rules 落 `<target>/.claude/rules/security-*.md`,`run_config.json::format == "claude"`

#### Scenario: Help / no actionable args
- **WHEN** 用户运行 `mgh-init --help` 或不带任何参数
- **THEN** 系统打印参数表后停止,零 LLM 调用、零代码扫描

#### Scenario: --include-dotfiles is a recognized flag
- **WHEN** 用户运行 `mgh-init --target . --format claude --include-dotfiles`
- **THEN** `--include-dotfiles` 被 `discover_controls.py` 接受(argparse 不报 unrecognized),
  发现阶段纳入点前缀路径;该 flag 出现在 `--help` 参数表(承 R5.1,`--help` 即契约面)

#### Scenario: --include-tests is a recognized flag

- **WHEN** 用户运行 `mgh-init --target . --format claude --include-tests`
- **THEN** `--include-tests` 被 `discover_controls.py` 接受(argparse 不报 unrecognized),发现阶段纳入测试
  源码树(回退到引入测试目录排除前的行为);该 flag 出现在 `--help` 参数表(承 R5.1)

#### Scenario: Dead command-level flags are removed from all three shells

- **WHEN** 审阅三面壳参数表中的 `--out <path>` 与 `--config <profile>`(命令级;无任何脚本
  的 `--help` 消费;run 目录由 write_runconfig 的 `--init-dir/--run-root` 承载)
- **THEN** 两旗 SHALL 从三面参数表与参数闭集移除(传则按未知 flag fail-loud 打参数表);
  对账断言「flag 表条目 ∈ 消费脚本 `--help` 并集」入契约 lint,防再生成

#### Scenario: --rules-dir row present on every face

- **WHEN** 审阅 claude 面 mgh-init 壳的参数表(opencode/dsh 面已有该行)
- **THEN** `--rules-dir <dir>`(T3 规则产物目录)行存在,三面同文

#### Scenario: Call-graph cache sentence states the real mechanism identically on all faces

- **WHEN** 审阅三面壳中 call-graph 缓存的描述句
- **THEN** 三面同文且与实现一致:缓存跨 run 复用、按源文件 mtime/size 失效、
  `--rebuild-cache` 强制重建;NEVER 出现「每次 run 必重建」与「mtime 跳过」并存的互斥陈述

## ADDED Requirements

### Requirement: Run directory is git-isolated by deterministic co-write

`write_runconfig.py`(step 0 原子写 run 配置)SHALL 以**确定性副作用** co-write
`<run-root>/.gitignore`(body 单行 `*`;幂等——已存在则不重写、不追加),使 run 目录下的
checkpoints / inputs / 进度产物在目标项目 git 中整体忽略。理由〔三面壳与契约多处承诺「随
`.mgh-init/` gitignore」但全仓无任何写入方——银行环境把敏感扫描产物误提交进客户仓是真实
风险;兑现承诺的单一确定性点位 = step 0 脚本副作用,与哨兵 co-write 同形(脚本一跑该文件
必在),NEVER 交给编排器 printf 或人工〕。该文件是运行时产物,SHALL NOT 出现在分发自检的
纯净面约束内;`--check` 校验(承边界校验纪律)SHALL 报告其存在性缺失(warn 级,不阻断——
gitignore 缺失不破坏 run 的正确性,只影响隔离承诺)。

#### Scenario: Fresh bootstrap lands the gitignore

- **WHEN** 编排器对新目标执行 step 0(`write_runconfig.py` 首次落盘 `<target>/.mgh-init/run_config.json`)
- **THEN** `<target>/.mgh-init/.gitignore` 同步出现(内容 `*`);目标项目 `git status` 不再
  列出 run 目录下的 checkpoints/inputs 产物

#### Scenario: Idempotent re-run does not duplicate or clobber

- **WHEN** 同一 run 目录再次执行 step 0(--resume 或重跑)
- **THEN** 已存在的 `.gitignore` 保持原样(不重写、不追加、不报错)

#### Scenario: Existing target .gitignore rules are untouched

- **WHEN** 目标项目根已有 `.gitignore`
- **THEN** co-write 只落在 run 目录内部,目标根的 ignore 规则零改动
