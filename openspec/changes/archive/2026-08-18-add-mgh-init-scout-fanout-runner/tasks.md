# Tasks: add-mgh-init-scout-fanout-runner

## 1. Spike(闸门:失败 → 收窄/撤销,结论回填 design D3)

- [x] 1.1 opencode headless spike:在真实目标项目 cwd 下并发 5 × `opencode run --agent init-scout
  "<固定消息>"`,验证 ① `--agent` 显式指定被接受 ② 并发 SQLite 无锁死/拒绝 ③ stdout 最终消息
  字段可解析 ack(记录确切命令形态与输出形态)
  → 实证:① subagent 模式被 run.ts 拒绝+静默降级 → 需 `mode: primary` 的 fanout agent 克隆;② 5 并发
  exit=0 无锁死;③ 默认 format 末行即 ack(结论回填 design D3「Spike 实证结论」)
- [x] 1.2 claude headless spike:`claude -p "<固定消息>"` cwd=目标项目根,验证 ① 项目级
  `.claude/agents/init-scout.md` 落位是否自然拾取(否则 `--agents` JSON 兜底)② `--allowedTools`
  白名单下 headless 无权限交互挂起 ③ stdout 可取最终 ack 行
  → 实证:① 双路均通(Task 拾取 + `--agents` inline JSON),采纳后者;② 白名单下 Read→单行 ack
  无挂起;③ stdout 末行即 ack;stdin 须 `< /dev/null`;spike 期 z.ai GLM-5.3 路由 529 与机制无关
- [x] 1.3 spike 结论回填 design.md D3 表格 + 定 `--wave` 默认值;失败 → 按 design D7 收窄或撤销,
  在本 change 记录决策 → 已回填;`--wave` 默认 5(双宿主并发实证通过);无需收窄/撤销

## 2. dispatcher 叶脚本(`core/scripts/fanout_runner.py`)

- [x] 2.1 骨架 + CLI 契约:`--scout-plan`/`--checkpoints`/`--inputs-dir`/`--wave`/
  `--time-budget-ms`/`--resume`/`--host`/`--purge-audit`/`--dry-run`/`--pending-file`(测试入口);
  `--help` 即契约面;stdout JSON / stderr 进度严格分流;退出码 0/1/2;零依赖(stdlib
  subprocess/concurrent.futures/argparse/json/pathlib/shutil)
- [x] 2.2 内部消费 `list_scout_batches.py --materialize`(兄弟脚本自寻址)取 pending;每波后
  经 list 重派生 pending(磁盘 marker 真相源,`.done`/`.failed` 跳过)
- [x] 2.3 任务消息构造:读 `core/prompts/fragments/fanout/scout-task.md` 模板,占位符
  (`{{input_path}}`/`{{checkpoint_path}}`/`{{done_marker}}`/`{{failed_marker}}`/`{{slice_dir}}`/
  `{{chunk_sources_abs}}`/`{{repo}}`/`{{codegraph}}`)逐字替换;替换后断言无残留 `{{`;每个路径
  字段 `Path.resolve()` 锚树校验(锚=`repo`),越树 → 该单元 `.failed`(reason=path-drift)+
  不 spawn;审计副本写 `<inputs-dir>/<batch_id>.task.md`
- [x] 2.4 宿主探测与 spawn 映射:`--host` 显式 > opencode > claude(`shutil.which`);均缺 →
  退出码 2 + stderr 回退 recipe;`ThreadPoolExecutor(max_workers=--wave)` + per-call
  `subprocess.run(timeout)`;cwd=repo;超时 kill → 无 ack → 留 pending
- [x] 2.5 ack 状态机:子进程 stdout 末行解析 `ok/oversize/failed`;`failed` ack → dispatcher 写
  `.failed` marker(body `{unit,reason,tier}`);拿不到可解析 ack 只信磁盘 marker;stdout 摘要
  `{repo,total,done,failed,pending,wave,partial}`;`--time-budget-ms` 软时限干净早退(退出码 0 +
  `partial:true`)
- [x] 2.6 `--purge-audit --dry-run` 清理出口(破坏性操作 dry-run 保护)

## 3. 模板与提示词面

- [x] 3.1 新 fragment `core/prompts/fragments/fanout/scout-task.md`:仅输入字段声明 + 指向
  stages/init-scout.md 的既有装载指令;零行为规则复制;过分发纯净性 lint
- [x] 3.2 `core/prompts/stages/init-scout.md` 与 agent 定义(`releases/{claude-code,opencode}`):
  核对 headless spawn 下装载路径与权限面等价于交互路径;「Input (from orchestrator)」段措辞
  对齐「字段来自 dispatcher 逐字填充」(行为不变,来源表述更新)
- [x] 3.3 `core/prompts/fragments/init-stage/scout.md` 派发段改写:主路径 = 一次 `Bash` 跑
  `fanout_runner.py`(per-call timeout)+ `partial:true` 重派;退出码 2 → 回退现状手派路径
  (保留原文);聚合/merge/fold-in 段不动;token 复测 ≤ 上限

## 4. 契约面与分发

- [x] 4.1 `core/scripts/list_steps.py` scout 步:增 dispatcher 调用行( invocation +
  `path_recipes` 增 fanout-runner 路径 recipe);`tools/check_contracts.py` 断言新 flag
- [x] 4.2 `install.sh` 自检清单增 `fanout_runner`;镜像规则覆盖新 fragment 目录
  `prompts/fragments/fanout/`
- [x] 4.3 双壳 `releases/{claude-code,opencode}/command/mgh-init.md`:仅当 scout 段引用需要时
  微调(调用行在 list_steps 契约面,壳正文预期不变);token lint 复测
- [x] 4.4 版本号 bump(改动的一切 `.md`/脚本)

## 5. 回归与冒烟

- [x] 5.1 `tests/test_fanout_runner.py`(21 tests,全绿):模板填充(占位符全集/残留断言)、
  锚树校验(盘符根漂移/`..` 链/缺字段拦截)、ack 解析(ok/oversize/failed/不可解析降级)、
  状态机 CLI(.failed marker 落盘/幂等重派/.done 短路/purge-audit dry-run + 裸调用守卫退出码 2/
  非法 flag 退出码 2)、`--help` flag 存在性;spawn 面经 `--pending-file` 测试钩子,不真调 CLI
- [x] 5.2 既有回归全绿:test_deterministic + test_fanout_runner + test_init_ack_contract +
  test_list_steps + test_resume_state + test_list_scout_batches + test_init_runtime +
  test_zero_deps + test_distributed_md_purity 全 OK;契约 lint 254 flags 全声明;纯净性 lint 0
  违规;双壳 token ~3.2K ≤ 5K 上限。注:test_plain_language 1 例失败为**预先存在**(其它未归档
  change 的 proposal 缺人话序,与本 change 无关,已在提交树上验证);`check_distributed_prompt_budget.py`
  尚不存在(AGENTS.md R5.6 规划项,非本 change 范围,token 复测以 measure_prompts.py 手动覆盖)
- [x] 5.3 真机冒烟(小仓 `C:/DEV/mgh-fanout-spike`,双宿主各一轮,全绿):
  - opencode host:`fanout_runner.py --host opencode` → init-scout-fanout(primary)headless spawn
    → 读 stage 提示词 → 读 input_path → 产出真实候选(TokenFilter.check → authentication,
    file:line 锚点)→ 写 checkpoint + .done → `ok <path> 1` ack → 摘要 done:1/1 partial:false
  - claude host:`--host claude` 同磁盘状态 → 等价 checkpoint(1 candidate + 1 unresolved)→
    .done + `ok` ack → done:1/1
  - 路径修复(冒烟暴露,已修 + 回归):① Windows npm `.cmd` shim 下 argv[0] 需 `shutil.which`
    解析(WinError 2);② 多行任务消息经 argv 被 shim 截断(子代理只收到 `<!--`)→ 改经 stdin
    管道(双宿主 stdin 消息形态均实证)
  - 哨兵:write_runconfig 已落 `.active`,子进程 cwd=repo 向上发现激活(spike 仓实证 run_config
    + sentinel 落盘);大仓(≥数百批)与 token 消耗对比留待维护者在大仓真机跑(本 spike 仓 1 批,
    对比无意义;dispatcher 路径编排器 scout 段 = 1 次 Bash + 1 次读摘要,结构上取代每波 1–3K × 波数)
