# Tasks — add-mgh-dimension-focus

> 实现顺序 = 依赖序。每步后跑相关 `--check` / 单测;最后全量回归 + 契约 lint + 纯净性 lint。
> 铁律:R2(零依赖)、R5(CLI 契约 = `--help`、`--check`、双端镜像)、R3(文档简练)、R5.10(分发物纯净)。
> 向后兼容硬门:无 `--focus` 路径行为逐字等价今天。

## 1. 新增确定性脚本 `core/scripts/focus_scope.py`(闭集 registry + parse/validate/render)

- [x] 1.1 实现 `focus_scope.py`:嵌入闭集 registry(9 维度 key+简体 label;sensitive-data 6 facet、
      injection 7 facet 的 key+label;其余 7 维度 facet 为空)。registry 为模块级常量,单一真相源。
- [x] 1.2 实现 CLI(`argparse`):`--list`(枚举 registry → stdout JSON)、`--parse <inline-json|path>`(解析+
      闭集校验+渲染 → stdout 输出 `{dimensions[], facets{}, directive}` 或 `null`)、`--render <inline-json|path>`
      (渲染指令别名)、`--check <inline-json|path>`(仅校验 → stdout `{"check":"focus-scope","ok":bool,
      "violations":[...]}`)、`--help`。
- [x] 1.3 闭集校验:未知维度/facet → 退出码 2 + 可操作 stderr(点名违例键 + 列允许集);facet 必须属于
      `dimensions` 且该维度有 facet;空 `dimensions` → 退出码 2;JSON 畸形/文件缺失 → 退出码 1。
      `dimensions:"*"`/缺省 = 全 9 维度。stdout=JSON / stderr=诊断 严格分流(R5.3b)。
- [x] 1.4 渲染 directive:确定性简体中文(按 registry 顺序、非输入顺序);全 9 → resolved `null`(不渲染)。
      `sys.path.insert(0, dir-of-__file__)` 自定位;输入判别:值以 `{` 起首=inline JSON,否则=文件路径(前导 `@` 可选剥离,`encoding="utf-8"` 读,缺失/不可读 exit 1);零副作用(R5.3a)。
- [x] 1.5 `py core/scripts/focus_scope.py --help` 确认四个 flag 都在(契约面);`--list` 输出 9 维度。

## 2. 适配器接入 `--focus`(sra a1 + srr r1)

- [x] 2.1 `core/scripts/prepare_augment.py`:`argparse` 加 `--focus <inline-json|path>`;`_emit_change_context`
      里 `import focus_scope`(sibling)解析+校验,失败 exit 2(任何 LLM 之前);把 resolved `focus`(对象或
      `null`)作为顶层字段写入 `change_context`。无 `--focus` → `focus: null`。
- [x] 2.2 `core/scripts/ingest_requirements.py`:同样加 `--focus`(经 `import focus_scope` 或经已 import 的
      `_sra` 间接);embed `focus` 进其 `change_context`(与 sra 同 shape)。无 `--focus` → `focus: null`。
- [x] 2.3 扩两者的 `--check`:`change_context.focus`(若非 null)shape 校验(dimensions 闭集、facets 维度
      匹配且闭集);违例 exit 2。
- [x] 2.4 更新两脚本顶部 docstring 的 CLI contract 段(加 `--focus` 行)+ stderr 进度行(加 focus 状态)。

## 3. subagent 提示词加「维度聚焦」覆盖层(srr 零新增提示词复用)

- [x] 3.1 `core/prompts/stages/sra-augment.md`:Input 段 + Task 1 段加一小段——「编排器传入 `focus.directive`
      时,SHALL 只对列出的维度(及维度内列出的 facet)查缺口;范围外 SHALL 不产缺口;范围内缺口的锚定/
      丢弃/三信号/codegraph 规则不变。无 directive = 全 9 维度」。规定性措辞(R5.5),非「may」。
- [x] 3.2 `core/prompts/stages/sra-clarify.md`:同形覆盖层——「传入 directive 时,SHALL 只对列出维度发澄清;
      范围外 SHALL 不发;无 directive = 全 9 维度」。
- [x] 3.3 确认两份提示词是 sra/srr 共享(single source);srr 命令壳「Middle engine reused verbatim」不变。

## 4. 维度目录标注 facet 键(使 focus spec 可发现、subagent 可映射)

- [x] 4.1 `core/prompts/fragments/security-dimensions.md`:在 sensitive-data 行标注 facet 键
      (id-card/bank-card/phone/email/password/token)、injection 行标注 facet 键
      (sqli/xss/command-injection/path-traversal/ssrf/deserialization/xxe),与 registry 锁步。
      保留溯源注释(R1 不涉,本仓原创文件);正文简练(R3)。

## 5. 四命令壳加 `--focus`(claude/opencode × sra/srr)

- [x] 5.1 `releases/claude-code/commands/mgh-sra.md`:参数表 + flag 表加 `--focus <inline-json|path>`;
      编排流 a1 步加「读 `change_context.focus.directive` 逐字透传 a2/a3」;bash 示例加 `--focus` 用法;
      「Always disclose」加一条聚焦范围。`--help`/无参早停不变。
- [x] 5.2 `releases/opencode/command/mgh-sra.md`:逐字镜像 5.1(双端对等,R5.7)。
- [x] 5.3 `releases/claude-code/commands/mgh-srr.md`:同 5.1(r1 步透传 directive;报告头注聚焦维度;
      manifest boundaries 加聚焦披露)。
- [x] 5.4 `releases/opencode/command/mgh-srr.md`:逐字镜像 5.3。
- [x] 5.5 四壳 bash 块里出现的 `focus_scope.py --flag` 与 `prepare_augment/ingest_requirements --focus` 须与
      脚本 `--help` 逐字一致(R5.1,由 `check_contracts.py` 自动断言)。

## 6. 契约文档记 `focus` 字段 + 指令语义

- [x] 6.1 `core/contracts/sra/augmentation.md`:`change_context.json` 表加 `focus` 行(对象或 null;null=全9);
      新增一小段「维度聚焦」(directive 语义、收窄规则、向后兼容)。`--check` 段加 focus 校验。
- [x] 6.2 `core/contracts/srr/intake-report.md`:delta 表加 `focus`(与 sra 同 shape);报告/manifest shape 加
      `focus` 字段 + 聚焦边界;`--check` 段加 focus 校验。

## 7. manifest/报告披露聚焦(sra 编排器产出 + srr render)

- [x] 7.1 `sra_manifest.json`(编排器产):加 `focus`(维度列表或 null);`focus` 非 null 时 `boundaries[]`
      加「本次仅扫描聚焦维度,范围外未覆盖」。
- [x] 7.2 `core/scripts/render_report.py`(srr r2):读各 draft 所属 `change_context.focus`(或经入参);
      报告头注聚焦维度;`srr_manifest.json` 加 `focus` + 聚焦 boundary。`--check` 校验之。
- [x] 7.3 (注:sra manifest 由编排器写,非脚本——在 mgh-sra 壳第7步文案里钉死字段;render_report 是 srr 脚本。)

## 8. 测试(R5.8 回归)

- [x] 8.1 新增 `tests/test_focus_scope.py`:registry 闭集(`--list` 9 维度 + facet);`--parse` 合法子集/
      `*`/缺省;闭集违例(未知维度/facet、facet 属非 facet 维度、facet 维度不在 dimensions、空 dimensions)
      均 exit 2 + stderr 点名;JSON 畸形 exit 1;directive 确定性(同输入字节一致)+ 简体中文含维度/facet label;
      全 9 → null;inline(以 `{` 起首)/裸路径/`@path` 三种输入形态判别;stdout/stderr 分流;任意 cwd 可跑。
- [x] 8.2 扩 `tests/test_sra_prepare.py`:`--focus` 嵌入 `focus` 字段;无 `--focus` → `focus: null`;
      非法 `--focus` exit 2 不产 change_context;`--check` 拒畸形 focus 字段。
- [x] 8.3 扩 `tests/test_srr_ingest.py`:同 8.2(ingest 侧);确认 focus 字段 shape 与 sra 一致(复用同模块)。
- [x] 8.4 扩 `tests/test_srr_report.py`:聚焦运行 → 报告头注 + manifest `focus` + boundary;无 focus → 无额外行。
- [x] 8.5 断言测试:registry 9 维度键 == `security-dimensions.md` 维度键列(防漂移)。
- [x] 8.6 既有 `test_sra_prepare.py`/`test_srr_ingest.py`/`test_srr_report.py`/`test_*_codegraph_parity.py`
      无 `--focus` 路径全绿(向后兼容硬门)。

## 9. 契约 lint + 分发纯净性 + 版本号 + 文档

- [x] 9.1 `py tools/check_contracts.py`:四壳所有 `--focus`/`focus_scope --flag` 均在脚本 `--help` 声明(R5.1)。
      (注:`check_contracts.py::DEFAULT_SHELLS` 已含四壳,无需改其源;若新增 `focus_scope.py` 调用出现于壳
      bash 块,自动被 lint。)
- [x] 9.2 `py tools/check_distributed_purity.py` + `tests/test_distributed_md_purity.py`:四壳/目录/契约文档无
      研发态悬空引用(R5.10);`--focus` 是操作性内容,保留。
- [x] 9.3 `py tests/test_zero_deps.py`:`focus_scope.py` 零第三方 import(R2,AST 扫描集含新脚本)。
- [x] 9.4 bump 受影响分发物版本号(四壳 frontmatter/正文版本、两提示词、两适配器 docstring、focus_scope、
      目录、两契约文档);承 R5.8。
- [x] 9.5 更新 `docs/mgh-sra-工作流程详解.md`:§6 名词表加「维度聚焦 / focus」一行;§8 参数速查加 `--focus`
      + 示例(只查越权;敏感数据只查身份证/银行卡)。承 R3 简练。
- [x] 9.6 更新 `README.md` 若列 sra/srr 参数(加 `--focus`,若有)。

## 10. 全量回归 + 诚实边界

- [x] 10.1 `py tests/test_deterministic.py` + 全 `tests/test_*.py` 绿。
- [x] 10.2 手工 smoke:带/不带 `--focus` 各跑一次 sra + srr 样例;确认聚焦运行 manifest/报告披露范围、
      范围外维度无缺口;无 `--focus` 行为等价今天。
- [x] 10.3 总结写明五条诚实边界 + 新增聚焦披露(范围外未覆盖);声明产物为 LLM 候选需复核。

## 11. README 完整示例(供用户复制编辑;编码完成后做)

- [x] 11.1 在 `README.md` 的 `/mgh-sra`、`/mgh-srr` 用法附近新增「维度聚焦(`--focus`)」小节,含:
      (a) 一句说明:默认扫全 9 维度,`--focus` 收窄到子集 + 维度内 facet;不传 = 全 9。
      (b) **完整可枚举值清单**(用户直接复制再删改):

      ```json
      {
        "dimensions": [
          "sensitive-data", "injection", "horizontal-authz", "vertical-authz",
          "authentication", "integrity", "audit", "rate-limiting", "secrets"
        ],
        "facets": {
          "sensitive-data": ["id-card", "bank-card", "phone", "email", "password", "token"],
          "injection":      ["sqli", "xss", "command-injection", "path-traversal", "ssrf", "deserialization", "xxe"]
        }
      }
      ```

      注:上例 = 全集(等价不传 `--focus`)。收窄 = 删掉不要的维度;对 `sensitive-data`/`injection`
      再删掉不要的 facet;其余 7 维度无 facet(整维收窄)。
      (c) 三种输入形态:`--focus '{...}'`(inline JSON,值以 `{` 起首)、`--focus config/focus.json`
      (裸路径)、`--focus @config/focus.json`(`@` 可选)。
      (d) 典型收窄示例:只查越权;敏感数据只查身份证 + 银行卡。
      过 `check_distributed_md_purity`(R5.10:只含操作性内容,无研发态悬空引用);bump README 版本/日期。
