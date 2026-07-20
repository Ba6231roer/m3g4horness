# Tasks — add-mgh-sensitive-catalog

> 实现顺序 = 依赖序。每步后跑相关 `--check` / 单测;最后全量回归 + 契约 lint + 纯净性 lint。
> 铁律:R2(零依赖)、R5(CLI 契约 = `--help`、`--check`、双端镜像)、R3(文档简练)、R5.10(分发物纯净)。
> 向后兼容硬门:无 `--sensitive-catalog` 路径行为逐字等价今天(`sensitive_catalog: null`)。

## 1. 新增确定性脚本 `core/scripts/sensitive_catalog.py`(闭集 category + mask 枚举 + parse/validate/render)

- [x] 1.1 实现模块级闭集常量:`CATEGORIES`(10 类 identity-doc/biometric/health/financial/location/
      communication/device/vehicle/general-pii/legal + 简体 label)、`MASK_LEVELS = ("full","partial")`、
      PIPL/GB-T 35273 `DEFAULT_TEMPLATE`(37 项,按 category 分组,每项 `{label,mask,rule}`)。单一真相源。
- [x] 1.2 实现 CLI(`argparse`,互斥 mode 组):`--list`(枚举 10 category + 印 37 项默认模板 → stdout JSON)、
      `--parse <inline-json|@path|->`(解析+闭集校验+渲染解析后对象)、`--check <...>`(仅校验 → stdout
      `{"check":"sensitive-catalog","ok":bool,"violations":[...]}`)、`--help`。
- [x] 1.3 闭集校验:每项 key 须为 `<category>/<field-type>`,category 在闭集 10 类内,`mask` ∈ {full,partial},
      `label` 非空字符串,`rule` 字符串或 null。违例 → 退出码 2 + 可操作 stderr(点名违例项 + 允许集);
      JSON 畸形/文件缺失 → 退出码 1。`version` 顶层 int 必填。stdout=JSON / stderr=诊断 严格分流(R5.3b)。
- [x] 1.4 输入判别 + 自定位:值以 `{` 起首 = inline JSON;`-` = stdin;否则 = 文件路径(前导 `@` 可选剥离,
      `encoding="utf-8"` 读,缺失/不可读 exit 1)。`sys.path.insert(0, dir-of-__file__)` 自定位(R5.3a);
      任意 cwd 可直接 `py`;零副作用(`--parse`/`--check`/`--list` 不写盘)。
- [x] 1.5 渲染解析后对象:`{version, source, categories[](去重+闭集序排序), items[](扁平、闭集 category 序
      排序,每项含 key/category/label/mask/rule), counts{items, full, partial, categories}, directive}`。
      directive = 确定性简体中文策略摘要(类别数 + 字段数 + 全/部分屏蔽计数 + 「须按 mask 规则在 at-rest/
      in-transit/log/response 脱敏,未脱敏记缺口」+ 「无目录时按现行 6 facet」)。
- [x] 1.6 `py core/scripts/sensitive_catalog.py --help` 确认四个 flag 都在(契约面);`--list` 输出 10 category +
      37 项;`--check` 对合法/非法样本分别 exit 0 / 2。纯标准库(无第三方 import)。

## 2. 适配器接入 `--sensitive-catalog`(sra a1 + srr r1)

- [x] 2.1 `core/scripts/prepare_augment.py`:`argparse` 加 `--sensitive-catalog <inline-json|@path|->`;
      `_emit_change_context` 里 `import sensitive_catalog`(sibling)解析+校验,失败 exit 1(读/解析)/
      exit 2(闭集违例),任何 LLM 之前;把 resolved `sensitive_catalog`(对象或 `null`)作为顶层字段写入
      `change_context`。无 `--sensitive-catalog` → `sensitive_catalog: null`。
- [x] 2.2 `core/scripts/ingest_requirements.py`:同样加 `--sensitive-catalog`(经已 import 的 `_sra` 间接
      复用解析,或直接 sibling import);embed `sensitive_catalog` 进其 `change_context`(与 sra 同 shape)。
      无 flag → `null`。
- [x] 2.3 扩两者的 `--check`:`change_context.sensitive_catalog`(若非 null)shape 校验(items[] 各项
      category 闭集、mask 枚举、key `<category>/<field-type>` 合法、label 非空、counts 自洽);违例 exit 2。
- [x] 2.4 更新两脚本顶部 docstring 的 CLI contract 段(加 `--sensitive-catalog` 行)+ stderr 进度行(加
      catalog 状态:`catalog=none|37items(10cat)`)。输入判别语义与 `--focus` 逐字一致(inline/`-`/path/`@`)。

## 3. subagent 提示词加「敏感数据目录」叠加覆盖层(srr 零新增提示词复用)

- [x] 3.1 `core/prompts/stages/sra-augment.md`:加一段叠加覆盖层——「传入非空 `sensitive_catalog` 时,SHALL
      对 `items[]` 每个字段类型逐项查脱敏缺口(据 mask+rule 判 at-rest/in-transit/log/response 是否按规则脱敏);
      缺口 MUST 锚定具体 requirement/接口/字段并标 `catalog_key`;据三信号关联 `category: data-masking` 控制
      (advisory recommended_control);`--focus` 覆盖层叠加(目录仅当 sensitive-data 在范围内时生效);
      `sensitive_catalog: null` = 仅现行 6 facet」。规定性措辞(R5.5),非「may」。
- [x] 3.2 `core/prompts/stages/sra-clarify.md`:同形覆盖层——「传入目录时,SHALL 对目录字段类型相关的业务事实
      发澄清(如某字段归属/是否流转);`null` = 现行行为」。
- [x] 3.3 确认两份提示词是 sra/srr 共享(single source);srr 命令壳「Middle engine reused verbatim」不变;
      目录覆盖层与既有 `--focus` 覆盖层、codegraph 覆盖层共存(不互斥)。

## 4. mgh-init 脱敏控制关联(sra 消费方,零改 mgh-init)

- [x] 4.1 确认 `prepare_augment.py::DIMENSIONS_BY_CATEGORY["data-masking"] == ["sensitive-data"]` 已存在
      (即 `category: data-masking` 控制已标 sensitive-data 维度);`candidate_controls[]` 已携带 data-masking
      控制条目。**不改** `discover_controls`/`validate_inventory`/inventory schema(R5.10 / 消费方纪律)。
- [x] 4.2 在 `sra-augment.md` 覆盖层(3.1)内明确:目录驱动的脱敏缺口经既有三信号匹配(`security-augmentation`
      「Three-signal semantic matching」)命中 `data-masking` 控制时附 `recommended_control` + `evidence` +
      「复用勿重造」;无命中仍产缺口(无控制锚点),MUST NOT 硬丢。
- [x] 4.3 (验收)mgh-init 侧文件零改动:对比 `releases/**/mgh-init*`、`core/scripts/discover_controls*`、
      `core/contracts/init/*` 变更前后逐字一致。

## 5. PIPL/GB-T 35273 默认模板 + install `.example`

- [x] 5.1 `sensitive_catalog.py::DEFAULT_TEMPLATE` 印全 37 项(承 task.260716.md §三,按 10 category 分组,
      mask/rule 齐);带 `version` + 来源注释(provenance)。`--list` 验证输出含全部 37 项。
- [x] 5.2 `install.sh`:镜像后落地 `.example` 模板到目标项目(如 `.mgh-sra/sensitive_catalog.json.example`);
      **不**自动 `cp` 为生效 `sensitive_catalog.json`(保 D9 向后兼容硬门)。install 自检 fail-soft 校验模板存在。
- [x] 5.3 (验收)装有 `.example` 但无生效目录时,默认 sra/srr 行为逐字等价引入目录前(`sensitive_catalog: null`)。

## 6. 契约文档

- [x] 6.1 新增 `core/contracts/sensitive-catalog.md`:记 `sensitive_catalog.json` schema(顶层 `version`/`items`;
      key=`<category>/<field-type>`;entry=`label`/`mask`/`rule`)+ 闭集 category(10)+ mask 枚举 + 解析后
      `change_context.sensitive_catalog` 字段语义 + directive 语义 + mgh-init 关联语义。简练、面向 AI(R3)。
- [x] 6.2 `core/contracts/sra/augmentation.md`:增 `sensitive_catalog` 字段说明(与 `focus` 字段并列)。
- [x] 6.3 `core/contracts/srr/intake-report.md`:增 `sensitive_catalog` 字段说明(与 sra 同 shape)。
- [x] 6.4 (可选)`core/prompts/fragments/security-dimensions.md`:在 sensitive-data 行补一句指向「项目级
      `sensitive_catalog.json` 可扩展识别字段类型(见 sensitive-catalog 能力)」,6 facet 闭集**不动**(承 D3/D5)。

## 7. 四命令壳加 `--sensitive-catalog`(claude/opencode × sra/srr)

- [x] 7.1 `releases/claude-code/commands/mgh-sra.md`:参数表 + flag 表加 `--sensitive-catalog <inline-json|@path|->`;
      编排流 a1 步加「读 `change_context.sensitive_catalog`(对象含 directive+items[])逐字透传 a2/a3」;
      bash 示例加 `--sensitive-catalog @.mgh-sra/sensitive_catalog.json` 用法;「Always disclose」加一条目录覆盖范围。
      `--help`/无参早停不变。
- [x] 7.2 `releases/opencode/command/mgh-sra.md`:逐字镜像 7.1(双端对等,R5.7)。
- [x] 7.3 `releases/claude-code/commands/mgh-srr.md`:同 7.1(r1 步透传;报告头注目录覆盖;manifest boundaries
      加目录披露)。
- [x] 7.4 `releases/opencode/command/mgh-srr.md`:逐字镜像 7.3。
- [x] 7.5 四壳 bash 块里 `sensitive_catalog.py --flag` 与 `prepare_augment/ingest_requirements
      --sensitive-catalog` 须与脚本 `--help` 逐字一致(R5.1,由 `check_contracts.py` 自动断言)。

## 8. 报告 / manifest 披露目录

- [x] 8.1 `sra_manifest.json` / `srr_manifest.json`:增 `sensitive_catalog`(`counts{items,full,partial,
      categories}` + `source`;`null` = 未用目录)。`boundaries[]` 增一条「据目录逐项查脱敏,目录外仅 6 facet」
      (仅当非 null)。
- [x] 8.2 `security_review_report.md`(srr render)+ sra draft 头注:目录覆盖范围(字段数 + 类别);无目录不注。

## 9. 测试 + 契约/纯净性 lint + 版本号 + 文档

- [x] 9.1 新增 `tests/test_sensitive_catalog.py`:闭集 category 校验(未知 category exit 2)、mask 枚举(非法
      exit 2)、key/label shape、`--list` 含 37 项、`--check` ok/违例、`--parse` directive 确定性(同输入字节一致)、
      零依赖 AST 扫描、任意 cwd 可跑。
- [x] 9.2 扩 `tests/test_sra_prepare.py` + `tests/test_srr_ingest.py`:`--sensitive-catalog` 嵌入 `change_context`
      (对象 vs null)、`--check` 校验 sensitive_catalog 字段(合法/违例)、**无 flag 路径逐字等价今天**(回归硬门)。
- [x] 9.3 扩 `tests/test_zero_deps.py`:含 `sensitive_catalog.py` 的 AST 扫描断言(纯标准库)。
- [x] 9.4 `tools/check_contracts.py`:四壳新增 `--sensitive-catalog` flag 自动纳入 lint(已机制覆盖,确认通过)。
- [x] 9.5 `tools/check_distributed_md_purity.py`:四壳 + 新增契约文档过纯净性(R5.10,无研发态悬空引用 R5.x/FDn/变更夹名)。
- [x] 9.6 bump 受影响 `.md`/`.py` 版本号(四壳 + 两脚本 + 两 stage 提示词 + 新契约 + 目录);更新 `CHANGELOG.md`。
- [x] 9.7 更新 `docs/mgh-sra-工作流程详解.md`(§6 名词 + §8 参数,加 `--sensitive-catalog`;承 R3 简练)。
- [x] 9.8 全量回归:`py tests/test_sensitive_catalog.py` + `py tests/test_sra_prepare.py` + `py tests/test_srr_ingest.py`
      + `py tests/test_zero_deps.py` + `py tools/check_contracts.py` + `py tools/check_distributed_md_purity.py` 全绿。
