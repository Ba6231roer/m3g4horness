> **人话序** 现状:需求分支研发完,代码 merge 进版本分支前没有一道「安全设计」关卡——存量安全设计
> (mgh-init 产出的 rules)定了规矩,但没人机械地回答「这次 diff 有没有漏按规矩做」。改什么:新增
> `/mgh-sdr`(security design review):拉 `git diff <base>..<branch>`,按**接口维度** + 剩余独立变更
> 内容分组 fan-out,逐组对照存量安全设计(垂直越权、横向越权、其他权限问题、SQL 注入、敏感信息屏蔽、
> 输入校验 6 维度默认开,可参数化)查设计遗漏,汇总成一份 md 报告落项目根(文件名含工具名 + 分支 +
> 秒级时间戳)。怎么验证:每个 stage 有 `--check` 边界校验;fan-out 走 `fanout_runner.py` 波次派发 +
> 磁盘 marker 恢复;回归测覆盖 diff 分组 / 枚举 / 渲染 / 守卫接线;`tools/check_contracts.py` 覆盖双
> 壳调用 flag;launcher 脚本 `py mgh_sdr_launch.py` 一条命令拉起 opencode 全流程(默认复核当前分支;
多分支 sweep 由 launcher `--multi-branch` 承担,壳不背多分支状态)。特例场景:存量设计
> 引用**前端仓**(如 buttonAuth.properties 配置即合规、接口不应在前端多处出现)时,编排器主流程先期
> 在外部仓做**受控检索**,把结论物化成本仓内只读 slice 文件再 fan-out——权限确认只发生在外壳主流程,
> subagent 零跨树读、零权限打断。

## Why

`/mgh-init` 产出的存量安全设计(claude rules / opencode `AGENTS.md` 索引 + `docs/security-controls/`
详述)回答「本项目安全设计是什么」,`/mgh-sra` / `/mgh-srr` 回答「新需求该怎么设计」。缺的一环是
**需求分支的代码变更**:研发完成、每日手动触发、merge 进版本分支之前,机械地对照存量安全设计逐接口
检查「有没有漏做」。现有命令无一以 `git diff base..branch` 为输入;`/mgh-sast` 是漏洞扫描器(SAST,
产 SARIF),不做「设计符合性」判断;`/mgh-sra` 的输入是 openspec 变更 / 自由文本,不是代码 diff。
补 `/mgh-sdr` 后,mgh 工具族形成「发现存量(init)→ 注入设计(sra/srr)→ **复核变更(sdr)**」闭环。

## What Changes

- **新增命令 `/mgh-sdr`**(security design review;java web 项目优先,非破坏性只读评审):
  - 新增编排命令壳 `releases/{claude-code/commands,opencode/command}/mgh-sdr.md`(双平台逐字镜像语义);
  - 新增 fan-out agent 定义(init-induct-fanout 同形的 `sdr-*-fanout`,`mode: primary` 克隆,opencode
    `run` 可派);
  - **新增确定性叶脚本**(全部 Python ≥3.10 标准库,承 R2):
    - `diff_group.py`:确定性 diff 采集与切分——`git diff --no-color <base>..<branch>` 取变更;按
      java web 接口维度(Controller/RequestMapping 注解启发式)分组接口单元;剩余变更内容(非接口
      文件、配置、SQL、工具类)归并为**独立变更单元**;每单元物化**只读 slice 文件**(diff hunk +
      邻近上下文),枚举 `pending[]`(每项含 `input_path`/`draft_path`/`done_marker`,全绝对,承
      R5.3(b) 扇出路径契约);
    - `sdr_context.py`:确定性外部仓库检索协调器——解析存量安全设计中的**外部仓声明**(前端仓路径 +
      分支一致性约定),若声明存在且目录可达:在**编排器主流程**(launcher 进程,非 subagent)对该
      外部仓做受控 `git diff` + 定向检索(buttonAuth.properties 命中、接口在前端的出现次数),把结论
      物化为本仓 `<run-dir>/external/` 下的小体积 slice 文件(逐仓字节预算,超限截断披露);subagent
      **NEVER** 直接读外部仓;不存在声明 → 本步零副作用跳过;
    - `render_sdr_report.py`:确定性汇总渲染——收各 fan-out 单元 draft JSON,去重合并,渲染
      `<project-root>/<工具名>-<分支名>-<YYYYMMDD_HHMMSS>.md`(简体中文、面向人、按严重度 + 接口
      分组)+ `sdr_manifest.json`(counts + boundaries 诚实边界);`--check` 边界校验。
  - **新增 fan-out task 模板** `core/prompts/fragments/fanout/sdr-task.md`(统一占位符集);
  - **`fanout_runner.py` 扩 1 个 tier**:`sdr`(枚举脚本 = `diff_group.py --materialize`,模板 =
    `sdr-task.md`,agent = `sdr-review-fanout`;波次循环 / ack 状态机 / 超时 / liveness / 断路器
    零改动,tier 表单点扩展);
  - **新增 launcher 脚本** `core/scripts/mgh_sdr_launch.py`(**随 install 分发**,人/cron 入口,
    NEVER 由宿主 subagent 调用):`py mgh_sdr_launch.py --repo <abs> [--branch X] [--base master]
    [--host opencode] [--multi-branch <file>]` 一条命令写好运行域 env / 哨兵 / 提示词文件,再
    spawn `opencode run`(或 `claude -p`)执行 `/mgh-sdr` 编排——外部仓的主流程受控检索在
    launcher 外壳内完成权限确认,subagent 会话零打断;`--multi-branch` 串行逐分支 sweep 是
    launcher 专属(管理者经定时工具多分支检查),`/mgh-sdr` 壳默认只处理当前分支。
- **敏感目录复用语义(显式分歧)**:`<target>/.mgh-sra/sensitive_catalog.json` 存在则复用(sibling
  import `sensitive_catalog` 模块解析 + 闭集校验);**不存在时回退按 `core/scripts/sensitive_catalog.json.example`
  默认模板检查**——这是 sdr 与 sra/srr 的**有意行为分歧**(sra/srr 域 null = 6-facet 兜底;sdr 是代码
  diff 复核,回退默认模板比收窄到 6 facet 更贴场景),`sdr_manifest.json::boundaries[]` 显式披露所用
  目录来源。
- **读域扩展(契约级)**:`core/contracts/hooks/runtime-enforcement.md` 的运行域哨兵 schema 增可选
  `read_roots[]`(额外只读根);守卫读侧判定扩展:声明过的外部只读根**放行工具面 `Read`/`Glob`/`Grep`**
  (Bash 搜索动词仍仅限 `MGH_TARGET` 子树,写侧永不放行外部根);sdr 编排器把已确认的外部仓写入哨兵
  `read_roots[]`,subagent 跨树读不再命中宿主权限提示。
- **install/CI 接线**:`install.sh` 共定位自检清单 + sdr 脚本;`tools/check_contracts.py`
  `DEFAULT_SHELLS` + 双平台 mgh-sdr 壳;零依赖 AST 扫描覆盖新脚本;回归测(见 tasks §5)。

非目标(明确不做):不做漏洞可达性验证(产出是 LLM 候选复核项,非确认漏洞,承 mgh-sast 诚实边界);
不改 mgh-init 产出物 schema 与 sra/srr 现有行为;不支持 java web 以外语言的接口分组(启发式仅识别
Spring/Servlet 注解,其他语言项目退化为纯独立变更单元模式,仍可运行);不做 CI 门禁集成(每日手动
触发 / merge 前手动触发)。

## Capabilities

### New Capabilities
- `security-design-review`: `/mgh-sdr` 端到端行为:diff 采集与接口维度分组(`diff_group.py`)、外部仓
  受控检索与 slice 物化(`sdr_context.py`)、fan-out 评审单元(a3 同形 subagent,6 维度默认 +
  `--focus`-式参数化)、统一问题记录 schema(单元 draft JSON)、汇总渲染(报告 + manifest + 诚实
  边界)、launcher 外壳、敏感目录复用/回退语义、`--check` 边界校验、幂等 resume。

### Modified Capabilities
- `runtime-hook-enforcement`: 运行域哨兵 schema 增可选 `read_roots[]`;读侧判定对声明根放行工具面
  只读(写侧 / Bash 搜索动词判定不变);新增 `MGH_SDR_ACTIVE` 运行域;wire-coverage CI 不变量覆盖
  sdr 域。
- `fanout-dispatch`: `fanout_runner.py` TIERS 表增 `sdr` tier(枚举脚本 / 模板 / agent / 占位符集
  映射),共享波次状态机零改动。

## Impact

- **代码**:`core/scripts/diff_group.py`、`sdr_context.py`、`render_sdr_report.py`(新增);
  `core/scripts/fanout_runner.py`(TIERS +1);`core/prompts/fragments/fanout/sdr-task.md`(新增);
  `releases/{claude-code/commands,opencode/command}/mgh-sdr.md`(新增);`releases/opencode/agent/`
  + `releases/claude-code/agents/` 新增 sdr fan-out agent 定义;`core/scripts/mgh_sdr_launch.py`
  (新增,随 install 分发);`releases/claude-code/hooks/block_adhoc_scripts.py` + opencode `.ts` 插件(`read_roots[]`
  判定扩展,双端字节级 parity)。
- **契约**:`core/contracts/sdr/`(diff/context/report I/O 契约,新增);`core/contracts/hooks/runtime-enforcement.md`
  (read_roots 扩展)。
- **测试**:`tests/test_diff_group.py`、`test_sdr_context.py`、`test_render_sdr_report.py`、
  `test_fanout_runner.py`(sdr tier 用例)、`test_opencode_hook_parity.py`(read_roots 用例)扩展。
- **安装/CI**:`install.sh` 自检清单 +2 脚本;`tools/check_contracts.py` DEFAULT_SHELLS +2 壳; purity
  lint 覆盖新壳(承 R5.10:壳内零 dev-meta)。
- **研发铁律对齐**:R2(全部新脚本零运行时依赖)、R5.1(双壳调用逐字镜像 + 契约 lint)、R5.2/R5.3
  (编排器即宿主;fan-out 刚性三元组,枚举脚本单点产 `pending[]` 绝对路径)、R5.4(resume 磁盘真相
  + per-call timeout)、R5.9(各产出者 `--check` fail-loud)、R5.10(新壳纯操作性内容)。
- **诚实边界**:sdr 发现是 **LLM 候选,非确认漏洞**;接口分组是**注解启发式**(漏分组接口退入独立
  变更单元,不漏检但分析粒度粗);外部仓结论是**检索时点快照**(不保证前端分支已同步);codegraph
  采纳为**可选减扇出信号**(on 时提供调用链归并建议、off 时纯 diff 分组,行为降级安全)。
