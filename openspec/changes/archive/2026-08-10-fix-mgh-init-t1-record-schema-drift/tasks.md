# fix-mgh-init-t1-record-schema-drift — Tasks

## 1. Validator 脚本:`core/scripts/validate_t1_records.py`

- [x] 1.1 新建 `core/scripts/validate_t1_records.py`(零依赖,承 R5.3a `sys.path` 自定位 + 兄弟
      `from init_tier import INIT_CATEGORIES, KIND`):docstring 镜像 `validate_inventory.py`(`--help` 即契约面,
      承 R5.1);`--checkpoints <dir>` 入参。
- [x] 1.2 抽 BOM helper `_strip_bom_bytes(raw: bytes) -> tuple[bytes, bool]`(去前导 `EF BB BF`,返回
      (去 BOM 后字节, 是否曾带 BOM));`--check` 与 `--strip-bom` 共用之(行为对齐)。
- [x] 1.3 `--check`(默认,只读):每条 `*.json` → 内存剥 BOM 再 `json.loads`(BOM 文件不误判 shape 错);
      断言 top-level dict + 根级 `cluster_id`/`name`/`category`∈`INIT_CATEGORIES`/`kind`∈vvah 6-enum/
      `category`→`kind`=`KIND[cat]`/`evidence` 非空 str 列表/`entry_points` 列表/`confidence` 数值;
      根级 `controls[]` 键 = 违例(`nested controls[] drift`);缺必填/枚举越界/映射不匹 = 违例。
- [x] 1.4 `--check` stdout 单 JSON `{"check":"t1","ok":bool,"records":N,"bom":[files],"violations":
      [{"file","cluster_id","issue"}]}`;`cluster_id` 记录可解析时抽取;stderr 进度/诊断;退出码 0 ok /
      1 缺目录 / 2 违例;空目录 = `ok:true, records:0, exit 0`。
- [x] 1.5 `--strip-bom`:每条 `*.json` 读字节 → `_strip_bom_bytes` → 若曾带 BOM 则原子重写(`.tmp`+
      `os.replace`,UTF-8 no-BOM)且记入 `stripped[]`;无 BOM 文件 byte-identical 不动;不可读文件 skip +
      stderr 记;idempotent(二次跑 `stripped[]` 空)。

## 2. 回归测:`tests/test_validate_t1_records.py`

- [x] 2.1 规范记录(根级 `evidence[≥1]`/`entry_points`/`confidence`,`category`∈8,`kind`∈6,映射对)
      → `--check` exit 0 / `ok:true` / `violations:[]`。
- [x] 2.2 嵌套 `controls[]` 漂移记录 → exit 2 / `violations` 含 `nested controls[] drift`。
- [x] 2.3 缺 / 空 / 非 list `evidence`、非 str 锚点 → exit 2 各形态。
- [x] 2.4 `category` 越界、`kind` 越界、`category`→`kind` 不匹配 → exit 2 各形态。
- [x] 2.5 BOM+合规记录:`--check` 内存剥 BOM 判 ok 且报 `bom[]`(exit 0);`--strip-bom` 磁盘去前导 BOM、
      后字节不变、入 `stripped[]`;无 BOM 文件 byte-identical、不入 `stripped[]`;二次 `--strip-bom`
      idempotent(`stripped[]` 空)。
- [x] 2.6 空目录 → `ok:true, records:0, exit 0`;缺目录 → exit 1;stdout shape + 退出码分流断言。
- [x] 2.7 validator 任意 cwd 可跑(非脚本目录 cwd 子进程,承 R5.3a 导入鲁棒性测)。

## 3. 编排接线 + 契约

- [x] 3.1 双壳 `releases/{claude-code/commands,opencode/command}/mgh-init.md`:step 4(T1 fan-out)末与
      step 5(T2)间插 `validate_t1_records.py --strip-bom --checkpoints <target>/.mgh-init/checkpoints/t1`
      然后 `--check`;退出码 2 recipe(对 `violations[]` 每项 `rm <file>.done` → 重跑 `list_clusters`
      重派该簇,外科式);逐字镜像、双壳字节级对等、不引研发编号(承 R5.1/R5.10)。
- [x] 3.2 `core/prompts/fragments/orchestrator-discipline.md` 补 T1 边界 fail-loud recipe(需校验 T1 记录 →
      跑 validator `--check`;违例 → 失效 `.done` 重派;NEVER 带破损记录进 T2)——非 prohibition 措辞。
- [x] 3.3 `core/contracts/init/` 增 validator I/O 契约文件:`--check`/`--strip-bom` stdout 形状、退出码
      0/1/2 分流、`bom[]` advisory、`violations[].file`/`cluster_id` 字段。
- [x] 3.4 `core/contracts/init/`(T1 边界相关,如 cluster-enumeration.md 或新增 t1-checkpoint.md)注明
      T1→T2 间的确定性校验步骤。

## 4. 契约 lint + 回归 + 版本

- [x] 4.1 `tools/check_contracts.py` 断言双壳 `validate_t1_records.py --check`/`--strip-bom` 在脚本
      `--help`(机械化 flag 存在断言,承 R5.1)。
- [x] 4.2 `tools/check_distributed_purity.py` 通过(双壳增补无悬空研发引用,承 R5.10)。
- [x] 4.3 全量回归:`py tests/test_validate_t1_records.py` + `test_distributed_md_purity.py` +
      `test_zero_deps.py` + `test_opencode_hook_parity.py` + 既有 `test_resume_state.py`/
      `test_merge_scout.py`/`test_list_clusters.py` 全绿。
- [x] 4.4 `py tools/check_contracts.py` + `py tools/check_distributed_purity.py` 通过;零依赖 AST 扫描
      无新增第三方 import(承 R2)。
- [x] 4.5 `VERSION` bump(承 R5.8);`install.sh` 自检照跑。
- [x] 4.6 手工复现:造嵌套 `controls[]` t1 记录 → `--check` exit 2 + recipe;造 BOM 记录 → `--strip-bom`
      → 再 `--check` exit 0。确认 `--no-scout` 路径不受影响(T1 记录形状校验与 scout 开关无关)。
