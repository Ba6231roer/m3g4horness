> **人话序** 现象:Linux 测试环境在 `/adhome/xxx/gitlab_pab/project_name/independent_sub_project/` 跑 `/mgh-init`,scout 409/409 完成后 T1 卡 0/9——agent 反复尝试访问 `/home`、`/adhome` 等项目外目录找提示词/脚本;另 `resume_state.py --target .` 时 stderr 报 `list_clusters.py:69: SyntaxWarning: invalid escape sequence`。根因:①守卫读侧 Bash 逃生路由只拦**搜索**动词(rg/grep/find/fd…),`ls`/`dir` 等列目录动词完全不在拦截面;②守卫只拦「无解释器的文件关联执行」,`py/py3/python/python3` 带**项目外脚本路径**执行反而因「显式解释器前缀」放行;③mgh-core 只装在根 proj、子项目没装时,脚本/提示词 404,agent 就地漫游(没有任何一处说「找不到就停,要求用户装」);④`list_clusters.py` 模块 docstring 里有 `` `\` `` 非法转义,import 即触发编译告警污染 stderr。改什么:守卫新增三条 Bash 规则(列目录动词越树拦截、解释器执行越树脚本拦截、mgh-core 脚本缺失 → 停止全部任务 + 要求用户安装);t1 任务模板/stage 提示词硬钉提示词唯一位置 + 找不到即 failed ack;docstring 改 raw 消告警。怎么验证:守卫单测(新三规则 hit/pass 双面)+ 双端 parity + 全叶脚本编译零告警回归测。

## Why

真机 Linux 大仓首跑暴露的守卫读侧三个并列缺口 + 一个 stderr 契约缺陷。mgh-* 的可用性前提是「找不到既定路径 → fail-loud 就地停止」,而当前守卫对「列目录漫游」与「解释器带外执行」完全不设防,对「产品自身未安装」给出的是 shell 原生 FileNotFoundError(无 recipe),弱模型的自然反应就是跨目录漫游找脚本/提示词——既烧 token 又可能读到项目外内容。

## What Changes

- 守卫(`block_adhoc_scripts.py`,双端 byte-identical)新增三条 Bash 规则:
  - **列目录动词越树拦截**:`ls`/`dir`/`Get-ChildItem`(含 pwsh 别名 `gci`/`ls`)作为首 token 或分隔符后子命令、scope(显式绝对路径参数或隐式 cwd)解析在 `MGH_TARGET` 树外 → exit 2 + 读侧 recipe(镜像现有 file-search 规则形态)。
  - **解释器越树执行拦截**:`py`/`py3`/`python`/`python3`/`python2` 作为首 token、第一个脚本扩展名参数解析在树外 → exit 2 + 写/读侧复合 recipe(镜像 file-association 规则的 operand-vs-arg 辨析:脚本路径是位置参数才判,`--flag <path>` 不判)。
  - **mgh-core 缺失安装拦截(stop-all)**:命令引用 `mgh-core/scripts` 路径段、其解析路径**不存在**或**在树外** → exit 2 + 专用 recipe:「mgh-core 未安装于当前 target——**停止全部任务**,报告用户在当前项目目录执行 install,NEVER 到其他目录找脚本/提示词」。治「只装根 proj、子项目没装」的真机形态。
- fan-out 任务模板(`t1-task.md` 等)+ reader stage 提示词:stage 提示词路径硬钉「唯一位置 = `{{repo}}` 内 mgh-core 安装路径」;该 Read 失败 → 立即 `failed mgh-core prompts not installed` ack(NEVER 跨目录漫游)。
- `list_clusters.py` 模块 docstring 改 raw string,消除 `` `\` `` SyntaxWarning;新增「全部 core/scripts 叶脚本编译零告警」回归测。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `runtime-hook-enforcement`:新增三条 Bash 收敛 requirement(列目录动词越树、解释器越树执行、mgh-core 缺失安装 stop-all)。
- `fanout-dispatch`:任务模板 requirement 增补——stage 提示词路径硬钉唯一位置 + not-found 即 failed ack(NEVER 漫游)。
- `orchestration-substrate`:叶脚本 stderr 严格分流契约增补——import/编译零 SyntaxWarning(回归测全量编译 core/scripts)。

## Impact

- `releases/claude-code/hooks/block_adhoc_scripts.py` + `releases/opencode/hooks/block_adhoc_scripts.py`(byte-identical 同步,`tests/test_opencode_hook_parity.py` 兜底)。
- `core/prompts/fragments/fanout/t1-task.md`(及同形 t3/scout/t2 模板的同位补句)、`core/prompts/stages/init-induct.md`(reader 锚定段补一句)。
- `core/scripts/list_clusters.py`(docstring 一处)+ 新回归测 `tests/`。
- 契约 lint(`tools/check_contracts.py`)与 purity lint 范围不变;守卫分派工具面不变(仍 Bash),wiring-coverage CI 不变量不受影响。
