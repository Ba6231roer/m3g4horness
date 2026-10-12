## MODIFIED Requirements

### Requirement: 宿主 CLI 探测与 headless spawn 映射

dispatcher SHALL 探测可用宿主 CLI(`claude` / `opencode` / `dsh`,PATH 查找)并映射为各自的
headless subagent 调用,agent 名按 tier 参数化:scout → `init-scout-fanout`、t1 →
`init-induct-fanout`、t3 → `init-rulewriter-fanout`(opencode 侧均为 `mode: primary` 的
fanout agent 克隆,install 落位 `.opencode/agent/`;claude 侧经 `--agents` inline JSON 按同名
单元装载,工具面白名单等价于交互路径;dsh 侧经 `dsh --profile <mgh profile> --patch
<tier 装载文件> -` 装载,装载物由 install 从 `releases/dsh/agents/` 编译生成)。自动探测次序
SHALL 保持既有 claude/opencode 相对次序不变、`dsh` 仅追加在链末(已装双端的老机器默认行为
零变化);显式 `--host` 恒优先于探测。spawn 的 dsh 子进程 SHALL 使用 plain 输出模式(推理/
进度持续产生 stderr/stdout 字节流)供双 reader 静默检测消费,**NEVER** 用按步提交事件的机器
可读输出做活性信号(事件稀疏会喂大误杀窗口)。任务消息的正文 SHALL NOT 出现在 argv 里
(npm `.cmd` shim 实测在首个换行处截断多行 argv,对 dsh 同样成立):claude/opencode 经 stdin
管道传递;dsh headless 无 stdin 任务通道(实测),经**进程环境注入**投递——dispatcher 把任务
全文放入子进程 env 的 `MGH_TASK_TEXT`,tier 装载文件的固定模板行以该 env 覆盖任务来源,
argv 仅携带无内容占位符 `-`。子进程 cwd SHALL 为 `repo`(目标项目根)。任一宿主 CLI 均不可用
→ 退出码 2 fail-loud,stderr 给出 recipe(回退 = 编排器现状波次式手派,行为不变)。spawn 的
子进程 SHALL 继承运行域守卫激活(经磁盘哨兵 `<target>/.mgh-init/.active`,env 不跨进程亦不
失效)。

#### Scenario: opencode 可用时走 opencode run
- **WHEN** `opencode` 在 PATH,dispatcher 以 `--tier t1` 派发一个 cluster 单元
- **THEN** 子进程命令形如 `opencode run --agent init-induct-fanout`(消息经 stdin),cwd =
  `repo`;完成后该单元 `.done` marker 出现

#### Scenario: 双 CLI 均缺失 fail-loud
- **WHEN** `claude`、`opencode`、`dsh` 三者在 PATH 全缺失
- **THEN** dispatcher 退出码 2,stderr 说明回退 recipe(编排器按现状波次式手派);无部分 spawn

#### Scenario: 仅装 dsh 的机器可完成扇出
- **WHEN** 机器只有 `dsh` 在 PATH,`--tier scout` 派发
- **THEN** 子进程命令形如 `dsh --profile <mgh> --patch <tiers/scout 装载文件> -`(任务全文
  经子进程 env `MGH_TASK_TEXT` 投递、argv 仅占位符),stall 检测吃其 plain 模式字节流;
  单元按既有 marker/ack 合同收口

#### Scenario: 双端既有次序不受 dsh 加入影响
- **WHEN** 机器同时装有 opencode 与 dsh
- **THEN** 自动探测仍选 opencode(dsh 在链末);`--host dsh` 显式指定才切 dsh
