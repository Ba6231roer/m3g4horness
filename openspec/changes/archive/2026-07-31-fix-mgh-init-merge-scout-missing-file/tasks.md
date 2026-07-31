## 1. 归一路径容错(`core/scripts/merge_scout.py`)

- [x] 1.1 `_normalize`:`file` 纳入与 `category` 同一 None-return 守卫
  (`if not c.get("category") or not c.get("file"): return None`);`"file": c["file"]` → `c.get("file")`;
  更新 docstring,把返回 `None` 的条件由「缺 category」泛化为「缺任一必填字段(category / file)」。
- [x] 1.2 调用方 skip-with-warn 措辞(现 `missing category - skipped`)泛化为如实指出**缺哪个**
  必填字段(`category` / `file` / `both`),保留 candidate `index` 与可得 `file:line` 定位。
- [x] 1.3 扫 `_normalize` 全字段,确认无其它**直索引必填字段**残留(当前仅 `file`,随 1.1 修掉)。

## 2. 回归测试(`tests/test_deterministic.py`)

- [x] 2.1 增用例:喂一条缺 `file` 的 scout candidate 经归一 → `_normalize` 返回 `None`、调用方 skip、
  stderr 打 warn、**不**抛 `KeyError`、merge 正常产出。
- [x] 2.2 覆盖 spec 其余 scenario:缺 `category`(行为不变)、两者同缺(只 skip 一次 + warn 列全)、
  well-formed candidate(不受影响、无 warn)。
- [x] 2.3 `py tests/test_deterministic.py` 全绿。

## 3. 契约 / 稳定性守卫(R5)

- [x] 3.1 确认 `merge_scout.py --check` 行为与 CLI I/O 契约**不变**(stdout JSON / stderr 诊断分流 /
  退出码 `0|1|2`);缺字段仍由 `--check` 退出码 2 挡(本变更只补归一非 check 路径)。
- [x] 3.2 `py tools/check_contracts.py` 通过(本变更不动任何 CLI flag,双壳 MD `--flag` ↔ `--help`
  镜像不退化)。
- [x] 3.3 按 R5.8 bump 版本号;`py tools/check_distributed_purity.py` 通过(本变更不引入 dev-only
  溯源 / 研发铁律编号到分发产物)。
