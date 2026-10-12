# tasks — add-mgh-dsh-subagent-fanout

## 1. Spike 定案(关闭 design D3/D4 与 Open Questions)

- [x] 1.1 实测 `--patch`/profile 能否为顶层 headless run 设定系统提示词与工具面白名单
      → 钉死 D3 档位(a 配置装载 / b 任务前置),回填 design 并写入 fan-out 运行契约
- [x] 1.2 实测宿主 shell 工具「超时晋升后台 job」可否经 profile/patch 关闭 → 定 D4 路线
- [x] 1.3 实测 `taskkill /T` 对 `dsh.cmd → node` 进程树的有效性;并发多 headless 进程经
      `--session-id` 的会话日志隔离度(dsh Open Question 2/3)
- [x] 1.4 记录本组实测所依赖的 dsh 精确版本号(兼容窗口锚点)

## 2. 子代理第三方言与 tier 生成器

- [x] 2.1 建 `releases/dsh/agents/`:fan-out 三件(scout/induct/rulewriter)+ sast 各 stage
      定义,叶提示词按路径引用 `mgh-core/prompts/` 不复制正文
- [x] 2.2 `tools/` 新增 tier 装载文件生成器(构建期,stdlib):agent 定义 → 
      `<target>/mgh-core/dsh/tiers/*`;缺件/坏定义 install 期 fail-loud(边界校验纪律)
- [x] 2.3 生成物入分发纯净 lint 与零依赖扫描面,加断言用例

## 3. fanout_runner dsh host

- [x] 3.1 `core/scripts/fanout_runner.py`:`--host` 枚举加 `dsh`;探测链末位追加(显式
      `--host` 恒优先);命令形 `dsh --profile mgh --patch <tier文件> -`,任务经子进程
      env `MGH_TASK_TEXT`(spike 推翻 stdin 假设,维护者已拍板 env 通道),
      cwd = `repo`;plain 模式活性信号(D2)
- [x] 3.2 装载缺件 → spawn 前退出码 2 + recipe(spec 场景);树杀/波次/熔断/cooldown 零改动
- [x] 3.3 `tests/test_fanout_runner.py`/`test_fanout_stale.py` 扩 dsh 用例:命令形快照、
      三 CLI 全缺 fail-loud、双端既有次序不受影响、仅 dsh 机器可派发;
      **in-process harness 层照设 `--cooldown-s 0`(慢测陷阱规,NEVER 例外)**
- [x] 3.4 定向跑 `test_fanout_runner` `test_fanout_stale`(本面默认姿势,不跑全量)

## 4. 交互式 stage 派发与 profile 资产

- [x] 4.1 mgh profile 组合资产(具名委派实例清单 = 2.1 文件集派生):shim 挂载、超时策略、
      委派工具实例;install 只增不改用户自有 profile
- [x] 4.2 五份 dsh 壳的 stage 派发表述改按名拾取具名实例;删除 change 2 留下的扇出降级段
      (其 design D4),sdr/init/sra/sast 四壳逐处核对
- [x] 4.3 三面契约 lint 复跑(壳内 flag 逐字镜像不回归)

## 5. install 与文档收口

- [x] 5.1 `install.sh`/`install.ps1 --dsh`:接 2.2 生成器落 tiers + profile 资产;自检加
      「tier 装载文件与 agents 定义一一对应」断言;幂等复验
- [x] 5.2 fan-out 运行契约文档登记:D3 档位、D4 路线、dsh 端 provider 前置条件(诚实边界)
- [x] 5.3 研发手册:测试映射 fan-out 行补 dsh 用例文件归属;版本号 bump

## 6. 真机端到端验收(路线 A 收口判据)

- [ ] 6.1 小仓 `/mgh-init` 全流水:scout+T1+T3 扇出经 dsh 跑通,marker/resume/ack 与双端
      同构;`--wave 2` 起步标定机器负载,结论写入契约(必要时 dsh 默认并发降档)
- [ ] 6.2 `/mgh-sdr` 全 6 维扇出走通 + 报告落地;中途 kill runner 再 `--kill-stale` +
      `--resume`,无孤儿 dsh/node 进程残留
- [ ] 6.3 超时合同验证:单元内制造超时长跑 → 按 D4 定案路线终止/job 回收,无隐形活口
- [ ] 6.4 守卫联动复验:扇出子进程内(哨兵激活)越树写/`run_code` 仍被 deny(地基×扇出闭环)
- [ ] 6.5 发布前全量回归(跨面改动闸门:fanout + install + 壳三面)
