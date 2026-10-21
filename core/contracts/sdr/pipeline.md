# Stage I/O contracts — `/mgh-sdr` pipeline (`security-design-review`)

`/mgh-sdr`(需求分支代码 diff 的存量安全设计符合性复核)的确定性叶脚本 I/O 契约。三个
producer(`diff_group.py` / `sdr_context.py` / `render_sdr_report.py`)全部 Python ≥3.10
标准库、自定位(`sys.path.insert(0, dir-of-__file__)`)、任意 cwd 可 `py`、stdout=结构化
JSON / stderr=诊断严格分流、退出码 `0` 成功 · `1` 输入错误(文件缺失/JSON 畸形/gate 形
失败同 2 见下)· `2` 误用(argparse / 闭集校验 / `--check` 违例)。`--help` 即 CLI 契约面。

## Run 目录布局

```
<repo>/.mgh-sdr/
├── .active                          # 运行域哨兵 {domain:"mgh-sdr", target, out_roots[], read_roots[], v:1}
└── runs/<ts>/                       # 一次评审 run(ts = YYYYMMDD_HHMMSS 本地时区)
    ├── context.json                 # sdr_context 产出(base/branch/baseline_path/external_repos[]);起始态唯一真相源
    ├── run_config.json              # 脚本写出,**唯一载荷** {"no_codegraph": bool};起始态字段 NEVER 写入
    ├── slices/                      # diff_group 物化的只读单元 slice(<unit_id>.slice.md);原生形态下 emit_native_plan 另落每单元任务文件 <unit_id>.task.md(同目录)
    ├── drafts/                      # fan-out 单元 draft JSON(<unit_id>.json)+ .done/.failed 落 markers/
    ├── native_plan.json             # emit_native_plan 产出(仅原生形态):波次表 + 短号三方映射 + 任务文件路径(全绝对);每轮重物化 = 重枚举
    ├── watchdog/                    # native_watchdog 工件(仅原生形态):events.jsonl 追加 + state.json 原子写(自退后留存)
    ├── external/<repo-slug>/        # sdr_context 物化的外部仓结论文件(summary.json + hits.md)
    ├── baseline.md                  # 存量安全设计基线投影(≤32KB 默认,优先级截断)
    ├── sensitive_catalog.json       # sdr_context 物化的解析后敏感目录对象(subagent 只读路径的指向)
    ├── readability_text_bundle.json # render 每次渲染写出;全部问题记录人类面文本的单束(读者模拟评审唯一输入)
    ├── readability_advisories.json  # 读者模拟评审建议(编排器在首次渲染后派发一次评审产出;可选)
    ├── markers/                     # <unit_id>.done / <unit_id>.failed(磁盘真相,resume 锚)
    └── sdr_manifest.json            # render 产出 counts + boundaries + failed_units[];整条 run 的终止凭证
```

**特殊授权说明不在 run 目录布局内**:它是项目所有的手工文件 `<repo>/.mgh/special-auth.md`
(可选入口;存在时命令壳/launcher/恢复输出只加一句「先 Read 该说明,按其鉴权说明执行」,
不存在零动作)。sdr 流程不预设任何凭证命令,也不在 run 目录里生成凭证参数/载荷/子配置/
数据目录;子进程派发器的 `--cred-file` 与 `mgh_credentials.py` 是**手动/遗留能力**,不被任何
sdr 流程引用。

**运行目录里没有起始态文件**:repo / base / branch 由 `context.json`(及 `grouping.json`)承载,
恢复时从它们重派生;`run_config.json` 只承载 codegraph 信号。`<repo>/.mgh-sdr/.active` 与
`run_config.json` **都由脚本副作用写出**(`sdr_context.py`),不是编排器手执行的 `printf` 配方——
命令壳里**不存在**写它们的步骤。恢复入口见
[`resume-state.md`](resume-state.md)。

## `diff_group.py` — diff 采集与接口维度分组

```
py diff_group.py --repo <abs> --base <ref> --branch <ref> --checkpoints <dir> --inputs-dir <dir>
                 --materialize <dir> [--max-standalone-bytes B] [--offset N] [--limit N] [--resume]
py diff_group.py --check <run-dir>
```

| 项 | 契约 |
|---|---|
| 输入 | `--repo` 绝对 git 仓;`--base` 默认 `master`;`--branch` 默认当前分支(`git rev-parse --abbrev-ref HEAD` 确定性解析);diff 源 = `git diff --no-color <base>..<branch>` |
| 分组 | **接口单元**(`kind=interface`):java web 注解启发式(`@RestController`/`@Controller`/`@RequestMapping`/`@GetMapping`/`@PostMapping`/`@PutMapping`/`@DeleteMapping`/`@PatchMapping`/`@Path`/`@GET`/`@POST` 等)命中文件按接口方法切,一个接口 = 该方法 hunk + 类级注解上下文;`route` = 类级路径 + 方法路径拼接。**独立变更单元**(`kind=standalone`):其余全部文件按目录簇归并,`--max-standalone-bytes` 超限按文件细分。启发式失败安全退化(全部 standalone,不报错) |
| 变更符号提取 | 分支版本 java 文件由**确定性本地扫描**(注解 + 方法声明 brace 域,含字符串/注释安全跳读)切方法符号;每个 diff hunk 锚到其**首个 added 行的宿主符号**(纯删除 hunk 锚最后一个上下文行;hunk 起点可能因 git 3 行上下文前漂进无关方法,故不按 hunk 起点归属);无宿主符号 → 文件级变更。**codegraph `node --file --symbols-only` 输出为 markdown 符号表(无 endLine、非 JSON),不作机器边界源**;符号边界单一真相源 = 本地扫描(退化路径本来就需要) |
| 调用链分组 | **codegraph 门控**:probe `<repo>/.codegraph/` 存在 ∧ `codegraph` 可解析(PATH,或 `MGH_CODEGRAPH_BIN` 显式覆盖;env 指向不存在路径 = 显式 off)才启用。每个变更符号跑 `codegraph callees/callers <name> --json --path <repo> --limit 500`,解析条目 `{name, filePath, startLine}`,以 `filePath::name` 匹配变更符号集(同名跨文件并集 → 集合过滤,多余端点被丢弃);仅保留两端均在变更集内的边。**含 ≥1 路由注解符号的分量按路由锚分解**:每个变更路由方法的**下游闭包**(沿调用边 BFS)→ 1 个 `interface` 单元,slice 合并整链 hunk(controller + 被调变更 service/dao);`route` = 类级 + 方法路由拼接。判不穿(反射/DI 残差、查询失败)→ 落 standalone |
| 共享下游 | 一个变更符号被 ≥1 变更路由引用时不并成一个分量:该符号 hunk 在每个引用它的 interface slice 内重复(受 `unit_bytes`,single-slice 仍≤预算),跨单元重复 finding 交渲染侧三元组去重 |
| 退化 | codegraph off / 全部查询失败 / 无 java 变更 → 注解接口单元 + 目录簇 standalone(**与 add-mgh-sdr 逐字等价**);codegraph 只供调用边,off 时零 codegraph 调用、退出码不受影响。java 独立残差(codegraph 模式下未达路由的非接口 java 变更)按**每文件一个 standalone 单元**(拆多个不硬塞);非 java/删除文件残差按目录簇归并 `--max-standalone-bytes` 拆分 |
| slice | 每单元物化只读 slice(diff hunk + 有限邻近上下文 + 文件相对路径 + A/M/D/R 变更类型标注)→ `<run-dir>/slices/<unit_id>.slice.md`;调用链 interface 单元另带 `## Annotation context(branch version)`(路由/权限注解 + 类级 base route) |
| `pending[]` | 每项 `{unit_id, input_path, draft_path, done_marker, failed_marker, kind, route, unit_bytes, slimmed, chain, baseline_path, external_dir}`——路径字段**全 `Path.resolve()` 绝对**且在 repo 子树内,编排器逐字透传;`slimmed` = 本单元被截断的描述性上下文块及其截断前大小(`{}` = 完整);`chain` = codegraph 模式下物化的调用链(standalone / codegraph off 恒 `[]`);`baseline_path`/`external_dir` = 前向推导的基线投影与外部仓结论目录(缺失 = 该步未跑,子代理跳过);`unit_id` 文件系统安全命名(`/ \ :` → `_`,NTFS ADS 教训) |
| stdout | `{repo, base, branch, empty, codegraph, total, done, failed, counts:{interface,standalone}, pending[], offset, limit}`;`codegraph` = bool:本次是否走调用链分组;`empty:true` + `pending:[]` = 零变更 diff(退出码 0,编排器不 spawn) |
| `--summary` | stdout 投影视图(同一执行流跑完、物化与 `grouping.json` 落盘**逐字不变**,缺省形态零回归):`{repo, base, branch, summary{pending_total, done, failed, by_type{interface, standalone, partN}, excluded_count, empty, effective_limit, offset}, pending[]}`。摘要形态 `pending[]` 各项**保持绝对路径逐字**(与缺省同形——非 `slices_dir + 相对后缀`,此选型一经定下不得漂移);仅剔除 `units[]` / `codegraph_stats` / `excluded.by_reason` 明细。分页:diff_group 无按字节自动收页(那是 init `list_*` 家族的能力),故 `--offset/--limit` 是唯一杠杆,`effective_limit` = 本页实返条数 |
| resume | `.done` marker 存在的单元跳过物化;`failed` 单元(`.failed` marker)终态不重派 |
| gate | base ref 不存在等 gate 形失败 → 退出码 2 + stderr recipe(fanout_runner 同形透传,NEVER 进重派循环) |
| `--check` | run 目录自洽:slice 齐备、pending 路径绝对且在子树、marker 与枚举一致;违例退出 2 |

## `sdr_context.py` — 基线投影 + 外部仓受控检索

```
py sdr_context.py --repo <abs> --run-dir <abs> [--dimensions <inline-json|@path>]
                  [--baseline-budget-bytes B] [--external-budget-bytes B] [--read-root <abs>]...
                  [--approve-external <abs>]... [--summary] [--no-codegraph] [--no-external]
py sdr_context.py --check <run-dir>
```

| 项 | 契约 |
|---|---|
| 基线投影 | 从 `<repo>/AGENTS.md` 安全章节 + `docs/security-controls/*.md` + `<repo>/.mgh-sra/business_context.json`(若存在)按 6 维度确定性抽取,投影 `<run-dir>/baseline.md`;默认 ≤32KB,超限按「接口授权 > SQL > 输入校验 > 敏感数据」优先级截断,stdout `baseline_truncated:true` + 截断字节数 |
| 外部仓检索 | 解析存量设计中的**外部仓声明**(正则匹配「本地路径 + 同名分支约定」描述)→ 主进程内受控检索(同名分支 diff 文件清单 / 权限配置文件命中 / 新增路由在前端仓的出现计数)→ 结论物化 `<run-dir>/external/<repo-slug>/`(逐仓 ≤64KB,超限截断披露)。**白名单内容**:配置命中行(带行号)/ 路由出现计数 + 路径列表 / 外部 diff 文件清单。NEVER 内联前端源码正文 |
| 降级 | 声明缺失 / 路径不可达 / 非 git 目录 → `external_repos: []` + `external_skipped: "<原因>"`,流程继续不失败 |
| stdout | `{repo, run_dir, base, branch, baseline_path, baseline_bytes, effective_baseline_budget, baseline_truncated, baseline_truncated_bytes, sensitive_catalog, sensitive_catalog_source, sensitive_catalog_path, external_repos[], external_skipped[], pending_approval[]}`;`effective_baseline_budget` = 本 run 实际生效的基线预算(`--check` 按它判定尺寸);`sensitive_catalog_path` = 解析后目录物化文件的绝对只读路径(`<run-dir>/sensitive_catalog.json`,subagent 任务消息按它指认,NEVER 内嵌对象本体);`external_repos[]` 每项 `{path, slug, branch_sync_note, branch_fallback, summary_path, diff_files, config_hits, route_hits[], bytes, truncated}`(`route_hits[]` 每项 `{route, count}`)——`path` 供编排器/launcher 写哨兵 `read_roots[]`(**只收实际检索过的根**,NEVER 透传任意路径);`pending_approval[]` = 已声明但未获批的仓(零读取降级,待宿主会话用户拍板) |
| 敏感目录 | 解析优先级:① `<repo>/.mgh-sra/sensitive_catalog.json` 存在 → sibling import `sensitive_catalog` 复用解析 + 闭集校验(`sensitive_catalog_source:"project"`;非法 → 退出码 2 早停);② 不存在 → 加载 `sensitive_catalog.json.example` 默认模板(`sensitive_catalog_source:"default-template"`,与 sra/srr 的显式行为分歧) |
| 运行级状态 co-write | 本步同时**原子写出**两样(脚本副作用;失败退出码 2,**不静默**):哨兵 `<repo>/.mgh-sdr/.active`(`target` = 本脚本 stdout 的 Windows 原生 `repo`;`read_roots[]` = **实际检索过的根** ∪ 操作者 `--read-root`,最小化、NEVER 透传任意路径)与 `<run-dir>/run_config.json`(`{"no_codegraph": bool}`,取自 `--no-codegraph`;**起始态字段 NEVER 写入**)。二者同源同落点——都由「这一步实际发生了什么」决定 |
| `--approve-external <abs>` | 审批单命令闭环(可重复):检索开始前,用与 `read_roots_config.py --add` **同源**的校验 + 原子写(`_mutate`)把每个路径登记进 `<repo>/.mgh/read-roots.json`(存在 ∧ 是目录,违者退出码 2 零写入;已配置 → 幂等 no-op),登记成功的仓**当次即检索**并随 co-write 进哨兵 `read_roots[]`。**该 flag 仅在宿主会话获用户明示同意后由编排器传入**——脚本/编排器 SHALL NOT 自行批准;既有 `read_roots_config.py --add` + 重跑路径逐字可用(两入口同 schema 同写实现,NEVER 各维护一份) |
| 未知参数出口 | 未识别 flag 命中词根 `{approve, read, external, root}` → argparse 原生报错后追加可照抄的批准 + 重跑配方(脚本绝对路径自拼),退出码 2;非命中词根维持 argparse 原报错(在册 flag 永不进此路径,故 `--approve-external`/`--read-root` 不误伤) |
| `--summary` | stdout 投影视图(同参运行、`context.json`/哨兵/`run_config.json` 落盘**逐字不变**,缺省形态零回归):stdout = `{repo, run_dir, base, branch, baseline_path, baseline_bytes, baseline_truncated, sensitive_catalog_source, sensitive_catalog_path, external_repos[], external_skipped[], pending_approval[]}`,其中 `external_repos[]` 每项仅 `{path, slug, summary_path, diff_files, bytes, truncated}`(**剔除 `route_hits[]` 明细**)、并剔除 `sensitive_catalog` 大对象(`sensitive_catalog_path` 保留——路径转发不承载对象体)。完整记录仍在 `<run-dir>/context.json` |
| `--check` | run 目录自洽:baseline.md 存在且 ≤ 预算、external 结论文件齐备、`sensitive_catalog` 对象 shape 合法、物化文件 `sensitive_catalog.json` 存在且 shape 合法(增量字段:记录该路径之前的旧产物按无此字段判定)、`pending_approval[]` shape + skip 一致性;违例退出 2 |

## `render_sdr_report.py` — 汇总渲染

```
py render_sdr_report.py --run-dir <abs> --repo <abs> [--out-dir <dir>]
py render_sdr_report.py --check <run-dir>
```

| 项 | 契约 |
|---|---|
| 输入 | `<run-dir>/drafts/*.json`(`.done` 且 JSON 可解析者);`.failed` 单元不阻断,计入 `failed_units[]` |
| 去重 | findings 按 `{dimension, route, file}` 三元组去重合并(`line_hint` 取并集;`repro`/`fix_diff` 取首个携带者) |
| 报告 | `<repo>/mgh-sdr-<branch-safe>-<YYYYMMDD_HHMMSS>.html` **自包含单文件**(工具名固定 `mgh-sdr`;分支名文件系统安全命名;秒级本地时间戳;同名原子覆盖幂等;样式/脚本/数据全内嵌、零外部引用,file:// 浏览器直开)。简体中文、面向人:头部(branch/base/时间/检查维度/敏感目录来源/外部仓结论摘要 + 分组概览平实主句 + 默认折叠「分组诊断」明细)→ 章节一简报表(行=单元,severity/维度筛选,P-NN 页内锚点跳转)→ 章节二问题详述(P-NN · 维度 · route · severity;位置/risk/suggestion/control_ref + 可选「复现方式」行与「修改前/修改后」对比块,数据携带才展示)→ 章节三内嵌 SVG 分支调用链图(缩放平移;线性链不入)→ 无问题单元清单 → 诚实边界节(**≥6 条**,见下)+ 默认折叠「可读性自检」小节(仅当建议文件可解析)。确定性文案措辞按能力 `human-facing-output-discipline`(闭集取值单源 `human_face_vocab.py`,回归测试强制) |
| 数据文件 | `<run-dir>/sdr_report_data.json`:报告全量结构化数据(单元行 `rows[]`、`findings[]` 含 P-NN 与可选 `repro`/`fix_diff`、分支链图数据、`boundaries[]`、头部元信息含 `overview_details`、可选 `readability[]`),与报告内嵌数据块 **JSON 等价**——下游确定性消费以它为接口,新字段按「字段缺席 = 不适用」,NEVER 解析 HTML |
| 可读性评审消费 | 每次渲染原子写出 `<run-dir>/readability_text_bundle.json`(合并后全部问题记录的人类面文本);发现可解析的 `<run-dir>/readability_advisories.json` → 数据文件增 `readability[]` + 报告增默认折叠「可读性自检」小节 + stderr 计数;缺席/不可解析/空 → 省略 + stderr note,退出码不变(评审是尽力而为,缺席不影响 resume 收尾) |
| manifest | `<run-dir>/sdr_manifest.json`:`{branch, base, dimensions, sensitive_catalog_source, external_repos[], rows[], counts:{units, interfaces, standalone, findings, findings_by_severity, failed_units, excluded_files}, boundaries[], failed_units[]}`(`rows[]` 的 `entry`/`chain` 保持纯文本短形) |
| 写面 | NEVER 写 `openspec/`、NEVER 写 run 目录与报告/数据文件/文本束之外的目标仓文件 |
| `--check` | run 目录自洽:manifest 计数与 draft 实际一致、数据文件存在可解析且与报告内嵌数据块 JSON 等价、manifest `rows[]` 与数据文件一致、报告(若已渲染)为 `.html` 且含内嵌数据块与各章节锚点标记;另对模型人类面文本(`risk`/`suggestion`/`repro`/`fix_diff`)做闭集扫描(闭集 import `human_face_vocab.py` 单源)——命中仅 stderr 计数告警(字段名 + 词),**退出码不变**(模型措辞是软质量);确定性文案闭集合规由回归测试保障,不入 `--check` 面。违例退出 2 |

## 原生派发形态(opencode 面缺省)

fan-out 的双形态契约。**形态由环境画像的单一路径解析**(`env_profile.resolve`,
`consumer=sdr`):显式 `dispatch_mode` 永远优先;**opencode 安装面在画像缺失或 `auto` 时缺省
`native`**(不要求用户创建任何配置文件);claude 与其它安装面、以及 `consumer=generic` 的
其它命令解析为 `runner`。显式 `dispatch_mode:"runner"` 是 opencode 上唯一回到子进程形态的
开关;坏画像 fail-closed(退出码 2 + recipe)。opencode 面解析为 native 但安装树缺
`sdr-review-native` agent 或本文件对应的波次纪律 fragment 时,编排面在进入 fan-out 前退出码
2 + 重装/显式 runner recipe(共享检查 `env_profile.require_native_assets`),**NEVER 静默回退
子进程**。评审本体(六维检查面、draft schema、写作纪律、检查基线投影)与形态无关,两形态
同源,报告数据可跨形态对照。

| 项 | 契约 |
|---|---|
| 物化与自检 | 每轮 `py emit_native_plan.py --tier sdr --repo <abs> --base <ref> [--branch <ref>] --checkpoints <run-dir>/markers --inputs-dir <run-dir>/slices --profile <project>` 物化 `<run-dir>/native_plan.json` + `<run-dir>/slices/<unit_id>.task.md`,随后**同参** `--check`(退出码 2 → 重跑同参物化即修复,NEVER 消费过期计划)。**每轮重跑物化 = 重枚举**:pending 由磁盘标记重派生,有终态标记的单元自动出局 |
| 波次派发 | 编排器**同一条 assistant 消息**并发发出当前波全部子代理调用(agent `sdr-review-native`,`mode: subagent`,权限面与 fanout 孪生一致);每调用 `description` = 计划短号(逐字复制),任务体 = **单行令牌** `mgh-dispatch: plan=<plan_path> unit=<短号>`(计划引用取物化 stdout 逐字、短号自计划逐字);派发插件 `mgh_dispatch.ts` 的令牌展开钩子把它展开为该单元任务文件全文(展开结果与计划物化产物逐字一致),模型输出里因此零任务路径。展开钩子缺席的旧版安装回退 = 固定句 + `task_file` 绝对路径逐字透传。波次尺寸 = 计划 `wave_size`(并发与画像配额算术的较小者)。NEVER 跨波合并 / NEVER 自增并发 / NEVER 自撰任务文本 / NEVER 拼接改写路径 |
| 标记写者 | `.done`/`.failed` 的唯一写者是子代理自身(指令仅住在 `sdr-review-native` agent 定义:成功 touch `done_marker`;失败自写 `failed_marker`,内容 `{"unit_id", "reason"}`);计划物化、看门狗、编排器 NEVER 写任何单元标记(唯一例外 = 重派认领时删除旧 `.failed`,与派发器 `--retry-failed` 的认领即删同形——是删除不是写入)。子进程形态的模板行与派发器写标记行为零改动——两形态失败终态语义等价、写者各自单一 |
| 重派与等窗 | `.failed` 单元(原因非限流特征)至多重派一轮:删旧 `.failed` → 重物化加 `--retry-failed`(该单元回 pending)→ 派发一次;再失败接受缺口随报告披露(`failed_units[]`),NEVER 无限重派。上一波失败原因含限流特征(429/rate limit/quota)→ 按画像配额窗口等满一窗再查询/重派,等待事实入 run 过程记录 |
| 看门狗接线 | native 步**第一波前**以后台形态启动 `native_watchdog.py --run-dir <run-dir>`(根会话 = 宿主注入的 `OPENCODE_SESSION_ID`,零手工传参;阈值缺省);run 落定自退;编排器 NEVER 代替看门狗做会话中止。启动/重启/收尾纪律在 fragment `prompts/fragments/sdr-native-dispatch.md` |
| 步骤与恢复形态感知 | `list_sdr_steps.py`(原生形态):fanout 步入口 = 物化脚本 + 新增 `native_arc` 三相(materialize→waves→render)+ native 纪律变体,顶层增 `dispatch` 字段 `{form, source:"profile"|"host-default", profile_exists, host_face, consumer, profile_path, plan_present, native_agent, discipline_fragment}`;`resume_sdr_state.py`(原生形态):stdout 增同形 `dispatch` 字段,fanout `next_action` 按计划工件在场与否指到物化/派波次,纪律变体与清单同表(字节等价断言在原生形态同样成立)。进度仍纯磁盘重派生;runner 形态输出零新字段 |
| launcher 提示词 | `mgh_sdr_launch.py` 在 `sdr_context` 之后、spawn 宿主之前按 `--host` 显式覆盖宿主面解析形态:`opencode + native` → 第 3 步只展开原生动作(看门狗 → 物化 + `--check` → 同消息令牌派发 → 重枚举),不出现子进程派发调用;`opencode + runner` 与 claude 宿主 → 现行子进程提示词;claude 宿主 + 画像显式 native → 退出码 2 + recipe(**NEVER 静默降级**);坏画像与缺原生资产同样 spawn 前退出码 2 |
| 报告披露 | `render_sdr_report.py` 在「本次 run 的计划工件在场 ∧ 解析形态 native」时:数据文件 `meta.dispatch`(含 `source`/`host_face`/`profile_exists`/`evidence`)、manifest `dispatch`、报告头部「派发形态」行、诚实边界增一条(波次粒度止损 / 父会话单点 / 路径转述残余)。**没有环境画像文件的 opencode 缺省 run 同样披露**,`evidence` 串写明是画像显式选择还是宿主缺省。依据不成立 → 零新字段(既有 run 输出字节不变);坏画像在渲染侧降级为不披露(fail-closed 启动契约属派发面脚本,它们根本不会带着坏画像跑到渲染) |
| 三面分歧 | 原生形态仅 opencode 面且为其缺省;claude/dsh 面保留子进程形态(步骤清单/恢复输出无 `dispatch` 字段),各面壳以一行如实披露当前支持面(宿主机制差异白名单类,非镜像断裂),后续按宿主能力另行接入 |

版本矩阵:opencode 2.1.0 实机闸门(本机);企业 2.0.32 CAS 真仓对照 = 交接内网闸门(差异
回填 fanout 运行契约([`fanout/runtime.md`](../fanout/runtime.md))的版本矩阵)。

## draft JSON schema(fan-out 单元问题记录)

```json
{
  "unit": "<unit_id>",
  "findings": [
    {"dimension": "horizontal-authz", "severity": "high",
     "route": "/user/detail", "file": "UserController.java", "line_hint": "88-102",
     "line": 95,
     "risk": "简体中文风险描述(首句写现象)",
     "suggestion": "简体中文整改建议",
     "repro": "可选,复现方式(怎么调 + 传什么 + 看到什么)",
     "fix_diff": [{"before": "修改前代码(slice 原文逐字)", "after": "修改后形态"}],
     "control_ref": "命中的存量安全设计名或 null"}
  ]
}
```

- `dimension` 闭集默认 6 键:`vertical-authz` / `horizontal-authz` / `other-authz` /
  `sql-injection` / `sensitive-data` / `input-validation`。`--dimensions` 收窄**当前不下发**:
  该开关只在 `sdr_context` 做闭集校验(闭集 6 键 + kebab-case 自由文本扩展键;非法键 →
  退出码 2 早停,任何 LLM token 之前)并记录进 manifest `dimensions`,**不**进入评审单元的
  任务消息——评审仍按全部 6 维进行(与三面命令壳的披露同口径;真正把收窄接线进任务消息后,
  恢复「扩展检查项随消息透传」的表述并同步三面壳)。
- `severity` 四枚举:`high` / `medium` / `low` / `info`。
- `repro`/`fix_diff` 可选(人类面写作纪律由任务模板 `sdr-task.md` 承载,三面 agent 定义同步):
  能落到具体接口/方法调用才带 `repro`(怎么调 + 传什么 + 看到什么);改动只有一两处代码才带
  `fix_diff`(1–2 组,`before` 从 slice 逐字摘原文)。本 schema 之前产出的旧 draft 没有这些
  字段 = 报告省略对应展示,渲染与 `--check` 不失败(字段缺席 = 不适用)。
- 读者模拟评审的两个约定路径(不新增 CLI flag):`<run-dir>/readability_text_bundle.json`
  (渲染器每次渲染原子写出;评审唯一输入)与 `<run-dir>/readability_advisories.json`
  (评审建议,`{"v":1,"advisories":[{term,field,pnum,why}]}`;可解析时渲染并入数据文件
  `readability[]` 与报告「可读性自检」小节,缺席/不可解析 = 省略 + stderr note)。

## 消费方

- 形态解析(`env_profile.py`,唯一真相源):`consumer=sdr` 的解析结果(CLI stdout
  `host_face`/`consumer`/`form`/`source`)是命令壳 step 0、`list_sdr_steps.py`、
  `resume_sdr_state.py`、`render_sdr_report.py` 与 launcher 的共同依据;各消费者 NEVER 各自
  比较原始 `dispatch_mode`。
- `fanout_runner.py --tier sdr`(子进程形态;claude/dsh 缺省与 opencode 显式 `runner` 回退):
  `diff_group.py --materialize` 是 pending 唯一来源;模板
  `core/prompts/fragments/fanout/sdr-task.md`;agent `sdr-review-fanout`。
- 原生形态(opencode 面缺省):`emit_native_plan.py --tier sdr` 物化计划
  (同一 pending 源、同一模板),编排器按「原生派发形态」节的波次循环派 `sdr-review-native`
  子代理;子进程形态原样保留为显式回退。
- 编排器(opencode 壳缺省原生、claude/dsh 壳子进程):step 链 sdr_context → diff_group →
  fan-out(按解析形态)→ render →(尽力而为的读者模拟评审,一次,经
  `readability-review.md` 评审模板——与 `sdr-task.md` 同目录)→ 重渲染,每步后跑产出者
  `--check`,失败(退出码 2)回退重跑;评审失败只少「可读性自检」小节,NEVER 阻断 run、
  NEVER 影响 resume 收尾。
- `resume_sdr_state.py`:恢复入口(崩溃 / 压缩 / 新会话)——从运行目录磁盘产物重派生
  `step` / `next_action` / `dispatch`(形态)/ 纪律子集;`list_sdr_steps.py` 给任一步的确切
  调用。详见 [`resume-state.md`](resume-state.md)。
- launcher(`mgh_sdr_launch.py`):调 `sdr_context` 完成外部仓先期检索(主进程内),
  随后按宿主与画像解析派发形态并据此生成编排提示词(原生/回退同源),在 spawn 宿主编排器
  **之前**对已确认根再做一次项目配置复核并刷新哨兵(幂等,内容与 `sdr_context` 同源,是版本
  错配的第二道闸门),spawn 宿主 CLI,退出后移除哨兵。每次调用**新建**一个时间戳运行目录
  (无 `--resume` / `--run-dir`),故「重跑 launcher = 续跑」**不成立**;续跑须带着**同一个**
  运行目录经 `resume_sdr_state.py` 进行。
