## Context

mgh 工具族现状(与本设计相关的锚点):

- **`fanout_runner.py`** 已是 tier 无关波次派发器:`TIERS` 表单点映射(枚举脚本/模板/占位符/
  agent/路径字段),波次循环、ack 状态机、三级超时不变式、liveness、`--kill-stale`、零推进熔断、
  sidecar 全部 tier 无关——加 tier = 表加一行 + 模板 + agent 克隆。
- **读侧禁锢契约**(`core/contracts/hooks/runtime-enforcement.md`):活跃守卫按 `MGH_TARGET`
  单根判树,越树 `Read`/`Glob`/`Grep` 与 Bash 搜索动词一律 exit 2 + recipe——设计目的是「不打断
  运行、fail-loud」,它**替换**了宿主权限提示。因此 subagent 读外部前端仓的现状 = 守卫拦截(不是
  权限弹窗),但结果同样是流程中断。跨树读必须有**声明式出口**。
- **哨兵 schema**(`{"domain","target","out_roots[]","v":1}`)已承载写侧 allowlist 扩展
  (`out_roots[]`);`read_roots[]` 是其读侧对偶,双端守卫共享同一 Python 判定核(parity 测试锚定)。
- **`sensitive_catalog.py`** 提供闭集解析/校验/渲染(sibling import 范式);sra/srr 域语义为
  「无目录 → `null` → 6 facet 兜底」,且其 spec 明文「默认模板 MUST NOT 自动应用」。sdr 的
  「无目录 → 回退默认模板」是**跨域行为分歧**,须显式决策(见 D5)。
- **`diff_seed.py`** 的 diff 是「工作树 vs ref」(`git diff --name-status <ref>`),不适用
  branch..branch;`diff_group.py` 需要自己的 diff 采集(`git diff --no-color base..branch`),但不
  复用 diff_seed。
- **launcher 先例**:`install_opencode_plugin.py`(install 期落插件)与 `tools/` 既有研发工具
  形态;opencode `run` 经 stdin 吃任务消息(`fanout_runner._spawn_cmd` 已验证)、claude `-p` 同。
- **约束**:R2(零运行时依赖)、R5.1(`--help` 即契约面 + lint)、R5.2(编排器即宿主 agent、
  黑盒纪律)、R5.3(b)(扇出 = 脚本枚举 + 绝对路径逐字透传)、R5.4(磁盘真相 resume)、
  R5.9(`--check` 边界校验)、R5.10(分发纯净)。目标项目多为企业内网 java web 单仓 + 可能有
  本地前端仓;宿主以 opencode 为主、claude 兼顾。

## Goals / Non-Goals

**Goals:**
- `/mgh-sdr` 端到端可跑:diff → 分组 → fan-out 复核 → 汇总报告,全链路确定性脚本承重、LLM 只做
  per-unit 判定。
- 外部仓(前端)依赖的两个体验/安全问题有结构性答案:权限打断只发生在 launcher 外壳;外部内容
  以**预算受控的结论文件**进上下文,永不整仓涌入。
- fan-out 复用 `fanout_runner` 共享状态机(新 tier 表行),NEVER 复制一份派发循环。
- 幂等 resume、`--check` 边界校验、双端(claude/opencode)对等、守卫 parity 不破坏。

**Non-Goals:**
- 不做漏洞可达性/动态验证(纯设计符合性复核,产出是候选)。
- 不改 sra/srr 的 sensitive_catalog 语义(分歧仅在 sdr 域内实现)。
- 不支持 java web 以外的接口注解启发式(其他项目退化 standalone 模式,不失败)。
- 不做 CI 门禁/定时触发(每日/merge 前手动触发由用户执行 launcher)。
- 不引入 codegraph 硬依赖(可选减扇出信号,见 D8)。

## Decisions

### D1 — 形态:新命令 `/mgh-sdr` + 新 tier `sdr`,而非塞进 mgh-sast 或 mgh-sra

备选 A「mgh-sast 加 `--design-review` 模式」:sast 是逐文件漏洞扫描(9 阶段、SARIF 产物),设计
符合性是 per-接口语义判断,阶段结构/产物/提示词全不同,塞入会同时腐化两者。
备选 B「mgh-sra 加 diff 输入适配器」:sra 中间引擎的单元是 capability/requirement 评审(9 维度
泛扫描),sdr 单元是接口/变更簇的 6 维度定向复核,维度集、基线来源(存量设计 vs 需求文本)、
记录 schema 均不同。
选独立命令 + 独立 tier:① mgh 族命名惯例(sra/srr 已分「注 入/自由文本」两种输入,再分「代码
diff 复核」正交合理);② `fanout_runner` tier 表就是为此类扩展预留的单点;③ 壳/agent/模板/契约
各自独立,不触既有命令的行为面。
〔职责单一 + 复用派发基建 + 不腐化既有命令〕

### D2 — 分组策略:接口维度(注解启发式)+ 目录聚类 standalone,拒绝「每文件一单元」/「纯按目录」

备选 A「每变更文件一单元」:一个 Controller 改 3 个接口 = 3 个重复读同文件的单元,token 翻倍且
类级设计(类注解/拦截器)被割裂。
备选 B「全 diff 一单元」:大 diff 直接爆 subagent 上下文,且失去并行度。
选接口维度分组:Controller 文件内**按接口方法**切(一个接口 = 该方法 hunk + 其类级注解上下文
+ 声明的权限注解/配置命中),`route` 即评审锚点——6 维度中 4 个(两类越权/SQL/校验)天然以
接口为判定单位;剩余文件按目录簇归并(粒度由目录共同前缀决定,`--max-standalone-bytes` 控制
单单元 slice 上限,超限再按文件细分)。启发式失败(无注解)安全退化为 B 的目录簇模式。
〔贴合判定语义 + token 效率 + 失败退化安全〕

### D3 — 外部仓权限问题:声明式 `read_roots[]` + launcher 外壳先期检索,双保险

用户观察正确:opencode(和 claude)对项目外读取会打断询问;而 mgh 守卫更是**主动拦截**越树读
(比权限弹窗更早)。两层各给结构性出口:
- **守卫层(通用能力)**:哨兵增 `read_roots[]`(本 change 对 `runtime-hook-enforcement` 的
  delta)——声明的根对**工具面只读**(Read/Glob/Grep)放行;Bash 搜索动词、写侧全层**不**放行
  (外部根只读、且仅工具面,收窄滥用面)。fail-closed:声明的根不存在时授予零。
- **流程层(sdr 专属)**:`sdr_context.py` 在**编排器主流程**(launcher 进程内)先期完成外部仓
  的全部受控检索,把结论物化为本仓内小文件;subagent task 消息只携带结论文件路径。设计目标:
  **正常路径下 subagent 零跨树读**——`read_roots[]` 是逃逸阀(基线 slice 漏了什么、subagent 需要
  追一个前端引用时可用),不是常规通道。
备选「编排器参数全局放开只读」(如 `MGH_READ_ANYWHERE=1`):一个 env 让全部域的越树读静默放行,
滥用面 = 所有 mgh 命令;拒绝。声明式逐 run 列根,run 结束哨兵即删,暴露面最小。
〔体验:打断只在外壳一次;安全:声明式 + 只读 + fail-closed;通用:read_roots 对全部域可用〕

### D4 — 外部内容上下文预算:结论文件 + 逐仓字节预算 + 透传不内联

`sdr_context.py` 物化的外部结论文件限额(默认 64KB/仓,超限截断 + stdout 披露),内容**白名单
式**:① 权限配置文件中与本分支新增路由的命中行(带文件内行号);② 新增接口路由串在前端仓的
出现计数与文件位置(计数 + 路径列表,NOT 文件正文);③ 外部 diff 的文件清单(变更类型标注)。
NEVER 内联前端源码正文进基线或 task 消息。基线 slice(存量设计投影)独立预算 32KB,按维度优先级
截断。subagent 拿到的外部信息上限 = 结论文件 ≤64KB + 基线 ≤32KB + 单元 slice(≤ 单元预算),
三者相加结构性地 bounded,复用 request-context-budget 的字节阈值经验值量级。
〔防上下文爆炸 + 白名单内容可审计 + 超限显式披露不静默〕

### D5 — 敏感目录:sdr 域内「缺省回退默认模板」,与 sra/srr 显式分歧

sra/srr 语义(目录 null → 6 facet)在其 spec 有「模板 MUST NOT 自动应用」的明文——那是**需求
评审**域的向后兼容门。sdr 是**代码 diff 复核**:输入已是真实代码,收窄到 6 facet 会让公司目录
缺位时的敏感数据检查显著弱于模板(模板 37 项 vs facet 6 项),漏检代价不对称。故 sdr 域内:
项目目录存在 → 复用(sibling import,同一解析/校验);缺失 → 加载 `.example` 模板为生效目录。
三处显式披露(spec Scenario、壳 `--help`、报告/manifest `sensitive_catalog_source`)。实现上
这是**sdr 侧的回退逻辑**,不改 `sensitive_catalog.py` 的任何行为(其「不自动应用」语义在
sra/srr 调用点保持不变)。
〔复核域漏检代价 > 评审域;分歧显式化,不静默改共享模块语义〕

### D6 — 报告落位:项目根 `<工具名>-<分支>-<时间戳>.md`;manifest 留 run 目录

报告是**人消费的一次性产物**(每日触发、merge 前触发),落项目根最贴用户「打开即见」诉求;
文件名含工具名+分支+秒级时间戳满足跨分支/跨次可追溯。run 目录(`<repo>/.mgh-sdr/runs/<ts>/`)
承载全部机器产物(slices/drafts/external/manifest),与报告解耦——manifest 是 `--check` 与
resume 的锚,不随报告进项目根污染。秒级时间戳内重跑 = 原子覆盖同名报告(幂等),跨秒重跑并存
(历史报告不删,用户自管)。
〔人面/机器面分离 + 项目根零机器产物污染 + 幂等〕

### D7 — 运行域与哨兵:`.mgh-sdr/` 第 6 域,launcher 负责生命周期

`MGH_SDR_ACTIVE=1` env 或 `<repo>/.mgh-sdr/.active` 哨兵激活守卫(与既有 5 域同机制,哨兵 JSON
增 `read_roots[]`)。哨兵由 **launcher**(step ② )写、宿主 CLI 退出后删——srd 的编排器是
launcher spawn 出的宿主会话,自身起步不写哨兵(与 init/sra 壳内 `printf` 哨兵不同:launcher
形态下外壳是更可靠的生命周期持有者)。崩溃残留哨兵:下次 launcher 启动检测到同 target 哨兵时
复用并刷新(续跑语义),`--dry-run` 早退时保留哨兵不当次删除(下次续跑仍被保护)。
〔生命周期单点持有者 + 崩溃安全〕

### D8 — codegraph:可选减扇出信号,不进分组依赖

`--no-codegraph` 缺省 auto(`<repo>/.codegraph/` 存在 ∧ PATH 有 codegraph 才 on)。on 时:
`diff_group.py` 分组阶段输出 `codegraph: "on"` 信号,接口单元 subagent 可经 `codegraph explore`
把「同接口内多 hunk」归并判定、把独立变更单元关联到受影响接口(减重复分析);分组数本身**不**
因 codegraph 改变(分组是确定性 diff 几何,不引入图依赖)。off 时零调用、行为等价。信号经模板
占位符逐字透传(与 scout/t1 同形)。作用域收敛在「减重复分析」,不做调用图驱动的切分——那是
mgh-sast 的 tree-sitter 规划,不在本 change。
〔低风险增量:off 零行为差;不重复 sast 的后端规划〕

### D9 — launcher 归属:`core/scripts/` 随 install 分发(人/cron 入口,非宿主 subagent 调用)

launcher 承担「外部仓检索 + 哨兵 + 提示词组装 + spawn」,其唯一调用方是**人/cron**(管理者
`py mgh_sdr_launch.py ...` 或定时工具),**NEVER** 由 `/mgh-sdr` 壳(编排器即宿主)调用——故不
存在「宿主 spawn 宿主」的递归路径(那是把 launcher 误当壳内步骤才有的顾虑)。故 launcher 随
install 分发到 `core/scripts/`(与 `diff_group.py` 等叶脚本同目录,`sys.path.insert(0,
dir-of-__file__)` 自定位 `sdr_context.py` 做外部仓先期检索),管理者无需克隆研发仓即可多分支
sweep。`/mgh-sdr` 壳对**已在宿主会话内**的用户(直接敲 `/mgh-sdr`)也必须可跑:壳 step 0 recipe
指示编排器先跑 `sdr_context.py`(此时外部仓读取发生在宿主 Bash——**可能**触发一次宿主确认,
诚实披露),并把确认后的外部根写入哨兵 `read_roots[]`。launcher 是零打断的**优选**入口,壳内
路径是功能等价的兜底入口;两者共用同一组确定性脚本,无双实现。
〔双入口同一引擎 + 诚实披露 + 无递归宿主(launcher 是人入口,壳 NEVER 调 launcher)〕

### D10 — 脚本契约与纪律落点(逐条对齐 R5.x)

| 规则 | 落点 |
|---|---|
| R5.1 | 三新脚本 `--help` 即契约;双壳调用逐字镜像;`tools/check_contracts.py` DEFAULT_SHELLS + 2 壳 |
| R5.2 | 壳顶部声明编排器=宿主 agent;NEVER Write `.py` / `py -c` 内省 / Read 叶源码;合法出口 = diff_group stdout / describe_artifact |
| R5.3a | 三脚本 stdlib 自包含、utf-8、任意 cwd 可 py |
| R5.3(b) | `diff_group.py --materialize` 是 pending 唯一来源;`pending[]` 全字段 `Path.resolve()` 绝对且在 repo 子树;`unit_id` 文件系统安全命名(NTFS ADS 教训) |
| R5.4 | `.done`/`.failed` marker 磁盘真相;`fanout_runner --resume`;三级超时不变式沿用;launcher 崩溃残留哨兵复用 |
| R5.5 | 壳/模板措辞 recipe + RFC-2119;fan-out 刚性三元组;路径 NEVER 拼装 |
| R5.6 | 壳 ≤5,000 tok lint;细节下沉 `core/prompts/fragments/sdr/`(仅 lazy Read);agent 有效系统 ≤5,000 tok |
| R5.7 | `MGH_SDR_ACTIVE` + 哨兵激活;read_roots 判定进共享 Python 核,双端 parity 测试扩展 |
| R5.8 | install.sh 共定位自检 +3 脚本 + 模板 + agent;回归测清单见 tasks §5;版本 bump |
| R5.9 | `diff_group --check` / `sdr_context --check` / `render_sdr_report --check`;编排器每步后跑,失败回退 |
| R5.10 | 双壳纯操作性内容;purity lint 覆盖新壳;敏感目录分歧在壳内披露为操作语义(非 dev-meta) |

### D11 — 多分支 sweep 仅 launcher 承担;`/mgh-sdr` 壳默认单分支

多分支是**管理者视角**的需求(定时工具 pull 全仓、逐个版本分支检查),天然落在 launcher 这一
人/cron 入口:`--multi-branch <file>`(本地文本,每行一个分支名,`#` 注释忽略)让 launcher 串行
循环,每分支独立 run 目录(`.mgh-sdr/runs/<ts-branch>/`)、独立报告、独立哨兵生命周期;单分支
`diff_group` 退出 1/2 时记失败清单继续下一支;launcher 退出码 1 当且仅当存在失败分支。不做
并行(版本分支场景分支数小、每分支本身已 fan-out 并行,外层并行只会放大宿主负载与 token 竞争)。
`/mgh-sdr` 命令壳 SHALL **不含** `--multi-branch`,默认只处理当前分支(经 `git rev-parse
--abbrev-ref HEAD`),把多分支循环从壳的编排面彻底移除——壳保持薄、编排器不背多分支状态。
〔多分支 = 管理面,归属人入口 launcher;壳 = 单分支,净简化〕

## Risks / Trade-offs

- [注解启发式漏识别非标准接口定义(纯 servlet、自定义路由注册)] → 漏识别文件落入 standalone
  单元仍被检查(粒度粗不漏检);壳与报告诚实边界披露启发式范围;后续可扩注解闭集不动结构。
- [`read_roots[]` 被声明过宽(声明盘符根)使读侧守卫形同虚设] → sdr_context 只把**实际检索过**的
  外部仓根写入哨兵(NEVER 透传用户给的任意路径);launcher `--read-root` 显式额外声明时 stderr
  提示暴露面;契约文档标注「read_roots 最小化」纪律。
- [外部仓同名分支不存在/未同步] → sdr_context 降级:分支缺失时回退该仓默认分支 diff + 结论文件
  标注 `branch_fallback: true`,报告边界披露「外部仓分支未同步,检索基于其默认分支」。
- [6 维度外的检查诉求] → `--dimensions` 闭集 + 自由文本扩展维度透传(闭集键外按自由文本检查项
  处理,无 control_ref 投影),满足「可配置化/参数化」而不引入开放枚举维护负担。
- [draft JSON 被 subagent 写坏(非 schema 形态)] → render 侧对不可解析 draft 记 `failed_units[]`
  继续渲染其余(与 `.failed` 同路径);`--check` 校验 manifest 计数与 draft 实际一致。
- [claude 端 Bash 600s 上限 vs sdr fan-out 长跑] → 沿用既有三级超时不变式与 `--time-budget-ms`
  建议(claude 宿主 480000),launcher 组装命令时按宿主注入建议值,复用 mgh-init 已验证的标定。

## Migration Plan

纯增量:新命令/新脚本/新模板/新 agent/守卫判定扩展,零既有行为变更(read_roots 缺省时守卫逐字
等价;三 tier 派发逐字不变)。部署 = install.sh 重装(自检清单自动覆盖新产物)+ 双端插件/守卫
同 install 更新。回滚 = 删新文件即可,无 schema 迁移、无状态迁移;`.mgh-sdr/` 目录可整体删除。

## Open Questions

- 报告是否需要机器可读的 finding 导出(JSON/SARIF-like)供后续 `/mgh-blst` 消费?draft JSON 已是
  结构化形态、留存在 run 目录,必要时后续 change 加导出即可,本期不做。
- 接口注解闭集是否需要覆盖非 Spring 的国产框架注解?首版以 Spring/JAX-RS/Servlet 常用注解为准,
  闭集常量单点可扩,首跑反馈后再补。
