# fix-mgh-init-discover-resilience

> **人话序**:mgh-init 的第一步是确定性发现——`discover_controls.py`(扫全仓找存量安全控制候选)
> 复用 `expand_scope.py`(文件遍历 + 文本调用图),产物再喂给后续扇出。2026-10-13 全流程深度
> 评审(维护者私有文档区)在这一层确认了三处 high 与一组 medium:① 调用图是**单遍**构建的
> ——边扫描边建「谁定义了这个名字」的索引,A 文件只能解析到枚举顺序中排在它前面的定义,
> 实测两份 Java 文件仅交换文件名,分析结果就从 1 个文件变 2 个文件——约一半跨文件调用边
> **静默丢失**(不进 `unresolved[]`,零披露),而同仓的 discover 里明明躺着一个正确的两遍
> 实现;② 文件数配额(默认 2 万)对**任意扩展名**计数——.txt/.xml/.sql 都吃配额,触顶后
> **静默收工**,而 discover 侧「多扫一个就报截断」的哨兵恰好建立在「配额只数源文件」的错误
> 假设上,配额被非源文件吃掉时哨兵永远不会触发;③ `--scope path:<拼错的目录>` 与「该模块
> 无源文件」不可区分——静默空集 + 退出码 0,产出「该模块无存量控制」的**错误安全结论**
> (mgh-sast 同病丢全部 findings)。medium 群:`--check` 对「合法 JSON 但形状错」裸崩
> TypeError(实机复现,违反退出码 2 + violations 契约);续点缓存键不含 `--scope/--language`
> (换参续跑产出新旧参数混合候选集);调用图两遍(最贵阶段)无软时限(超宿主超时即全损);
> 续点每 1000 文件全量重写累积候选(O(n²) 写放大);`plan_scout` 裸写非原子;step 0 的
> run_config 原子写缺 flush/fsync(掉电可产零长度恢复锚点)+ 哨兵的域取自 `--run-root` 名而
> 位置取自 `--init-dir`(显式错组可激活错误域);`describe_artifact --field` 单独使用无界
> 倾倒;文件遍历的剪枝检查**绝对路径全部分量**——仓库放在 `D:\build\…` 或任何带排除名/
> 点前缀的祖先目录下就**整仓静默扫空**。本 change 逐一收口;验证 = 每项先红后绿 + 定向
> 测试面(init 发现五件套 + sast 侧 expand_scope 共用面)全绿。

## Why

评审基线(VERSION 0.1.60)后批次 1-5 已落地;本批全部发现按**内容**在当前工作树态(批次 5
实施已入树、归档进行中;批次 6 涉改文件与批次 5 零重叠)重定位并逐一确认仍在:

| # | 缺陷 | 评审定级 | HEAD 验证锚点 |
| --- | --- | --- | --- |
| H5 | `expand_scope.build_call_graph` 单遍顺序依赖:def 索引边走边建,跨文件边约半数静默丢失(不进 `unresolved[]`) | High | 同循环内 `name_to_files[d].add(rel)` 与调用解析;discover_controls 内有两遍正确实现(自证语义已知);mgh-sast scope resolver CLI 直调本脚本 |
| H6 | `walk_sources` 配额对任意扩展名计数(.txt/.xml/.sql 耗额),触顶静默 return;discover 的 `max_files+1` 截断哨兵假设配额只数源文件 | High | `limit_files -= 1` 在 `if lang:` 之外;`_collect_files` 的 `+1` 哨兵逻辑 |
| H7 | `--scope path:<不存在目录>` / `--package <无匹配>` 静默空集 exit 0 | High | `seeds = collect_dir(...) if d.is_dir() else []` → 空 → "empty seed set" + exit 0 |
| M1 | `discover --check` 对「合法 JSON 但 wrapper 形状错」裸崩 TypeError(违反 exit 2 + violations 契约) | Medium | 实机复现:`[1,2,3]` 作 candidates 文件 → `enumerate(None)` traceback;not-list 分支漏置 `[]` |
| M2 | scan 续点缓存键不含 `--scope/--language`:换参 `--resume` 产出新旧参数混合候选集 | Medium | `scan_candidates` 的过滤在扫描循环内按 `language`/`seed_files` 逐文件施加,续点只记 `scanned_index` |
| M3 | callgraph 两 pass 无软时限:最贵阶段不设防,超宿主超时即零全损(scan 续点尚未产生) | Medium | deadline 检查仅在 scan 边界 + 一处前置;两 pass 循环体内无检查 |
| M4 | scan 续点每 `--progress-every` 全量重写累积候选列表(O(n²) 写放大,大仓 GB 级冗余写) | Medium | `_write_scan_progress(outdir, i, candidates, manifest)` 携全量列表 |
| M5 | `plan_scout` 写 scout_plan.json 裸 `write_text` 非原子(同族都有原子写;是续点 fail-open 的主要触发供给) | Medium | 单处 `Path(args.out).write_text(` 直写 |
| M6 | `write_runconfig` 原子写缺 flush/fsync(掉电后 replace 可落零长度 run_config——崩溃恢复锚点);哨兵 domain 派生自 `--run-root` 名、位置派生自 `--init-dir`,显式错组激活错误域的受信子树 | Medium | `tmp.write_text` 直 `os.replace` 无 fsync;docstring 自证 domain「by --run-root」+ sentinel 落 init_dir |
| M7 | `describe_artifact --field` 单独使用无界输出(整份值倾倒 stdout,正是该脚本要替代的反模式) | Low | `--field` 在模式必选清单内可单独使用,导航后原样回显值 |
| M8 | `walk_sources` 剪枝(EXCLUDE_DIR + 点前缀)检查绝对路径**全部分量**:repo 放 `D:\build\…`、`~\.cache\…` 等祖先下 → 整仓静默扫空(实测);点前缀剪枝规格明写「相对 repo 的路径」而代码检查绝对分量 | Medium | `any(part in EXCLUDE_DIR for part in p.parts)` + `any(part.startswith(".") for part in p.parts)` |

全部为异常/边界分支(错组参数、大仓、崩溃恢复、祖先目录布局),正常小仓流程不经过;但一旦
触发,后果是**静默丢数据**(调用边、截断文件、整仓)或**错误安全结论**(空 scope)——比
fail-loud 更危险的一类。

## What Changes

涉改 = 发现层 4 个脚本 + 2 个共用件(`expand_scope.py` / `discover_controls.py` /
`plan_scout.py` / `write_runconfig.py` / `describe_artifact.py`),零 LLM 提示词、零分发面:

1. **调用图两遍化(H5)**:`expand_scope.build_call_graph` 改两遍——pass 1 全量建 def 索引 +
   框架标记,pass 2 对**完整**索引解析调用(镜像 discover_controls 内同名实现的结构;对
   mgh-sast 的 CLI 消费面输出 shape 不变)。
2. **配额只数源文件 + 截断上浮(H6)**:`walk_sources` 的 `limit_files` 仅对源扩展名文件计数;
   触顶时 stderr 告警 + 截断信号上浮(可选 accumulator 形参,镜像 `dot_skipped` 家族形态);
   discover 侧 `+1` 哨兵因此真正生效,`truncated` 如实上浮。
3. **scope 歧义输入 fail-loud(H7)**:`--path` 指向不存在路径 / `--package` 无任何匹配目录 →
   退出码 2 + recipe(闭集参数拒歧义输入纪律);「目录存在但无源文件」保持 exit 0 + note
   (合法空集)。
4. **`--check` 形状错收口(M1)**:not-list / not-dict 分支将目标归一为 `[]`(violation 照报),
   任何合法 JSON 形状错 → violations + 退出码 2,NEVER traceback。
5. **续点参数指纹(M2)**:`scan_progress.json` 记录生效扫描参数(scope/language 指纹);
   `--resume` 参数与续点指纹不符 → 弃续点从头扫 + stderr 披露(NEVER 混合候选集)。
6. **调用图软时限(M3)**:deadline 检查扩至两 pass 内部(`--progress-every` 节奏);pass 1
   完成态落 `cache/callgraph_defs.json` 供 resume 复用(pass 1 是完整即缓存件);pass 2 中途
   超限 → 干净 partial 早退(退出码 0 + `partial:true`),scan 续点与缓存留存,零全损。
7. **续点增量日志(M4)**:累积候选改追加式 `scan_journal.jsonl`(每检查点窗口只写新增候选)
   + 小体积 `scan_progress.json`(索引/计数/指纹);总写放大从 O(n²) 降 O(n);resume 读
   journal 重放;完成时清理 journal(幂等 resume 语义不变)。
8. **plan_scout 原子写(M5)**:scout_plan.json 改 `.tmp` + `os.replace`(原子写家族统一)。
9. **step 0 持久性(M6)**:`write_runconfig` 原子写补 flush + `os.fsync` 再 replace(run_config
   与哨兵/gitignore co-write 同治);哨兵 domain 与位置单一来源——显式传参组合违反
   `init_dir == target/run_root` 不变式 → 退出码 2 + recipe(默认组合行为零变化)。
10. **`--field` 有界输出(M7)**:单独使用时值截断(实现常量上限)+ `truncated` 标志 + 容器
    计数(len);与 `--count`/`--shape` 组合时行为不变。
11. **剪枝按相对分量(M8)**:EXCLUDE_DIR 与点前缀剪枝判定改用 `p.relative_to(repo).parts`
    (repo 外祖先分量不参与);点前缀剪枝回归其规格明文的「相对 repo」语义。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `control-discovery`: 10 条 requirement 修改——「Skip dot-prefixed paths during discovery」
  (剪枝按 repo 相对分量判定,祖先不误剪)、「Reuse call-graph engine for control wiring」
  (调用图两遍化、顺序无关)、「Scoped and partial-merge analysis」(scope 歧义输入 fail-loud)、
  「Bounded single-pass scan performance on large repos」(配额只数源文件 + 截断上浮)、
  「Sanctioned artifact-inspection primitive」(`--field` 有界输出)、「Stage-boundary contract
  checks」(discover `--check` 形状错 → violations 退出码 2)、「Discover scan resumes from a
  checkpoint」(续点参数指纹 + 增量日志)、「Discover soft time-budget clean exit」(软时限
  扩至调用图两 pass + pass 1 缓存复用)、「Discover writes are atomic」(原子写家族补
  plan_scout)、「Persisted run configuration for stateless resume」(fsync + 哨兵 domain/位置
  单一来源)。

## Impact

- **涉改脚本**:`expand_scope.py`(H5/H6/H7/M8,注意 mgh-sast 共用——`test_focus_scope` 必跑)/
  `discover_controls.py`(H6 哨兵消费/M1/M2/M3/M4)/ `plan_scout.py`(M5,原子写一行——批次 5
  刚改过该文件的预算记录/`--check` 面,零冲突)/ `write_runconfig.py`(M6)/
  `describe_artifact.py`(M7)。
- **stdout 契约变化**:`expand_scope` 在截断时新增 stderr 告警(信号经 accumulator 上浮,
  stdout JSON 形态不变);`scan_progress.json` schema 增参数指纹字段 + journal 新文件(内部
  缓存产物,非编排器消费面);`describe_artifact --field` 单独使用时输出增 `truncated` 键。
  其余 stdout 零变化。
- **回归面**(AGENTS.md 映射表):`test_init_discover` / `test_discover_resilience` /
  `test_init_runtime` / `test_write_runconfig` / `test_describe_artifact` + sast 共用面
  `test_focus_scope` + `test_zero_deps` / `test_no_compile_warnings`。
- **批次边界**:批次 5 归档写回 control-discovery 的 5 条 requirement 与本批 10 条**不重叠**
  (按名合并,归档互不覆盖);批次 7(stage 提示词/契约批量 + H11 拍板项)不涉。
- **VERSION**:脚本改动 → apply 会话 bump + CHANGELOG。
