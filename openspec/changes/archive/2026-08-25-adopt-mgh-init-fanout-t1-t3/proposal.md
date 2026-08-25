# Proposal: adopt-mgh-init-fanout-t1-t3

> **人话序**
> **现象**:scout 层经 `add-mgh-init-scout-fanout-runner` + `improve-…-longrun-timeout-visibility`
> 两轮落地后,大仓真机已稳定(数千批零 LLM 回合派发、路径漂移构造性消失、软时限先于宿主硬杀、
> 人可看 sidecar 进度)。但 `/mgh-init` 的另两个 LLM fan-out tier——T1 per-cluster 归纳
> (`list_clusters` → init-induct)与 T3 per-category 出规则(`list_rule_jobs` → init-rulewriter)
> ——仍是编排器逐波手派旧形态:每波一次 LLM 回合、任务消息由弱模型逐次撰写、无三级超时接线。
> **根因**:dispatcher 首版按 Non-Goals 明确收窄为 scout 专用(`--tier` 泛化入口留而未实现),
> 优化经验没有传导到同构 tier。**改什么**:`fanout_runner.py` 泛化为 tier-aware
> (`--tier scout|t1|t3`,消费各自 list 脚本、模板、agent 克隆),t1/t3 fragment 改
> dispatcher-first + 手派回退,T3 枚举 stdout 补 `repo` 锚,T1 scout 闸门退出码 2 透传。
> **怎么验证**:`tests/test_fanout_runner.py` 增 tier 参数化用例 + 契约 lint(新 flag)+
> 双壳 token lint + 双宿主真机冒烟(t1/t3 批全 `.done`、marker 集合与手派路径等价)。

## Why

scout 两轮优化沉淀出的承重经验,对 T1/T3 同样成立且尚未兑现:

| 经验(scout 已实证) | T1/T3 现状缺口 |
| --- | --- |
| 派发循环下沉纯代码波次(1 次 Bash + `partial:true` 重派,零 LLM 回合) | 编排器逐波手派,每波 1–3K token + 弱模型漂移面 |
| 任务消息 = 固定模板 + 枚举 stdout 逐字填充(路径拼写错误构造性不可能)+ spawn 前锚树拦截 | 任务消息逐次手写;`list_rule_jobs` stdout 无 `repo` 锚,锚树校验无从谈起 |
| 三级超时不变式(软时限先于宿主硬杀)+ 宁慢勿杀 + sidecar + 宿主外直跑逃生门 | 均无接线;大仓 T1 簇数百时同样会遭遇「杀→查盘→重派→又被杀」循环 |
| opencode `mode: primary` fanout agent 克隆 + stdin 传消息 + `shutil.which` 解析(真机实证) | T1/T3 无 fanout agent 克隆,headless spawn 不可寻址 |

且 T1/T3 与 scout 的派发形态同构(枚举脚本 stdout slim `pending[]` + per-unit 物化
`input_path` + `.done`/`.failed` marker 真相源),泛化是复制已验证机制,非新设计。

## What Changes

- **`fanout_runner.py` 泛化为 tier-aware**:新增 `--tier scout|t1|t3`(默认 scout,既有调用
  面零变化);tier → {枚举脚本调用、任务模板、占位符集、锚树路径字段集、fanout agent 名、
  `.failed` marker `tier` 值} 的映射集中单点;T1 透传 `--clusters`/`--candidates`,T3 透传
  `--inventory`/`--format`/`--rules-dir`;`--checkpoints`/`--inputs-dir`/波次/超时/sidecar/
  ack 状态机全部复用。
- **新任务模板** `core/prompts/fragments/fanout/t1-task.md` / `t3-task.md`(与 `scout-task.md`
  同形状:仅输入字段声明 + 指向各自 stage 提示词的装载指令,零行为规则复制)。T3 占位符集用
  `rule_path`(无 `checkpoint_path`/`slice_dir`)。
- **`list_rule_jobs.py` stdout 补 `repo` 锚字段**(取 `--target` resolve 绝对值;`list_clusters`
  已有)——dispatcher 锚树校验的前提。
- **T1 scout 闸门透传**:`list_clusters` 因 scout 未完成退出码 2 时,dispatcher 以退出码 2 +
  stderr recipe fail-loud(先完成 scout 层),NEVER 进入 crash 重派循环。
- **进度 sidecar 按 tier 命名**:`fanout_progress.<tier>.json`(scout 由 `fanout_progress.json`
  改名;运行态披露件非契约产物,人类面文档同步)。
- **opencode 侧新 fanout agent 克隆**:`init-induct-fanout.md` / `init-rulewriter-fanout.md`
  (`mode: primary`,正文 = 既有 induct/rulewriter 定义);claude 侧 `--agents` inline JSON 已是
  per-tier 参数化路径,无新增落位文件。
- **t1/t3 fragment 派发段改 dispatcher-first**(`init-stage/t1.md`/`t3.md`):主路径 = 一次
  `Bash` 跑 `fanout_runner.py --tier …`(带 `--time-budget-ms` 接线)+ `partial:true` 重派;
  退出码 2 → 回退现状手派路径(原文保留);T1→T2 validate 闸门、T3 后续 assemble 步不动。
- **`list_steps.py` t1/t3 步契约面**增 dispatcher 调用行 + `discipline_core.py` path_recipes
  增软时限重派纪律;`tools/check_contracts.py` 断言 `--tier` 等新 flag;install 自检清单覆盖
  新模板/agent 文件;版本号 bump。

## Capabilities

### New Capabilities

(无——`fanout-dispatch` 基座已存在,本 change 是其消费方从 scout 扩到 T1/T3)

### Modified Capabilities

- `fanout-dispatch`:dispatcher 从 scout 专用泛化为 tier-aware——`--tier scout|t1|t3` 映射
  (枚举脚本/模板/占位符集/锚树字段集/agent 名/marker tier 值);T1 scout 闸门退出码 2 透传
  语义;sidecar 按 tier 命名;`list_rule_jobs` stdout `repo` 锚;编排器 t1/t3 步调用面切换与
  回退(对偶 scout 已有 requirement)。
- `request-context-budget`:「Orchestrator context is bounded by a slim paged work-list」
  requirement 增量——dispatcher 路径从 scout 步扩至 t1/t3 步:t1/t3 编排器 SHALL 一次 `Bash`
  调用 `fanout_runner.py --tier …`,`partial:true` 重派;该路径下 NEVER 手动翻页、NEVER 逐次
  撰写 subagent 任务消息;重派传 per-call `timeout` > `--time-budget-ms` 同 scout 纪律。

## Impact

- **代码**:`core/scripts/fanout_runner.py`(tier 映射泛化)、`core/scripts/list_rule_jobs.py`
  (stdout `repo` 字段)、`core/prompts/fragments/fanout/{t1-task,t3-task}.md` 新增、
  `core/prompts/fragments/init-stage/{t1,t3}.md` 派发段改写、`releases/opencode/agent/
  {init-induct-fanout,init-rulewriter-fanout}.md` 新增、`core/scripts/list_steps.py` +
  `core/scripts/discipline_core.py`(t1/t3 步契约面与 recipe)、`tools/check_contracts.py`
  (新 flag lint)、`install.sh`(镜像/自检清单)、`docs/man/mgh-init.md`(sidecar 名 + 手动直跑
  说明)、`tests/test_fanout_runner.py` 扩展、CHANGELOG/VERSION bump。
- **既有安装项目**:重跑 `install.sh` 获新模板/agent/脚本;无磁盘 schema 变更
  (`run_config.json`/`init_manifest.json` 不动;sidecar 改名是运行态文件,旧名残留无害)。
- **风险**:① T3 `rule_path` 双格式(claude `.claude/rules/` / opencode `docs/security-controls/`)
  均在 repo 树内,锚树校验已覆盖,需单测锚定;② T1 簇数在大仓可达数百,首跑标定同 scout
  (三级超时默认值沿用,`--wave 5` 不动);③ sidecar 改名对刚形成的 man page/使用习惯是小破坏
  (一次性,文档同步)。
- **非目标**:不治 mgh-sra a2/a3/a4、mgh-ut-init、scout-merge shard 等其它 fanout 的采纳
  (同构可复制,后续 change);不改 marker/resume/翻页契约与 T1→T2/T3 后续步骤语义;不引入
  pip 依赖。
