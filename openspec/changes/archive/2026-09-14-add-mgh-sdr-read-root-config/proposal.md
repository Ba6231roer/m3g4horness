> **人话序** 现在 /mgh-sdr 对外部目录（比如前端仓）的授权是「存量设计文档里写了路径就算数」：每次运行自动放行，用户不知情也管不着，换个项目还得重新翻文档。本次改成用户拍板制：流程发现存量设计声明了外部目录后，先停下来问用户「是否把这个目录加入本项目的可读清单」；同意就写一次项目配置（`.mgh/read-roots.json`，只读、永久有效、可提交版本库），以后每次运行直接放行不再问；拒绝就本次跳过外部检索、报告里如实声明。改什么：新增一个配置管理小脚本（增/删/查/校验，原子写，每次变更打印到 stderr 留痕）；launcher 与检索脚本对外部目录先核对配置再动手，未配置一律跳过并列入待批清单；两条命令壳加问询步骤。怎么验证：新脚本与 launcher/sdr_context 放行、跳过两条路径的单测，报告降级声明变体，契约 lint 覆盖新脚本 flag。

## Why

- 现状的外部仓授权是**隐式且每 run 的**：存量设计声明路径 → `sdr_context.py` 检出 → launcher 自动写进 `.mgh-sdr/.active` 的 `read_roots[]` → subagent 全程可读。用户全程无感知、无决策点；授权不持久，run 结束即失效。
- 基础层 change `harden-mgh-bash-path-allowlist` 建立了「默认非 target 全禁 + 项目配置目录只读」模型，并留下「配置由谁写、何时写」的空位——本 change 用 sdr 流程补上这个答案：**发现 → 用户拍板写一次 → 以后永久可读**。
- sdr 是目前唯一需要外部只读根的命令；授权门做在 sdr 侧（而非守卫侧）是结构必需：launcher 进程内的检索不经过守卫，授权核对必须发生在检索之前。

## What Changes

- **新增确定性叶脚本 `core/scripts/read_roots_config.py`**（标准库、自定位）：`--target <abs>` + `--add <abs>`（可重复）/`--remove <abs>`/`--list`/`--check`，原子写 `<target>/.mgh/read-roots.json`；`--add` 校验目标存在且为目录（否则退出码 2）；幂等（重复 add 为 no-op）；每次变更打印 stderr（审计留痕）；stdout 结构化 JSON，退出码 0/1/2。
- **授权门接入 sdr_context.py**：外部仓受控检索前先核对项目配置——**已配置** → 照常检索 + 输出根绝对路径；**未配置** → SHALL NOT 检索该仓，降级 `external_skipped:"unapproved: <path>"` + stdout 新增 `pending_approval:[<abs>…]`，流程继续不失败（沿用既有降级语义）。
- **授权门接入 launcher**：哨兵 `read_roots[]` 仅取**已配置**且本次参与检索的外部仓；未配置声明同样跳过 + 待批披露；launcher 保持零 TTY、退出码语义不变。
- **编排流新增「外部仓授权」步**（两壳 `mgh-sdr.md`）：读 launcher/sdr_context stdout 的 `pending_approval[]` → 宿主会话向用户呈现并请求决策 → 同意：逐仓 `py …/read_roots_config.py --target <repo> --add <abs>` 后**重跑 launcher 同参数**（配置即时生效，launcher 幂等可续）；拒绝：不写配置，按降级继续，报告边界声明「外部仓未授权，相关检查面未覆盖」。
- **报告降级变体**：`render_sdr_report.py` 边界声明支持「外部仓未授权」（区别于既有「外部仓声明不可达」）。
- 非目标（明确不做）：不做交互式 TTY / 配置 UI（问询只发生在宿主会话）；不改配置 schema 与守卫判定（基础层已定）；不扩 init/ut-init 写允许集；不在本 change 把 `.mgh` 写入收窄为仅脚本可写（列为后续可选加固）。

## Capabilities

### New Capabilities

<!-- 无。授权门、配置写脚本、报告变体都是 security-design-review 既有流程的要求级变更。 -->

### Modified Capabilities

- `security-design-review`: ① 「存量安全设计基线投影与外部仓受控检索」——检索前加配置授权核对，未配置仓不检索、进待批清单，降级原因枚举 +`unapproved`；② 「launcher 单命令外壳与运行域激活」——哨兵 `read_roots[]` 以配置为前提，launcher 跳过未配置仓并披露待批；③ 新增「外部仓读取授权经用户确认并持久化到项目配置」要求（问询流程、`read_roots_config.py` 契约、拒绝降级、幂等再入）。

## Impact

- **代码**：新增 `core/scripts/read_roots_config.py` + `tests/test_read_roots_config.py`；`sdr_context.py`、`mgh_sdr_launch.py` 授权核对与待批输出（对应单测扩展）；`render_sdr_report.py` 降级变体；两壳 `mgh-sdr.md` 各 +「外部仓授权」步（R5.6 token 预算自查，超限则 shard 进按需 fragment）。
- **契约/lint**：`tools/check_contracts.py` 增 `read_roots_config.py` flag 断言 + launcher/sdr_context 新 flag；`install.sh` 共定位自检列表 +1；零依赖 AST 扫描覆盖新脚本。
- **文档**：`docs/man/mgh-sdr.md`（人类面）补外部仓授权一节；CHANGELOG/VERSION bump。
- **依赖**：`harden-mgh-bash-path-allowlist` 须先行落地（配置文件路径/schema/守卫并集语义由其建立）；本 change 只做「谁写、何时写」。
- **协调**：当前工作树存在未提交的 mgh-sdr 系列改动触及同一批文件，apply 前需先落或合并。
