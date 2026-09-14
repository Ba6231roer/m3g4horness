## 1. 配置写脚本

- [x] 1.1 新增 `core/scripts/read_roots_config.py`：`--target <abs>` + `--add <abs>`（可重复）/`--remove <abs>`/`--list`/`--check`；原子写 `<target>/.mgh/read-roots.json`（schema `{"v":1,"read_roots":[…]}`，未知字段保留）；幂等；`--add` 校验存在 ∧ 目录（否则退出码 2）；实际变更打印 stderr（前后条目）；stdout JSON `{configured[],added[],removed[]}`；退出码 0/1/2；条目以 `Path.resolve()` 归一后存储与比较
- [x] 1.2 新增 `tests/test_read_roots_config.py`：add/list/remove/check 全路径、幂等 no-op、非法 `--add` 退出码 2、坏 JSON 修复路径、`D:/x` 与 `D:\x` 归一不双记、非脚本目录 cwd 子进程导入鲁棒

## 2. 授权门接入（sdr 两侧核对）

- [x] 2.1 `sdr_context.py`：检索前对每个声明外部仓核对配置（复用 1.1 同款「resolve 后在配置列表 ∧ 存在 ∧ 目录」判定）；未配置仓零读取 + `external_skipped:"unapproved: <path>"` + stdout `pending_approval[]`；`--check` 覆盖新字段
- [x] 2.2 `mgh_sdr_launch.py`：哨兵 `read_roots[]` 仅取已配置且参与检索的仓；未配置声明跳过 + stderr warn + stdout/编排提示词携带 `pending_approval[]`；退出码语义与 multi-branch 串行不变
- [x] 2.3 扩展 `tests/test_sdr_context.py` 与 launcher 单测（按既有测试文件命名）：已配置放行 / 未配置跳过 / 混合声明（一配置一未配置）/ `pending_approval` 输出形态 / 哨兵 `read_roots` 不含未配置仓

## 3. 壳、编排流与报告

- [x] 3.1 两壳 `releases/{claude-code/commands,opencode/command}/mgh-sdr.md` 增「外部仓授权」步：读 `pending_approval[]` → 宿主会话问用户 → 同意：逐仓 `py …/read_roots_config.py --target <repo> --add <abs>` 后重跑 launcher 同参数；拒绝：不写配置、降级继续 + 报告披露；`NEVER` 未经同意写配置；R5.6 token 预算自查（超限 shard 进按需 fragment）
- [x] 3.2 `render_sdr_report.py`：边界声明 + 「外部仓未授权」变体（区分 `not-found`/`unapproved`），`tests/test_render_sdr_report.py` 扩展

## 4. 契约、lint 与文档

- [x] 4.1 `tools/check_contracts.py`：`read_roots_config.py` flag 断言 + `sdr_context.py`/`mgh_sdr_launch.py` 新 flag/行为面断言
- [x] 4.2 `install.sh` 共定位自检列表 + `read_roots_config.py`；零依赖 AST 扫描覆盖确认
- [x] 4.3 `docs/man/mgh-sdr.md` 补「外部仓授权」一节（人类面：现象→原因→改法）；`docs/glossary.md` 缺词则补；CHANGELOG.md / VERSION bump
- [x] 4.4 全量校验：`py tests/test_read_roots_config.py` 等新测全绿 + 既有 sdr 系测试无回退 + `check_contracts`/`check_distributed_purity` 无新违例
