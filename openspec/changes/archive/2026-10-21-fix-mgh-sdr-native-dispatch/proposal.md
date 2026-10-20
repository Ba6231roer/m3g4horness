> **人话序** 现象:企业内网的多单元安全设计复核(每个代码改动单元派一个子代理去对照存量安
> 全设计检查)此前靠「脚本另起子进程」派发,在内网鉴权体系下几乎全灭;前四个 change 已把地基
> 打好——插件能在新宿主上跑、权限询问不再弹、确定性计划能物化、看门狗能兜住挂死——但主
> 力命令本身还是老形态,地基没人用。根因:派发形态的选择与消费没接上:命令壳还只会调子进程
> 派发器,步骤查询/断点恢复/报告也不知道「原生形态」的存在。改什么:/mgh-sdr 在 opencode 面
> 接入原生派发——环境画像显式选 native 才启用(缺省一切照旧);fan-out 步变为「物化计划 →
> 编排器按波次同回合并发派原生子代理 → 子代理自写完成/失败标记 → 波次间重物化重派 → 报
> 告」;子代理复用同一任务模板与六维检查契约,报告数据与老形态同源;启动看门狗兜无人值守;
> 子进程派发器原样保留作回退。怎么验证:小仓六单元全链跑通且报告数据与老形态一致;故障注
> 入(单单元失败/全波限流/权限询问/挂死/中断续跑)全部按契约收口;不配画像时行为逐字节照旧。

## Why

- 企业内网子进程派发 >99% 鉴权失败、不可持续修(维护者拍板转向原生);四个基础件(插件
  2.x 迁移、权限询问闸门、计划物化、看门狗)已全部归档,但没有消费方——sdr 是第一个,
  也是当前痛点所在的主力命令。
- sdr 的 fan-out 形态当前钉死在子进程派发器上:壳的刚性三元组、步骤清单、恢复指引、报告
  披露全部只认 `fanout_runner.py --tier sdr`;原生形态的计划工件、短单元号、标记语义、看
  门狗无人值守闭环都需要一个命令把它们串成可跑的流水线。
- 六维检查契约、统一问题记录 schema、检查基线摘要、写作纪律这些**评审本体**与派发形态无
  关——本次只换「怎么派」,不换「查什么、怎么记」;报告数据必须与老形态同源,历史对照不
  断档。

## What Changes

- **派发形态选择(缺省零变化)**:`/mgh-sdr` step 0 读环境画像;仅当 `dispatch_mode` 显式
  为 `native` 时走原生形态(画像缺失/auto/runner 一律现行子进程形态,行为逐字节不变);
  子进程形态原样保留为回退路径。
- **原生 fan-out 步(opencode 面)**:
  - 物化:`emit_native_plan.py --tier sdr` 产出计划与每单元任务文件,`--check` 自检;
  - 派发:编排器**同一条 assistant 消息**并发派 N 个原生子代理(agent `sdr-review-native`,
    `mode: subagent`),每单元调用 `description` = 短单元号、任务体 = 固定一句 + 任务文件绝
    对路径(自计划逐字透传);波次尺寸来自计划(并发与配额算术的较小者);
  - 标记:子代理成功 touch `done_marker`、失败**自写** `failed_marker`(带原因;仅原生
    agent 定义承载此指令,任务模板与 runner 行为零改动);磁盘标记仍是唯一真相源,计划物
    化与看门狗永不写标记;
  - 收敛:波次间**重跑计划物化**作为重枚举(pending 由标记重派生),失败单元至多重派一
    轮,重派再败接受缺口并披露;上一波失败原因含限流特征时按画像配额窗口等待后再查询;
  - 无人值守:native 步启动看门狗(后台,根会话取自宿主注入的会话环境变量,`--run-dir`
    为当前 run,阈值用缺省),run 落定自退;
  - 报告:`render_sdr_report.py` 数据源不变(drafts + 标记),报告与 manifest 披露实际派发
    形态与计划工件在场证据。
- **步骤与恢复的形态感知**:`list_sdr_steps.py` / `resume_sdr_state.py` 在原生形态下给出对
  应的步骤形状与可执行下一步(物化/派波次/渲染;进度仍纯从磁盘重派生),恢复指引首调状态
  查询的既有契约不变。
- **壳与预算**:opencode 面 `mgh-sdr.md` 增原生步骨架(紧凑、按画像条件),波次纪律详情
  下沉新 fragment(`core/prompts/fragments/` 按需加载),壳 token 预算不破;**claude/dsh 面
  本 change 不变**(保留子进程形态,分歧在壳与规格中显式披露;属宿主机制差异的白名单类)。
- **契约**:`core/contracts/sdr/pipeline.md` 增原生形态节(形态选择/波次循环/标记写者/看门
  狗接线/披露);fanout 契约的 native 段补「sdr 为首个消费方」一句。
- **非目标**:不动六维检查本体、draft schema、写作纪律、基线投影;不做插件令牌展开(路径
  转述的残余防线见 design,展开插件留后续 hardening);不做通道 B(插件派发工具,第 6 个
  change);不改 claude/dsh 面;不动 Python 守卫与权限闸门。

## Capabilities

### New Capabilities

<!-- 无。 -->

### Modified Capabilities

- `security-design-review`: ①MODIFIED「fan-out 评审单元与 6 维度默认检查面」——派发升级为
  双形态(子进程回退 + 原生按画像显式启用),原生形态的 agent/中继/标记自写语义入约,六维
  契约与 schema 不变;②ADDED「原生派发的波次纪律与无人值守闭环」——波次循环/至多一轮重
  派/限流等窗/看门狗接线/标记真相源不变量/残余披露(波次粒度止损、父会话单点、路径转述残
  余)/三面分歧披露。

## Impact

- **代码**:`core/scripts/list_sdr_steps.py`、`resume_sdr_state.py`(原生形态感知);
  `render_sdr_report.py`(派发形态披露行);新增 `releases/opencode/agent/sdr-review-native.md`
  (mode: subagent 孪生);`core/prompts/fragments/` 新增 sdr 原生波次纪律 fragment;
  `releases/opencode/command/mgh-sdr.md`(原生步骨架)。
- **零改动面**:`fanout_runner.py`、`emit_native_plan.py`、`native_watchdog.py`、
  `env_profile.py`、`block_adhoc_scripts.ts`(插件)、`sdr-task.md` 模板、claude/dsh 壳。
- **契约**:`core/contracts/sdr/pipeline.md`(原生形态节)。
- **测试**:`test_list_sdr_steps`、`test_resume_sdr_state`、`test_render_sdr_report`(原生分
  支)、`test_distributed_md_purity`、`test_dsh_command_surface`(三面分歧披露的形状)、
  `test_sdr_tier`/`test_fanout_runner`(回退路径不破)、新增原生纪律的壳/fragment 形状锚;
  lint 四件套 + `openspec validate --strict`;壳预算 lint(R5.6)。
- **实机闸门**:本机 2.1.0——小仓 6 单元原生全链(物化→并发→标记→重枚举→报告)对照
  runner 同输入报告数据一致;故障注入五件套(单单元 .failed/全波限流特征/权限 ask/挂死
  interrupt/中断 resume);缺省零变化抽查(无画像时与主分支行为一致)。企业 2.0.32——CAS
  真仓 6 单元对照(原失败场景;交接内网执行,附步骤)。
- **VERSION/CHANGELOG**:按仓库惯例 bump。
