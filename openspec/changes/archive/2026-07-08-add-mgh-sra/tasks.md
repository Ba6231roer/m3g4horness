# Tasks — add-mgh-sra

> 依赖顺序:维度目录+契约+profile → 确定性脚本+单测 → 提示词 → subagent → 命令壳 →
> hook/安装/自检/文档 → 验证。每条可独立验收。遵守 AGENTS.md R1–R5。决策 D1–D10 见 `design.md`。
> **重心 = 分析脑子(D1 维度目录 / D2 三信号匹配)+ 交互记忆(D4 澄清问答 / D5 业务记忆)。**

## 1. 维度目录 + 契约 + 配置(地基)

- [x] 1.1 写 `core/prompts/fragments/security-dimensions.md`(D1):9 维度表(敏感数据 / 注入 /
  横向越权·IDOR / 纵向越权 / 认证 / 完整性·关键操作 / 审计 / 限流·滥用 / 密钥·配置)×
  (检查什么 + 典型缺口 + 该维度缺口如何触发控制匹配的 category);说明 augment 逐维度查缺口、
  clarify 据维度找缺失业务事实;头注 `rewrite-original`;面向人读用简体中文,锚点/路径原样。
- [x] 1.2 写 `core/contracts/sra/augmentation.md`:`change_context.json`(`capabilities[]`/
  `requirements[]`/`tasks[]`/`mentioned_files[]`/`endpoints[]`/`data_fields[]`/`role_hints[]`/
  `candidate_controls[]` 每项 `{name,category,dimensions,entry_points,evidence,file_overlap}`/
  `pending[]` 每项 `{capability,draft_path(绝对),done_marker}`);draft(`gaps[]` 每条
  `{dimension,anchor{requirement/endpoint/field},risk,recommended_control?,matched_signals?}` /
  `security_requirements[]`/`security_tasks[]`);`sra_manifest.json`。含 ≤5 行内联片段。
- [x] 1.3 写 `core/contracts/sra/business-context.md`:`business_context.json`(`version`/
  `roles[]`/`domains[]`/`sensitive_fields[]`/`interface_authz[]`/`business_rules[]`/
  `clarifications[]`,每条记忆 `{fact_key,value,source:user-asserted,updated_at?}`)+ `clarification`
  shape(`{id,capability,dimension,question,why_it_matters,default_guess,fact_key}`)。标注项目级
  落位 `<project>/.mgh-sra/`、跨迭代累积、与 mgh-init inventory 同构。
- [x] 1.4 写 `core/profiles/sra.yaml`:角色 `clarify`/`augment`/`consistency`(`model: inherit`)、
  `allowed_tools: [Read, Glob, Grep, Bash]`、`budget`、`fanout`(augment per-capacity 扇出 +
  `max_concurrent`)。沿用 `init.yaml` 结构(D9:无 scout/resume/sharding)。
- [x] 1.5 `core/contracts/README.md`:末尾补一行指向 `sra/augmentation.md` 与 `sra/business-context.md`
  (sra 增补 I/O + 业务记忆契约),不动现有 sast 表。

## 2. 确定性脚本(a1 prepare / a5 merge / merge_memory)+ 单测

- [x] 2.1 写 `core/scripts/prepare_augment.py`(标准库):解析变更 → `change_context.json`;
  抽 `endpoints[]`/`data_fields[]`/`role_hints[]`(机械信号,供 D1 维度分析);`--rules` 接受
  inventory 文件**或** `.mgh-init/` 目录(自动发现),自持 `json.load` + 最小 shape 校验(D9,**不 import**
  `load_controls`/`validate_inventory`);对每控制派生 `dimensions`(由 `category`)并标文件重叠 →
  `candidate_controls[]`(D2 信号-1,不硬切);载入项目级 `business_context.json`(若存在);
  `--change`(默认最新未归档)解析项目根(含 `openspec/` 的目录,= `MGH_TARGET`)与变更根;输出
  `pending[]` 每项**绝对** `draft_path` + `done_marker`(D8)。CLI:`--change --out? --rules? --dry-run?
  --no-interactive?`,`--check`(退出码 `0/1/2`)。stdout=JSON / stderr=诊断(R5.3b)。
- [x] 2.2 写 `core/scripts/merge_augment.py`(标准库):读 a4 后全部 draft → 受管块
  `<!-- mgh-sra:begin --> … <!-- mgh-sra:end -->` 幂等追加进各 `specs/<cap>/spec.md`
  (`## ADDED Requirements` 下)+ `tasks.md`;无 capability specs 时建 `specs/security-augmentation/spec.md`;
  重跑仅原地替换受管块,块外字节不变(D3)。CLI:`--change --drafts-dir --check`(校验仅动受管块、
  退出码 `0/1/2`)。
- [x] 2.3 写 `core/scripts/merge_memory.py`(标准库):把澄清答案按 `fact_key` 幂等累积进
  `<project>/.mgh-sra/business_context.json`(已存在 `fact_key` 原地更新 + 记 `updated_at`,新键追加;
  首跑无文件则创建 + `version`)。CLI:`--memory <path> --answers <json> --check`(校验 shape +
  `fact_key` 无冲突、退出码 `0/1/2`)。所有写落在 `MGH_TARGET`(项目根)子树内(D8)。
- [x] 2.4 写 `tests/test_sra_prepare.py`:fixture 变更(含 `specs/payment-api/spec.md` + 提及
  `POST /api/transfer`、`bankCardNo`)+ fixture inventory(`category:authorization` 控制、
  `entry_points` 含同域接口)→ 验证 `capabilities`/`requirements`/`endpoints`/`data_fields` 抽取、
  控制 `dimensions` 派生、文件重叠 flag、`pending[]` draft 路径绝对且在项目子树、载入记忆字段、
  无 `--rules` 时 `candidate_controls` 空、`--check` 对破损 inventory 退出码 2。
- [x] 2.5 写 `tests/test_sra_merge.py`:受管块追加后用户原 requirement 字节不变、二次合并幂等、
  `--check` 检出块外改动则退出码 2、无 capability specs 时建回退文件、合并仅写项目子树。
- [x] 2.6 写 `tests/test_sra_memory.py`:`fact_key` 幂等(重答原地更新非追加、重跑不重复)、首跑
  创建带 `version`、`--check` 检出 shape/`fact_key` 冲突退出码 2、写落在项目子树。
- [x] 2.7 AST 扫描 + 运行确认三脚本零第三方 import、零 `vvaharness` import、零兄弟命令内部
  import;`sys.path.insert(0, dir-of-__file__)` 自定位、utf-8、任意 cwd 可 `py`(R5.3a);三单测全绿。

## 3. 提示词(a2 clarify / a3 augment / a4 consistency)

- [x] 3.1 写 `core/prompts/stages/sra-clarify.md`(**单上下文扫全变更**,D4):输入 =
  `change_context` + 维度目录(`security-dimensions.md`)+ 已载记忆;据各维度识别「分析必需但
  代码/proposal/inventory/记忆均判不出」的业务事实 → 发 `clarification`(含 `why_it_matters` +
  `default_guess` + `fact_key`);**跨 capability 去重**(角色/域类问题只问一次);已记 `fact_key`
  不重发;输出 `clarifications[]`(结构化 JSON)。头注 `rewrite-original`;人读用简体中文。
- [x] 3.2 写 `core/prompts/stages/sra-augment.md`(**per-capacity 扇出**,D1+D2):输入 = 单
  capability 的 requirements + 业务面 + `candidate_controls` + **增补后记忆**;**逐维度**(读
  `security-dimensions.md`)查缺口,每缺口锚定 requirement/接口/字段;对每缺口三信号匹配(维度
  契合必要条件 + 业务域相似语义 + 记忆业务事实)→ 推荐控制(带 `evidence` + 派生规则文件路径 +
  「复用勿重造」+ 业务域相似理由);仅文件重叠非充分不推荐;无 `--rules` 时缺口仅产安全属性
  requirement;无锚点缺口丢弃。输出 draft(结构化 + 可渲染 spec/task)。
- [x] 3.3 写 `core/prompts/stages/sra-consistency.md`(**跨类一致性**):输入 = 全部 draft;跨
  capability 命名/引用去重、消冲突、同一控制多类引用归一;输出最终 draft 集。
- [x] 3.4 提示词纪律(R5.5):recipe 不用 prohibition(硬边界才 `NEVER`);`MUST/SHALL` 取代
  should/may;无长代码块(承 R3);禁 dev-meta/研发铁律编号/失败 ID/变更夹名(R5.10)。

## 4. Subagent 定义

- [x] 4.1 写 `releases/claude-code/agents/sra-clarify.md`(单上下文,读 `change_context` + 记忆
  + 维度目录 → 输出 `clarifications[]`;不碰 specs/tasks)。
- [x] 4.2 写 `releases/claude-code/agents/sra-augment.md`(per-capacity 扇出:读该 capability 段
  + `candidate_controls` + 增补记忆 + 维度目录 → 恰好写其绝对 `draft_path` + touch `done_marker`)。
- [x] 4.3 写 `releases/claude-code/agents/sra-consistency.md`(读全部 draft → 跨类去重定稿)。
- [x] 4.4 在 `releases/opencode/agent/` 镜像 4.1–4.3(opencode frontmatter 约定)。

## 5. 命令壳(替换 TODO 骨架)

- [x] 5.1 重写 `releases/claude-code/commands/mgh-sra.md`:a0 参数解析 + 零 token 守卫(`--help`/
  无参打印表 STOP)、编排器纪律段(= 宿主 agent,`NEVER` 硬边界 + fan-out 刚性三元组,逐字镜像
  mgh-init.md 该段)、a0→a5 编排流(stage→component 表 + 确定性调用 + per-capacity 扇出 + 批量
  澄清暂停问 + `--check` 边界)、**澄清交互说明**(claude 用原生交互、`--no-interactive` 跳过)、
  产物路径、诚实边界;起步 `export MGH_SRA_ACTIVE=1` + `export MGH_TARGET=<绝对项目根>`(供 hook
  判树,覆盖变更子树 + 项目记忆)。正文 ≤500 行(R5.6)。
- [x] 5.2 重写 `releases/opencode/command/mgh-sra.md`:同 5.1,opencode 调用约定(opencode 无
  PreToolUse hook + 澄清回退产 `clarifications.md` 待用户回填,纪律靠壳铁律 + `--check`)。
- [x] 5.3 校验两壳参数表一致、`--rules` 文件/目录二选一、`--no-interactive` 语义明确。

## 6. hook 扩展 + 安装 / 自检 / 文档

- [x] 6.1 扩 `releases/claude-code/hooks/block_adhoc_scripts.py`:① 运行域加 `MGH_SRA_ACTIVE=1`
  (`main()` 读取 + `domain` 选择);② `_WORKLIST` 加 `"mgh-sra": "prepare_augment.py /
  merge_augment.py / merge_memory.py"`;③ `_is_out_of_tree` 子树守卫对 sra 域**也生效**(当前
  init-only,见 `:119`;改为 init 或 sra 域均判;`MGH_TARGET`=项目根覆盖变更子树 + 项目记忆)。
- [x] 6.2 扩 `tests/test_block_adhoc_scripts.py`:加 sra 列(`_DOMAIN_ENV` 加 `"sra":
  "MGH_SRA_ACTIVE"`;镜像 init 列的三类断言:微脚本内省 / 越权 `*.py` / 子树外写——含写项目记忆
  路径与变更 draft 路径两类合法、写盘符根非法)。
- [x] 6.3 更新 `install.sh`:① 自检循环(line ~85 的 `for s in ...`)加 `prepare_augment
  merge_augment merge_memory`;② 末尾 `echo` 命令清单加 `/mgh-sra`;③ sra 资产(命令/subagent/
  提示词/脚本/契约/profile)经既有 `core/` + `releases/<plat>/` 镜像到 `.claude/mgh-core/` 自动分发。
- [x] 6.4 零依赖自检:`grep -rnE "^[[:space:]]*(import[[:space:]]+vvaharness|from[[:space:]]+
  vvaharness[[:space:]]+import)" --include=*.py .` 应无输出;AST 扫描三新脚本无第三方 import、无
  兄弟命令内部 import。
- [x] 6.5 扩 `tools/check_contracts.py`:断言两壳 MD 里所有 `*.py --flag` 经 `py <script>.py --help`
  存在(R5.1);扩 `tools/check_distributed_purity.py` 覆盖 sra 新增 md(命令壳/提示词/契约/维度目录)
  无研发铁律编号/失败 ID/变更夹名等 dev-only 悬空引用(R5.10)。
- [x] 6.6 更新 `docs/upstream-index.md`:登记 `/mgh-sra` = **rewrite-original**(无 vvah 源;openspec
  安全增补 + 业务记忆是 m3g4horness 原创工作流链中段),保真度栏「不适用(原创)」。
- [x] 6.7 更新 `AGENTS.md` 命令状态表:`/mgh-sra` 由 🚧 TODO → ✅ 可用(实现完成后)。

## 7. 端到端验证

- [x] 7.1 `./install.sh --claude .` 与 `--opencode .` 各装一次,确认 sra 资产就位(命令/3 subagent/
  3 脚本/契约/profile/维度目录镜像到 `.claude/mgh-core/`)。
- [x] 7.2 维度+匹配验证:样例变更(含 `payment-api` + 接口 + 敏感字段)+ inventory(同域鉴权控制)
  跑 `mgh-sra --change <c> --rules <inv>`:确认逐维度缺口(横纵越权/敏感数据/完整性)、三信号
  推荐控制(带 evidence + 业务域理由)、specs 受管块追加(用户内容不变)+ tasks 追加 +
  `sra_manifest.json` 含四条边界;重跑幂等。
- [x] 7.3 澄清问答验证:首轮跑触发澄清(如「refund 哪些角色用」)→ 编排器批量暂停一次问 →
  答案写回 `<project>/.mgh-sra/business_context.json`(`fact_key` 幂等)→ augment 用增补记忆产
  锚定推荐;`--no-interactive` 跳过暂停用默认、产物标「未确认·默认」。
- [x] 7.4 跨迭代复用验证:对同项目第二个变更跑 sra → 确认读累积记忆、澄清数显著少于首轮、
  同业务域接口直接复用 `interface_authz[]`。
- [x] 7.5 降级验证:无 `--rules` → 仍逐维度产安全 requirements(缺口无控制锚点,不阻断);
  无记忆首跑 → 空记忆起步经澄清创建。
- [x] 7.6 `--dry-run`:仅产 `change_context.json` + stdout 摘要,**不写** specs/tasks/记忆。
- [x] 7.7 hook 验证:`MGH_SRA_ACTIVE=1` + `MGH_TARGET=<项目根>` 下,`py -c "import json..."` 内省、
  越权 `*.py`、写盘符根 / 写项目子树外 均被拦(退出码 2 + stderr recipe 指向
  `prepare_augment`/`merge_augment`/`merge_memory`);写变更 draft 与项目记忆两类合法路径放行。
- [x] 7.8 边界校验:破损 inventory → `prepare_augment --check` 退出码 2;改块外内容 →
  `merge_augment --check` 退出码 2;记忆 `fact_key` 冲突 → `merge_memory --check` 退出码 2。
- [x] 7.9 全测绿:`py tests/test_sra_prepare.py` + `test_sra_merge.py` + `test_sra_memory.py` +
  `test_block_adhoc_scripts.py` + `test_distributed_md_purity.py` + 现有 `test_init_*.py`/
  `test_sast_runtime.py`;零依赖自检无输出;`tools/check_contracts.py` 无违例。
