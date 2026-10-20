# fix-mgh-sdr-fanout-auth-isolation — tasks

## 1. fanout_runner:执行环境隔离与静态凭证注入

- [x] 1.1 新增 `--cred-file <path>` 与 `--isolate-data` 两个 flag(`--help` 契约面同步);
       `--cred-file` 非 opencode host 传入 → 退出码 2 + recipe;`--isolate-data` 非 opencode
       host → stderr note 后忽略
- [x] 1.2 cred 文件启动期一次性读取与闭集 schema 校验(`{v, baseURL, apikey, provider_id,
       global_config, keep_plugins, expired_signatures[]}`;缺文件/坏 JSON/缺字段/空 apikey
       → 退出码 2 零 spawn + 重取证 recipe;`~` 前缀路径脚本内 expanduser)
- [x] 1.3 按单元物化子配置:复制 `global_config` 指向的全局 opencode 配置到
       `<run>/childcfg/<safe-unit>/opencode/opencode.json`,仅覆盖 `provider_id` 定位的
       provider 为静态 baseURL + apikey(id 不变,plugin/agent/model 保留,
       `keep_plugins:false` 时摘 plugin 列表);幂等,已 `.done` 单元不物化不重派
- [x] 1.4 spawn env 注入:`--cred-file` 激活 → opencode 形子进程 env 增设
       `XDG_CONFIG_HOME=<run>/childcfg/<U>` + `XDG_DATA_HOME=<run>/ocdata/<U>`;
       `--isolate-data` 单独 → 仅 `XDG_DATA_HOME`;两 flag 缺席 → env 与现状逐字段一致
       (现有 `PWD` 剥离 / `MGH_TASK_TEXT` 语义不动)
- [x] 1.5 secret 卫生:apikey 不出现在 stdout/stderr/marker/run.log/遥测 params;摘要披露
       仅 cred 路径、provider_id、baseURL
- [x] 1.6 special-auth 通用 advisory:安装树存在 `<mgh-core>/mgh-special-auth.md`
       (`Path(__file__).parent.parent` 探测)且未传 `--cred-file` → 派发前 stderr 一行
       提示(不阻塞、不改退出码、全 tier 一致)

## 2. fanout_runner:凭证过期分类与暂停续跑

- [x] 2.1 非 ok 终态(crash/timeout/stall/failed ack)输出尾部按 `expired_signatures[]`
       (大小写不敏感子串)扫描;命中 → 单元记 credential_expired 原因,计入 stdout
       `credential_expired:true` + `credential_expired_units[]`,与 stall/限流计数分开;
       空特征集 = 扫描面不激活
- [x] 2.2 暂停截断:首个命中即停止派发(优先级高于限流风暴截断与快败冷却),在飞单元
       照常收割,退出码 2;stderr recipe = 重取证 → 更新 cred 文件 → 同参
       `--resume --retry-failed`;marker 语义不变
- [x] 2.3 启动期孤儿 advisory:liveness 文件存在存活 PID → stderr 一行 kill-stale recipe
       (非阻塞,不改退出码;复用既有 `--kill-stale` 机制,不加新清理路径)

## 3. fanout_runner:`--dry-run` 纯计划

- [x] 3.1 派发 dry-run 去审计副本写入与一切目录/文件创建,计划摘要(单元清单、将写的
       审计与 marker 路径、命令形)只走 stdout;`--kill-stale` / `--purge-audit` 的
       dry-run 审视守卫语义不动
- [x] 3.2 既有「dry-run 冒烟」用法与其测试迁移(stdout 摘要或非 dry-run 路径)

## 4. mgh_credentials.py(新叶脚本)

- [x] 4.1 落 `core/scripts/mgh_credentials.py`(零依赖、自定位导入、utf-8、任意 cwd;
       CLI 扁平 flag 形:`--source <run>/cred_source.json --out <run>/cred.json
       [--login-timeout-s <s>]` 取证与 `--check <run>/cred.json` 校验;
       退出码 0/1/2;stdout 结构化摘要含模式/变量名/成败/输出路径、NEVER 含 token 值;
       cred 校验函数导出供 fanout_runner import 单源共用)
- [x] 4.2 三模式取证:inherit(读本进程 env)/ env-file(解析 KEY=VALUE 文件)/
       login-process(物化内嵌泛型探测插件模板〔参数化 env 变量名+输出路径〕→ 备份并
       外科式追加进全局 opencode 配置 plugin 列表 → spawn 一次性登录子进程〔中性 cwd、
       `--print-logs`、可配超时〕→ 轮询取 token → try/finally 重读盘仅摘除自己条目还原
       → 写输出;失败/超时同样还原,退出码 2 + recipe)
- [x] 4.3 cred.json 写入权限 best-effort 收紧(POSIX 0600);`--check` 只验 schema 完整性,
       零联网

## 5. 清单与 resume 面(sdr 首落地)

- [x] 5.1 `list_sdr_steps.py`:顶层 `special_auth{present, path}` 字段(探测
       `<mgh-core>/mgh-special-auth.md`;两态;缺席时其余字段逐字节不变);docstring
       「零磁盘前置」承诺收窄为「唯一探测 = 可选 special-auth 文档」
- [x] 5.2 `resume_sdr_state.py`:当前待办步为 fanout 且文档在场 → stdout notes 一行指引
       (凭证续期与重派口径以文档为准)

## 6. 三面壳 + 安装面 + 仓库策略

- [x] 6.1 三面 mgh-sdr 壳(opencode/claude/dsh)逐字镜像各加 fan-out 步前引导行:
       清单 stdout `special_auth.present==true` → 先 Read 该文档(路径取 stdout),凭证
       准备与配套派发 flag 以文档为准(优先范围仅限凭证与环境准备,NEVER 链不可放宽);
       缺席 → 逐字节现状;`--dry-run` 披露行如实列出壳级 dry-run 会产生的产物
       (run 目录/context.json/哨兵)
- [x] 6.2 `install.sh` 与 `install.ps1`:可选复制收敛——仓库根
       `mgh-special-auth.md` 在场 → 落 `<dest>/mgh-core/mgh-special-auth.md` 并安装输出
       披露;缺席 → 移除目标侧残留副本;两态安装行为差异仅此文件,自检清单不因缺席告警
- [x] 6.3 `.gitignore` 增 `mgh-special-auth.md` 与 `docs/enterprise-environment.md` 两项
- [x] 6.4 `tools/check_distributed_purity.py` 的 `SDD_EXEMPT_CHANGES` 登记本 change
       (交付物与编辑目标含 docs/ 路径:enterprise-environment、glossary、man),注释
       说明豁免理由

## 7. 不进 git 的交付物首版(维护者私档,apply 时落盘不提交)

- [x] 7.1 仓库根 `mgh-special-auth.md`:按 design「文档结构」九节撰写(已知事实/Linux
       一步/Windows 三步/cred_source 取值表与执行序列/验证步骤/故障对照/续期 runbook/
       并发与超时映射含不变式不可改告诫/dsh follow-up 与硬边界声明);企业值以用户
       提供实录为准(含 `api/v1` 原始拼写)
- [x] 7.2 `docs/enterprise-environment.md`:按 design 六节撰写(模型服务/限频/认证闭环/
       共享数据目录危害/宿主上限与孤儿处置/与铁律对应关系 = 原 AGENTS.md 运行环境约束表
       全量迁入 + 本次新增定制)
- [x] 7.3 `AGENTS.md`:「用户画像与设计目标」节的环境细节改一句概括 + 必读指引(注明
       文件缺席时按通用公开 clone 语境、铁律自足);改动面→测试映射表补
       `mgh_credentials.py`/`test_mgh_credentials` 与 special-auth 安装面两行

## 8. 契约与文档同步(通用面,不含企业定制)

- [x] 8.1 `core/contracts/fanout/runtime.md`:spawn env 注入语义、cred 文件契约、凭证
       过期分类与暂停、dry-run 纯计划、special-auth advisory
- [x] 8.2 `core/contracts/sdr/pipeline.md`:run 目录布局补 `childcfg/`/`ocdata/`/
       `cred_source.json`/`cred.json`,`special_auth` 清单字段与壳引导约定
- [x] 8.3 `docs/glossary.md` 补通用词条:凭证中心、静态注入、子配置目录、数据目录隔离
       (不含企业词汇);`docs/man/mgh-sdr.md` 补通用机制段(special-auth 在场引导与注入
       模式,企业细节指向私档)
- [x] 8.4 三面壳预算复核与(如需)对冲裁剪,`tools/check_distributed_prompt_budget.py` 过

## 9. 测试

- [x] 9.1 `test_fanout_runner` 扩:注入模式 env 形状断言(PWD 剥离保持 + per-unit XDG 两
       变量)/子配置物化形状与幂等/provider id 不变/apikey 不落 stdout·stderr·run.log/
       cred 损坏 fail-loud 零 spawn/非 opencode host 拒识/两 flag 缺席 env 逐字段不变
- [x] 9.2 `test_fanout_runner` 扩:过期分类(命中入 `credential_expired_units`、不进限流
       风暴判定集)/截断优先级与退出码 2 + recipe/在飞收割/空特征集零变化/resume 幂等
       (done 不重派、cred 续期新值生效)/dry-run 零写盘(全树快照对比)/advisory 两态
       (文档在场未注入、缺席静默)/孤儿启动提示
- [x] 9.3 新增 `test_mgh_credentials`:inherit 命中零登录/env-file 解析与缺失 recipe/
       login-process 成功路径与失败也还原(重读盘外科式移除断言)/超时路径/`--check`
       schema/输出权限/stdout 无 token 值
- [x] 9.4 `test_list_sdr_steps` 扩:special_auth 两态 + 缺席时其余字段字节不变;
       `test_resume_sdr_state` 扩:fanout 步在场提示与缺席零变化
- [x] 9.5 安装面测试:install 复制收敛三态(源在场复制/源缺席清残留/两态均不告警);
       `test_zero_deps` / `test_no_compile_warnings` 带上新脚本
- [x] 9.6 定向回归全绿(按 AGENTS.md 映射表:sdr 面 + fanout 面 + 壳/提示词面 +
       `tools/check_contracts.py` 新 flag 对账)

## 10. 验证门与收尾

- [x] 10.1 lint 四件套过:contracts(含新 flag)/purity(先完成 6.4 登记)/budget
       (三面壳增量后)/plain_language;`openspec validate
       fix-mgh-sdr-fanout-auth-isolation --strict` 过
- [x] 10.2 隔离小仓实机冒烟:install(带 mgh-special-auth.md)→ 清单 special_auth 字段 →
       伪造 cred(Linux env-file 模式)→ 注入派发单单元(子配置物化 + env 断言 +
       `opencode debug paths` 验证隔离)→ 坏 apikey 演练 401 分类暂停 → 重取证 →
       resume 续跑 → 报告收口;卸载验证:无该文件安装后目标侧无残留
- [x] 10.3 企业真仓验证清单(交接给内网执行,不阻塞本仓归档):Windows XDG 两变量生效
       确认(F7-C)、保留 plugin 下子进程不自登录确认(F8-C)、原失败场景 6 单元重跑
       对照、db locked/EPERM 消失确认、真实 401 续期演练
- [x] 10.4 `VERSION` bump 与 `CHANGELOG.md` 分组条目;交接备忘:两份私档文件的维护责任、
       dsh host 注入 follow-up、init/ut-init 清单字段 follow-up
