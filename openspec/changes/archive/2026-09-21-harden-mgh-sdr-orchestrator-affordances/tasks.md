## 1. 审批闭环单命令化（sdr_context.py）

- [x] 1.1 从 `read_roots_config.py` 提取（或确认可直接导入）原子写 + 校验函数，`sdr_context.py` 经同目录自定位导入复用（design D1；`read_roots_config.py` 行为逐字不变）
- [x] 1.2 `sdr_context.py` 新增 `--approve-external <abs>`（可重复）：检索开始前逐路径校验（存在 ∧ 是目录，违者退出码 2 零写入）并原子写配置；登记成功的仓当次即检索、随既有 co-write 进哨兵 `read_roots[]`；`--help` 契约文案写明「仅在宿主会话获用户明示同意后传入」
- [x] 1.3 未知参数配方（design D2）：`parse_known_args` 分离未知 `--*`，命中词根 `{approve,read,external,root}` 且不在册 → stderr 追加可照抄的批准+重跑命令行（绝对脚本路径自拼），退出码 2；非命中词根行为逐字不变
- [x] 1.4 测（`test_sdr_context`）：同意后单命令闭环、非法目标 fail-loud 零写入、重复批准 no-op、发明 flag 得到配方、在册 flag 不误伤；跑定向 `test_sdr_context`

## 2. 摘要视图与审批滞留提醒

- [x] 2.1 `sdr_context.py --summary`：stdout 投影（规格字段集，`external_repos[]` 剔除 `route_hits[]` 明细），磁盘产物与缺省形态逐字一致（同一执行流尾部投影，不新增文件）
- [x] 2.2 `sdr_context.py` stderr 收敛：逐文件检索进度降为每仓一行汇总；error/提醒行保留（design D4 末段）
- [x] 2.3 `sdr_context.py --check`：`context.json::pending_approval` 非空 → stderr WARN 列条目、不改退出码；为空无该行
- [x] 2.4 `diff_group.py --summary`：物化照常幂等执行，stdout = `summary{...}` + 全路径 `pending[]`；分页仅由既有 `--offset/--limit` 驱动（`effective_limit` = 本页实返条数），`diff_group` 无按字节自动收页（那是 init `list_*` 家族的能力，本脚本从未有 `--orch-budget-bytes`）
- [x] 2.5 测：两脚本缺省 stdout 与改动前基线逐字一致（回归护栏）；摘要字段集符合规格；`--check` WARN 两态；跑定向 `test_sdr_context` `test_diff_group`

## 3. step 0 预武装闭合守卫失败窗口（resume_sdr_state.py）

- [x] 3.1 新增 `--arm-sentinel`（与 `--rearm-sentinel` argparse 互斥组）：`target` 取 `--repo`（缺失且布局推不出 → 退出码 2 + recipe）；同 target 已存在 → no-op（NEVER 清空 `read_roots[]`）；stdout `{sentinel_path, armed, target}`
- [x] 3.2 `--rearm-sentinel` 在 `context.json` 缺失时退出码 2 + stderr 指向 `--arm-sentinel`（不静默写空 target）
- [x] 3.3 `not-started` 步的 `next_action` 文本携带 `--arm-sentinel` 前置命令行
- [x] 3.4 测（`test_resume_sdr_state` 或既有姊妹文件）：预武装写最小哨兵、幂等 no-op、target 冲突退出码 2、rearm 缺 context 指向 arm；跑定向对应测试文件

## 4. hook 拦截面扩形态（双端 block_adhoc_scripts.py）

- [x] 4.1 新增独立正则 `_PY_INLINE_RX`（design D5）：解释器 + `-c`（既有路径不动）/ 独占 `-` 跟 `<<`（heredoc）/ `- <<<`（here-string）；命令体分段判定；命中 → 退出码 2 + 现行 `_recipe(domain)`，不做体内 token 嗅探
- [x] 4.2 claude 与 opencode 两份守卫文件同改动，保持字节级 parity；`core/contracts/hooks/runtime-enforcement.md` 契约文档同步拦截面措辞
- [x] 4.3 测（`test_block_adhoc_scripts`）：真机形态反例 `python3 x.py … | python3 - <<'EOF'` 被拦、`py - <<<` 被拦、`py -c`  benign 体行为不变、`py … | tail -5` 不误伤、域外零变化；跑定向 `test_block_adhoc_scripts` `test_opencode_hook_parity`

## 5. 指令面同步（双壳 + fragment + launcher 提示语）

- [x] 5.1 `core/prompts/fragments/orchestrator-discipline.md` 硬边界②扩为三喂入形态措辞（design D7 统一措辞），并保留「stdout 直消费」句
- [x] 5.2 `releases/claude-code/commands/mgh-sdr.md` 与 `releases/opencode/command/mgh-sdr.md` 双端同构更新：step 0 增 `--arm-sentinel` 命令（含干净停止残哨移除行）；step 1/2 增 `describe_artifact.py` 确切配方 + 「stdout 直消费、过大用 `--summary`」声明；硬边界 (b) 措辞与 fragment 同扩；审批「同意」分支以 `--approve-external` 为推荐、`read_roots_config.py --add` 标注等价
- [x] 5.3 `mgh_sdr_launch.py` 待批提示语更新为推荐 `--approve-external` 形态（纯文案；`read_roots_config.py --add` 提示保留为等价行）
- [x] 5.4 壳正文 token 预算复查（`tools/measure_prompts.py`）：双壳增量若逼近编排器上限，把新增配方迁 lazy fragment 而非删承重内容；跑定向 `test_distributed_md_purity` `test_plain_language` + `py tools/check_contracts.py`

## 6. recipe 可见性机械检查（tools/check_contracts.py）

- [x] 6.1 新增独立函数：提取守卫 `_WORKLIST`/`_recipe` 文本中 `\w+\.py` 脚本名集合，断言 ⊆（该域双端壳 ∪ 共享 fragment）字面出现的脚本名集合；缺项退出码 2 并列出（域, 缺失脚本）对（design D6；与 in-progress 的调用域断言规则避免同函数耦合）
- [x] 6.2 fragment 中把「artifact-inspect 脚本」抽象处补一处字面 `describe_artifact.py`（或等价白名单决策，二选一落 code）
- [x] 6.3 反向用例测：临时从 sdr 壳删除 `describe_artifact` 引用 → 检查必须失败；恢复 → 通过；跑定向 `test_ut_init_ack_contract`（`--help` 全跑面）不必须，按映射表跑 `test_distributed_md_purity` + lint 本体

## 7. 失败链固化与全量闸门

- [x] 7.1 把真机失败链四动作（发明审批 flag → heredoc 内联 → `> /tmp` 文件中介 → `py -c` 处理产物）写成一组端到端反例用例：逐一断言「被拦（退出码 2 + recipe）」或「被引导（新 flag/新配方一次跑通）」，落在 §1/§2/§4 对应测试文件内
- [x] 7.2 跨面全量回归（本 change 触 `core/contracts/`、hook 双端、多脚本）：`for f in tests/test_*.py` 全量跑（in-process harness 记得 `--cooldown-s 0` 既有约定）
- [x] 7.3 `py tools/check_distributed_purity.py` + `py tools/check_contracts.py` 全绿；零依赖 AST 自检与 `test_no_compile_warnings` 通过
- [x] 7.4 版本号 bump（承发布纪律）；`install.sh` 自检在目标项目实测一轮（含 hook 双端接线覆盖测通过）
