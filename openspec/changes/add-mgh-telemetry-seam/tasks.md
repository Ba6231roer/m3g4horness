# Tasks — add-mgh-telemetry-seam

> 实现顺序按依赖排:先定缝(契约)→ 再写产出者(脚本)→ 再接命令壳 → 再补 install/lint/测试 → 收尾文档与版本。
> 每条均可独立验收。企业 overlay 不在本仓实现(见 `design.md` 参考设计),故无对应代码任务。

## 1. 缝契约(schema 先行)

- [ ] 1.1 新增 `core/contracts/run-receipt.md`:定义回执落盘路径(`<project-root>/.mgh-receipts/<cmd>-<iso-ts>-<shortid>.json`)、版本化 schema(=1)、完整字段表(`schema/cmd/host/user_sha/started/ended/status/artifacts[{path,kind,bytes,sha256}]/counts{}`)、「无正文」约束、向前兼容(消费者忽略未知字段)。表格优先(承 R3)。
- [ ] 1.2 在 `core/contracts/README.md` 增一行索引指向 `run-receipt.md`,标注其为「企业 overlay 唯一依赖的稳定缝」。

## 2. 回执产出者 `emit_run_summary.py`(零网络)

- [ ] 2.1 新增 `core/scripts/emit_run_summary.py`:仅 Python ≥3.10 标准库;`sys.path` 自定位兄弟导入、`encoding=utf-8`、任意 cwd 可 `py`(承 R5.3a)。**禁** import 任何网络模块(`urllib/http/socket/ssl/requests`)。
- [ ] 2.2 CLI 契约(承 R5.1,`tools/check_contracts.py` 将覆盖):`--cmd <mgh-init|mgh-sra|mgh-sast>`、`--target <abs project-root>`、`--artifact <abs-path>:<kind>`(可重复,关键产物)、`--count <k=v>`(可重复)、`--started <ts>` `--ended <ts>`、`--status <ok|failed>`(默认 ok);`stdout`=JSON 摘要、`stderr`=进度、退出码 `0/1/2`、闭集参数拒歧义 + 可操作报错。
- [ ] 2.3 行为:对每个 `--artifact` 计算 `bytes` + sha256;`user_sha` = sha256(env `USER`/`USERNAME` 或 `git config user.email`)截断(无原文 PII);`host` 取 env(`HOSTNAME`/`COMPUTERNAME`/`hostname`);写回执到 `<target>/.mgh-receipts/<cmd>-<iso-ts>-<shortid>.json`(绝对)。`MGH_NO_RECEIPT=1` → 不写、stdout 标 `skipped`、退出 0。
- [ ] 2.4 `--check <receipt.json>`:按 schema 校验单份回执(字段齐全、`artifacts[]` 形状、sha256 重算一致),失败退出 2(承 R5.9 boundary validator)。
- [ ] 2.5 幂等:文件名含 `<iso-ts>-<shortid>` 不冲突;同次重写覆盖安全。

## 3. 接入三命令壳(成功末步 +1 行;claude + opencode 双平台)

- [ ] 3.1 `releases/claude-code/commands/mgh-sast.md`:成功末步(emit_sarif/report 之后)加一行 `py .claude/mgh-core/scripts/emit_run_summary.py --cmd mgh-sast --target <abs-repo> --artifact <abs>/report.sarif:report ...`(关键产物;计数取 emit_sarif/findings 字段,逐字透传绝对路径)。
- [ ] 3.2 `releases/claude-code/commands/mgh-init.md`:成功末步(assemble_rules 完成后)加一行调用,`--cmd mgh-init --target <MGH_TARGET> --artifact <abs>/controls_inventory.json:inventory --artifact <abs>/AGENTS.md:rules ...`。
- [ ] 3.3 `releases/claude-code/commands/mgh-sra.md`:成功末步(merge 完成后)加一行调用,`--cmd mgh-sra --target <project-root> --artifact <abs>/business_context.json:memory ...`。
- [ ] 3.4 `releases/opencode/command/mgh-{sast,init,sra}.md`:对应 opencode 路径(`.opencode/mgh-core/scripts/...`)各 +1 行同构调用。
- [ ] 3.5 每壳顶部「输出/诚实边界」小节注明:新增 `.mgh-receipts/`(本地、零网络、可 `.gitignore`、`MGH_NO_RECEIPT=1` 可关);不改变现有产物路径。

## 4. install 自检 + 契约 lint + 零依赖扫描

- [ ] 4.1 `install.sh` 共定位自检脚本列表(第 4 步 `_missing` 循环)加入 `emit_run_summary`;同步更新该步的 ✓ 提示文案。
- [ ] 4.2 `tools/check_contracts.py`:覆盖三壳(双平台)对 `emit_run_summary.py` 的调用 flag——提取 `emit_run_summary.py --*` 并对每个 flag 跑 `--help` 断言存在(承 R5.1)。
- [ ] 4.3 零运行时依赖 AST 扫描目标扩到 `emit_run_summary.py`,并**新增断言**:该脚本不得 import 网络模块(与既有 vvaharness import 扫描并列,作为「零网络」凭据)。

## 5. 测试(确定性,`tests/`)

- [ ] 5.1 `tests/test_emit_run_summary.py`:① 成功写出回执 + 字段完备 + 无正文;② `artifacts[]` 的 `bytes`/`sha256` 与实算一致;③ 文件名/路径落在 `<target>/.mgh-receipts/` 且绝对;④ `MGH_NO_RECEIPT=1` 不写;⑤ `--check` 对合法回执退出 0、对破损回执退出 2;⑥ 退出码 0/1/2 分流 + stdout/stderr 分流;⑦ 任意 cwd 运行(非脚本目录 cwd 子进程)。
- [ ] 5.2 零网络单测:断言 `emit_run_summary.py` 源码 AST 中无网络模块 import(与 4.3 同源,作为测试侧凭据)。
- [ ] 5.3 既有回归不退化:跑 `tests/test_deterministic.py` + `tests/test_block_adhoc_scripts.py` + `tests/test_distributed_md_purity.py`(确认命令壳 +1 行调用不引入 dev-only provenance,承 R5.10)全绿。

## 6. 文档收尾 + 版本

- [ ] 6.1 `AGENTS.md` 命令表 / 诚实边界小节:补一句「开源仓提供 `.mgh-receipts/` 良性回执缝;企业埋点(采集+上传)由独立 overlay 承接,不在本仓」(面向维护者;不进分发产物)。
- [ ] 6.2 README(面向使用者,若提及)简注 `.mgh-receipts/` 可 `.gitignore`、`MGH_NO_RECEIPT=1` 可关;**不**在 README 暴露企业 overlay 实现细节。
- [ ] 6.3 按 R5.8 bump 受影响命令壳 + `emit_run_summary.py` 版本号;`install.sh` 自检 fail-soft、CI 必 fail 的约定保持。
- [ ] 6.4 全量验收:`./install.sh --claude <tmp-target>` 跑通自检(含新脚本共定位 + 零网络 + 纯净性);`tools/check_contracts.py` 与全部 `tests/` 绿。
