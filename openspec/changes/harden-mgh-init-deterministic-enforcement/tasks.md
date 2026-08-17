## 1. 哨兵确定性副作用(write_runconfig.py)

- [ ] 1.1 `core/scripts/write_runconfig.py` 增 `_derive_out_roots(args, target)`:`--out`/`--rules-dir` 非默认时解析为绝对根列表(默认产物根不列),供哨兵 `out_roots[]` 复用
- [ ] 1.2 `write_runconfig.py` 在原子写 `run_config.json` 后 co-write `<init-dir>/.active`(`domain:"mgh-init"`、`target=target_abs`、`out_roots[]`、`v:1`),原子写(`.tmp`+`os.replace`)、幂等;stdout ack 增 `sentinel` 字段
- [ ] 1.3 `tests/test_write_runconfig.py` 增:哨兵 co-write 存在性 + `domain`/`target`/`out_roots[]`/`v` 字段 + 默认根不列 + 自定义 `--out` 列根 + 幂等重写

## 2. 哨兵存在性校验 + resume re-arm(resume_state.py)

- [ ] 2.1 `core/scripts/resume_state.py` `check()` 增哨兵存在性校验:`run_config` 存在 ∧ step ≠ `done` ∧ `<init-dir>/.active` 缺失 → `violations[]` 一项(守卫休眠,退出码 2 + re-arm recipe);`done` 步缺失非违例
- [ ] 2.2 `resume_state.py` 增确定性 re-arm 动作(据 `run_config.target` + `rules_dir`/`out` 派生 out_roots 重写 `<init-dir>/.active`),`--resume`/压缩后第一步可调用;stdout 契约注明
- [ ] 2.3 `tests/test_resume_state.py` 增:`--check` 对「进行中 + 哨兵缺失」退出码 2、对「done + 哨兵缺失」退出码 0、re-arm 写出哨兵 + `target` 与 `run_config.target` 一致

## 3. 叶源码 Read 拦截(守卫,双端 byte-identical)

- [ ] 3.1 `releases/claude-code/hooks/block_adhoc_scripts.py` 读侧分支增:resolve 后 `file_path` 落在含 `mgh-core/scripts` 路径段目录 ∧ 扩展名 ∈ `_SCRIPT_EXTS` → 退出码 2 + 叶源码 recipe(stderr 诊断,NEVER Read 叶子源码)
- [ ] 3.2 `releases/opencode/hooks/block_adhoc_scripts.py` 同步(byte-identical;parity 测断言两文件一致)
- [ ] 3.3 `tests/test_block_adhoc_scripts.py` 增:运行域内 Read `mgh-core/scripts/*.py` 拦、目标项目自身 `.py` 放行、非 `mgh-core/scripts` 的 `.py` 放行、非运行域放行
- [ ] 3.4 `tests/test_opencode_hook_parity.py` 断言双端 `.py` byte-identical + 新分支不新增工具名(接线覆盖集 `matcher`/`HANDLED` 不变)

## 4. 提示词瘦身

- [ ] 4.1 `core/prompts/fragments/init-stage/bootstrap.md` 删 `printf` 哨兵配方,改为「`write_runconfig.py` 已自动写哨兵(副作用);`--resume` 经 `resume_state` re-arm」
- [ ] 4.2 `core/prompts/fragments/orchestrator-discipline.md` 删「NEVER Read 叶子 `.py` 源码」要求(改注「hook 已确定性拦截,报错看 stderr」)
- [ ] 4.3 `core/scripts/discipline_core.py` 删 `discover` 步 `nevers` 里的「NEVER Read discover_controls.py 源码」(其它步同形 NEVER 同步复核)

## 5. 契约与分发同步

- [ ] 5.1 `core/contracts/hooks/runtime-enforcement.md` 更新:哨兵 Producer 从「orchestrator printf」改「`write_runconfig` 确定性副作用 + `resume_state --check` 校验 + re-arm」;读侧增叶源码拦截条目
- [ ] 5.2 `openspec/specs/runtime-hook-enforcement/spec.md`(基线,非 delta)同步 Purpose 措辞(哨兵 producer 变更)与新增 requirement 归档位
- [ ] 5.3 `AGENTS.md` R5.7 段 B 措辞同步(哨兵确定性副作用 + 叶源码读拦截);版本号 bump(受影响的 `.md`/脚本)
- [ ] 5.4 跑 `py tools/check_contracts.py` + `py tools/check_distributed_purity.py` + 零依赖 AST 扫描,确认无新增 flag 契约违例 / 无 dev-meta 泄漏 / 无第三方 import

## 6. 全量回归 + 冒烟

- [ ] 6.1 `py tests/test_write_runconfig.py`、`py tests/test_resume_state.py`、`py tests/test_block_adhoc_scripts.py`、`py tests/test_opencode_hook_parity.py`、`py tests/test_init_runtime.py`、`py tests/test_zero_deps.py` 全绿
- [ ] 6.2 真机 opencode 冒烟:hook 阻断叶源码 Read vs 宿主权限询问先后顺序;哨兵经 `write_runconfig` 副作用在无 env 的 opencode 上可靠激活(脚本只读/越树写均 fail-loud)
