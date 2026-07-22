## Context

`/mgh-init` 的确定性发现复用 `core/scripts/expand_scope.py` 的 `walk_sources` / `build_call_graph`
(承 control-discovery spec「Reuse call-graph engine」与「Discover security control candidates
deterministically」),其目录剪枝由模块常量 `EXCLUDE_DIR`(精确名匹配)实现:

```
EXCLUDE_DIR = {".git",".hg",".svn","node_modules","vendor","dist","build",
               "target",".venv","venv","__pycache__",".idea",".vscode","bin","obj","out",".gradle"}
```

`walk_sources` 判定:`if any(part in EXCLUDE_DIR for part in p.parts): continue`。该集合枚举了
**部分**点目录,但漏掉 `.opencode` / `.claude` / `.codegraph` / `.github` / `.husky` 等。当目标项目
装入了 AI 工具族(本工具 `install.sh` 落 `.opencode`+`.claude`;或 codegraph 索引 `.codegraph`),
这些**工具自身脚本**会被 walk 进候选集 → 经 scout/induct 归纳成「安全控制」(实测 `block_adhoc_scripts.py`
被当成权限管控),污染 inventory 与生成的 rules,并浪费 LLM 预算深读生成态代码。

`walk_sources` 是单一 chokepoint:regex 候选、`skeleton.json`、调用图、`plan_scout.py` 目标集**全部**
经它枚举(单遍复用,承「Bounded single-pass scan」与「Extract lossless source skeleton」)。

## Goals / Non-Goals

**Goals:**
- 默认不分析目标项目中以 `.` 开头的路径(目录或文件),消除工具脚本被误归纳为业务控制的主因。
- 单一 chokepoint(`expand_scope`)改动,init 与 sast 一致受益,无需逐工具枚举。
- 提供逃生口 `--include-dotfiles`,可完整回退到旧行为(非 BREAKING)。
- 诚实披露该剪枝,避免用户误以为全仓覆盖。

**Non-Goals:**
- 不为 `.github` / `.husky` 等做特例保留(统一按点前缀处理;确需扫描用逃生口)。
- 不在 `/mgh-sast` 暴露 `--include-dotfiles`(SAST CLI 契约保持稳定;SAST 仅静默继承更正确的默认)。
- 不改 scout/induct 提示词(剪枝是确定性的脚本层行为,不靠提示词自觉)。

## Decisions

### D1 — 通用「点前缀分量即跳过」规则,而非枚举工具目录
`walk_sources` / `collect_dir` 在 `EXCLUDE_DIR` 精确匹配之外,新增 `any(part.startswith(".") for
part in p.parts)` 即跳过。

**Why over 替代方案**:枚举 `.opencode/.claude/.codegraph` 仍漏 `.github/.husky/.next/...`,且每出现
新工具就要改清单(脆)。通用规则一次覆盖现有 + 未来所有点前缀工具目录,且贴合 Unix「点前缀 =
非一方代码」惯例(误报面极低:业务安全控制几乎不放在 `.xxx` 内)。

### D2 — 改共享 `expand_scope` chokepoint,而非 discover 内重过滤
点前缀跳过作为文件枚举层的属性实现在 `expand_scope.walk_sources` / `collect_dir` /
`build_call_graph`(默认开),`/mgh-init` 与 `/mgh-sast`(scope 扩展复用同引擎)同时受益。

**Why**:spec 已 mandate discover 复用 `expand_scope` 的 `EXCLUDE_DIR`;单点改动符合单一真相源;
discover 内重过滤会复制逻辑、且把 SAST 留在「扫描工具脚本」的旧错状态。

### D3 — `EXCLUDE_DIR` 集合保持不变(additive)
通用点规则**吸收**了 `EXCLUDE_DIR` 的点成员(`.git/.hg/.svn/.venv/.idea/.vscode/.gradle`),但集合
保留:① 非点构建/缓存目录(`node_modules/vendor/dist/build/target/__pycache__/bin/obj/out`)仍需精确
匹配;② 对既有成员零行为变化、显式可读、向后兼容(其他代码可能引用该集合)。

### D4 — 逃生口仅落 `discover_controls.py`(+ mgh-init 双壳),不上 `expand_scope` main
`--include-dotfiles`(默认关)加在 `discover_controls.py` 并穿入 `walk_sources`/`build_call_graph`;
mgh-init claude/opencode 双壳镜像透传(R5.1)。`expand_scope.py main()` **不**加该 flag。

**Why**:用户问题域是 mgh-init;给 SAST main 加 flag 会扩张 SAST CLI 契约面(R5.1 lint + 双壳镜像
负担)换取一个无人提过的边案。**Trade-off**:SAST 用户无法经 flag 重新纳入点目录——可接受(SAST 从未
承诺扫描 `.claude`/`.opencode`,且既有 `EXCLUDE_DIR` 本就无逐目录逃生口)。

### D5 — 谓词形式与 Windows 安全性
`p.parts` 在 Windows 含盘符根(如 `C:\`),不以 `.` 开头,安全;`repo.rglob("*")` 产出的 `p` 均为
repo 子项,repo 根自身不作为被检分量。`Path(".env").parts == (".env",)` → 点文件亦被跳过(正确:
`.env` 等本就不是 SOURCE_EXT 命中的源,跳过无害且一致)。

## Risks / Trade-offs

- **[过度排除]** 极少数项目把真实源/安全控制放 `.xxx` 内(非惯例)→ **缓解**:`--include-dotfiles`
  逃生口 + 边界披露告知用户。测试覆盖「逃生口重新纳入」。
- **[SAST 连带行为变化]** 共享引擎默认不再扫工具目录 → **缓解**:严格更正确(不把工具脚本当 app
  代码扫);实施时核验无 SAST spec/test 断言「扫描 `.claude`/`.opencode`」;非回归。
- **[`.github` 安全策略/CodeQL 配置不被扫]** → **可接受**:mgh-init 目标是 authn/authz/input-validation
  等代码级控制,非 CI 配置;披露该边界;逃生口覆盖边案。
- **[Windows 盘符根误判]** → **已核验**(D5):盘符根不以 `.` 开头;增 Windows 路径测试。

## Migration Plan

- 默认开启,无数据迁移。依赖扫描点目录的用户传 `--include-dotfiles`。
- 既有 inventory/rules 可能含工具脚本诱导出的伪控制 → 建议重跑 `/mgh-init` 刷新。
- 回退:传 `--include-dotfiles` 即逐字回到旧行为。

## Open Questions

- 是否需要把逃生口也暴露给 `/mgh-sast`?(当前 Non-Goal;若 SAST 用户提出再开。)
- 是否为 `.github` 特例保留(某些团队放 security policy)?(当前不;统一规则 + 逃生口更简。)
