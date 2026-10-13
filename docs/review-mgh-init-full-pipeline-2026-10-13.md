# /mgh-init 全流程深度代码评审报告(2026-10-13)

> **评审基线**:分支 `main` HEAD `6e6ac63`(VERSION 0.1.60),干净树。
> **性质**:研发维护性评审(非运行域,守卫未激活),全量文件评审而非 diff 评审;只评审未改代码。
> **受众**:维护者(人类·仅研发仓)。本文是修复工作的输入,按严重度分组,每条发现带 `文件:行号` 证据。
> **方法**:open-code-review-delegate 流程 —— 以给定清单为起点,与 opencode 壳、`fanout_runner --tier init`
> 引用面、`core/contracts/init/**` 交叉核对出权威评审面 **97 文件**;`ocr delegate rule` 分 7 批解析出
> 2 个规则组(md 通用 / Python 专项);同规则组内按内聚性细分 12 批,每批一个 subagent **逐文件全读**;
> 之后 7 个二次验证 subagent 对全部 29 个 critical/high 候选逐项独立复核(关键结论均含实机复现:
> 在本机构造 `.mgh-init` 产物树、伪造枚举器/孤儿进程、GBK 管道喂守卫 payload 等实验)。

## 修复工作清单(按优先级)

| # | 工作项 | 涉及 | 对应发现 |
| --- | --- | --- | --- |
| 1 | resume 状态机 t1 分片死锁:canonical id 集与枚举器口径合一(含 `--check` 孤儿误报、508-510 死赋值) | `resume_state.py:517` | CR-1 |
| 2 | 守卫 redirect 越树分支对 sast/sra/srr/sdr 四域放行 | `block_adhoc_scripts.py:1353-1366` | H2 |
| 3 | 守卫 stdin 强制 UTF-8(一行修复)+ GBK 管道回归测 | `block_adhoc_scripts.py:1199-1202` | H3 |
| 4 | `--kill-stale` 加 PowerShell CIM 回退(Win11 24H2 无 wmic) | `fanout_runner.py:1369-1377` | H1 |
| 5 | 分发死链:codegraph-hint ×4 处 + rules-format ×4 面(stage prompt / agent 定义) | `init-{induct,scout,survey,resolve}.md`、`init-rulewriter*` | H10、H14 |
| 6 | 哨兵收尾链:done.md 加载可达性 + 两处「残留哨兵只挡脚本写」错误文档 | `resume_state.py:415-420`、`orchestrator-discipline.md:51`、`runtime-enforcement.md:143-145` | H12、H13 |
| 7 | `--merge` 无确定性出口:实现 `merge_inventories.py` 或三面拒绝该模式 | `init-stage/merge.md`、`list_steps.py:176`、`step-manifest.md:92` | H11 |
| 8 | 切片簇失败吞失(簇级计数三分)+ t2 聚合预算改物化口径 | `list_clusters.py:897-902`、`plan_aggregate.py:163-165,529-547` | H4、H8 |
| 9 | expand_scope 三连:单遍 callgraph 改两遍、limit 只计源文件 + 截断告警、`--path` 不存在 fail-loud | `expand_scope.py:143-184,272-275`、`discover_controls.py:284-292,663-665` | H5、H6、H7 |
| 10 | dsh 派发面:补齐披露(T2 单上下文/rollup 均无实例、任何 flag 组合无法完成)或建 delegate | `releases/dsh/skills/mgh-init/SKILL.md:54-61` | H9 |
| 11 | 待实测:opencode `edit: deny` 是否封禁 Write(单 T1 单元 live 验证) | `releases/opencode/agent/init-*.md` | 见「待实测项」 |
| 12 | medium 批量收口(按五类横切根因,见第九节) | 全域 | M1-M68 |

---

## 一、覆盖与方法明细

| 覆盖 | 数量 |
| --- | --- |
| 总文件 | 97(壳 3 / opencode agent 16 / 脚本 20 / 契约 18 / 提示词 40) |
| reviewed | **97 / skipped 0** |

- 权威面构成:清单 19 个脚本之外,交叉核对纳入被 `resume_state.py`/`list_steps.py` 导入的
  `discipline_core.py`;agent 实为 16 个(含 -fanout/-rollup 变体)而非清单所写 11 个。
- 排除项(带理由):`lenses/specialist-hints.md`、`baselines/s2-*.md`(init 链 grep 零引用,
  属 mgh-sast 资产);`fragments/fanout/sdr-task.md`(sdr 域);`sra-*/srr-*` flow fragments
  (sra/srr 域);claude/dsh agent 镜像(镜像不变量由壳承担,另经机械 diff + 抽查核对)。
- 过程披露:12 批中 6 批首轮因供应商侧 `Model request failed`/限流失败,重派后全部完成,
  覆盖率不受影响。

## 二、结论总览

| 严重度 | 数量 | 说明 |
| --- | --- | --- |
| Critical | **1** | 实机复现 ×3 方独立 |
| High | **14** | 全部经二次验证确认 |
| Medium | 68 | 含 11 项由 high 校准降级(均经二次验证) |
| Low(精选保留) | 19 | 其余 low 按政策丢弃 |

二次验证裁决:29 个 critical/high 候选中 **0 个整体误报**;11 项校准为 medium、1 项降 low、
1 项转「待实测」、1 项并入 critical。个别子主张被修正(见第七节)。

## 三、Critical(1)

### CR-1 resume 状态机对含分片簇的 run 永久卡死在 step=t1

**位置**:`core/scripts/resume_state.py:517`(契约侧对应 `core/contracts/init/resume-state.md:52-53,70,126-130`,
方向是**文档对、代码错**)。

`t1_ids = collect_canonical_ids(cl["clusters"], {}, 0, None)` 传了**空候选集和零预算**:该收集器的
`::shard-<n>` 分片派生依赖真实候选与 `--max-unit-bytes`(默认 192KB)算出的分片计划,空入参下
返回值**永只含整簇 id**。而超预算簇经 `list_clusters` 物化后只派发 shard 级单元、只写 shard 级
`.done`/`.failed` marker,整簇 marker 无任何写入者 → `resume_state.py:610` 的
`(t1_done + t1_failed) < clusters_total` 恒真 → **step 永卡 t1**,而 `list_clusters`(簇级口径)
报 done=total/pending=0,dispatcher 空转,编排器按纪律(进度纯信 resume_state)无限循环。目标
环境(数百万行 Java 仓,分布式注解簇极易超 192KB)下分片是**常态而非边角**。

连带:`--check` 用同一退化 id 集,把合法 shard marker 误报为「孤儿 marker」advisory,对该 livelock
本身反而零违例;`508-510` 行的首个赋值被 517 行无条件覆盖(死代码 + 二次 `_load_json`);manifest
已在的完成态 run 也受波及(闸门排在 manifest 检查之前)。

**验证**:三方评审者独立发现 + 验证 C 与验证 G 各自实机复现(单簇切 2-3 shard 全 touch `.done`:
`list_clusters` 报 `{done:1,pending:0}`,`resume_state` 报 `{done:0,total:1}` + `step=t1`,输出逐字一致)。

**修复方向**:与枚举器口径真正合一 —— 回查 `controls_candidates.json` 真实候选 + run_config 预算
复算分片计划,或改用「整簇 marker 存在 OR 其全部分片 marker 终态即算该簇终态」的兜底口径;补
「分片簇全 done → step 越过 t1」回归测试;顺带删 508-510 死赋值。

## 四、High(14,均经二次验证确认)

### 状态机与脚本域

**H1** `core/scripts/fanout_runner.py:1369-1377` — **`--kill-stale` 在 Windows 11 24H2+ 上静默全瘫**。
`_pid_cmdline` Windows 分支只依赖 `wmic`,本机(build 10.0.26200)实测 wmic 已被系统移除 →
`FileNotFoundError` → 恒返回 `""` → liveness 匹配恒失败 → 孤儿进程一个杀不掉且 `exit 0, killed:[]`。
实机复现:构造真活孤儿(cmdline 含 `opencode run --agent init-induct-fanout`)→ `--kill-stale --dry-run`
报 `none:true`;换 PowerShell CIM(`Get-CimInstance Win32_Process`)后同一数据立即正确分类。硬杀后
的孤儿清理唯一指定工具在主开发平台静默归零,CI 因全 mock 探测不可见。修复:wmic 外加 CIM 回退链。

**H2** `core/scripts/block_adhoc_scripts.py:1353-1366` — **redirect 越树拦截对 sast/sra/srr/sdr 四域
整体放行**。`_is_out_of_tree` 为真后复用 `_redirect_in_sanctioned`,而后者对无 allowlist 域直接
`return True`("no-allowlist => OK to proceed")→ 1361-1366 的越树 block 对四域是不可达死代码。
实测:sdr 域 + 声明 read_roots + `echo x > <readroot>/f` → **exit 0 全链路放行**,直接违反「声明
只读根永不可写」铁律;允许集外目标仍被规则 m 拦但报的是读侧 recipe(引导错位)。根因是同一
helper 被用在语义相反的两个调用点(树内 P1 白名单检查 vs 树外拦截豁免)。注:与已披露残余①
(未知写动词写只读根)部分重叠,但 redirect 规则是专为该形态建的已知写形状规则,属**未披露的
接线回归**。修复:树外分支显式判 out_roots,四域统一「树外 + 授权根内放行,其余拦」。

**H3** `core/scripts/block_adhoc_scripts.py:1199-1202` — **stdin 未强制 UTF-8,中文 Windows(GBK
locale)下守卫整域静默休眠**。`json.load(sys.stdin)` 在 cp936 管道下把 UTF-8 payload 解成
mojibake → `cwd` 锚点坏 → 哨兵向上 walk 失败 → `domain is None` → **六域全部规则对每次调用
静默放行**(实测 A/B:同一份 UTF-8 字节,utf-8 stdin 下 exit 2 拦截,gbk stdin 下 exit 0)。
受影响面 = claude 面(payload 带 cwd)与 dsh 面(shim 传 session cwd)—— `C:\Users\<中文名>\...`
正是中文 Windows 默认布局;三端宿主侧均发 UTF-8 字节,错在守卫 decode。原报告的
「UnicodeDecodeError 被吞」机制经查在 Windows 上不可达(surrogateescape),实际机理是锚断裂,
**比原报告更严重**。修复一行:`sys.stdin.buffer.read().decode("utf-8","replace")`;补 GBK
管道回归测。

**H4** `core/scripts/list_clusters.py:897-902`(packed 路径 `:626-640` 同病)— **切片簇「全单元终态
但含失败」被残差公式计为 done,failed 吞失**。`clusters_failed` 只统计整簇 `.failed`,shard 全终态
时簇落入 done:实测 1 簇 2 片全 `.failed` → stdout `{done:1, failed:0, pending:0}`,违反契约
「failed = 终态失败单元(整簇+分片同判)」;后果:跨 run 的 shard 失败对 `--retry-failed` 链路
不可见、报告披露失真。修复:簇级计数三分(全 done→done;≥1 failed 且无 pending→failed;否则
pending),packed 路径同步。

**H5** `core/scripts/expand_scope.py:163-184` — **build_call_graph 单遍扫描,顺序依赖**。
`name_to_files` 边走边建,文件 A 的调用只能解析到 rglob 顺序中**先于 A** 的文件里定义的名字 →
约**一半跨文件边静默丢失**(丢失边不进 `unresolved[]`,零披露),双向图与 bfs 扩展同受影响。
实验:两 java 文件仅交换文件名,`in_scope` 从 1 个变 2 个。同仓 `discover_controls.py:345-386`
有正确的两遍实现(注释自证语义已知),而 mgh-sast 的 scope resolver 直接 CLI 调用本脚本。
修复:改两遍(全量建 def 索引后再解析调用)。

**H6** `core/scripts/expand_scope.py:143-148`(+ `discover_controls.py:284-292` 哨兵失灵)—
**limit 配额被非源文件消耗 + 静默截断**。`limit_files`(默认 20000)对通过过滤的任意扩展名文件
计数(.txt/.xml/.sql/资产均耗配额),触顶静默 `return` 零告警;discover 侧「max_files+1+truncated」
哨兵建立在「limit 只数源文件」的错误假设上。实验:2 万个 .txt + 2 个 .java → 只 yield 排在前的
1 个 .java,`truncated:False`。大仓(mybatis xml/配置/资产)现实可达,丢哪些文件随枚举序不可
预测,违反「截断须显式告警」。修复:limit 只计源文件;触顶 stderr 告警 + truncated 上浮。

**H7** `core/scripts/expand_scope.py:272-275` + `discover_controls.py:663-665` — **`--scope
path:<不存在目录>` 静默空集**。目录不存在与「无源文件」不可区分:exit 0 + 空集 + 零告警;
mgh-init 侧空 seed 过滤掉一切候选 → 拼错一次路径产出「该模块无存量控制」的**错误安全结论**,
mgh-sast 侧丢全部 findings。违反闭集参数拒歧义输入纪律。修复:`d.is_dir()` 为假 → stderr
告警或 exit 2(`--package` 无匹配同治)。

**H8** `core/scripts/plan_aggregate.py:163-165,529-547` — **t2 节点预算按紧凑序列化计量,物化
文件可超预算 ~23%**。t2 分桶/瘦身全用 `_byte_len`(紧凑、无 envelope/indent/CRLF),落盘写
`indent=2` + envelope + Windows CRLF;实测 96KB 预算下物化 121KB(1.23×),凡触发 part 切分
必超;`item["bytes"]` 丢弃 `st_size` 按紧凑值低报。scout-merge 节点已用 `_materialized_bytes`
修正,t2 属漏改,测试只断言紧凑字段故照过 —— 违反「已派发 shard 两节点恒 ≤ 预算」硬不变量
与诚实边界承诺。修复:t2 统一改 `_materialized_bytes`,`bytes` 回填 st_size,补「落盘 ≤ 预算」
回归测。

### 分发面与提示词域

**H9** `releases/dsh/skills/mgh-init/SKILL.md:54-61` — **dsh 派发面披露不完整且有事实错误,任何
flag 组合都无法在 dsh 完成 mgh-init**。(a) SHALL 停止清单漏列 T2 单上下文 `init-synthesis`、
T2 rollup、scout-merge rollup 等无派发实例的交互 stage —— **即使聚合不超预算(单上下文路径)
T2 也必停**,不止 reduce 段;(b) 已接线 tier 清单写「scout/t1/t2/t3」漏 scout-merge(实态与
`gen_dsh_tiers.py` REQUIRED_TIERS/测试断言矛盾,文件内部 :54 与 :71 自相矛盾);(c) 唯一完整
路径连「--no-scout + --skip-consistency」也不成立(T2 无跳过 flag);(d) mid-run 无法改投
`--skip-consistency`(run_config 不覆盖)、停在 t4 永无终态 manifest/report 未交代。修复:补齐
披露,或给 T2/rollup 建 delegate 实例;至少如实声明「dsh 仅能跑确定性+波次段」。

**H10** `core/prompts/stages/init-induct.md:67-76`(同款 `init-scout.md:96`、`init-survey.md:24`、
`init-resolve.md:38`)— **codegraph-hint 引用研发仓死路径 + fragment 头注虚假「内联」声明**。
要求 Read `core/prompts/fragments/codegraph-hint.md`,目标项目实际装在 `<host>/mgh-core/prompts/...`,
`core/` 路径不存在;fragment 头注自称「Inlined into the task message when codegraph=on」但全链路
(`_fill_template`/任务模板/agent 定义/壳)grep 零内联机制。同文件 39-42 行毒输入规则规定锚内
路径 Read 失败 → 立即回 `failed` ack → 弱模型按字面执行会把簇误判失败。codegraph=on 时四个
stage 每个单元暴露。修复:内联机制落地,或引用改宿主中立相对表述。

**H11** `core/prompts/fragments/init-stage/merge.md:9` + `core/scripts/list_steps.py:176` +
`core/contracts/init/step-manifest.md:92` — **`--merge` 模式无任何可执行路径**。三面壳 flag 表
声明可用、resume_state 会把编排器路由到 step=merge,但 `merge_inventories.py` 全仓不存在(仅
两处死引用),fragment 只有一行散文 → 编排器拿到 `script_abs:null` 只能即兴 LLM 合并(无 gate、
无确定性去重),违反「机械重活下沉确定性脚本」。修复:实现脚本或在三面拒绝该模式(exit 2)+
清死引用。

**H12** `core/prompts/fragments/init-stage/done.md:2-14` — **done.md 经声明的加载机制不可达,
收尾纪律(尤其哨兵移除)无人执行**。`_FRAGMENT_STEPS` 明确排除 done(「done has no further
load」),壳亦无 done.md 固定路径加载(仅 bootstrap 有),壳自己写「空纪律仅对 done 步合法」=
承认什么都加载不到。后果:done 步独有的「`rm <target>/.mgh-init/.active`」、manifest 收尾纪律
在长跑/压缩后不可达(bootstrap 的同款指令只在 fresh-run 起始加载),**run 完成后哨兵残留** →
与 H13 叠加。`--check` 不查 done 后哨兵残留。修复:done 加入 `_FRAGMENT_STEPS` 或壳写固定
路径加载 recipe。

**H13** `core/prompts/fragments/orchestrator-discipline.md:51` +
`core/contracts/hooks/runtime-enforcement.md:143-145` — **「残留哨兵只挡脚本写、不挡
JSON/.md/读」与守卫实现矛盾**。实测守卫对 init/ut-init 域哨兵激活时拦截受信子树
(`.mgh-init`/`.claude/rules`/`docs/security-controls` + out_roots)外**一切写,任何扩展名**,
树外读亦拦 → 残留哨兵 = 目标项目日常开发会话的全面写锁定(bootstrap.md 自己警告的「锁死
日常开发」)。两处文档给良性预期,会让维护者误判无害而不清理。修复:改述为真实语义并同步
两处;建议加回归测断言哨兵激活时子树外 .md/.json 写被拦。

**H14** `releases/opencode/agent/init-rulewriter.md:23-25`(fanout 孪生 `:29-31`、stage prompt
`core/prompts/stages/init-rulewriter.md:30,33`、claude 面
`releases/claude-code/agents/init-rulewriter.md:19-20` 同病)— **rules-format fragment 引用
研发仓死路径**。T3 每次运行必选一种 format,引用写
`core/prompts/fragments/rules-format-{claude,opencode}.md`(目标项目不存在),dsh 面
`releases/dsh/agents/t3.md:24-25` 已正确写 `mgh-core/prompts/...` 证明是漏改;毒输入规则同样
放大为 failed ack。缓解:Format selection 段内联了两格式要点摘要。修复:四面引用改安装布局
路径(或相对 stage prompt 的表述)。

## 五、Medium(68,按域分组;标 ★ = 经二次验证由 high 校准降级)

### 守卫域(7)

- `block_adhoc_scripts.py:816-853` — `_out_of_tree_mutation` 不认哨兵 out_roots:同一授权写根,
  Write/Edit 工具面放行、redirect 放行、Bash 写动词却拦(三入口结论翻转;
  `_emit_bash_write_block` 的 out_roots 形参是死参数)。
- `block_adhoc_scripts.py:674-689` — 解释器正则的负向前瞻 `(?!-(?:c|m)\b)` 对带空格形式无效
  (死代码);`py -m pytest <树外.py>`、`py -c "..." <树外.py>` 的尾随参数被误当执行脚本拦截。
- `block_adhoc_scripts.py:1203-1210` — 判定用 `Path.cwd()`、哨兵激活锚用 payload `cwd`,两来源
  可错根;opencode 插件 normalize() 不构造 cwd 字段。
- `block_adhoc_scripts.py:222-244` — `python3.11`/`python3.12` 带点版本号绕过全部 `py -c` 内省
  与 heredoc 检测(版本段正则不含点号)。
- `block_adhoc_scripts.py:704-719` — 规则 l 把引号内字符串字面量(如
  `grep -n "mgh-core/scripts/run.py" notes.md`)当磁盘引用,触发最重的 stop-all 阻断。
- `releases/dsh/plugins/mgh-guard.ts:116-141` — 守卫文件缺失时 python 的「can't open file」
  退出码恰为 2,与阻断退出码同值 → 三端误判 deny(与 fail-soft 契约「file moved → PASS」矛盾)。
- `discipline_core.py:386-398` — `get_discipline` 返回共享可变结构(表本体引用/浅拷贝
  `_EMPTY`),消费方一次 append 即永久污染跨域纪律表。

### fanout_runner(6)

- `:2588-2597` — 前置熔断退避挂起 + 队列空 + 冷却未到期 = 无 sleep 的 100% CPU 忙等(默认 300s)。
- `:1095-1106` — `_run_unit` 忽略 `_kill_tree` 返回值、POSIX 无 SIGKILL 升级 → 杀失败时单元
  重入队与幸存进程**并发双跑**、竞写 checkpoint,且 pid 从 liveness 摘除变成不可追踪孤儿。
- `:777-789` — path-drift 拦截(防投毒输入)的响应动作是**向被检测为越树的那个路径**写
  failed marker + mkdir ——「检测到投毒后反而执行投毒路径」。
- `:1479-1485` — `--kill-stale` PID 复用守卫的 cmdline 匹配用 `cl.find(h) >= 0` 子串匹配,
  任意位置含 opencode/claude/dsh 的无关进程被整树强杀。
- ★ `:2684-2689` — 收尾 failed 计数双计(枚举器已计入本次写入的 marker,又
  `+ len(failed_written)`;实测 3 单元 1 failed 输出 failed=2)。六 tier 全中;测试因
  `_disk_stub`/`--pending-file` 冻结计数而不可见。仅污染摘要计数,编排器终态判定走磁盘
  marker,故降 medium。
- ★ `:1027-1046` — spawn 未剥离 PWD(姊妹脚本 `mgh_sdr_launch.py:354` 已修同形并注明
  opencode 按 `PWD ?? cwd` 解析项目);主路径 cwd=repo 不受影响,触发面 = out-of-host 手动
  运行,降 medium。

### 状态机 / discover(13)

- ★ `discover_controls.py:792-835` — `--check` 对「JSON 可解析但 wrapper 形状错」裸崩
  (traceback + exit 1,违反 exit 2 + violations 契约);str 子项不崩(原报告该子项误报)。
  原子写产物下畸形输入主要来自外部篡改,降 medium。
- ★ `merge_scout.py:231-244` — scout 簇与 regex 簇 cluster_id 碰撞无守卫(重复 id → 二次物化
  幂等覆盖 → 一侧候选静默丢失 + 双派发,实验证实后果);但确定性触发路径不可达(scout 候选
  无 pattern 字段、文件级排除挡住集中式碰撞),残余触达 = LLM 漂移,降 medium。
- ★ `init_tier.py:207-228` — `stale_marker_paths` 漏 `checkpoints/t2/shards/` 下 marker →
  跨 run 过期凭证恢复时 marker-aware 判 shard 已完成,rollup 吞旧 summary、新增 scout 候选
  静默丢弃(实验复现);且 t2 done shard 无重置路径(validate 失败后修复死循环)。触达需
  跨 run 残留状态,降 medium。
- ★ `init_tier.py:187-195` — `scout_complete` 对损坏 scout_plan fail-open(截断 plan →
  batches=0 → 判「scout 完成」→ 整层静默跳过,--check 零违例,实验复现);触发概率低
  (plan_scout 写入窗口)但后果是查漏层整体消失,降 medium。
- `resume_state.py:912-932` — `--invalidate-stale` 不复用「scout 启用+未完成」前置判定(对
  no_scout/scout 已完成的 run 会删有效凭证迫使 T2-T4 全量重跑);unlink 失败仍 exit 0;与
  `--check`/`--rearm-sentinel` 组合时静默短路。
- `resume_state.py:530-531` — t3 计数仍裸 glob 口径(孤儿 marker 抬高 done 可静默跳过 pending
  category;check 的孤儿审计只扫 scout/t1)。
- `resume_state.py:598-649` — step 派生永不产出 survey/resolve/t4(三 fragment 头部「Loaded
  per-step via resume_state」是虚假声明;T4 纪律仅靠 next_action 一句话兜底,压缩后恢复到
  「assemble 完、T4 未跑」时 stage_flow_files 只给 assemble.md)。
- `discover_controls.py:389-616` — scan 续点缓存键不含 `--scope/--language`(换参续跑产出
  新旧参数混合候选集,静默)。
- `discover_controls.py:345-602` — callgraph 两 pass 内无软时限检查(最贵阶段不设防,超宿主
  上限即被硬杀、零缓存零 checkpoint 落盘,「零全损推进」在该阶段不成立)。
- `discover_controls.py:404-450` — scan checkpoint 每 `--progress-every` 全量重写累积候选列表
  (O(n²) 写放大,大仓 GB 级冗余写)。
- `plan_scout.py:191-192` — scout_plan.json 裸 `write_text` 非原子写(同族都有
  `_atomic_write_json`),是上条 fail-open 的主要触发供给。
- `merge_scout.py:235-246` — fold-in 对 controls_candidates/clusters 双文件重写均非原子 +
  跨文件不一致窗口(`_foldin_done` 只查 provenance 键 → candidates 已并但 clusters 缺 scout
  簇时带病进 T1,--check 无违例)。
- `merge_scout.py:178-231` — fold-in 对「合法 JSON 但形状错误」输入多处裸崩(audit 路径完全
  绕过 --check;anchor 非 dict 通过 --check 后在 form_clusters 崩)。

### 枚举 / 聚合 / 装配(7)

- `list_scout_batches.py:281-285` — pending 的 checkpoint/done/failed 路径用裸 bid 拼,判定侧
  却走 `forward_marker_paths` 编码(该 import 是死 import);bid 一旦含 `:`/超长,广告路径与
  判定路径分叉 → 无限重派(正是正向计算要消灭的缺陷类)。
- `list_rule_jobs.py:92-133` — done/failed 判定全程 glob + 记录体/stem 反推(违反正向计算
  家族不变量;三枚举器中唯一无 orphan 审计、唯一私有拷贝 `_safe_name`)。
- `expand_scope.py:119-127` — EXCLUDE_DIR/dotfile 剪枝检查绝对路径全部分量:repo 放在
  `D:\build\...`、`~\.cache\...` 等祖先目录下 → **整仓静默扫空**(实测)。
- `assemble_rules.py:210-221` — 受管块合并对孤儿哨兵(begin 无 end)不设防:下次重跑从孤儿
  begin 替换到追加块 end,**静默删除两哨兵间用户内容**;双完整块只替换第一个。
- `plan_aggregate.py:620-631` — needs_reduce 时每页 stdout 携带完整 `rollup.summary_paths`
  (1000 shard ≈ 100KB),击穿 64KB orch 预算承诺。
- `fanout_runner` TIERS(`:518-616`)+ `core/contracts/init/unit-inputs.md:74-75` — run_config
  记录的 `budgets.max_unit_bytes` **主路径无消费者**(runner 不透传 `--max-unit-bytes` 给
  scout/t1/t3 枚举器):用户传 `--max-unit-bytes 65536` 时切分仍按默认 192KB,预算静默失效。
- `plan_scout.py:76-83,130-139` — `--check` 对损坏 plan 退出码 1(merge_scout 同类失败用 2,
  闸门 recipe 只认 2);plan 未记录生成预算 → 自定义批字数的合法 plan 在缺省 --check 下回退
  循环。

### scout / 切片(3)

- `chunk_sources.py:35-103` — JAVA_DEF 把 `while/for-each/catch/switch/synchronized` 块识别
  为函数节点(实机验证):大文件按循环体而非方法体切、外层方法 line_end 被截断;Java 是
  首要目标语言。
- `chunk_sources.py:171-186` — `--in` 指向不存在文件静默成功(空骨架 exit 0,subagent 路径
  typo 得到「成功+空产物」)。
- `merge_scout` fold-in 未映射类别 skip+warn 与契约「fold-in/--check 边界 fail-loud」承诺
  不一致(仅 --check 侧 exit 2;audit 路径无闸门)。

### 壳 / agent 定义(9)

- `releases/claude-code/commands/mgh-init.md:68` — call-graph 缓存句事实错误且句内自相矛盾
  (「rebuilt each run」vs「mtime-based skip」;实现是缓存命中复用,opencode/dsh 面正确)。
- `releases/claude-code/commands/mgh-init.md:24-25` — claude flag 表缺 `--rules-dir` 行(flag
  表增删不属白名单五类)。
- 三面壳 `--out`(opencode 壳:26)— 命令级 flag 无任何消费点(run_config 不记录、assemble
  canonical 调用行不传,resume 后漂移回默认);与 `write_runconfig --out`(run_config 路径)
  同名异义,桥接即写错位置。
- 三面壳 `--config`(opencode 壳:32)— 死旗:全仓零消费方(14 个脚本 --help 均无),用户
  传参被静默吞。
- 三面壳(opencode:74)—「随 .mgh-init/ gitignore」未兑现:无任何脚本/install 写 .gitignore,
  银行环境有内部产物误提交风险。
- `releases/claude-code/commands/mgh-init.md:70-82` — 三面镜像漂移聚合:Output 节展开不对称
  且丢「T1 经 list_clusters 枚举,禁手搓内省」半句、flag 表措辞/拆行差异、assemble_rules
  描述分歧等(白名单外)。
- `releases/opencode/agent/init-induct-fanout.md:37` 等 8 文件 — ack 形态与所引 stage prompt
  的 Return-to-orchestrator 段不一致(枚举了 stage 未定义的 oversize / ok 参数占位符漂移)。
- `releases/opencode/agent/init-scout-audit.md:9-10` — `bash: deny` 与 stage prompt 授权
  chunk_sources 切片直接矛盾(跑 py 只能走 Bash),且 Input 未传 slice_dir,授权悬空。
- ★ claude 分发缺 agent(验证 E):主路径靠 `claude -p --agents <inline JSON>` 是**有意设计**
  (archive tasks.md 明证),map 段不断;真缺口收窄为 scout-merge rollup 一步(scout.md:45
  无 claude 装载注记而 t2.md:25 有)+ 罕见手派回退。降 medium:补 rollup 文件或把内联装载
  注记下沉到 scout.md。

### stage 提示词(11)

- ★ `init-induct.md:11-29` — T1 stage prompt 完全未覆盖 Form B pack 形态(t1-task.md:48-68
  定义 pack_id/members[]):「unit = cluster_id 行的值」在 pack 形态下会写 pack id →
  validator 的 unit≠cluster_id 违例 → rm .done 重派循环;pack 默认关闭(opt-in)且模板侧
  指令正确、零推进熔断兜底,降 medium。
- `init-synthesis.md:29-38` — 「本聚合节点无硬阈值」陈述过时(T2 硬闸门 + partial/rollup
  已落地,姊妹篇 scout-merge 已改写,唯本文件漏改)。
- `init-rulewriter.md:122-128` — oversize ack 时是否 touch done_marker、是否写规则文件完全
  未规定(T3 是 oversize 真实可达的 stage;partial/手派重派下会反复重派)。
- `init-scout.md:135-137`(+`init-resolve.md:111-113`)— evidence_snippet 被列入「简体中文
  对象」与同文「逐字源码行」定义矛盾(弱模型会把代码行翻译成中文,破坏证据锚定)。
- `init-rulewriter.md:99-103` — 13 份中唯一缺读侧三件套(锚 repo 根/NEVER 越界/Bash 搜索
  同禁)的 stage。
- `init-induct.md:49-65` — 输出 schema 只给 kind 六枚举,category 未列 canonical 8、未给
  category→kind 映射(闸门会拒自造类名,烧配额)。
- `init-survey.md:14-32` — Task 第 1 步用 repo 相对路径(与其余 12 份「绝对路径 verbatim」
  纪律矛盾),且读侧白名单字面禁止读第 1 步要求读的两个文件(互斥指令)。
- `init-rules-consistency.md:5-8` — opencode 评审对象写成「managed block」(与 Task 4/预算段
  的详述文件矛盾,还诱导去动明令禁止的哨兵)。
- `init-stage/t2.md:9-12` — resume 直落 t2 时 T1→T2 闸门被静默跳过(marker 派生纯磁盘;最后
  单元 done 后、闸门前被打断 → 破损记录不带校验进综合)。修复:t2 fragment 加无条件前置
  `validate_t1_records --check`(幂等)。
- `orchestrator-discipline.md:16-18` — 「三条 NEVER」摘要与 fragment 实际(两条提示词级 +
  Read 叶源码已降级 hook 拦截)漂移,五处壳引用旧版。
- `rules-format-claude.md:48-52` / `rules-format-opencode.md:64-69,82-86` — `--check` 覆盖面
  夸大(「any leak」/T1/T2/T3 词;脚本 FORBIDDEN_TOKENS 有意排除裸 tier 词与
  category:/source:/evidence:)—— 泄漏恰在被承诺覆盖的项上无确定性兜底。

### 契约(12)

- ★ `resume-state.md:14-45` — CLI 缺 `--run-root`/`--rearm-sentinel`(后者被 bootstrap 明确
  指示使用)、stdout 示例缺 `discipline_reminders`/`stage_flow_files`/`stale_fanout` 三个
  恒存在且壳明确消费的字段、--check 清单缺哨兵违例(实装 exit 2)。
- ★ `step-manifest.md:80-93` — Step→IO 表 4/12 行漂移:scout/t1/t3 的 script 应为
  `fanout_runner.py`、t2 应为 bash(runner)而非 subagent「—」、scout 漏 extra_invocations;
  失同步约 7 周横跨 4 次架构演进。运行时零影响(编排器消费 list_steps stdout),降 medium。
- `clusters.md:37` — cluster_id 公式失真:集中式实为 4 段(含 file 槽位),判别尾是 sha1 前
  12 hex 非「sha8」(按 8 hex 解析 id 尾的校验会全失配)。
- `scout-plan.md:39-47` — 通篇引用 plan_scout 不存在的 flag 名(`--scout-batch-bytes` 等三名
  是 write_runconfig 层),照契约构造调用行直接 argparse 报错。
- `unit-inputs.md:20-22` — 「done 检测读 unit 字段」是 forward-marker 重设计前的陈旧陈述
  (与另两份契约的「NEVER 读记录体」矛盾)。
- `unit-inputs.md:55-62` — bytes/oversize 语义按 tier 漂移未分列(scout=批声明字节,t1/t3=
  文件字节);「NEVER 以原始形态进请求」与 scout/T3 oversize 照发矛盾。
- `manifest.md:44-60` — 幻影条目:i1/resolve 的 checkpoint 形状全仓无产出者;「unit record」
  形状亦无产出者。
- `aggregate-sharding.md:46-48` — stdout 示例 `bytes:150000 > budget 98304` 与同文件「恒 ≤
  预算」不变量冲突(旧时代残留)。
- `cluster-enumeration.md`/`scout-enumeration.md`/`rule-jobs.md` — CLI flag 清单大面积缺
  (`--materialize/--offset/--limit/--orch-budget-bytes/--include-failed` 等)、stdout 缺分页
  四字段、`total == done+failed+len(pending)` 恒等式在默认分页/页收紧下不成立、pack 模式
  18 份契约零记载。
- `candidates.md:49-50` — source 枚举含幻影值 `regex+scout`(全仓无产出者)。
- `cluster-enumeration.md:56` — 「记录内 unit = canonical cluster_id」与 t1-record-schema
  的 shard 场景(unit=cluster_id=shard id)矛盾,照写会触发 validator 违例。
- ★ `resolved.md` + `init-stage/resolve.md:18` — resolved.json 的 additive 并入无任何确定性
  出口(list_clusters 物化不读它、全仓无 fold-in 脚本):设计把「按簇键路由候选」这类纯
  机械工作留给弱编排器徒手执行,大概率不发生;富化实质值(候选进 T1-T3)无机械通道。
  resolve 为 optional + codegraph-gated,降 medium。

## 六、Low(精选 19;其余按政策丢弃)

- ★ `core/prompts/stages/init-scout.md:40` — `regex_known[]` 幽灵输入字段:全链路无
  producer(plan_scout 只产计数),「Do not re-report」无从执行。无确定性失败面,降 low。
- `core/scripts/describe_artifact.py:122-134` — `--field` 单独使用无界输出(整份
  clusters/candidates 倾倒进 stdout,正是该脚本要替代的反模式;建议 value 截断 +
  truncated 标志)。
- 三枚举器 `--limit` 未校验 <1(空页 + effective_limit=0,按 offset 推进的编排器原地自旋);
  `--offset` 有校验,不对称。
- `list_clusters.py:133` — `MAX_UNIT_FILENAME_STEM = 200` 本地重定义遮蔽同名 import(自称
  alias 实为独立副本,死代码)。
- `fanout_runner.py:681-683` — `_safe_name` 私有拷贝已与 `init_tier.safe_unit_filename`
  漂移(无 200 截断:超长 id 的 .task.md/.run.log 超 NTFS 255 上限写入失败仅 warn)。
- `init_tier.py:33-50` — `safe_unit_filename` 截断编码存在中段碰撞理论风险(两 id 前 140 +
  末 59 字符相同仅中段不同 → 同 marker 路径);建议判别尾改内容寻址(sha1[:8])。
- `write_runconfig.py:80-85` — 原子写缺 flush/fsync(掉电后 os.replace 可能完成而
  run_config 零长度,崩溃恢复锚点持久性缺口)。
- `write_runconfig.py:225-232` — 哨兵 domain 派生自 `--run-root` 名而位置派生自
  `--init-dir`,显式组合可分歧(激活错误域的受信子树)。
- `chunk_sources.py:174-176` — `--line 0` 因 `if args.line:` 真值判断静默落骨架模式(应为
  `is not None` + ≥1 校验)。
- `block_adhoc_scripts.py:339-342` — 净网正则左边界字符类缺 `<`,`>D:/out/f` 无空格重定向
  形态提取不到 token(与 H2 联动时彻底无拦截)。
- `block_adhoc_scripts.py:583-585` — f2 叶源码拦截的路径段比较大小写敏感
  (`.CLAUDE/Mgh-Core/Scripts` Windows 变体绕过)。
- `block_adhoc_scripts.py:145-179` — 模块 docstring 规则 (m) 说明段整段粘贴两遍(编辑事故,
  将来只改一处会产生内部矛盾)。
- `install.sh:55-92` — 分发拷贝把本机 `__pycache__` 带进目标项目(core/scripts 与 hooks 下
  实际存在);建议拷贝后 `find -name __pycache__ -prune -exec rm -rf`。
- `install.sh:261` — 成功消息 tier 清单漏 scout-merge(与 gen_dsh_tiers 实际生成集不符)。
- `orchestrator-discipline.md:2-4` — 头注过期(ut-init 已发布仍写「to come」;「every mgh-*」
  过度声明,实际消费集仅 init/ut-init)。
- `init-stage/t2.md:25` — 「openmode」笔误(应为 opencode,全仓唯一)。
- `controls-context.md:49` — 「中和」中英混杂笔误。
- `self-verification.md` / `severity-guidance.md` / `exhaustiveness.md` — 无加载者孤儿
  fragment,仅作 s4-system 手工组合副本消费,却随 install 分发(双真相源无字节包含回归测;
  与 init 链无消费关系)。
- `resume_state.py:461-471` — merge 模式 stdout 缺 `stale_fanout` 字段(契约承诺「field
  always present」,消费方 KeyError)。

## 待实测项(非误报,需一次 live 验证裁决)

`releases/opencode/agent/` 约 13-17 个 agent 设 `edit: deny` 但职责必须 Write 检查点。
opencode 官方文档称 edit 键覆盖 edit/write/patch —— 若当前版本如此,这些 agent 的 Write 全
被拒。反向证据:维护者 2026-09 的 T1 真机记录(docs/opencode-fanout-runner-guide.md)显示
deny 下单元照常完成(可能模型静默走 bash 回退,守卫对 .mgh-init 内 bash 写放行),且
init-rulewriter(产物是 .md)是 `edit: allow`,说明「edit 管文件写」是已知事实、checkpoint
写手被 deny 与其 Write 指令自相矛盾。建议:单 T1 单元 live 验证 Write 是否被拒;若拒,按
rulewriter 先例给检查点写手 `edit: allow`,或改显式 bash 写 recipe。

## 七、二次验证与校准记录(29 个 critical/high 候选的去向)

| 去向 | 数量 | 条目 |
| --- | --- | --- |
| 确认 critical | 1 | CR-1(三方独立 + 两轮实机复现) |
| 确认 high | 14 | H1-H14(其中 H2/H3/H4/H5/H6/H7/H8/H9 相关项含实机实验) |
| 校准 high→medium | 11 | discover --check 崩溃、簇 id 碰撞、t2 shard 过期凭证、scout_complete fail-open、claude agent 缺失、Form B、resolved.json、step-manifest 表、resume-state.md 缺字段、failed 双计、PWD 未剥离 |
| 校准 high→low | 1 | regex_known[] 幽灵字段 |
| 转待实测 | 1 | opencode edit:deny vs Write |
| 并入 critical | 1 | resume-state.md 契约侧(与 CR-1 同根,方向为文档对代码错) |

子主张修正(核心成立但细节被纠正):stdin 编码问题的失败机制实为「surrogateescape
mojibake → 哨兵锚断裂 → 整域休眠」(比原报告的「异常吞掉」更严重,Windows 上该异常路径
不可达);`discover --check` 的 str-子项不崩(其余畸形形状确认崩);dsh 披露的遗漏范围比
原报告更大(单上下文 T2 也断,不止 reduce 段);「哨兵移除指令只在 done.md」校准为
「bootstrap 亦有但长跑压缩后不可达」。完全整体误报:**0**。

## 八、经核验无问题的面(正面结论)

- **三端接线不变量通过**:守卫 12 工具分派集 ⊆ claude matcher(12)⊆ opencode HANDLED(12)
  ⊆ dsh TOOL_MAP(12+别名),无死分支;canonical 与两个 releases 镜像副本字节一致。
- **三面壳镜像纪律基本成立**:diff 差异绝大多数落白名单五类;壳内 10 项默认值
  (96KB/40/15/192KB/64KB/96KB/200KB/8/1000/15000)与 argparse 逐项一致;壳内出现的脚本级
  flag 与 `--help` 全部对上,无契约破裂。
- fanout TIERS 表与 5 个任务模板的 placeholder 集逐字节相等;`.failed` marker「dispatcher
  写、subagent reference only」职责一致;枚举 stdout 字段名与契约一致。
- `t1-record-schema` 三方一致(schema / init_tier 常量 / validator 规则);7 份契约完全干净
  (describe / discover-cache / inventory / resolved / rules-detail / skeleton /
  t1-record-schema)。
- `form_clusters` 经 import 复用无语义漂移;原子写体系(write_runconfig / discover /
  resume_state 的 `_atomic_write_json`)基本到位;零依赖、utf-8 文件读写、stdout/stderr
  分流在绝大多数脚本上成立。
- 分发纯净性(agent 定义 / fragment 中的研发私有引用)零命中;security-dimensions 的维度
  键与三处脚本逐项锁步。

## 九、总体判断(修复排序依据)

流水线的**架构纪律**(正向 marker、磁盘化 resume、原子写、受管块、三端单一判定源)设计
扎实且大部分兑现;问题集中在五类横切根因,medium 收口建议按根因分批:

1. **口径分裂** —— 同一计数/编码/预算在枚举器、resume、tier 定义间多份实现(CR-1、
   list_scout_batches 裸拼、list_rule_jobs 反推、t2 预算紧凑口径、failed 双计全属此类);
2. **研发仓路径随原样拷贝进入分发产物变成死链**(H10、H14,且被毒输入规则放大为
   failed ack);
3. **per-step 加载机制与步骤派生图不同步**(H12、survey/resolve/t4 死文件、t2 闸门
   跳过);
4. **fail-open 残留**(H3 守卫休眠、scout_complete fail-open、--invalidate-stale 无前置,
   与全仓 fail-loud 文化相悖);
5. **契约/文档滞后于 dispatcher 化重构**(resume-state / step-manifest / unit-inputs /
   scout-plan 等,约 7 周失同步)。

建议修复顺序:CR-1 → 守卫双 high(H2/H3)→ H1(kill-stale)→ 分发死链双 high(H10/H14)
→ 其余 high → 口径分裂类 medium 一并收口。
