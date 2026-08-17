> **人话序**(先讲清楚,再讲规格):最近几代模型升级后,本仓写出的中文文档越来越像「写给另一个模型的暗号」——英文原词裸嵌中文当零件(`mid-session`、`recipe`)、一句话压成没有主谓宾的等式(`来源层 = producer 物化 repo 锚 + reader 统一拒识 recipe`)、自造压缩词满天飞(`锚`/`物化`/`拒识`/`承`)。维护者靠猜才能读懂每个迭代在干嘛,装进别人项目的工具说明用户也看不懂。
>
> 根因不是模型写不出人话——`docs/r5-plain-language.md` 是全仓唯一能顺畅读完的长文档,证明模型被明确要求时完全写得出来。根因是**章程明文写着「面向 AI 阅读」**(R3),等于在奖励变难。
>
> 怎么改:把「给谁读」写进章程。给人类读的文件(命令说明书、术语词典、proposal 开头一段)强制大白话;给 agent 读的文件(NEVER 链、flag 表、纪律段)**一字不动**——两类读者按**文件**分开,不混。终端报告的人话化这次**不做**(要过 R5.7 A/B 闸门、还和在途改动撞车),压到下一个 change。
>
> 怎么验证:CI 加一台「代理 lint」——proposal 有没有人话序(机器能查)、人话文件里有没有出现黑名单术语(机器能查);真正「人读得懂」机器测不了,靠一条人工闸门:维护者只读人话序 + 任务清单,能复述出这个 change 在干嘛,做不到就是没就绪。

---

## Why

模型升级(自 GLM5.2 起)后本仓全部产物——spec 工件、AGENTS.md、分发提示词、终端报告——出现系统性的「难懂」:英文原词当零件、名词堆叠等式句、生造压缩词、写给「共享全部上下文的自己」。根因在项目层可控处:**R3 明文「面向 AI 阅读」把人类可读性排除在验收之外,R5.5 措辞纪律(为弱模型服从而设)外溢到所有写作,术语通胀无词典,自消费架构整条链路无「人能读懂」这一验收标准**。两个目标:(a) 维护者能看懂每个迭代在干啥;(b) 目标项目用户能看懂工具在干啥。

## What Changes

- **R3 修订(受众声明制)**:每份产物声明受众(人类 / agent / 双受众);人类面强制大白话(现象→原因→改法、术语首次出现给一句解释、允许冗余);R5.5 措辞纪律只辖 agent 指令、不蔓延到人类面;`proposal.md` 是唯一**双受众**文件(人话序 ~200–300 tok 便宜且对 `opsx:apply` agent 也有益,非零成本、是「低成本+双赢」)。加**人工闸门**进就绪标准:维护者只读人话序 + tasks.md 能复述出本 change,做不到 = 未就绪。
- **proposal 人话序**:proposal 模板(本仓 convention,写进 R3)加 ~200–300 字人话序(现象→根因→改什么→怎么验证),先写人话再压缩成 spec。
- **`docs/glossary.md` 种子**:~30–50 条术语(取自 AGENTS.md + `docs/r5-plain-language.md` 术语表);规则「人类面产物用词前词典必须有,缺则先补词典」。
- **CI 代理 lint `tools/check_plain_language.py`**(stdlib,承 R2/R5.3):存在性检查(proposal 人话序存在)= fail-loud(exit 2);术语黑名单(`物化`/`拒识`/`接线`/`承`/`兑现`/`治类`…)出现在人类面文件 → WARN;英文原子密度超阈值 → WARN(仅扫人类面文件)。
- **`docs/man/<cmd>.md` ×5**:mgh-sast / mgh-init / mgh-sra / mgh-srr / mgh-ut-init 的人话版说明(做什么 / 会动哪些文件 / 产出什么 / 风险边界)。
- **man 文档分发**:`install.sh` 拷贝 `docs/man/` → `<target>/docs/man/`;每壳加一行人类读者指针(~20 tok);`tools/check_distributed_purity.py::SCAN_DIRS` 加 `docs/man`(维持「shipped = scanned」不变量)。
- **不做 / 压后**:C(终端产物语域 report.md / `docs/security-controls/<cat>.md` 人话化——需 R5.7 A/B + 与在途 `init-scout.md` 同文件冲突)、详述文件 1.3× 软上限(随 C)、改写壳操作散文 / NEVER 链 / stage 行为段(**永不**)。

## Capabilities

### New Capabilities

- `plain-language-doctrine`: 双层产物制度——受众声明制(每份产物声明给谁读)、人类面人话规范(现象→原因→改法、术语首次出现给解释、允许冗余)、术语词典(`docs/glossary.md`,用词前必有)、命令 man 文档(`docs/man/<cmd>.md`,人话版)、proposal 人话序(现象→根因→改什么→怎么验证)、CI 代理 lint(存在性 fail / 黑名单+密度 warn)。

### Modified Capabilities

- `distribution-purity`: shipped md 文件集扩为含 `docs/man/`(新增一类分发的面向人类 md),维持「shipped 集 = `install.sh` 拷贝 source globs = `check_distributed_purity.py::SCAN_DIRS` 扫描集」三同源不变量。

## Impact

- **代码 / 文件**:`AGENTS.md`(R3 段修订 + 人工闸门)、`docs/glossary.md`(新)、`docs/man/*.md`(新 ×5)、`tools/check_plain_language.py`(新)、`install.sh`(加 man 分发段)、`tools/check_distributed_purity.py`(SCAN_DIRS 加 `docs/man`)、5 命令壳 ×2 平台 = 10 文件(各加 1 行人类读者指针)、`tests/test_plain_language.py`(新)、CI 接线。
- **依赖**:无第三方(R2,`check_plain_language.py` 仅标准库)。
- **在途冲突**:`AGENTS.md` R3 段与 `harden-mgh-init-scout-path-binding` 的 R5.7 段 B 改动**同文件不同段**,轻度交集,错开合入即可;其余零冲突(4 个在途 change 均不碰 5 命令壳、install.sh 的 man 分发面)。
- **既有安装项目**:重跑 `install.sh` 后获得 `docs/man/`(新增,幂等);壳指针行为不变(仅一行提示)。
