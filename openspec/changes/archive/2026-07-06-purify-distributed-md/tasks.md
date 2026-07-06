## 1. 确定性 lint(强制闭环的基石,先建后用以驱动清理)

- [x] 1.1 写 `tools/check_distributed_purity.py`:扫描 shipped md 文件集(镜像 install 拷贝 globs:`releases/{claude-code/{commands,agents,skills},opencode/{command,agent}}` + `core/prompts/**` + `core/contracts/**`),八类高精度禁用模式:① `\bR\d+(\.\d+)?\b` ② `\bFD\d+\b` ③ `\bD\d+\b` ④ `AGENTS\.md\s+R\d` ⑤ `\b(add|fix|harden|improve|purify)-mgh-(init|sast|sra|blst)-[a-z0-9-]+` ⑥ `glasswing_docs/` ⑦ `\btask\.\d+\.md\b` ⑧ `范式锚点` / `承\s*R\d+` / `兑现\s*R\d+`;`--allowlist` 行级例外(默认空);stdout=JSON `{scanned, violations[], allowlisted}` / stderr=诊断分流;退出码 `0/1/2`;`--help` 即契约;stdlib only、自定位、`encoding="utf-8"`(承 R5.3 / R2)。**MUST NOT** 误报 runtime 路径 `.claude/mgh-core/scripts/*.py`、输出路径 `<target>/AGENTS.md`、操作阶段标签 `T1`/`s1`..`s9`;**MUST NOT** 把 `vvah`/`design_controls` 纳入硬边界(与受保护 Source: 头同形,交人工)
- [x] 1.2 写 `tests/test_distributed_md_purity.py`:子进程跑 lint 断言退出码 0;反向用例(临时植入 `R5.2` / `(D12)` / `improve-mgh-init-…` 进 fixture 应得退出码 2)
- [x] 1.3 跑 lint 产出当前违例 baseline(预期命中 mgh-init 分发物 ~60+ 处 + sra/blst 8 处),作清理收敛靶 → 实测 91 文件 / 91 offending lines,sast 分发物零命中

## 2. AGENTS.md 铁律 R5.10

- [x] 2.1 在 AGENTS.md R5.9 之后新增 **R5.10 分发产物纯净性**(design D5 措辞:recipe + 硬边界 `NEVER` + RFC-2119 + 无豁免子句 + 理由〔省 token + 防目标项目误读 + 平台无关〕),覆盖**完整 8 类**禁引(规则/失败/决策 ID、变更夹名、glasswing_docs、task.md、dev-meta、上游溯源行话),指向 `tools/check_distributed_purity.py` 承 R5.7
- [x] 2.2 若 AGENTS.md / 命令壳有「R5 条目索引」处,登记 R5.10 与 lint / 测试 → 无 R5 索引处(AGENTS.md / 命令壳均无),vacuous 满足

## 3. shipped md 清理 —— 按「删 / 嫁接」二选一(design D8),每批后跑 lint + `git diff` 自证

> 总原则(spec「delete-or-graft」):被引内容目标**不需要** → 删;**必需** → 最简内联再删指针。
> 受保护类(spec R3)`Source: vvaharness/...` 头 / skills Apache 归因 / `core/docs/prompt-provenance.md` /
> 操作性 `design_controls` / `CVE-2025-41248` —— **不动**。

### 3.1 mgh-init 命令壳 + agent 定义(releases/{claude-code/commands,opencode/command,claude-code/agents,opencode/agent})
- [x] 3.1.1 剥 `(R5.2 / R5.9)`、`校验(R5.9)`、`(兑现 R5.7)`、`R5.9 T2 边界`、`范式锚点`、`承 R5.x`;**保留** `--check`/退出码 2/`<target>/AGENTS.md`/脚本调用路径
- [x] 3.1.2 剥决策 ID `(D9)`/`D2`/`D4`/`(D12)`/`via D8`/`(D5)`(mgh-init.md 输出说明 + 各 agent `description:`);操作语义已内联则删
- [x] 3.1.3 剥上游行话作归因:`vvah 兼容`(mgh-init.md 表)、`vvah design_controls-compatible`(init-synthesis.md 描述)→ 换述为「design_controls-compatible」或删(操作性 schema 字段已在 mgh-init.md:101/:95 陈述)
- [x] 3.1.4 修 claude/opencode 变体不对称:claude mgh-init.md 仍带 `D9`/`D2`/`D4` 括注,opencode 已删 —— 统一到「已删」

### 3.2 mgh-init stage 提示词(core/prompts/stages/init-*.md)
- [x] 3.2.1 剥 6 处 `Sanctioned tools(白名单,R5.2 / FD8)` 尾标 → `Sanctioned tools(白名单)`(induct/scout/scout-merge/scout-audit/survey/rulewriter/rules-consistency)
- [x] 3.2.2 剥决策 ID `(D12)`/`D2`/`(D5)`/`D12-isomorphic`(induct/scout/scout-merge/scout-audit/rulewriter/rules-consistency)
- [x] 3.2.3 剥变更夹名 `improve-mgh-init-llm-discovery`(scout/scout-merge/scout-audit)
- [x] 3.2.4 剥 `glasswing_docs/09 §x.x`(induct:3 / survey:4)
- [x] 3.2.5 剥 `(R3)` / `(R2: zero runtime deps)` 标签,保留内联规则正文(rulewriter:29 / survey:5)
- [x] 3.2.6 剥 `vvah 6-enum` 行话(scout-merge:27)→ `kind` (6-enum);枚举值已在别处
- [x] 3.2.7 **嫁接(c)** init-scout-audit:6:保留 `Skeptic bias — "assume WRONG until confirmed":`,删 `mirrors mgh-sast s6`
- [x] 3.2.8 **嫁接(c)** init-survey:6:保留 `See core/contracts/init/`(分发),删 `and AGENTS.md R1–R4`

### 3.3 fragments(core/prompts/fragments/rules-format-{claude,opencode}.md)
- [x] 3.3.1 剥 `(R3)`(claude:42 / opencode:49)
- [x] 3.3.2 **嫁接(c)** rules-format-opencode:2:保留 `(.opencode/AGENTS.md NOT loaded)` 约束,删 `GitHub issue #11454` 票号
- [x] 3.3.3 (可选)rules-format-claude:2 的 `Source: code.claude.com/…` URL —— 保留(URL 归因,非强制);若维护者认为会腐烂可删

### 3.4 I/O 契约(core/contracts/init/*.md)
- [x] 3.4.1 剥 `承 R5.1` / `承 R5.3b` / `(R5.4 …)` / `(R3)`(scout-enumeration/rule-jobs/describe/scout-plan/rules-parts);操作性 CLI/退出码契约保留
- [x] 3.4.2 剥决策/失败 ID:`D9 = D12`/`D2`/`FD3`/`FD5`/`FD6`/`D4`(clusters/skeleton/scout-plan/candidates/scout-enumeration/rule-jobs/manifest/describe)
- [x] 3.4.3 剥变更夹名 `improve-mgh-init-llm-discovery` / `harden-mgh-init-orchestration-discipline`(skeleton/scout-plan/candidates/scout-enumeration/rule-jobs/describe)
- [x] 3.4.4 inventory.md:剥 `vvah`/`vvah-compat`/`vvah 6` 谱系词(标题 + 行标),**保留 alias 映射表体**(intake 实际接受的别名)
- [x] 3.4.5 `core/docs/prompt-provenance.md` —— **不动**(R1 受保护归因记录)

### 3.5 mgh-sra / mgh-blst 骨架(releases/{claude-code/commands,opencode/command}/mgh-sra.md、mgh-blst.md)
- [x] 3.5.1 剥仓根开发态文件指针 `task.260630.md`(每文件 2 处 × 4 文件 = 8 处);**保留**「TODO 未实现 + 打印参数表 + 不消耗 token」指令

### 3.6 终检:每批 `check_distributed_purity.py` 收敛 + `git diff` 自证「仅删标记/嫁接,操作语义无损」

## 4. mgh-sast 分发物(审计已确认 CLEAN —— 仅登记,不改动)

- [x] 4.1 确认 sast 命令壳 / 8 agent × 2 / 14 skills / stage prompts+baselines+lens+fragments 经 6-agent 审计零违例;lint 跑过应退出码 0(作回归基线)

## 5. install 自检 + 回归闭环

- [x] 5.1 `install.sh` 镜像后接入 `check_distributed_purity.py` 自检:fail-soft warn,不阻断 install(承 R5.8)
- [x] 5.2 跑全套回归测:`test_zero_deps` / `test_init_runtime` / `test_distributed_md_purity` / `tools/check_contracts.py` / `tools/check_distributed_purity.py` 全绿
- [x] 5.3 按 R5.8 既定版本位置 bump 受改 `.md`/脚本的版本号 → VERSION 0.1.3 → 0.1.4
- [x] 5.4 `/mgh-init --help` 与 `/mgh-sast --help` 烟测正常打印参数表(design D7(3)) → 9 脚本 --help exit 0 + check_contracts 63 flags 一致

## 6. 归档前终检

- [x] 6.1 全仓跑 `check_distributed_purity.py` = 退出码 0
- [x] 6.2 grep 复核 shipped md 无 8 类残留;`AGENTS.md` R5.10 存在且覆盖完整 8 类 + 引用 lint
- [x] 6.3 复核受保护类未被误伤:`Source: vvaharness/...` 头 / skills Apache 归因 / `prompt-provenance.md` / 操作性 `design_controls` / CVE 原样在
