# Stage I/O contracts — `/mgh-sdr` pipeline (`security-design-review`)

`/mgh-sdr`(需求分支代码 diff 的存量安全设计符合性复核)的确定性叶脚本 I/O 契约。三个
producer(`diff_group.py` / `sdr_context.py` / `render_sdr_report.py`)全部 Python ≥3.10
标准库、自定位(`sys.path.insert(0, dir-of-__file__)`)、任意 cwd 可 `py`、stdout=结构化
JSON / stderr=诊断严格分流、退出码 `0` 成功 · `1` 输入错误(文件缺失/JSON 畸形/gate 形
失败同 2 见下)· `2` 误用(argparse / 闭集校验 / `--check` 违例)。`--help` 即 CLI 契约面。

## Run 目录布局

```
<repo>/.mgh-sdr/
├── .active                          # 运行域哨兵 {domain:"mgh-sdr", target, out_roots[], read_roots[]?, v:1}
└── runs/<ts>/                       # 一次评审 run(ts = YYYYMMDD_HHMMSS 本地时区)
    ├── slices/                      # diff_group 物化的只读单元 slice(<unit_id>.slice.md)
    ├── drafts/                      # fan-out 单元 draft JSON(<unit_id>.json)+ .done/.failed 落 markers/
    ├── external/<repo-slug>/        # sdr_context 物化的外部仓结论文件(summary.json + hits.md)
    ├── baseline.md                  # 存量安全设计基线投影(≤32KB 默认,优先级截断)
    ├── markers/                     # <unit_id>.done / <unit_id>.failed(磁盘真相,resume 锚)
    └── sdr_manifest.json            # render 产出 counts + boundaries + failed_units[]
```

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
| `pending[]` | 每项 `{unit_id, input_path, draft_path, done_marker, failed_marker, kind, route, unit_bytes}`——**全字段 `Path.resolve()` 绝对**且在 repo 子树内,编排器逐字透传;`unit_id` 文件系统安全命名(`/ \ :` → `_`,NTFS ADS 教训)。**字段 shape 零变**(调用链是内部算法升级) |
| stdout | `{repo, base, branch, empty, codegraph, total, done, failed, counts:{interface,standalone}, pending[], offset, limit}`;`codegraph` = bool:本次是否走调用链分组;`empty:true` + `pending:[]` = 零变更 diff(退出码 0,编排器不 spawn) |
| resume | `.done` marker 存在的单元跳过物化;`failed` 单元(`.failed` marker)终态不重派 |
| gate | base ref 不存在等 gate 形失败 → 退出码 2 + stderr recipe(fanout_runner 同形透传,NEVER 进重派循环) |
| `--check` | run 目录自洽:slice 齐备、pending 路径绝对且在子树、marker 与枚举一致;违例退出 2 |

## `sdr_context.py` — 基线投影 + 外部仓受控检索

```
py sdr_context.py --repo <abs> --run-dir <abs> [--dimensions <inline-json|@path>]
                  [--baseline-budget-bytes B] [--external-budget-bytes B] [--read-root <abs>]...
py sdr_context.py --check <run-dir>
```

| 项 | 契约 |
|---|---|
| 基线投影 | 从 `<repo>/AGENTS.md` 安全章节 + `docs/security-controls/*.md` + `<repo>/.mgh-sra/business_context.json`(若存在)按 6 维度确定性抽取,投影 `<run-dir>/baseline.md`;默认 ≤32KB,超限按「接口授权 > SQL > 输入校验 > 敏感数据」优先级截断,stdout `baseline_truncated:true` + 截断字节数 |
| 外部仓检索 | 解析存量设计中的**外部仓声明**(正则匹配「本地路径 + 同名分支约定」描述)→ 主进程内受控检索(同名分支 diff 文件清单 / 权限配置文件命中 / 新增路由在前端仓的出现计数)→ 结论物化 `<run-dir>/external/<repo-slug>/`(逐仓 ≤64KB,超限截断披露)。**白名单内容**:配置命中行(带行号)/ 路由出现计数 + 路径列表 / 外部 diff 文件清单。NEVER 内联前端源码正文 |
| 降级 | 声明缺失 / 路径不可达 / 非 git 目录 → `external_repos: []` + `external_skipped: "<原因>"`,流程继续不失败 |
| stdout | `{repo, run_dir, baseline_path, baseline_bytes, baseline_truncated, sensitive_catalog, sensitive_catalog_source, external_repos[], external_skipped}`;`external_repos[]` 每项 `{path, branch_sync_note, summary_path}`——`path` 供编排器/launcher 写哨兵 `read_roots[]`(**只收实际检索过的根**,NEVER 透传任意路径) |
| 敏感目录 | 解析优先级:① `<repo>/.mgh-sra/sensitive_catalog.json` 存在 → sibling import `sensitive_catalog` 复用解析 + 闭集校验(`sensitive_catalog_source:"project"`;非法 → 退出码 2 早停);② 不存在 → 加载 `sensitive_catalog.json.example` 默认模板(`sensitive_catalog_source:"default-template"`,与 sra/srr 的显式行为分歧) |
| `--check` | run 目录自洽:baseline.md 存在且 ≤ 预算、external 结论文件齐备、`sensitive_catalog` 对象 shape 合法;违例退出 2 |

## `render_sdr_report.py` — 汇总渲染

```
py render_sdr_report.py --run-dir <abs> --repo <abs> [--out-dir <dir>]
py render_sdr_report.py --check <run-dir>
```

| 项 | 契约 |
|---|---|
| 输入 | `<run-dir>/drafts/*.json`(`.done` 且 JSON 可解析者);`.failed` 单元不阻断,计入 `failed_units[]` |
| 去重 | findings 按 `{dimension, route, file}` 三元组去重合并(`line_hint` 取并集) |
| 报告 | `<repo>/mgh-sdr-<branch-safe>-<YYYYMMDD_HHMMSS>.md`(工具名固定 `mgh-sdr`;分支名文件系统安全命名;秒级本地时间戳;同名原子覆盖幂等)。简体中文、面向人:头部(branch/base/时间/检查面/敏感目录来源/外部仓结论摘要)→ 按维度分组问题清单(severity/route/file/line_hint/风险/建议/control_ref)→ 无问题单元清单 → 诚实边界节(**≥6 条**,见下) |
| manifest | `<run-dir>/sdr_manifest.json`:`{branch, base, dimensions, sensitive_catalog_source, external_repos[], counts:{units, interfaces, standalone, findings_by_severity, failed_units}, boundaries[], failed_units[]}` |
| 写面 | NEVER 写 `openspec/`、NEVER 写 run 目录与报告文件之外的任何目标仓文件 |
| `--check` | run 目录自洽:manifest 计数与 draft 实际一致、报告(若已渲染)结构齐备;违例退出 2 |

## draft JSON schema(fan-out 单元问题记录)

```json
{
  "unit": "<unit_id>",
  "findings": [
    {"dimension": "horizontal-authz", "severity": "high",
     "route": "/user/detail", "file": "UserController.java", "line_hint": "88-102",
     "risk": "简体中文风险描述", "suggestion": "简体中文整改建议",
     "control_ref": "命中的存量安全设计名或 null"}
  ]
}
```

- `dimension` 闭集默认 6 键:`vertical-authz` / `horizontal-authz` / `other-authz` /
  `sql-injection` / `sensitive-data` / `input-validation`;`--dimensions` 可收窄,闭集键外
  按自由文本扩展检查项透传(无 control_ref 投影)。非法键 → 编排器退出码 2 早停(任何
  LLM token 之前)。
- `severity` 四枚举:`high` / `medium` / `low` / `info`。

## 消费方

- `fanout_runner.py --tier sdr`:`diff_group.py --materialize` 是 pending 唯一来源;
  模板 `core/prompts/fragments/fanout/sdr-task.md`;agent `sdr-review-fanout`。
- 编排器(双壳):step 链 sdr_context → diff_group → fanout_runner → render,每步后跑
  产出者 `--check`,失败(退出码 2)回退重跑。
- launcher(`mgh_sdr_launch.py`):调 `sdr_context` 完成外部仓先期检索(主进程内),
  写哨兵(含 `read_roots[]`),spawn 宿主 CLI。
