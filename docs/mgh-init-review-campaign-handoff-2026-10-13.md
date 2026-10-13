# mgh-init 评审修复战役 · 交接文档(2026-10-13)

> **用途**:换开发环境后继续本战役。输入源 = `docs/review-mgh-init-full-pipeline-2026-10-13.md`
> (2026-10-13 全流程评审:1 Critical + 14 High + 68 Medium + 19 Low,零整体误报,关键结论均实机
> 复现)。修复按七批独立 openspec change 推进;本文档承载当前进度、剩余批次的自包含规划、以及
> 规划期间累积的接地情报(新会话不必重新考古)。
> **工作模式**(维护者已确认):指挥部会话负责逐批 propose(每批动笔前重新核实 HEAD),apply +
> archive 在新会话执行(`/opsx:apply <change>` → 实施者按 tasks.md 先红后绿 → `/opsx:archive`),
> 循环至七批完成。

## 一、当前进度

| 批次 | change | 状态 |
| --- | --- | --- |
| 1 | `fix-mgh-init-resume-state-machine` | ✅ 已 apply(2ae05fb)+ 归档(15f72b2),VERSION 0.1.68 |
| 2 | `fix-mgh-guard-enforcement-integrity` | ✅ 已 apply(37a9b9b)+ 归档(4b35700),VERSION 0.1.69 |
| 3 | `fix-mgh-fanout-dispatcher-hygiene` | ✅ 已 apply + 归档(1557e4d,archive/2026-10-13-fix-mgh-fanout-dispatcher-hygiene),VERSION 0.1.70;specs 5 MODIFIED 已回写主规格 fanout-dispatch 并随该提交推送 |
| 4 | `fix-mgh-init-distribution-links` | ✅ 已 apply + 归档(8b7e7a8,archive/2026-10-13-fix-mgh-init-distribution-links),VERSION 0.1.71;specs 5 能力 8 条已回写;拍板项 A/B 状态见三.14 |
| 5 | `fix-mgh-init-enumeration-caliber` | ✅ 已 apply + 归档(archive/2026-10-14-fix-mgh-init-enumeration-caliber),VERSION 0.1.72;specs 11 MODIFIED 已回写主规格(control-discovery 5 / request-context-budget 3 / fanout-dispatch、resume-step-discipline、rules-emission 各 1);apply 期新发现见三.15 |
| 6-7 | 见第四节 | 未 propose |

**下一步**:指挥部会话说「propose 批次 6」;批次 4 拍板项 A/B(三.14)回执仍开放。

## 二、批次 2 摘要(apply 前必读)

范围:守卫域 13 项(H2 redirect 越树四域放行、H3 stdin 未强制 UTF-8〔GBK 中文 Windows 守卫整域
休眠〕、H13 哨兵残留文档失实 + M×7 + L×3)。

关键裁决(实施者必须遵守,详见该 change 的 design.md):

- **D1 统一写目的地谓词,按域镜像工具面**:三个写入口(Write/Edit 工具面 / Bash 写动词 / redirect)
  同判——init/ut-init 树外目的地经哨兵 `out_roots` 豁免(与工具面同一查询 `_allowlist_write_blocked`),
  四域(sast/sra/srr/sdr)树外一律拦(镜像其工具面);**`read_roots` 在任何写面永不豁免**。评审字面
  的「四域也放行授权根」被否——会造成新的工具面 vs Bash 面翻转。
- **D7 双 shim 同修**:opencode 插件与 dsh shim 都把 code===2 当 deny,守卫文件缺失时 python
  「can't open file」退出码恰为 2 → 误判 deny;两面都加 `existsSync` 预检 + stderr 签名兜底。
  (opencode 面同病是规划期新发现,评审只点名了 dsh。)
- **镜像同步纪律**:`core/scripts/block_adhoc_scripts.py` 改后 MUST 字节级同步
  `releases/claude-code/hooks/` 与 `releases/opencode/hooks/` 两份副本(parity 测试强制)。
- tasks.md 有 9 组先红后绿回归;GBK 管道测试用
  `io.TextIOWrapper(io.BytesIO(utf8_payload), encoding="gbk")` 替身。

## 三、接地情报与坑(本会话累积,勿重复劳动)

1. **行号漂移警告**:评审基线是 0.1.60(`6e6ac63`);之后 5 个 mgh-sdr 修复 change 落地。
   `fanout_runner.py` 被重写 293 行(a092e65)——**批次 3 的评审行号全部失效,必须按内容重定位**;
   `runtime-enforcement.md` 挪了 28 行(批次 2 已处理);`describe_artifact.py` 挪了 19 行
   (d1a1f23 修的是 `--field` 索引守卫,评审 Low 的「--field 无界输出」是另一件事,仍开放,归批次 6)。
   其余评审涉改文件经 git diff 核实自基线零改动。
2. **已被 sdr 批次顺带修掉(勿重修)**:H1(kill-stale wmic 失效,CIM 回退)、fanout 退出摘要
   failed 双计(均为 a092e65)。
3. **批次 1 的锁步注记**:批次 5 修 runner 预算转发(`--max-unit-bytes` 透传给枚举器)时,
   `resume_state.py` 的 t1 复算预算必须**同一 change 内**从共享默认常量切到 run_config 值
   (批次 1 design D1 + 代码注释已落,漏掉会复活 CR-1 死锁)。
4. **每批 propose 前重新核实 HEAD**:`git log --oneline -3` + 对涉改文件
   `git diff --stat <基线>..HEAD -- <files>`(本会话两批均如此执行,成本很低)。
5. **SDD 工件禁引 `docs/` 路径**(R5.11,purity lint 强制):提到评审报告用「维护者私有文档区的
   mgh-init 全流程评审报告(2026-10-13)」;发现编号(CR-1/H2/M*/L*)可引用但要**自包含描述**,
   不让读者翻原文。
6. **proposal 人话序必写**:blockquote 开场(~200-300 字,现象→根因→改什么→怎么验证);
   `check_plain_language.py` 的 exit 2 是既有噪音(四个更早的活跃 change 缺人话序),与本战役无关。
7. **openspec 流程**:`openspec new change "<name>"` → 按 status --json 的依赖顺序写
   proposal → specs → design → tasks(每步可 `openspec instructions <artifact> --change <name>
   --json` 取模板)→ `openspec validate "<name>" --strict` + `py tools/check_distributed_purity.py`
   收尾。MODIFIED requirement 必须**整块复制原文后改**,场景用恰好 4 个 `#`。
8. **指挥部会话只产 `openspec/changes/**` 工件**,不改产品代码;apply 归 apply 会话。
9. **解释器**:本机(Windows)`py` 可用、`python` 是 Store 占位;**换环境后先探测**
   `py --version; python --version` 取可用者(仓库两套文档各写一个,都有历史原因)。
10. 若想提前连产多批 propose(不 apply):可以,但行号/前提漂移风险自担,每批仍须核实当时 HEAD;
    维护者先前确认的默认节奏是「一批一 propose、apply 后再下一批」。
11. **工作树并行提交记录**:批次 2 propose 期间,另一会话归档了 `fix-mgh-sdr-multibranch-findings`
    并回写两份主规格(31ae96c:`runtime-hook-enforcement` 净网/file-search/listing 三 requirement
    统一补 glob 通配语义;`security-design-review` launcher 单命令外壳 ①–⑧;另含真仓回归 f091565)。
    批次 2 的净网 requirement delta **已重定基到含 glob 段的现行文本**,归档不会覆盖;该提交属 sdr 域,
    与本战役各批次无范围交集(其 launcher PWD 剥离是 `mgh_sdr_launch.py` 面,批次 3 的
    `fanout_runner` spawn PWD 项仍然开放)。换环境前本战役需提交的内容 = 本文档 +
    `openspec/changes/fix-mgh-guard-enforcement-integrity/`。
12. **存量测试失败(批次 3 实测,勿追查)**:`TestRateLimitStorm.
    test_all_rate_limit_storm_truncates_fast`(test_fanout_runner)在本机 Python 3.14 上
    **HEAD 4b35700 即失败**(waves_run 3 != 2,干净 worktree 5/5 复现;屏障构造拦不住两次
    crash 记账窗口之间的第三次补位派发)——批次 3 落地后依旧失败,与本批改动零关联。批次 5
    (runner 预算转发)与任何要跑 `test_fanout_runner` 的批次都会撞上:对照 worktree 确认
    非自己引入即跳过,是否修测试确定性留维护者拍板。
13. **批次 3 落地后的 runner 新形态(批次 5 必读)**:`_run_unit` 返回 5→**6 元组**
    (新增第 6 元 `kill_ok`,杀失败 False;17 处测试 unpack 已同步);`_dispatch` 消费
    `kill_ok=False` 走「幸存者拥有单元」分支(不回队 + drain re-list 排除 +
    `_breaker_observe(wsnap, stuck_pending)` 新操作数);`_kill_tree` POSIX 侧有
    `_KILL_TREE_GRACE_S=1.5` 宽限(真杀最坏多 ~1.5s);`_write_failed_marker` 签名多了
    `repo` 参数且返回 bool;`_safe_name` = `init_tier.safe_unit_filename` 别名;kill-stale
    的 `_classify_targets` 走 `_cmdline_exe_token`(引号 span 优先)。批次 5 动 TIERS/
    转发面时以这些形态为基线,NEVER 按旧记忆改。
14. **批次 4 落账与两个拍板项回执(VERSION 0.1.71)**:分发死链/披露/对账/gitignore/install
    卫生全量落地,先红后绿,定向面 + install 三面实机冒烟(opencode/claude/dsh,零
    `__pycache__` 落标)全绿。**落地增量情报**:(a) 第 10 类死链实测比 propose 多 3 处命中
    (init-survey 头注注释 `core/contracts/init/`、sra-clarify/sra-augment 的 security-dimensions
    引用),同形态并入 init 切片修掉——init 切片以外的存量命中以
    `tools/purity_allowlist.txt` 钉基线(**186 行**,propose 估 209 含 init 切片;lint 自动
    加载、基线外新增即红、陈旧钉扎与计数上限由 `test_distributed_md_purity` 检出);
    (b) claude 面 `init-scout-audit.md` 的 `tools:` 白名单同样否定 stage 授权(缺 Bash 与
    Write,与 opencode `bash: deny` 同病不同方言),已按 stage 授权补齐——M8 的冲突面
    实为双面而非单面;(c) dsh SKILL.md 派发披露段原含「本 change 未建具名派发实例」
    dev-meta 措辞(变更夹名族,纯净性 lint 的第 4 类只匹配 kebab 全名故未报),已随 H9
    改述移除,后续改披露段时勿回填;(d) `write_runconfig.py` 新增 `--check`(run_config
    缺失 exit 2、sentinel/gitignore 缺失 warn),批次 6 若做该脚本原子写加固时在同一个
    `--check` 面上扩展。
    **拍板项 A(不阻塞,待维护者参与)**:opencode `edit: deny` ×22 的 live 验证——真机
    opencode 会话对 `init-induct-fanout`(T1 波次主力)跑单单元,观察其 Write 是否被拒;
    被拒 → 按 `init-rulewriter`(`edit: allow` 先例)批量放开 22 面(双分支方案全文见该
    change 归档 design D8);未被拒 → 保持钉扎,记录「opencode 官方文档对 edit 键覆盖面
    断言失实」于本情报区。
    **拍板项 B(范围决策,待维护者选)**:第 10 类基线 186 行(约 30 文件,横跨六命令
    三面壳 + 契约)的全家族扫尾:(b1) 独立小批机械改写(推荐——与本批同修法:契约引用改
    安装布局路径、stage/fragment 引用改兄弟相对表述;各命令壳三面镜像须同步核对;零行为
    风险);(b2) 并入批次 7 顺带扫(批次 7 体量已大,209→186 行机械改写会稀释其评审密度)。
    两案均须同步把 `tools/purity_allowlist.txt` 对应条目删净(基线只减不增)。

15. **批次 5 apply 期新发现(批次 4 遗留,未在本批修)**:`test_fanout_runner::
    TestAgentCloneParity::test_clone_hard_constraints_and_output_match_base` 在 HEAD 8b7e7a8
    即红(stash 对照确认):批次 4 删了三面 **fanout 克隆** agent(init-scout/induct/rulewriter-fanout)
    的 `oversize` ack 枚举,但 **base** agent(init-scout/induct/rulewriter,opencode+claude 两面)
    的回传 ack 行仍保留 `oversize <绝对路径>` → 克隆 parity 断言(Hard constraints/Output 段逐字同)
    失败。修法 = base 面同步删该枚举(与批次 4 同判:stage Return 段未定义 oversize ack),双面镜像
    同步;归批次 6/7 的分发面对账面顺带修,或独立一行小批。

## 四、剩余批次自包含规划(propose 时直接取用)

### 批次 3 — fanout_runner 派发器剩余(change 名建议 `fix-mgh-fanout-dispatcher-hygiene`)

✅ **已完成**(0.1.70,1557e4d;落地形态与增量情报见三.13,历史规划保留于下):

评审行号失效(见三.1),按内容重定位:

- **冷却期 100% CPU 忙等**:前置熔断退避挂起 + 队列空 + 冷却未到期 = 无 sleep 的自旋(默认 300s)。
- **`_kill_tree` 返回值被忽略 + POSIX 无 SIGKILL 升级**:杀失败时单元重入队与幸存进程并发双跑、
  竞写 checkpoint,pid 从 liveness 摘除成不可追踪孤儿。
- **path-drift 拦截的响应动作反写越树路径**:检测到投毒输入后,响应却是向被检测为越树的那个路径写
  failed marker + mkdir(「检测到投毒后反而执行投毒路径」)。
- **`--kill-stale` PID 复用守卫的 cmdline 匹配用子串包含**:任意位置含 opencode/claude/dsh 的无关
  进程被整树强杀。
- **spawn 未剥离 PWD**:opencode 按 `PWD ?? cwd` 解析项目(姊妹脚本 mgh_sdr_launch.py:354 已修
  同形);主路径 cwd=repo 不受影响,触发面 = out-of-host 手动运行。
- **Low**:`fanout_runner._safe_name` 私有拷贝已与 `init_tier.safe_unit_filename` 漂移(无 200
  截断:超长 id 的 .task.md/.run.log 超 NTFS 255 写失败仅 warn)。

Spec delta:`fanout-dispatch`(a092e65 归档时同步过 2 条 MODIFIED,可参照)。测试:
`test_fanout_runner` / `test_fanout_stale` + zero_deps/no_compile_warnings;**harness 调
`fanout_runner.main()` MUST 显式 `--cooldown-s 0`**(R5.8,漏传 = 单测静默挂 5 分钟)。注意该文件
六域共用:定向面跑完顺带确认 sdr tier 用例(test_fanout_runner 内)零回归。

### 批次 4 — 分发死链与壳/agent 面(建议 `fix-mgh-init-distribution-links`)

- **H10 codegraph-hint 死链 ×4**:`core/prompts/stages/init-{induct,scout,survey,resolve}.md` 要求
  Read `core/prompts/fragments/codegraph-hint.md`,目标项目实际装在 `<host>/mgh-core/prompts/…`,
  `core/` 路径不存在;fragment 头注自称「Inlined … when codegraph=on」但全链路零内联机制。同文件
  毒输入规则规定锚内路径 Read 失败 → 立即回 `failed` ack → 弱模型按字面执行会把簇误判失败。修:
  引用改宿主中立表述(或落地内联机制)。
- **H14 rules-format 死链 ×4 面**:T3 引 `core/prompts/fragments/rules-format-{claude,opencode}.md`
  (目标项目不存在);涉及 opencode agent `init-rulewriter.md`(+ fanout 孪生)、stage prompt
  `init-rulewriter.md`、claude 面 agent;dsh 面 `t3.md` 已正确写 `mgh-core/prompts/…`(漏改实锤)。
  修:四面引用改安装布局路径。
- **H9 dsh 派发披露**:`releases/dsh/skills/mgh-init/SKILL.md` SHALL 停止清单漏 T2 单上下文
  `init-synthesis`、T2 rollup、scout-merge rollup 等无派发实例的交互 stage(单上下文路径也必停);
  已接线 tier 清单写「scout/t1/t2/t3」漏 scout-merge(文件内自相矛盾);mid-run 无法改投
  `--skip-consistency`;停在 t4 永无终态 manifest 未交代。修:补齐披露或建 delegate 实例;至少
  如实声明「dsh 仅能跑确定性 + 波次段」。
- **待实测项(需维护者参与 live 验证)**:opencode 约 13-17 个 agent 设 `edit: deny` 但职责必须
  Write 检查点;opencode 官方文档称 edit 键覆盖 edit/write/patch。单 T1 单元 live 验证 Write 是否
  被拒;若拒 → 按 init-rulewriter(edit: allow)先例放开,或改显式 bash 写 recipe。
- **壳面 medium ×9**:claude 壳 call-graph 缓存句事实错误且自相矛盾;claude flag 表缺 `--rules-dir`
  行;三面壳 `--out`(命令级)无消费点且与 `write_runconfig --out` 同名异义;三面壳 `--config`
  全仓死旗;「随 .mgh-init/ gitignore」未兑现(银行环境误提交风险);三面镜像漂移聚合(Output 节
  不对称等,白名单外);opencode 8 个 fanout agent 的 ack 形态与 stage prompt 不一致(枚举了未定义
  的 oversize/ok 占位);`init-scout-audit.md` `bash: deny` 与授权 chunk_sources 矛盾且 Input 未传
  slice_dir;claude 分发缺 scout-merge rollup agent(真缺口收窄为此 + 手派回退)。
- **Low**:install.sh 分发拷贝把本机 `__pycache__` 带进目标(拷贝后 prune);install.sh 成功消息
  tier 清单漏 scout-merge;orchestrator-discipline.md 头注过期(ut-init 已发布仍写 to come)。

注意:壳改动 → `check_distributed_prompt_budget.py` 必跑 + 三面镜像同步;三面壳是逐字镜像纪律
(方言差异仅白名单五类)。Spec:propose 时查 `openspec/specs/`(dsh-command-surface、
orchestration-substrate、agents-md-discipline 等)选归属。

### 批次 5 — 枚举/聚合/切片口径(建议 `fix-mgh-init-enumeration-caliber`)

- **H4 切片簇失败吞失**:`list_clusters.py` 簇级计数三分(全 done→done;≥1 failed 且无 pending→
  failed;否则 pending),packed 路径同病——实测 1 簇 2 片全 `.failed` → stdout `{done:1,failed:0}`,
  shard 失败对 `--retry-failed` 不可见。
- **H8 t2 聚合预算物化口径**:`plan_aggregate.py` t2 分桶/瘦身用紧凑 `_byte_len`,落盘 indent=2 +
  envelope + CRLF,实测 96KB 预算物化 121KB(1.23×);scout-merge 节点已用 `_materialized_bytes`
  修正,t2 属漏改;`bytes` 字段低报。修:统一改物化口径 + bytes 回填 st_size + 「落盘 ≤ 预算」回归。
- **runner 预算转发**(与批次 1 锁步,见三.3):fanout TIERS 不透传 `--max-unit-bytes` 给 scout/t1/t3
  枚举器,run_config `budgets.max_unit_bytes` 无消费者;修复时 resume_state 复算预算同 change 切换。
- 其余 medium:`list_scout_batches` pending 路径裸 bid 拼 vs 判定侧 forward 编码(死 import)→ 广告
  与判定分叉无限重派;`list_rule_jobs` 全程 glob+记录体/stem 反推(唯一无 orphan 审计、私有
  `_safe_name` 拷贝)→ 正向化;三枚举器 `--limit <1` 未校验(空页自旋);`list_clusters` 本地
  `MAX_UNIT_FILENAME_STEM` 重定义遮蔽 import;`plan_aggregate` needs_reduce 时每页 stdout 携带完整
  `rollup.summary_paths`(1000 shard ≈100KB,击穿 64KB orch 预算);`plan_scout` `--check` 对损坏
  plan 退出码 1(闸门 recipe 只认 2)+ plan 未记录生成预算;`chunk_sources` JAVA_DEF 把
  while/for-each/catch/switch/synchronized 块识别为函数节点(Java 是首要目标语言)+ `--in` 不存在
  文件静默成功 + `--line 0` 真值判断落骨架模式;`merge_scout` fold-in 双文件非原子 + 跨文件不一致
  窗口 + 合法 JSON 形状错裸崩 + 未映射类别 skip+warn 与契约 fail-loud 不一致。

Spec:`control-discovery`(T1 枚举 requirement 批次 1 刚改过,注意基于最新主规格)、`fanout-dispatch`、
`scout-tier-gate`。测试:`test_list_clusters` / `test_list_scout_batches` / `test_chunk_sources` /
`test_merge_scout` / `test_scout_plan` / `test_fanout_runner`(TIERS)/ `test_plan_aggregate`。

### 批次 6 — discover/expand 扫描韧性(建议 `fix-mgh-init-discover-resilience`)

- **H5 callgraph 单遍顺序依赖**:`expand_scope.py` `build_callgraph` 边走边建 def 索引,文件 A 只能
  解析到 rglob 顺序中先于 A 的定义 → 约一半跨文件边静默丢失(不进 `unresolved[]`);同仓
  `discover_controls.py` 有正确两遍实现;mgh-sast 的 scope resolver 直接 CLI 调本脚本(sast 侧联动)。
- **H6 limit 配额被非源文件消耗 + 静默截断**:`limit_files`(默认 20000)对任意扩展名计数
  (.txt/.xml/.sql 耗配额),触顶静默 return;discover 侧哨兵建立在「limit 只数源文件」的错误假设上。
  修:limit 只计源文件;触顶 stderr 告警 + truncated 上浮。
- **H7 `--scope path:<不存在目录>` 静默空集**:拼错路径产出「该模块无存量控制」的错误安全结论
  (mgh-sast 侧丢全部 findings)。修:fail-loud exit 2 或显式告警;`--package` 无匹配同治。
- medium 群:`discover --check` 对「JSON 可解析但 wrapper 形状错」裸崩 exit 1(违 exit 2 契约);
  scan 续点缓存键不含 `--scope/--language`(换参续跑混合候选集);callgraph 两 pass 无软时限
  (最贵阶段不设防,超时即零全损);scan checkpoint 每 `--progress-every` 全量重写(O(n²) 写放大);
  `plan_scout` 裸 `write_text` 非原子;`write_runconfig` 原子写缺 flush/fsync + 哨兵 domain 派生与
  位置可分歧;`describe_artifact --field` 单独使用无界输出(值截断 + truncated 标志);
  `expand_scope` EXCLUDE_DIR 剪枝检查绝对路径全部分量(repo 放 `D:\build\…` 下整仓静默扫空)。

Spec:`control-discovery`。测试:`test_init_discover` / `test_discover_resilience` /
`test_init_runtime` / `test_write_runconfig` / `test_describe_artifact` + sast 侧
`test_focus_scope`(expand_scope 共用面)。

### 批次 7 — stage 提示词与契约批量 + 拍板项(建议 `fix-mgh-init-prompts-contracts-sync`)

- **拍板项 H11(propose 时用对比陈述请维护者选)**:`--merge` 模式无任何可执行路径——
  `merge_inventories.py` 全仓不存在(仅两处死引用),三面壳 flag 表声明可用,resume_state 会路由到
  step=merge,fragment 只有一行散文 → 编排器拿到 `script_abs:null` 只能即兴 LLM 合并(无 gate 无
  确定性去重)。选项:(a) 实现 `merge_inventories.py`(确定性合并 + 去重 + `--check`,工作量较大);
  (b) 三面拒绝该模式(exit 2)+ 清死引用 + 契约/step-manifest merge 行同步(轻)。
- stage 提示词 medium ×10:Form B pack 形态 T1 prompt 完全未覆盖(t1-task.md 定义 pack_id/members[],
  「unit = cluster_id 行的值」会写 pack id → validator 违例 → rm .done 重派循环;与批次 5 的 pack
  口径相邻);init-synthesis「无硬阈值」陈述过时;init-rulewriter oversize ack 行为未规定;
  evidence_snippet 被列入简体中文化对象(与「逐字源码行」矛盾,弱模型会翻译代码行);
  init-rulewriter 缺读侧三件套;init-induct 输出 schema 未列 canonical 8 category + 映射;init-survey
  repo 相对路径 + 读白名单字面互斥;init-rules-consistency「managed block」措辞诱导动哨兵;
  orchestrator-discipline「三条 NEVER」摘要与实况漂移(五处壳引用旧版);rules-format 两文件的
  `--check` 覆盖面夸大。
- 契约 medium ×12:`clusters.md` cluster_id 公式失真(实为 4 段含 file 槽位,判别尾 sha1 前 12 hex
  非「sha8」);`scout-plan.md` 通篇引用 plan_scout 不存在的 flag(真 flag 名在 write_runconfig 层,
  照契约构造调用行直接 argparse 报错);`unit-inputs.md` done 检测陈旧 + bytes/oversize 按 tier 漂移
  未分列;`manifest.md` 幻影条目;i1/resolve「unit record」形状无产出者;
  `aggregate-sharding.md` stdout 示例与「恒 ≤ 预算」不变量冲突;三枚举器契约 CLI flag 大面积缺 +
  分页四字段缺 + `total == done+failed+len(pending)` 恒等式在分页下不成立 + pack 模式 18 份契约零
  记载;`candidates.md` source 枚举幻影值 `regex+scout`;`cluster-enumeration.md`「记录内 unit =
  canonical cluster_id」与 shard 场景矛盾;`resolved.json` additive 并入无确定性出口(list_clusters
  不读它、无 fold-in 脚本,富化实质值无机械通道)。
- Low:init-scout `regex_known[]` 幽灵输入字段(全链路无 producer);t2.md「openmode」笔误;
  controls-context.md「中和」中英混杂;self-verification/severity-guidance/exhaustiveness 三个孤儿
  fragment(仅 s4-system 手工组合消费,随 install 分发但无加载者)。

Spec:`control-discovery` / `init-artifacts-reference` / `request-context-budget`(propose 时核对
归属)。测试:`test_distributed_md_purity` / `test_recipe_visibility` / `test_dsh_command_surface` /
contracts lint;提示词改动 → purity + budget lint。

## 五、固定收尾清单(每批通用)

- validate:`openspec validate "<change>" --strict`;`py tools/check_distributed_purity.py`;
  `py tools/check_plain_language.py`(exit 2 = 既有噪音)。
- apply 会话:先红后绿(tasks 1.x 组)、定向测试面(AGENTS.md「改动面 → 测试文件」映射表)、
  VERSION bump + CHANGELOG、`/opsx:archive`。
- 指挥部会话在每批 archive 后:核对该批 commit 落点,再开下一批 propose。
