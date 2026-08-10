## Why

AI 编程 Agent 写新单元测试时,**不知道项目既有的测试家法**——重新发明框架、断言库、mock、夹具、
命名;还会把**应付式弱测试**(零断言、mock 不全、只跑 happy-path)当成家法学下去。

`/mgh-ut-init` 扫描项目的存量测试代码 + 构建配置,提炼出团队真正在用的**测试约定**,写成 Agent
可直接消费的 rules,让 Agent(opencode / Claude Code)写新测试时自动遵循既有家法。它是 mgh-族
(目前是安全纵向)的**第二纵向:测试质量**——共享同一套骨架(确定性脚本 + 磁盘可恢复 + hook 强制 +
诚实边界),只是被分析对象从「安全控制」换成「测试约定」。

为什么现在做:共享基座(宿主无关的编排纪律 fragment、可参数化的运行目录)已由上一个变更交付,
ut-init 是它的第二个消费方。

## What Changes

- **新命令 `/mgh-ut-init`**(claude + opencode 两个薄壳):一条**精简、LLM 为主**的流水线——
  `归类 → 逐组抽样提炼 → 汇总去重 → 出 rules`。**不照搬** mgh-init 那套 5 层 + regex 发现器 +
  scout(那是被百万行生产代码规模逼出来的;测试代码面小得多、逐文件词法特征更密,用不上)。
- **fan-out 单元 =「层组」,不是逐文件**。测试代码高度模板化(Controller 测试一个风格、Service
  一个风格、Util/Common 更杂);先按「被测层 + 实际用到的注解/import」把测试文件分桶,每组只读
  一个**代表性样本**(均匀组读少几个、异质组读多一些或再细分),提炼该层约定。这把 fan-out 单元
  从「N 个测试文件」降到「K 个层组」,消掉模板冗余,也给了 LLM 足够证据看清模板。
- **弱测试不学成家法**:提炼时 LLM 在上下文里识别样本中的应付式弱测试、**不把它的模式当约定**;
  弱测试只**标记不删**;弱信号主导的约定在产物里标低置信、提示需人评。(语义类弱信号——「这测试
  flip 个运算符还会过吗」「mock 没覆盖到真实依赖」——本质上要靠 LLM 判断,不强行做成确定性脚本。)
- **确定性脚本只做「便宜的、可回归的」预处理 + 收尾**:归类器(分桶 + 抽样清单)、rules 组装 +
  纯净 lint、边界校验、**pitest mutator 默认清单派生**(确定性解析 `pom.xml`/`build.gradle` 的
  pitest 配置;没配则用内置标准集;留给后续 `/mgh-ut` 消费)。其余发现/归纳/汇总都交 LLM。
- **复用共享基座**:宿主无关的编排纪律 fragment(经 `REQUIRED SUB-SKILL` 引用)、预算闸门 / 大文件
  切片 / 结构瞄一眼 / 可恢复 resume 等域无关脚本——零改动复用。
- **新增第 5 个 hook 运行域** `mgh-ut-init`(env `MGH_UT_INIT_ACTIVE` 或磁盘哨兵激活),双端
  (claude + opencode)对等,拦越权的脚本写 / `py -c` 内省 / 越出项目树的写。
- **诚实边界**:`/mgh-ut-init` 的 rules 是**提示、不是完备规约**——抽样提炼必有遗漏,可接受;后续
  `/mgh-ut`(diff 测试质量门)的 LLM 在写测试时会看到真实测试、自适应,即便 rules 不全也能贴合
  项目家法。约定是 LLM 归纳候选,需人评。

**明确不做**:JVM 以外语言(本版只 JVM);`/mgh-ut` 本身(后续变更);实跑 pitest 验证变异是否被
杀死(后续 opt-in);新增任何 pip 依赖。

## Capabilities

### New Capabilities

- `test-convention-discovery`: `/mgh-ut-init` 的测试约定提炼流水线契约——(1) 归类:按被测层 + 实际
  注解/import 把测试文件分桶,带均匀度提示;(2) 逐组抽样提炼:每组读代表性样本,LLM 提炼该层约定
  并标记弱测试(不学成家法);(3) 汇总去重:跨组归并成 rules;(4) 双宿主 rules 输出(结构不混)+
  pitest mutator 默认清单派生;(5) 复用共享基座的可恢复 / 预算 / fan-out 契约;(6) 自包含 + 诚实
  边界披露(rules 是提示非完备、弱测试标记不删、约定需人评)。

### Modified Capabilities

- `runtime-hook-enforcement`: 运行时守卫的域表从 4 个扩到 5 个,新增 `mgh-ut-init`(env
  `MGH_UT_INIT_ACTIVE=1` 或 `<cwd>/.mgh-ut-init/.active` 哨兵);该域的写入受信子树限定姿态(类比
  mgh-init 的正向允许清单 `.mgh-ut-init`/`.claude/rules`/`docs/test-conventions`/`AGENTS.md`,而非
  仅越树检查——ut-init 同样会把 rules 写进这些受信子树,有同样的「树内根污染」风险要拦)。

## Impact

- **新脚本(Python ≥3.10 标准库,零依赖)**:`classify_tests.py`(分桶 + 抽样清单)、
  `list_test_groups.py`(fan-out 工作清单 + 样本物化)、`assemble_test_rules.py`(rules 组装 + 纯净
  lint)、`validate_test_rules.py`(边界校验)、`derive_mutators.py`(pitest 配置 → 默认 mutator
  清单)、`resume_ut_init_state.py` + `write_ut_runconfig.py` + `list_ut_steps.py`(可恢复 resume /
  起始态意图 / step 枚举;拷贝自 init 对应脚本,改 ut 的步骤图与产物名,不改 init 的)。
- **改脚本(双端 byte-identical 守卫)**:`releases/{claude-code/hooks,opencode/hooks}/block_adhoc_scripts.py`
  —— `_DOMAINS` 加一行 `mgh-ut-init`;判定逻辑不动,只扩域表 + recipe + 该域的受信子树集。
- **新提示词**:`releases/claude-code/commands/mgh-ut-init.md`、`releases/opencode/command/mgh-ut-init.md`
  (薄壳)+ ut stage subagent 提示词(`core/prompts/stages/ut-{classify-survey,extract,synthesize,
  rulewriter,consistency}.md`)。
- **新契约**:`core/contracts/ut-init/`(分组清单 / 样本输入 / rules / mutators / resume-state 等,
  镜像 `core/contracts/init/` 的目录结构,换 schema)。
- **新测试**:`tests/test_classify_tests.py`、`test_ut_init_runtime.py`、`test_resume_ut_init_state.py`、
  `test_ut_init_ack_contract.py`、`test_test_rules_purity.py`;扩 `tests/test_block_adhoc_scripts.py` +
  `test_opencode_hook_parity.py`(第 5 域)、`test_distributed_md_purity.py`(新壳 + 新 stage 提示词)。
- **工具**:`tools/check_contracts.py`(加 ut-init 壳 + 新脚本 CLI 契约断言);`install.sh` 自检共定位
  清单加 ut-init 脚本族。
- **依赖**:零(纯标准库)。
- **分发**:`install.sh` 镜像新壳 + 新脚本 + ut stage 提示词 + ut 契约到目标项目;版本号 bump 触发
  install 自检(失败只 warn 不阻断 install,但 CI 必 fail)。
- **与在途变更衔接**:`add-mgh-telemetry-seam`(在途)给每条 mgh-* 命令成功末步加一行运行回执脚本
  调用——谁先 apply,另一方就给 ut-init 两壳补这一行。软排序,非阻塞。

## 评审修订(docs/review-add-mgh-ut-init.md,2026-08-06)

`docs/review-add-mgh-ut-init.md` 评审发现 10 条 spec/契约/壳与实现漂移(无运行时破坏)。**F1–F9 本次原地
修订本 change**(两个 spec delta + 双壳/契约/脚本/tests);**F10**(`write_ut_runconfig.py` 共享去重)**暂缓**——
共享 `write_runconfig.py` 不带 ut 抽样 flag,真换需碰 init 或丢持久化(冲突 F9),符决策 5 演进路径待
`/mgh-ut` 再做。逐条修复决策 + 已对源码核实的失败形状见 `design.md`「评审修复」段;实现侧任务见 `tasks.md` §12。
