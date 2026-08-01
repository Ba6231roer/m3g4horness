# Tasks — improve-mgh-init-deterministic-step-manifest

> 依赖顺序:L1 叶脚本(核心,纯 additive)→ 契约(镜像 stdout)→ 双壳 recipe(引用脚本)→
> 测试(含跨脚本一致性)→ 版本号 + lint + 回归 + validate。每条可独立验收。
> 遵守 AGENTS.md R1–R5(零依赖、文档简练、复用导入、R5.1 CLI lint、R5.8 回归 + bump 版本号)。
> **不动既有 CLI flag / 磁盘 schema / stage 提示词**(纯 additive 新脚本 + 新契约 + 壳 +1 行 recipe)。
> 设计决策见 `design.md`(D1–D6)。范围:init-only(见 D5)。

## 1. L1 — `core/scripts/list_steps.py`(新叶脚本,R2 零依赖、R5.3 自包含)

- [x] 1.1 骨架:`argparse`(`--target <dir>` 默认 `.`、`--step <id>` 单步、`--help` 即 CLI 契约 R5.1);
      `sys.path.insert(0, dir-of-__file__)` 自定位;utf-8;任意 cwd 可 `py`;`py`/`python` 直执行无需 `python -c`;
      退出码 `0/1/2`;stdout=结构化 JSON、stderr=诊断/进度(R5.3b 严格分流)。
- [x] 1.2 **静态 step→IO 表**(数据驱动,一处定义):step id 集合 = `resume_state.py` 的 step 枚举
      (`not-started|discover|survey|scout|resolve|t1|t2|t3|assemble|t4|merge|done`);每步记录
      `{step, kind∈bash|subagent, script_name(相对 core/scripts/), cli_args(规范化), input{artifact, shape},
      output{artifact, shape, path_pattern}}`。`script_name` 经 `Path(__file__).resolve().parent / script_name`
      派生为**绝对** `script_abs`(D2);`invocation` = `py <script_abs> <cli_args>`(逐字可执行)。
- [x] 1.3 **零磁盘前置**(D3):不读 `run_config.json`、不扫 `.mgh-init/`、不依赖任何 run 态产物;
      pre-run 可查;`--target` 仅作未来扩展锚点(本版可不计入 manifest 内容,但接受且不因不存在而报错)。
- [x] 1.4 默认输出全量紧凑 `steps[]` JSON;`--step <id>` → 仅该 step(单步确切调用行);未知 `--step` →
      exit 2 + stderr 可操作报错(闭集拒歧义,R5.3b);不静默截断。
- [x] 1.5 **不 import** codegraph / vvaharness / 任何第三方;不 `subprocess` 调脚本(只 emit 调用行文本,
      不执行);零 AST 第三方 import(R2 自检绿)。

## 2. 契约 `core/contracts/init/step-manifest.md`(新,人读单一真相源)

- [x] 2.1 逐 step 表格:`step | kind | script(相对 `core/scripts/`) | 输入产物 + shape | 产物路径 + shape`;
      与 `list_steps.py` stdout `steps[]` **逐字镜像**(D4)。
- [x] 2.2 头部声明:① 宿主前缀经 `__file__` 派生、双壳无手镜像;② 零磁盘前置、pre-run 可查;
      ③ 与 `resume_state.py` 互补分工;④ pattern 可对称后置移植到其它 mgh-*(锚点,不落实现,D5)。
- [x] 2.3 与既有 `clusters.md`/`scout-enumeration.md`/`rule-jobs.md`/`resume-state.md`/`unit-inputs.md`
      并列、同风格(简练、面向 AI、表格优先,承 R3)。

## 3. 双壳 recipe(`releases/{claude-code/commands,opencode/command}/mgh-init.md`,**逐字镜像**)

- [x] 3.1 Orchestrator discipline 段「implementation-intention」recipe 列表 +1 行:「确切每步脚本路径 /
      调用行 / IO shape → `list_steps.py` stdout `steps[]`(或 `--step <id>` 单步);宿主前缀自动派生,
      **NEVER** 猜 `scripts/` vs `mgh-core/scripts`、**NEVER** 漏宿主前缀;`--resume`/压缩后与 `resume_state.py`
      配套(后者给当前 step)」。
- [x] 3.2 Re-entrancy & compaction 段:压缩后首步 `resume_state.py` 取 `step` → 据以 `list_steps.py --step <id>`
      取确切调用行(配套语义,1 行)。
- [x] 3.3 既有 `Deterministic invocation` 示例块 + inline flow + `Stage → component map` **保留不动**(manifest
      非替代,是确认/兜底互补层);manifest 表**不**内联进提示词(护 R5.6)。
- [x] 3.4 双壳引用 `list_steps.py --step` → `tools/check_contracts.py` 按既有机制断言 `--help` 存在(R5.1)。

## 4. 回归测试 `tests/test_list_steps.py`(R5.8)

- [x] 4.1 **前缀派生**:在 dev 位置(`core/scripts/list_steps.py`)跑,断言每步 `script_abs` =
      `Path(core/scripts).resolve() / <name>.py`(绝对、同族);断言指向的脚本名在 `core/scripts/` 实际存在
      (防幽灵脚本)。
- [x] 4.2 **step id 一致性**(D4 跨脚本防漂移):断言 `list_steps.py` 的 `steps[].step` 集合 == `resume_state.py`
      的 step 枚举(或 documented 超集)——可 `import` resume_state 的枚举常量或解析其 `--help`/stdout。
- [x] 4.3 **pre-run 可查**(D3):在空临时目录(无 `.mgh-init/`)跑 `list_steps.py` → 退出码 0、完整 manifest,
      不 exit 2。
- [x] 4.4 **`--step` 单步 + 闭集**:`--step t1` 仅返 t1;`--step bogus` → exit 2 + stderr;默认全量。
- [x] 4.5 **stdout/stderr 分流 + JSON 合法**:stdout 可 `json.loads`;stderr 不混入 stdout。
- [x] 4.6 **零依赖 AST 扫描**:对 `list_steps.py` 做 AST 扫描,无非标准库 import(并入既有零依赖自检)。
- [x] 4.7 `py tests/test_deterministic.py`(及 `test_init_runtime.py`/`test_opencode_hook_parity.py`)不退化。

## 5. install 镜像 + 稳定性守卫 + 收尾(R5)

- [x] 5.1 `install.sh` 镜像 `list_steps.py` 到 `.claude/mgh-core/scripts/` 与 `.opencode/mgh-core/scripts/`
      (既有镜像机制);自检 fail-soft 校验同目录共存(承 R5.8)。
- [x] 5.2 `py tools/check_contracts.py` 通过(新脚本 `--step` flag 经 `--help` 断言;双壳镜像不退化)。
- [x] 5.3 `py tools/check_distributed_purity.py` 通过(新契约仅操作性内容,无 dev-only 溯源 / 研发铁律编号 /
      内部 issue 指针 / FDn;承 R5.10)。
- [x] 5.4 bump `VERSION`(当前 0.1.16 → 0.1.17)+ `install.sh` 自检 fail-soft 通过。
- [x] 5.5 `openspec validate improve-mgh-init-deterministic-step-manifest` 绿;端到端 dry sanity
      (claude/opencode 两 install 形态各跑 `list_steps.py` 验前缀 + step 集一致性)。
