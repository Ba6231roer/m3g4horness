# fix-mgh-init-distribution-links

> **人话序**:装进目标项目的提示词、agent 定义和命令壳里,有一批「按图索骥找不到」的断链与
> 失实披露。最典型的一类:六个 stage 提示词让子代理去读 `core/prompts/fragments/codegraph-hint.md`,
> 这个路径只在开发仓存在,装到目标项目后根本不存在;T3 的规则格式手册在三个宿主面的 agent
> 定义里同样指错路(只有 dsh 面写对了);dsh 的派发披露说接了四个 tier 实际接了五个,该停的
> 交互 stage 清单漏了三个;claude 壳的参数表列了两个没有任何脚本消费的旗(`--out`/`--config`)、
> 漏了一个真旗(`--rules-dir`),同一段缓存说明三面壳有三种互相矛盾的说法;claude 还少分发一个
> 壳里点名要用的 agent 定义。根因:分发内容从开发态拷进目标项目时,引用路径没有随安装布局改写,
> 而纯净性 lint 只盯「研发编号/私有目录」两类死链,不认「源码树路径前缀」这种死链形态,壳自己的
> 参数表也没有与脚本实际消费点对账的机制。本批把死引用全部改成安装可达路径并把新形态加进 lint
> (先红后绿)、披露改成实况、参数表与脚本 `--help` 对账、agent 的 ack/权限枚举与其 stage 提示词
> 对形、install 自检补上「壳点名的 agent 文件必须存在」与拷贝卫生(`__pycache__` 不带进目标),
> 并兑现「run 目录随 gitignore 忽略」的既有承诺(write_runconfig 落盘时同步写 `.gitignore`)。
> 验证 = lint 扩展先红后绿 + 三面镜像定向回归 + install 实机冒烟;另有一项 opencode `edit: deny`
> 权限钉扎是否真的拦住 Write 需要维护者参与一次 live 验证(拍板项,方案给了两个分支)。

## Why

发现源:维护者私有文档区的 mgh-init 全流程评审报告(2026-10-13)。本批 = 战役批次 4,
发现于批次 3 propose 会话按**内容**在当前 HEAD(8788c0b)逐一重定位确认,全部仍在:

| # | 发现 | 定级 | HEAD 证据 |
| --- | --- | --- | --- |
| H10 | `codegraph-hint.md` 死链 ×6(评审记 ×4):`core/prompts/stages/init-{scout,induct,survey,resolve}.md` + `sra-{clarify,augment}.md` 均要求 Read `core/prompts/fragments/codegraph-hint.md`——目标项目无 `core/` 前缀路径;fragment 头注自称「Inlined … when codegraph=on」但全链路零内联机制;同文件毒输入规则规定锚内路径 Read 失败 → 立即回 `failed` ack → 弱模型按字面执行会把批次误判失败 | High | 6 个 stage 文件 + fragment 头注,实位确认 |
| H14 | `rules-format-{claude,opencode}.md` 死链 ×4 面:stage `init-rulewriter.md`、claude agent `init-rulewriter.md`、opencode `init-rulewriter.md` + `init-rulewriter-fanout.md` 均引 `core/prompts/fragments/…`;dsh 面 `t3.md` 已正确写 `mgh-core/prompts/…`(漏改实锤) | High | 4 面死形 + dsh 正确形,实位确认 |
| H9 | dsh 派发披露失实:`releases/dsh/skills/mgh-init/SKILL.md` ①已接线 tier 清单写「scout/t1/t2/t3」漏 scout-merge(同文档脚本清单行含 scout-merge,自相矛盾);②交互 stage 停止清单漏 T2 单上下文 `init-synthesis`、T2 rollup(`init-synthesis-rollup`)、scout-merge rollup(`init-scout-merge-rollup`);③「T4 可 `--skip-consistency` 跳过」未交代该 flag 只能在 run 起始传入、mid-run 不可注入;④停在 t4(未跳过时)永无终态 manifest 未交代处置 | High | SKILL.md 派发披露段,实位确认 |
| M1 | claude 壳 call-graph 缓存句事实错误且自相矛盾:「Call graph is rebuilt by discover each run; …(mtime-based skip otherwise)」前后半句互斥,且与 opencode 面同位置句不同文 | Medium | claude/opencode 壳各 L68,实位确认 |
| M2 | claude flag 表缺 `--rules-dir` 行(opencode/dsh 面有) | Medium | claude `mgh-init.md` 无该行,实位确认 |
| M3 | 三面壳命令级 `--out` 无消费点(`write_runconfig.py --help` 无此 flag),与 run 配置写盘的 `--init-dir/--run-root` 语义重叠且无人消费 | Medium | write_runconfig `--help` 对账,实位确认 |
| M4 | 三面壳命令级 `--config <profile>` 全仓死旗(无任何脚本消费) | Medium | 同上 |
| M5 | 三面壳+契约四处「随 `.mgh-init/` gitignore」承诺未兑现(全仓无任何脚本写 gitignore;银行环境误提交风险) | Medium | `grep gitignore core/scripts/` 零命中,实位确认 |
| M6 | 三面镜像非白名单漂移聚合:Output 节行文不对称、assemble_rules 表格单元两样、缓存句两样(M1 是其特例) | Medium | 三面壳 diff 聚合,实位确认 |
| M7 | opencode fanout agent 的 ack 形态与其 stage prompt 的 Return-to-orchestrator 段不一致:agent 枚举了 stage 未定义的 `oversize`(scout 面 stage 只定义 `ok`/`failed`)——约 8 个 fanout agent 同病 | Medium | `init-scout-fanout.md` vs `init-scout.md` L159-162,实位确认 |
| M8 | `init-scout-audit.md` frontmatter `bash: deny`,但其 stage prompt L50 明确授权该 agent 经 `py` launcher 调 `chunk_sources.py`(需 Bash);且 agent Input 段未携带切片所需的 `slice_dir` 字段 | Medium | 两文件对照,实位确认 |
| M9 | claude 分发缺 `init-scout-merge-rollup.md` agent 定义,而三面壳的 subagent inventory 表都点名它——claude 面引用悬空 | Medium | `releases/claude-code/agents/` 无该文件,实位确认 |
| L1 | install.sh 分发拷贝不 prune `__pycache__`,本机字节码缓存带进目标项目 | Low | install.sh 无 prune 逻辑,实位确认 |
| L2 | install.sh 成功消息的命令/tier 清单与实际分发面漂移(漏 scout-merge 相关表述) | Low | 收尾 echo 段,实位确认 |
| L3 | `orchestrator-discipline.md` 头注过期:「mgh-init today; mgh-ut-init / mgh-ut to come」——ut-init 已发布 | Low | fragment 头注,实位确认 |
| 待拍板 | opencode 约 22 个 agent 设 `edit: deny`(评审记 13-17,现网 grep 22),但其中多数职责要求 Write 检查点/规则文件;opencode 官方文档称 `edit` 键同时覆盖 edit/write/patch。若真拦,这批 agent 全部无法完成本职 | 拍板项 | frontmatter grep,实位确认;需 live 验证(见 design D8) |

共同根因:分发内容从开发态拷入目标项目时,引用路径没有随安装布局改写;纯净性 lint 只认
「研发编号 / 私有目录」两类死链形态,「源码树路径前缀」(`core/…`)不在其扫描面;壳的参数表
没有与脚本实际消费点(`--help`)对账的机制;agent 定义与 stage 提示词之间没有操作契约同形的
机械校验。修复必须同时落「内容修正」与「lint 兜底」,否则同类死链会随下次分发再生成。

## What Changes

1. **死链修复(H10/H14,含同形态扩展)**:六个 stage 的 codegraph-hint 引用改「同安装 prompts
   树内可达」表述(stages/ 的兄弟 fragments/ 目录——宿主中立,机制同 dsh `t3.md` 正确先例);
   fragment 头注「Inlined … when codegraph=on」失实改述(如实:按 `codegraph=on` 信号 Read 的
   独立 fragment,无内联机制);rules-format 四面引用改各自安装布局路径;同形态顺带修:三面壳
   Output 节的 `core/contracts/init/unit-inputs.md` 死链 → `mgh-core/contracts/…` 安装布局路径。
2. **dsh 派发披露改实况(H9)**:接线 tier 清单补 scout-merge;交互 stage 停止清单闭集枚举补
   T2 单上下文 `init-synthesis`、T2 rollup、scout-merge rollup;`--skip-consistency` 只能在 run
   起始传入、mid-run 不可注入的后果如实披露;停在 t4 时永无终态 manifest 的处置路径(`--resume`
   语义 + 用户显式收尾)写明。
3. **壳参数表与消费点对账(M1–M4/M6)**:`--out`/`--config` 从三面壳 flag 表与 spec 参数集移除;
   claude 补 `--rules-dir` 行;call-graph 缓存句三面统一为实况(cache 跨 run 复用 mtime 失效,
   `--rebuild-cache` 强制重建);Output 节与 assemble_rules 表格单元三面对齐(白名单五类方言差
   异保留)。`check_contracts.py` 扩展:壳 flag 表条目对账 `write_runconfig.py --help`(闭集豁免
   清单显式)。
4. **gitignore 承诺兑现(M5)**:`write_runconfig.py` step 0 原子写 run 配置时同步 co-write
   `<run-root>/.gitignore`(幂等;银行环境敏感产物不入 git)。
5. **agent 定义与 stage prompt 对形(M7/M8/M9)**:fanout agent 的 ack 枚举逐字镜像对应 stage
   prompt 的 Return-to-orchestrator 段(stage 未定义 `oversize` 的从 agent 删该行,dispatcher
   侧 `_parse_ack` 容错不变);`init-scout-audit` 的 `bash` 钉扎改 `allow`(与其 stage 授权的
   chunk_sources 调用同形)+ Input 段补 `slice_dir`;claude 补发 `init-scout-merge-rollup.md`
   agent 定义。
6. **install 卫生与自检扩展(L1/L2/M9 兜底)**:分发拷贝 prune `__pycache__`;install 自检新增
   「壳 subagent inventory 点名的 agent 定义文件必须存在于分发产物」断言(fail-soft,与既有
   自检同形);成功消息清单核准。
7. **lint 兜底(防再生成)**:`check_distributed_purity.py` 新增死链形态——shipped md 中
   `core/(prompts|contracts|scripts)/…` 源码树路径前缀引用 = 违例(合法引用只有安装布局路径
   `<host>/mgh-core/…` 或提示词内兄弟相对表述)。propose 会话实测:该形态在分发面共 **209 行
   命中、约 30 个文件**,横跨六个命令的壳与契约——远超本批(init 切片)的修复面。处置:本批
   只修 init 切片命中并从基线移除,其余存量命中以纯净 lint 既有 allowlist 机制**钉基线放行**
   (新增违例仍即红);全家族扫尾是否独立成批见拍板项 B。`orchestrator-discipline` 头注改述(L3)。
8. **拍板项 A(不阻塞本批)**:opencode `edit: deny` ×22 的 live 验证——单 agent(如
   `init-induct-fanout`)实际跑一个 Write;若被拒 → 按职责放开(与 `init-rulewriter`
   `edit: allow` 先例同形);若未被拒 → 保持钉扎,在本文档记录 opencode 文档断言失实。
   双分支方案见 design D8;验证需维护者在真机 opencode 会话参与一次。
9. **拍板项 B(范围决策,propose 时请维护者选)**:`core/` 前缀死链形态经实测横跨全家族
   (209 行 / ~30 文件,含 mgh-sast/sra/srr/sdr/ut-init 的三面壳与契约),本批只修 init 切片
   并以 allowlist 钉其余基线。后续处置两选:(a) **独立小批全家族扫尾**(推荐——机械改写,
   与本批同修法;各命令壳是三面镜像,须同步面核对;估中等体量、零行为风险);(b) 并入批次 7
   (提示词与契约批量)顺带扫——批次 7 体量已大,塞入 209 行机械改写会稀释其评审密度。

## Capabilities

### Modified Capabilities

- `distribution-purity`:3 条 requirement 修改——「Shipped artifacts are free of dev-only
  provenance and dangling references」(死链类别增补第 10 类:源码树路径前缀引用,含 codegraph-hint
  / rules-format / `core/contracts` 三组实位);「Dangling references resolved by delete-or-graft」
  (失实头注按改述处理,操作性内容保留);「Install self-check and CI regression close the loop」
  (install 自检增 agent 引用存在性断言 + 拷贝 prune `__pycache__` + 成功消息核准)。
- `dsh-command-surface`:1 条 requirement 新增——dsh 派发面如实披露(接线 tier 闭集、交互 stage
  停止清单闭集、mid-run flag 注入不可能性、t4 停止的终态处置)。
- `orchestration-substrate`:1 条 requirement 修改——orchestrator-discipline fragment 头注随
  命令发布状态维护(`to come` 清单只列未发布命令)。
- `control-discovery`:1 条 requirement 修改 + 1 条新增——「Parse arguments and guard zero-token
  no-op」(参数闭集对账消费点:`--out`/`--config` 移除、`--rules-dir` 入表、缓存句实况化);
  新增 run 目录 git 隔离(write_runconfig co-write `.gitignore`)。
- `fanout-dispatch`:1 条 requirement 新增——fanout/审计 agent 定义与其 stage prompt 的操作契约
  同形(ack 枚举镜像 Return 段;权限钉扎与 stage 授权一致)。

### New Capabilities

(无)

## Impact

- **涉改文件(内容面)**:`core/prompts/stages/init-{scout,induct,survey,resolve}.md` +
  `core/prompts/stages/sra-{clarify,augment}.md` + `core/prompts/fragments/codegraph-hint.md`(头注)+
  `core/prompts/stages/init-rulewriter.md` + `core/prompts/fragments/orchestrator-discipline.md`(头注);
  `releases/claude-code/agents/init-rulewriter.md` + 新增 `init-scout-merge-rollup.md`;
  `releases/opencode/agent/init-rulewriter.md` + `init-rulewriter-fanout.md` + 8 个 fanout agent
  ack 对形 + `init-scout-audit.md`;`releases/{claude-code,opencode}/` 两面 `mgh-init` 壳 +
  `releases/dsh/skills/mgh-init/SKILL.md`;`core/scripts/write_runconfig.py`(.gitignore co-write);
  `install.sh`(prune + 自检 + 消息);lint:`tools/check_distributed_purity.py` +
  `tools/check_contracts.py`。壳改动 → `check_distributed_prompt_budget.py` 必跑 + 三面镜像纪律。
- **不改动**:dispatcher 与六域脚本运行行为(`write_runconfig` 的 co-write 是唯一脚本行为增量,
  幂等、不触 run_config schema);守卫三镜像;枚举器。
- **回归面**:`test_distributed_md_purity` / `test_dsh_command_surface` / `test_recipe_visibility` /
  `test_write_runconfig` / `test_zero_deps` / `test_no_compile_warnings` + 契约 lint 三件套;
  实机 install 冒烟一次。
- **拍板项**:edit: deny live 验证(维护者参与,双分支见 design D8)——不阻塞本批其余任务。
- **VERSION**:md/脚本改动 → apply 会话 bump(0.1.70 → 0.1.71)+ CHANGELOG。
