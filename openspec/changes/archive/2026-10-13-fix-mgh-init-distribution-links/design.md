# fix-mgh-init-distribution-links — Design

> 范围:分发面死链与披露/契约失实(H10/H14/H9 + M1–M9 + L1–L3),内容修正与 lint 兜底并落。
> 全部发现已于 propose 会话按内容在 HEAD 8788c0b 重定位确认;评审行号(基线 0.1.60)早已失效。

## D1 — H10 死链修法:stage 提示词用兄弟相对表述,fragment 头注改述实况

codegraph-hint 的引用修复在**单源 stage 提示词**上做(host 中立,一处修六处受益——六个 stage
共用同一表述形态),不动 agent 定义:

- 引用句统一改为「同安装 prompts 树内可达」形态:`本提示词位于 <mgh-core 安装根>/prompts/stages/;
  所指 fragment 为同树 fragments/ 目录下的 codegraph-hint.md(即 stages/ 的兄弟目录 fragments/)`,
  后接原有 prescriptive 正文(对 batch/接口/调用方走 codegraph 优先)与「codegraph=off 时忽略」
  边界,逐字保留。兄弟相对表述对三宿主同时成立:agent 定义已把 stage 提示词的**绝对路径**钉给
  subagent(`.opencode/mgh-core/prompts/stages/init-scout.md` / `.claude/mgh-core/…` /
  dsh `mgh-core/…`),subagent 按自身钉扎路径换算兄弟目录即可达,NEVER 需要知道宿主前缀。
- **被否**:①落地「内联机制」——新增装载机制面、无消费痛点(信号与 Read 路径已闭环),且
  fragment 自称的 inline 行为从不存在,改述即诚实;②按宿主分别改写单源 stage——stage 是
  单源镜像分发,写死任一宿主前缀都会在另两宿主变死链。
- fragment 头注 `Inlined into the task message … ONLY when … codegraph=on` 改述为实况:
  `Read by the stage agent when the task input signals codegraph=on(独立 fragment,无内联机制)`;
  头注其余溯源/意图段保留。
- **sra 两 stage(sra-clarify/sra-augment)同形修**:propose 实测比评审多两处命中(评审记
  ×4、实为 ×6),同句同修,不另立 finding。

## D2 — H14 修法:per-host agent 定义写安装布局绝对路径(dsh 先例)

rules-format 的四个引用面分两类:

- **per-host agent 定义(claude `init-rulewriter.md`、opencode `init-rulewriter.md` +
  `init-rulewriter-fanout.md`)**:每个文件本就只服务一个宿主,引用写该宿主安装布局绝对路径
  (`.claude/mgh-core/prompts/fragments/rules-format-*.md` / `.opencode/mgh-core/…`)——
  dsh 面 `t3.md` 的根级 `mgh-core/prompts/…` 即正确先例,逐字对齐其形态。
- **单源 stage `init-rulewriter.md`**:与 D1 同形,兄弟相对表述(fragments/ 兄弟目录)。
- opencode 两个 agent(交互 + fanout)与 claude 一个 agent 的操作语义行(`--format` 决定格式
  手册、NEVER 混用)逐字保留。

## D3 — H9 披露面修法:闭集枚举 + 不可注入性 + 非终态处置(见 dsh-command-surface delta)

SKILL.md 派发披露段四处改实况:接线清单补 `scout-merge`(与同文档脚本行对齐);停止清单闭集
补 T2 单上下文 `init-synthesis`、`init-synthesis-rollup`、`init-scout-merge-rollup`;
`--skip-consistency` 注明「run 起始参数,mid-run 不可注入,需跳过 = 以该 flag 重新 bootstrap、
磁盘进度幂等承接」;停在 t3 后 T4 未跳过 = 无终态 `init_manifest.json` 的形态与 `--resume`
收尾写明。设计取向:**只修披露与清单,不新增任何 delegate 实例**——评审的「补齐披露或建
delegate 实例」二选一取披露(dsh 的交互 stage 具名实例是 dsh-agent-surface 的独立议题,体量
与验证面都超出本批;披露如实化已消除「即兴内联执行」的失败形态)。

## D4 — M1/M2/M6 壳面对账:三面同文 + 消费点对账

- `--out`/`--config`(命令级)从三面壳参数表移除:实测无任何脚本消费(run 目录由 write_runconfig
  的 `--init-dir/--run-root` 承载,`--out` 还与该面同名异义)。移除后传之 = 未知 flag fail-loud,
  与「闭集参数拒歧义」既有语义一致。
- claude 面补 `--rules-dir` 行(与 opencode/dsh 同文)。
- call-graph 缓存句三面统一:`Call-graph cache is reused across runs (invalidated by source
  mtime/size); --rebuild-cache forces a rebuild.`(claude 旧句「rebuilt each run」与自己的
  括号互斥,删)。discover_controls 实况即缓存复用语义,无行为改动。
- Output 节/assemble_rules 表格单元三面对齐(白名单五类方言差异保留;align 以 opencode/dsh
  现行文为基,claude 面孤例措辞并入)。
- **对账 lint(M3/M4 的防再生成)**:`check_contracts.py` 扩展一类断言——壳参数表的 `--x`
  条目 ∈ 消费脚本 `--help` 并集(`write_runconfig.py`/`discover_controls.py`/…,闭集豁免清单
  显式:`--help`/`--target` 等纯壳面旗)。实现取「提取壳参数表行 → 逐条对账」,存量两死旗先红。

## D5 — M5 gitignore 兑现:write_runconfig 确定性 co-write(镜像哨兵先例)

`write_runconfig.py` 落盘 run_config.json 的同一函数内 co-write `<run-root>/.gitignore`
(内容单行 `*`;`exists` 则跳过——幂等,NEVER 覆盖用户手改)。选脚本副作用而非壳/编排器动作:
与哨兵 co-write 同形(「脚本一跑该文件必在」,不依赖编排器纪律),resume/重跑幂等安全。
被否:①改文案删承诺——银行环境误提交是评审确认的真实风险,机制兑现优于撤承诺;②install 时
写——run 目录在 run 时才存在。`--check` 增 warn 级存在性报告(不阻断)。

## D6 — M7 ack 对形:stage prompt 为真相源,agent 删未定义形态

八个 opencode fanout agent 的「回传有界 ack」段逐字对齐各自 stage 的 Return-to-orchestrator
闭集:scout 面 stage 只定义 `ok`/`failed` → agent 删 `oversize` 行;其余 tier 按 stage 现行
文本对形(t1/t3 的 stage 若定义了 oversize 则保留)。dispatcher `_parse_ack` 的 oversize 容错
**不变**(运行时容错与文档对形是两层;stage 侧将来补 oversize 立法时 agent 回填即可)。
核对动作本身落测试:提取 agent ack 枚举行 vs stage Return 段的形态词集,断言前者 ⊆ 后者。

## D7 — M8 scout-audit:bash 放开 + Input 补 slice_dir(stage 授权为准)

实测证据链完整:stage L50 明确授权该 agent「仅 `chunk_sources.py` 且仅当需切片大文件」经
`py` launcher 绝对路径调用(需 Bash),frontmatter 却钉 `bash: deny`——钉扎否定授权,审计的
大文件复核路径不可执行。修:`bash: allow`(钉扎与授权一致;stage 的「其余确定性脚本由编排器
调用」收窄句与全部 NEVER 边界保留——bash 的允许面被 stage 文本天然收窄,无需 frontmatter
表达细粒度);Input 段补编排器透传的 `slice_dir` 字段(授权命令的 `--out` 落点),编排器手派
路径的透传清单同步补。**edit: deny 的 22-agent 疑云不在本批修**(见 D8)。

## D8 — 拍板项 A:edit: deny ×22 live 验证(维护者参与,双分支)

opencode 官方文档称 frontmatter `edit` 键覆盖 edit/write/patch;22 个 agent(评审记 13-17,
现网 grep 22)钉 `edit: deny` 而多数职责要求 Write 检查点/规则文件。验证方案:真机 opencode
会话对代表性 agent(建议 `init-induct-fanout`,T1 波次主力)跑单单元,观察其 Write 是否被拒:

- **分支一(被拒)**:按职责放开——与 `init-rulewriter`(`edit: allow` 先例)同形,批量改
  22 面 frontmatter + 三面镜像核对;改动属「权限钉扎与职责一致」范畴,可作独立小 change 或
  经本 change 的追加任务清单由维护者确认后执行。
- **分支二(未被拒)**:保持钉扎,记录「opencode 官方文档对 edit 键覆盖面的断言失实」于交接
  文档(情报区),零代码改动。

验证需维护者参与(消费一次真实 LLM 调用),不阻塞本批其余任务;本批 tasks 将其单列为可选
尾任务,结果回填交接文档。

## D9 — M9/L1/L2 install 面修法

- **claude 补发 `init-scout-merge-rollup.md`**:以 opencode 面同名 agent 为源做 claude 形态
  镜像(frontmatter 语言差异按白名单;正文引用路径用 claude 安装布局),三面 agent 集合
  对账入 install 自检(壳 subagent inventory 点名的 agent 文件 MUST 存在于各平台分发集;
  fail-soft 告警 + CI 断言,与 purity 自检同形)。
- **`__pycache__` prune**:镜像拷贝后 `find <dest> -name __pycache__ -type d -prune -exec
  rm -rf {} +`(bash 面;Windows 由 install.ps1 同形 `Remove-Item -Recurse -Force`)——拷贝
  排除与拷贝后 prune 二选一取 prune(对 rsync/cp 两种实现都稳健)。
- **成功消息核准**:install 收尾 echo 的命令清单与 tier 相关表述对齐实际分发面(含
  scout-merge;不列不存在条目)。

## D10 — lint 兜底与基线(第 10 类 + allowlist 钉基线)

`check_distributed_purity.py` 新增第 10 类:`\bcore/(prompts|contracts|scripts)/` 在 shipped
md 中命中即违例(合法 = `<host>/mgh-core/…` 安装布局或兄弟相对表述;对 `core/scripts/*.py`
注释不生效,与 1–8 类口径一致)。**propose 实测**:该形态分发面共 209 行命中、约 30 文件
(六命令三面壳 + 契约 + stage),远超本批 init 切片。处置:

- 本批修复 init 切片命中并**从 allowlist 基线移除**;其余命中以 purity lint 既有 allowlist
  机制钉基线放行(工具 JSON 已有 `allowlisted` 字段,机制现成)。
- 基线外新增命中即红(防再生成);基线只减不增由 CI 断言基线计数单调不增兜底。
- 全家族扫尾 = 拍板项 B(独立小批 vs 并入批次 7),maintainer 选;两案的修法都与本批同形
  (机械改写 + 三面镜像同步),不重新设计。

## D11 — 三面镜像与预算纪律(壳改动的一般约束)

本批碰两面 mgh-init 壳 + dsh SKILL.md:改动后 `check_distributed_prompt_budget.py` 必跑
(壳增删行不越 5K tok 上限,本批为删多补少、预算余量只增);三面镜像逐字核对以白名单五类
frontmatter/召唤语义/执行边界披露/工具名归一/主机机制事实为唯一合法差异。凡涉 shipped md,
apply 会话 bump VERSION + CHANGELOG。

## 批次边界

- 不新增任何 dsh 具名 delegate 实例(D3 披露化方案);不做 edit: deny 批量放开(D8 待 live
  验证);不扫全家族 209 行(D10 基线放行 + 拍板项 B);不碰批次 5/6/7 的枚举口径、扫描韧性、
  提示词批量发现。
- run_config schema 零变化(D5 只加 co-write 文件);dispatcher 零涉及(批次 3 已收口)。
