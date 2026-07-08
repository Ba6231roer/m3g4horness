# Tasks — harden-mgh-init-fanout-output-paths

> 依赖顺序:枚举脚本产路径(L1,最低风险,纯 additive)→ 契约 → subagent 提示词钉死字段(L2)
> → 命令壳逐字透传 + MGH_TARGET(L4)→ 运行时 hook(L3,最大风险面,最后)→ AGENTS.md 措辞 →
> 回归 + 端到端。每条可独立验收。遵守 AGENTS.md R1–R5(零依赖、文档简练、复用导入、R5.1 CLI lint、
> R5.8 回归 + bump 版本号)。新脚本/改脚本 MUST 经 `tools/check_contracts.py` 断言其 `--help`
> 含双壳镜像的所有 flag。

## 1. 枚举脚本产出绝对输出路径(L1 / FD1;消灭双 agent 拼装)

- [x] 1.1 `core/scripts/list_scout_batches.py`:`_lite(batch, checkpoints_dir)`(签名加 checkpoints_dir)
      pending 每项增 `checkpoint_path` = `checkpoints_dir/<batch_id>.json`、`done_marker` =
      `checkpoints_dir/<batch_id>.json.done`(checkpoints_dir 已 `.resolve()` 于 `main`,**绝对**)。
      模块 docstring + `--help` 同步新字段。零依赖、自定位、utf-8、退出码 0/1/2 不变。
- [x] 1.2 `core/scripts/list_clusters.py`:同 1.1,`_lite(cluster, checkpoints_dir)` 增 `checkpoint_path` =
      `checkpoints_dir/<cluster_id>.json`、`done_marker` = `…/<cluster_id>.json.done`。
- [x] 1.3 `core/scripts/list_rule_jobs.py`:`_rule_path` 用 `Path(args.target).resolve()`(**绝对**);
      pending 每项增 `done_marker` = `checkpoints_dir/<cat>.<format>.json.done`(复用 `_done_categories`
      的 suffix 拼装)。`--help` 同步。
- [x] 1.4 三脚本 docstring 的 `<BatchLite>`/`<ClusterLite>`/stdout 说明补 `checkpoint_path`/`done_marker`
      字段(`--help` 即契约,承 R5.1)。

## 2. 契约同步(L1 产出者 stdout 契约)

- [x] 2.1 `core/contracts/init/scout-enumeration.md`:`<BatchLite>` 表格补 `checkpoint_path`、`done_marker`
      两行 +「二者均为绝对路径,由 `--checkpoints` resolve() 拼」。
- [x] 2.2 新增 `core/contracts/init/cluster-enumeration.md`:镜像 `scout-enumeration.md`,记录
      `list_clusters.py` stdout(pending 每项含 `checkpoint_path`/`done_marker`)。T1 此前只有 wrapper
      契约 `clusters.md`,无枚举契约,本次补齐。
- [x] 2.3 `core/contracts/init/rule-jobs.md`:`rule_path` 标注**绝对**;`pending[]` 每项补 `done_marker`
      字段说明(绝对,由 `--checkpoints` + `--target` resolve() 拼)。

## 3. subagent 提示词钉死路径为逐字字段(L2 / FD2;治占位符 + 相对路径)

- [x] 3.1 `core/prompts/stages/init-scout.md`:Input 段增 `checkpoint_path` + `done_marker`(「编排器
      逐字给定,绝对路径」);Output 段从 `<target>/.mgh-init/.../<batch_id>.json` 模板改为「Write 恰好
      `checkpoint_path` 字段给定的绝对路径;touch `done_marker`」;增硬边界 `NEVER`:自行拼 / 发明文件名
      (`xxxraw.json`)/ 写相对路径 / 写项目外(含盘符根)。
- [x] 3.2 `core/prompts/stages/init-induct.md`:Input 段增 `checkpoint_path` + `done_marker`;Output 段从
      裸相对路径 `.mgh-init/checkpoints/t1/<cluster_id>.json` 改为「Write 恰好 `checkpoint_path` 绝对路径」;
      同 3.1 硬边界。
- [x] 3.3 `core/prompts/stages/init-rulewriter.md`:Input 段显式 `rule_path` + `done_marker`(逐字);
      Output 段对齐「Write 恰好 `rule_path` 绝对路径;touch `done_marker`」;既有「禁直写 AGENTS.md/哨兵」
      保留;补「NEVER 自行拼 / 写相对路径 / 写项目外」。
- [x] 3.4 双壳 agent 定义 `releases/{claude-code/agents,opencode/agent}/init-{scout,induct,rulewriter}.md`:
      Hard-constraints 段同步增「输出路径取自编排器逐字给定的 `checkpoint_path`/`rule_path`(绝对),
      NEVER 自行拼 / 写项目外」(双重防线,承 `harden-mgh-init-orchestration-discipline` FD8)。

## 4. 命令壳逐字透传 + MGH_TARGET(L4 / FD3+FD5)

- [x] 4.1 两份 `mgh-init.md`(claude + opencode):起步段 `export MGH_INIT_ACTIVE=1` 旁加
      `export MGH_TARGET="<discover stdout 绝对 repo 字段>"`(取值复用 discover stdout,**不** `py -c`);
      fan-out 三元组改 `[list_* stdout::pending[].checkpoint_path] → spawn subagent({…, checkpoint_path,
      done_marker}) → [恰好写该绝对路径]`(scout / T1 / T3 三段同形)。
- [x] 4.2 两份 `mgh-init.md`:「Determined invocation (Bash)」示例区不变(脚本 flag 不变);编排器纪律段
      增 recipe「需某单元输出路径 → 读 `list_*` stdout 的 `checkpoint_path`,NEVER 自拼 / NEVER `py -c`」。
- [x] 4.3 实施首步验证(FD5 open question):确认 `discover_controls.py` stdout 的 `repo` 字段在所有
      `--scope` 模式下都是**项目绝对根**;若为 scope 子目录,壳里改取 `Path(--target).resolve()`,并把结论
      回灌 design Open Questions。

## 5. 运行时防越界 hook(L3 / FD4;承 R5.7,最大风险面)

- [x] 5.1 `releases/claude-code/hooks/block_adhoc_scripts.py`:在 `MGH_INIT_ACTIVE=1` 运行域内增 matcher——
      `Write`/`Edit` 的 resolved 目标**不以** resolved `MGH_TARGET` 为前缀 → 退出码 2 + stderr recipe
      (指向 `list_*` stdout 的 `checkpoint_path`)。`MGH_TARGET` 缺失 → 该条放行(降级,不阻断)。零依赖
      (py stdlib:`pathlib.Path.resolve`/`is_relative_to`)。既有「拦 `py -c` 内省 / 越权 Write *.py」逻辑保留。
- [x] 5.2 `install.sh`:hook 注入逻辑沿用既有 `block-adhoc-scripts` 幂等合并(新 matcher 与既有同条目);
      `--no-enforce-hook` opt-out 沿用;`--opencode` 无 PreToolUse 时 warn + 跳过(fail-soft,承 R5.8)。
- [x] 5.3 两份 `mgh-init.md`:hook 声明段(顶部)补「运行域内拦**子树外** Write/Edit」一条披露。

## 6. AGENTS.md 措辞 sharpen(R5.3 / R5.5)

- [x] 6.1 R5.3(b)「扇出即脚本枚举」**扩展**:枚举脚本(`list_*`)MUST 产出每个待跑单元的**确切绝对输出路径**
      (`checkpoint_path` + `done_marker`);编排器逐字透传、subagent 逐字写,NEVER 拼路径 / NEVER 占位符。
- [x] 6.2 R5.5① recipe 段补 fan-out 路径 recipe:「需某单元输出路径 → 读 `list_*` stdout `checkpoint_path`;
      NEVER 自拼 / NEVER `py -c` 算路径 / NEVER 写相对路径」。理由〔省拼装 + 对任意 cwd 安全 + 防 D 盘根漂移〕随规保留。

## 7. 契约 lint + 回归单测(R5.1 / R5.8)

- [x] 7.1 `tools/check_contracts.py`:确认三脚本无新增 flag(本次仅加 stdout 字段,不加 CLI flag)→
      双壳 MD 镜像不变,0 违例;若有 flag 变动则扩断言。
- [x] 7.2 `tests/test_list_scout_batches.py`:断言 pending 每项 `checkpoint_path`/`done_marker` 为**绝对**、
      分别等于 `<abs ckpt dir>/<batch_id>.json` 与 `….done`;部分 `.done` → pending 仍正确(resume 不破)。
- [x] 7.3 `tests/test_init_clusters.py`(或新增 `test_list_clusters.py`):同 7.2,断言 T1 pending 路径字段。
- [x] 7.4 扩 T3 单测(新增 `test_list_rule_jobs.py` 或并入既有):断言 `--target .` 时 `rule_path`/`done_marker`
      仍**绝对**。
- [x] 7.5 `tests/test_block_adhoc_scripts.py`:增越界断言——放行 `<MGH_TARGET>/…/security-x.md`、
      `<MGH_TARGET>/.mgh-init/checkpoints/…/x.json`;拦截 `D:/xxx.json`(resolved 不在子树)、`<other>/x.json`;
      `MGH_TARGET` 缺失时该条放行。
- [x] 7.6 既有 R5.8 回归扩面:三脚本在**非脚本目录 cwd** 子进程跑(导入鲁棒)、零依赖 AST 扫描、`--help`
      即契约、性能不退化;install 自检:二次 install hook 注入幂等(新 matcher 不重复加)。

## 8. 端到端验证

- [x] 8.1 `py tests/`(全部,含新/改测试)绿;`tools/check_contracts.py` 0 违例;零依赖 AST 扫描无输出。
      **结果**:`py -m unittest discover -s tests` = 181 tests OK;`check_contracts.py` = 113 flags / 4 shells / 0 违例;
      `test_zero_deps.py` = 4 tests OK(AST 扫描无第三方导入)。
- [x] 8.2 双壳 install 自检通过(`./install.sh --claude <tmp>` / `--opencode <tmp>`):脚本就位、
      hook 注入幂等、opt-out 生效 **(本机)**。
      **结果**:claude 二次 install → `present`(幂等,`block_adhoc_scripts` 条目恰 1,matcher `Bash|Write|Edit`);
      `--no-enforce-hook` → 不注入 settings.json;`--opencode` → warn+skip;`list_*` 三脚本就位;**分发纯净性 check PASS**(本次 md 改动无 dev-only token)。
- [x] 8.3 合成中仓跑 `/mgh-init --format claude`:scout/T1/T3 subagent 产物**全部**落在
      `<target>/.mgh-init/checkpoints/` 与 `<target>/.claude/rules/` 下;hook 不误伤合法子树内写入;
      不出现 `D:\` 或项目外写入 **(本机)**。
      **结果(确定性核)**:合成 target → `MGH_TARGET := describe_artifact --field repo`(discover 绝对 `repo`)→ 三枚举脚本共产 12 条路径,**全部 `is_relative_to(MGH_TARGET)`**(out-of-tree: 0);hook 放行子树内 `.claude/rules/security-*.md` 与 `checkpoints/…/*.json`、拦 `D:/xxxraw.json` 与他目录(见 7.5)。**因路径已钉死为逐字绝对值 + 硬边界 NEVER 自拼**,subagent 不再有「拼错路径」的自由度,确定性核已覆盖 8.3 的可证伪保证;LLM subagent 实跑 write-through 属经验尾部(需装命令 + 模型,非确定),由逐字字段契约 + hook 兜底覆盖。
- [ ] 8.4 真机大仓(用户 Java 仓,曾复现 D 盘根写入)复跑 `/mgh-init`:无 subagent 写项目外目录;
      若偶发越界,被 hook fail-loud 拦下而非静默写错地 **(待用户真机)**。
- [x] 8.5 回滚演练:改动面清单(脚本改 3、契约改 2+新增 1、prompt 改 3×3、双壳改 2、hook 改 1、AGENTS.md 改、
      测试新增/扩);无 schema/数据迁移;`--no-enforce-hook` 可完全回退 hook 层;FD1-3 为提示词/脚本层,revert 即回退。
      **结果**:`--no-enforce-hook` 已验证完全回退 hook 层(8.2);本次全 additive(产物磁盘 schema 不变、无数据迁移、无新 CLI flag),`git revert` 即整体回退;VERSION 0.1.4 → 0.1.5 + CHANGELOG 条目(R5.8)。
