<!--
  mgh-init stage-flow detail — step-by-step pipeline body (steps 0–8) for the
  /mgh-init orchestrator. Consumed via `REQUIRED SUB-SKILL: Use init-stage-flow`.
  init-specific (NOT host-agnostic — names init-only scripts/products/fan-out
  triples); BOTH shells reference the SAME single file; host variance is only the
  `.claude/mgh-core` / `.opencode/mgh-core` script-prefix resolved by the shell at
  load (never hard-coded here). Shell keeps its OWN parse-args / Stage→component
  table / Resume·cache / Output / Always disclose; this fragment holds ONLY the
  stage-flow steps. Install mirrors it to <mgh-core>/prompts/fragments/.

  Discipline (stated once, NOT echoed per step): every `--field`/`--count`/paging
  read goes through `describe_artifact.py`/`list_*`; NEVER `py -c` to introspect
  run-domain products, NEVER `Read` an aggregate JSON wholesale. Per-step reminders
  kept ONLY where they guard a concrete failure shape (scout-incomplete-gate,
  T1→T2 `--check` shape gate).
-->

## init-stage-flow

```
0. parse + self-check (host agent/model available; else STOP with fix hint;发现脚本统计源文件数,超 `--large-repo-threshold` 则建议 `--scope`+`--merge`(**花 token 前**前置建议;波次进行中不再因规模打断,见 orchestrator-discipline fragment),扫描期向 stderr 打印进度)
   · **起步**:`Bash: export MGH_INIT_ACTIVE=1`(声明运行域,激活 PreToolUse hook,含子树外 Write/Edit 拦截)
   · **run_config(无状态 resume 意图源)**:起步后、花 token 前,**原子写** `<target>/.mgh-init/run_config.json`
     (起始态意图:记决定步骤图的本次 flag;与终态 `init_manifest.json` 边界清晰、互不替代):
     `py .claude/mgh-core/scripts/write_runconfig.py --target <abs target> --format <fmt> [--no-scout] [--no-codegraph] [--skip-consistency] [--merge <dir>] [--include-dotfiles] [--include-tests] [--scope ..] [--scope-mode ..] [--max-aggregate-bytes ..] [--max-unit-bytes ..] [--orch-budget-bytes ..] [--scout-* ..]`
     该文件使 `/mgh-init --resume` **无需重输 flag**;`resume_state.py` 据它解析 optional/codepath 分支。
     `--resume` 复用既有 run_config(不覆盖);新 run(`.mgh-init/` 不存在或被清)重写。
   · **哨兵(磁盘激活信号,opencode 可靠激活兜底)**:`write_runconfig.py` stdout 的 `target` 即**绝对项目根**
     (Windows 原生、供守卫 `Path.resolve()` 判树;**NEVER** 用 bash `pwd`,其 MSYS `/c/...` 在 Windows pathlib 误解析)。
     据此写哨兵:
     `printf '%s' '{"domain":"mgh-init","target":"<write_runconfig stdout 的 target>","out_roots":[<非默认 --out/--rules-dir 解析后绝对根,默认产物根不列>],"v":1}' > <target>/.mgh-init/.active`
     守卫激活 = `MGH_INIT_ACTIVE=1` env **或** 该哨兵(opencode 插件进程不继承 mid-session env → 哨兵兜底,使
     脚本只读 / 受信子树守卫在 opencode 上整 run 可靠激活)。哨兵携 `target` 使 `MGH_TARGET` 在 opencode step 0 即就绪。
     完成态(step 8)/ 干净停止 `rm <target>/.mgh-init/.active`(避免残留锁死日常开发);`--resume` step 0 重写覆盖。
   · **MGH_TARGET**(供 hook 判树):`controls_candidates.json::repo` 即**绝对项目根**(= 哨兵 `target`,二者一致)。该产物首次 discover 后落盘、**`--resume` 时 discover 跳过但产物仍在**——故编排器在 fan-out 前(无论本次是否实跑 discover)**逐字读**该字段并 `export MGH_TARGET=<repo>`。取值经 `describe_artifact.py --field repo`(合法瞄结构出口)。hook 在 `MGH_TARGET` 缺失时该条**降级放行**(不阻断)。
   · **codegraph 检测**(花 token 之前):`Bash: if test -d <target>/.codegraph && command -v codegraph >/dev/null 2>&1; then echo on; else echo off; fi`
     → `codegraph=on|off`。默认 `auto`(可用即启用);传 `--no-codegraph` 或检测不可用 → `codegraph=off`。该信号**逐字透传**进
     scout/induct/survey/resolve subagent task 输入(仅 `codegraph=on` 时这些 stage 启用 codegraph 外科式上下文 + 执行 `init-resolve` stage)。
1. IF --merge: merge partial inventories by evidence anchor → STOP
2. i1 discover (Bash, deterministic, streaming):
     py .claude/mgh-core/scripts/discover_controls.py --repo <target> --out <target>/.mgh-init
        [--scope .. --scope-mode .. --language .. --max-files .. --big-file-bytes .. --sample ..]
   → controls_candidates.json (regex, `source:regex`) + clusters.json + skeleton.json  (skip on --resume if present & not --rebuild-cache)
   · 派生量直读 discover stdout:`candidates/clusters/unresolved_count/big_files`
   · **MGH_TARGET**:discover 跑过后(产物在盘上)取其 `repo` 字段(绝对根)——
     `py .claude/mgh-core/scripts/describe_artifact.py --in <target>/.mgh-init/controls_candidates.json --field repo`
     → stdout `{"value":"<绝对 target>"}`;`export MGH_TARGET=<该 value>`(供 hook 判树)。
     **`--resume` 时 discover 跳过,但 `controls_candidates.json` 仍在 → 同法重设 `MGH_TARGET`**(别让子树守卫在 resume 上 fail-soft)。
   · 校验:`py .claude/mgh-core/scripts/discover_controls.py --check <target>/.mgh-init`(wrapper + 每条 `source` + cluster_id 唯一;退出码 2 → 回退重跑)
3. (optional) init-survey subagent → i1_enriched.json
   · **advisory + non-fatal**:产出仅作审计/T2 参考,**非 T1 输入**(T1 读 `clusters.json`);
     缺失 `i1_enriched.json` **不阻断**、不报致命错。`total` 过大(单 subagent 装不下整仓簇)
     时**跳过**,并在摘要披露。
3b. SCOUT FAN-OUT (除非 `--no-scout`)——让 LLM 找出 regex 闸门漏掉的自研控制:
     [skeleton.json + controls_candidates.json] → plan_scout.py → [scout_plan.json::batches[]]
     py .claude/mgh-core/scripts/plan_scout.py --skeleton <target>/.mgh-init/skeleton.json \
        --candidates <target>/.mgh-init/controls_candidates.json --out <target>/.mgh-init/scout_plan.json \
        [--batch-bytes .. --batch-cap .. --budget ..]
     · 批数涌现 = ceil(Σtarget_bytes / --scout-batch-bytes);按包内聚切批,每批字节≤预算且文件数≤cap。派生量 `regex_known_count` 在 stdout / `scout_plan.json` 顶层。
     · 校验:`py .claude/mgh-core/scripts/plan_scout.py --check <target>/.mgh-init/scout_plan.json`(batches 非空除非 0 target、每批 bytes≤预算、needs_slice 仅含超批文件;退出码 2 → 回退)。
     [scout_plan.json::batches[]] → list_scout_batches.py --materialize → [stdout slim pending[](每项 `input_path`/`oversize`/`needs_slice`/`checkpoint_path`/`done_marker`/`slice_dir`)](禁手挖 `scout_plan`)
     py .claude/mgh-core/scripts/list_scout_batches.py --scout-plan <target>/.mgh-init/scout_plan.json --checkpoints <target>/.mgh-init/checkpoints/scout --materialize <target>/.mgh-init/inputs/scout
     按 `offset`/`effective_limit` 翻页(单页 > `--orch-budget-bytes` 时 `shrunk:true`;NEVER wrapper `.py`);per batch in page `pending[]`(**每批一个隔离 subagent 上下文**;`--resume` 跳过已 `.done`/`.failed`):
       - spawn init-scout(透传 `input_path` + checkpoint_path + done_marker + failed_marker + slice_dir + `<list_steps script_abs 派生的绝对 chunk_sources 路径>`;subagent 读 `input_path`,needs_slice 文件写 `<绝对 chunk_sources> --in <big_file> --big-file-bytes <N> --line <L> --out <slice_dir>/<safe-stem>.slice.json` 并回读该确切路径,**绝不**整文件喂 LLM)→ 成功则恰好写 `checkpoint_path`(绝对) + touch `done_marker`;失败回 `failed <原因>` ack → 编排器写 `failed_marker`、不重试不阻断(见上「fan-out 单元 `failed` ack」)
     spawn init-scout-merge 前**先判聚合预算** — `py .claude/mgh-core/scripts/plan_aggregate.py --node scout-merge --init-dir <target>/.mgh-init --budget <max-aggregate-bytes> [--materialize <target>/.mgh-init/inputs/scout-merge]`
       · `needs_reduce=false`(≤ 预算)→ 既有 single-context `init-scout-merge`(只见全部 scout 批记录,无原始码)→ `scout_candidates.json` + `checkpoints/scout/merge.json.done`
       · `needs_reduce=true`(> 预算)→ 每 shard(batch 簇)扇出 `init-scout-merge`(partial;读 shard `input_path`,ack 回传)→ 单一 rollup 仅吞各 shard 摘要 → `scout_candidates.json` + `checkpoints/scout/merge.json.done`。每请求 ≤ 预算。
     · 校验:`py .claude/mgh-core/scripts/merge_scout.py --check <target>/.mgh-init/scout_candidates.json`(每条 `source:"scout"` + file:line;退出码 2 → 回退)。
     spawn init-scout-audit(随机 ≈--scout-audit-pct 的 scout 拒绝项)→ checkpoints/scout/audit.json + .done
     py .claude/mgh-core/scripts/merge_scout.py --candidates <target>/.mgh-init/controls_candidates.json \
        --scout <target>/.mgh-init/scout_candidates.json --audit <target>/.mgh-init/checkpoints/scout/audit.json \
        --clusters <target>/.mgh-init/clusters.json
     · 候选集并入 `source:"scout"`;clusters.json **追加** scout 簇(regex 簇与其 usage_sites 不变)。复用 `discover_controls.form_clusters`,无逻辑漂移。
     · **并入>0 级联失效**:fold-in 实际并入 N>0 候选时自动删除下游 t2/t3/t4 聚合 `.done`(stderr 注明 + stdout `invalidated_tiers[]`),使 scout 补完后 plain `--resume` 重跑 T2–T4;并入 0(全重复/全失败)不删(输入没变)。
     · **终态**:`scout_candidates.json` / `controls_candidates.json` / `clusters.json` 此时为终态——不再二次聚合 / 重切批(NEVER `_aggregate_scout.py`)。
3c. (optional, codegraph-gated) init-resolve — 仅当 `codegraph=on` **且** `unresolved[]` 非空时执行;
     排空文本/AST 图结构性漏掉的框架路由 / DI / AOP / interface→impl / 反射控制。**non-fatal + bounded**:
     [controls_candidates.json::unresolved[]] → describe_artifact.py --field → init-resolve subagent → [resolved.json]
     · 取 `unresolved[]` 清单(合法瞄结构出口):
       `py .claude/mgh-core/scripts/describe_artifact.py --in <target>/.mgh-init/controls_candidates.json --field unresolved`
       → stdout `{"field":"unresolved","value":["<file>",...]}`;空列表 → 跳过本 stage(摘要披露)。
     · spawn init-resolve({unresolved[], repo root, checkpoint_path=<target>/.mgh-init/resolved.json(绝对),
       done_marker=<target>/.mgh-init/checkpoints/resolve/.done(绝对)}, codegraph=on)
       → 恰好写 `checkpoint_path`(绝对)+ touch `done_marker`(产 `{repo, resolved[]{…source:"codegraph", resolved_path[]}, unresolved_residual[]}`,见 `core/contracts/init/resolved.md`)
     · **additive 并入 T1 候选流**:`resolved[]` 按既有 `category::anchor` 簇键由编排器路由到对应簇的 candidate hits(additive;**不** mutate regex/scout 候选、**不**改任何确定性脚本;簇形成语义与既有 form_clusters 一致)。`source:"codegraph"` 结构标签一路保留进 inventory/manifest。`unresolved_residual[]` 残留计 manifest `codegraph.unresolved_residual`。
     · **MGH_TARGET / 子树守卫**:`resolved.json` 写在 `<target>/.mgh-init/` 下,既有子树守卫覆盖;`checkpoint_path` 是编排器**逐字给定**的绝对路径(NEVER 拼装 `<target>/<id>`、NEVER 占位符、NEVER 相对)。
     · **fail-soft / non-fatal**:`codegraph=off` / `unresolved[]` 为空 / 清单过大超单 subagent 上下文预算 → 跳过整 stage + 摘要披露,流水线**不阻断**、不报致命错(对标 init-survey 的 optional/advisory/non-fatal 语义)。T1 从 `clusters.json` 正常扇出不受影响。
4. T1 FAN-OUT — 经确定性脚本枚举 + per-unit 物化(**禁手搓**;`clusters.json` 是包装字典
   `{repo,clusters[],truncated}`,对顶层 `len()` 得 3 **不是**簇数;编排器 NEVER 整份读 `clusters.json`):
   [clusters.json::clusters[]] → list_clusters.py --materialize → [stdout slim pending[](每项 `input_path`/`bytes`/`oversize`/`checkpoint_path`/`done_marker`/`slice_dir`)]
     py .claude/mgh-core/scripts/list_clusters.py --clusters <target>/.mgh-init/clusters.json --checkpoints <target>/.mgh-init/checkpoints/t1 --candidates <target>/.mgh-init/controls_candidates.json --materialize <target>/.mgh-init/inputs/t1
     → stdout `{repo,total,done,pending[],truncated,offset,limit,effective_limit,shrunk}`;物化每簇完整记录(簇字段 + 候选命中回查 `controls_candidates.json`)到 `inputs/t1/<unit>.input.json`(≤ `--max-unit-bytes`;oversize 簇切 `<cluster_id>::shard-<n>`)
     · **scout 闸门(承重,保留此反例)**:`run_config.json` 启用 scout(`no_scout=false`)而 scout 层未完成时,`list_clusters.py` **退出码 2**(`{"error":"scout-incomplete-gate"}`,无 `pending[]`,stderr 给 recipe)——先完成 scout 层,NEVER 以纯 regex 簇继续 T1(`--no-scout` 显式绕行则闸门跳过)。
   按 `offset`/`effective_limit` 翻页(单页 > `--orch-budget-bytes` 时 `shrunk:true`;NEVER wrapper `.py`);for each unit in page `pending[]`(NOT `clusters.json` 顶层;`--resume` 跳过已 `.done`/`.failed`):
     - spawn init-induct(透传 `input_path` + checkpoint_path + done_marker + failed_marker + slice_dir + `<list_steps script_abs 派生的绝对 chunk_sources 路径>`;subagent 读 `input_path`,运行时发现的大证据文件写 `<绝对 chunk_sources> --in <big_file> --big-file-bytes <N> --line <L> --out <slice_dir>/<safe-stem>.slice.json` 并回读该确切路径)
     → 成功则恰好写 `checkpoint_path`(绝对) + touch `done_marker`;失败回 `failed <原因>` ack → 编排器写 `failed_marker`、不重试不阻断(见上「fan-out 单元 `failed` ack」)
4b. T1→T2 边界闸门(T1 fan-out 波次完成后、进 T2 前 MUST 跑;BOM 剥离 + 形状校验,与 step 5 的 T2 边界 `validate_inventory` 对偶):
     py .claude/mgh-core/scripts/validate_t1_records.py --strip-bom --checkpoints <target>/.mgh-init/checkpoints/t1
     py .claude/mgh-core/scripts/validate_t1_records.py --check --checkpoints <target>/.mgh-init/checkpoints/t1
   · `--strip-bom` 始终先跑(无损、idempotent,剥离 LLM 子代理 `Write` 产物的前导 UTF-8 BOM 宿主产物);`--check` 是 fail-loud 形状闸门(根级 `cluster_id`/`name`/`category`∈8/`kind`∈vvah 6-enum/`category`→`kind` 归一/`evidence`≥1 非空锚点/`entry_points` 列表/`confidence` 数值 + 无嵌套 `controls[]` 漂移签名)。
   · `--check` 退出码 2(形状漂移)→ 外科式重派:对 stdout `violations[]` 每项 `rm <其 file>.done` 失效该违例簇 `.done` marker、重跑 `list_clusters` 重派该簇;NEVER 带破损 T1 记录进 T2 综合(承重,保留此反例)。BOM 非 shape 违例(`--check` 内存剥 BOM、记 `bom[]` advisory;`--strip-bom` 已磁盘剥离,故 `--check` 实跑时不见 BOM)。空目录 = `ok:true, records:0`(T1 是否跑过由 `resume_state` 判,非形状 validator)。
5. T2: **先判聚合预算** — `py .claude/mgh-core/scripts/plan_aggregate.py --node t2 --init-dir <target>/.mgh-init --budget <max-aggregate-bytes> [--materialize <target>/.mgh-init/inputs/t2]`
     · `needs_reduce=false`(≤ `--max-aggregate-bytes`,常见小仓)→ 既有 **single-context** `init-synthesis`(sees all T1 records, no raw code)→ `controls_inventory.json` + `checkpoints/t2/.done`(行为等价于引入硬阈值前)。
     · `needs_reduce=true`(> 预算)→ 每 shard 扇出 `init-synthesis`(partial;读 shard `pending[].input_path`,ack 回传,恰好写 `pending[].checkpoint_path`)→ 单一 **rollup** `init-synthesis` 仅吞 `rollup.summary_paths`(各 shard 摘要,非原始记录全集)→ 写 `controls_inventory.json` + `checkpoints/t2/.done`。**每个大模型请求 ≤ 预算**。
   · 校验:`py .claude/mgh-core/scripts/validate_inventory.py --inventory <target>/.mgh-init/controls_inventory.json`(`design_controls` 兼容字段 + 每条 evidence 锚点 + category→kind 归一;退出码 2 → 回退重跑;map-reduce rollup 产物 schema 不变,同样适用)。
   · 降级触发 + shard 数进 `init_manifest.json::boundaries[]` + `report.md`(无静默溢出)。
6. T3 FAN-OUT — 经确定性脚本枚举 + per-category 物化(**禁手挖** inventory;编排器 NEVER 整份读 `controls_inventory.json`):
   [controls_inventory.json::controls[].category] → list_rule_jobs.py --materialize → [stdout slim pending[](每项 `input_path`/`bytes`/`oversize`/`rule_path`/`done_marker`)]
     py .claude/mgh-core/scripts/list_rule_jobs.py --inventory <target>/.mgh-init/controls_inventory.json --format <format> --checkpoints <target>/.mgh-init/checkpoints/t3 --target <target> --rules-dir <target>/docs/security-controls --materialize <target>/.mgh-init/inputs/t3
     → stdout `{total,done,pending[],format,offset,limit,effective_limit,shrunk}`;物化每 category 完整 controls 到 `inputs/t3/<category>.input.json`(oversize 标 `oversize` + recipe,**不**切分)
   按 `offset`/`effective_limit` 翻页;per category in page `pending[]`(WITHOUT `.done`/`.failed`;`--resume` 跳过):
     - spawn init-rulewriter(透传 `input_path` + --format + rule_path + done_marker + failed_marker;subagent 读 `input_path`)
     → 成功则恰好写 `rule_path`(绝对;claude: `.claude/rules/security-<cat>.md`;opencode: 详述文件 `docs/security-controls/<cat>.md`)+ touch `done_marker`;失败回 `failed <原因>` ack → 编排器写 `failed_marker`、不重试不阻断(见上「fan-out 单元 `failed` ack」)
6b. ASSEMBLE / LINT (Bash, deterministic; uses the run's --format, after T3 / before T4):
     py .claude/mgh-core/scripts/assemble_rules.py --target <target> --format <format>
   · opencode: 扫 `<rules-dir>/*.md` 详述文件建 `<target>/AGENTS.md` 简洁**惰性索引块**(幂等、迁移旧 `mgh-init:` 块、内置 lint);正文留详述文件按需加载
   · claude: 无索引(T3 已直写文件),仅对 `.claude/rules/security-*.md` 做纯净性 lint
   · lint(fail-loud 退出码 2)= 规则正文泄漏:T3 禁 front matter / inventory schema 字段
     (`found_controls`/`evidence_count`)/ 过程散文(`扫描器模式定义` 等)/ 无源码锚点的控制;lint 覆盖
     工具内部 token + schema 字段 + 特征过程散文(opencode 另查 `---` YAML 围栏;claude `paths:` frontmatter 豁免)。
     回 T3 修正后重跑
7. T4 (unless --skip-consistency): spawn init-rules-consistency
     → in-place edits to rule files (claude) / detail files (opencode) + checkpoints/t4/.done
8. i4: write init_manifest.json + report.md; print artifact paths + disclaimers
   · manifest 含 `codegraph:{available,used,resolved_count,unresolved_residual}`:`available`=检测到 `.codegraph/`+CLI;`used`=`codegraph=on` 且 `init-resolve` 实跑;`resolved_count`/`unresolved_residual` 取自 `resolved.json`(经
     `py .claude/mgh-core/scripts/describe_artifact.py --in <target>/.mgh-init/resolved.json --field resolved --count` 计数);`codegraph=off` 时 `used=false`/`resolved_count=0`,不出现解析计数。report.md 同步披露 codegraph 用量 + 残留盲区。
   · **fan-out 失败披露**(任一 tier `failed>0`):据 `resume_state.py` stdout `tiers[<tier>].failed`(磁盘真相、**NEVER** 对话记忆)写 `init_manifest.json::failures`(per-tier `{done,failed,total}`)+ `boundaries[]`(「fan-out 单元确认失败、已跳过、终局需人评」)+ `report.md` 同步披露失败计数/率。
   · **scout_merged 落账**:读 `resume_state.py` stdout `tiers.scout.merged`(fold-in 实际并入数;fold-in 未跑 / `--no-scout` 时缺省)写入 `init_manifest.json::scout.scout_merged`(既有 `scout` 段增字段,不改段结构)。
   · **收尾移除哨兵**:`rm <target>/.mgh-init/.active`(run 完成;避免残留哨兵锁死日常开发)
```
