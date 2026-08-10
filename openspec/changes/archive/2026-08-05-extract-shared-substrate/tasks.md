# Tasks — extract-shared-substrate

> 行为保持(P0)。所有改动 SHALL 不改变 mgh-init 流水线可观测行为;每步可独立验证。
> 满足 `orchestration-substrate` spec 各 Requirement(见 `specs/orchestration-substrate/spec.md`)。
> 研发铁律:R2 零依赖 / R3 文档简练 / R5.1 `--help` 即契约 / R5.6 `REQUIRED SUB-SKILL` 替代 `@` /
> R5.8 版本号 bump / R5.10 分发纯净。

## 1. 共享 fragment(满足 R1)

- [ ] 1.1 新建 `core/prompts/fragments/orchestrator-discipline.md`:顶部加 `<!-- … -->` 用途注释
      (对齐既有 fragment 体例,说明「被 mgh-init/ut-init/ut 壳经 REQUIRED SUB-SKILL 引用」)。
- [ ] 1.2 从 `releases/claude-code/commands/mgh-init.md` 的「Orchestrator discipline(铁律)」+
      「Re-entrancy & compaction」段抽取**宿主无关**纪律正文:① 编排器 = 宿主 agent;② 三条 `NEVER`
      硬边界(脚本扩展名 Write / `py -c` 内省 / Read 叶脚本源码);③ implementation-intention recipe;
      ④ fan-out 刚性三元组;⑤ `.failed` 终态 + crash≠失败;⑥ 长跑 Bash per-call `timeout` + opencode
      env-var 边界;⑦ resume-from-disk(进度真相 = 磁盘)。
- [ ] 1.3 把抽取正文**泛化**:用「该命令的 `list_*` 枚举脚本」「resume-state 脚本」等抽象名词替换
      init 专属名(`list_clusters.py`/`resume_state.py`/`controls_candidates.json` 等不进 fragment)。
      验证:fragment 正文 grep 不到 init 专属脚本名/产物名。
- [ ] 1.4 纯净性自检:fragment 正文无 `R5.x`/`FDn`/`Dn`/变更夹名/`承 R5`/`范式锚点` 等 dev-meta
      (操作性 `NEVER`/`--check`/退出码 2 保留)。

## 2. 两壳改引用(满足 R2)

- [ ] 2.1 `releases/claude-code/commands/mgh-init.md`:删被 fragment 覆盖的纪律正文块(三条 `NEVER`
      详述、implementation-intention recipe 详述、fan-out 刚性三元组详述),保留一句指引「编排器 =
      宿主 agent;完整纪律见 orchestrator-discipline fragment」+ 顶部 `REQUIRED SUB-SKILL: Use
      orchestrator-discipline` 标记。
- [ ] 2.2 同上改 `releases/opencode/command/mgh-init.md`(两壳引用同一 fragment、正文零 drift)。
- [ ] 2.3 验证两壳 stage 流 / Deterministic invocation / `MGH_INIT_ACTIVE`+`.mgh-init/.active` 哨兵 /
      init 边界披露段**未随纪律正文一并移出**(仍留壳内);`test_init_runtime.py` 绿。

## 3. `--run-root` 参数(满足 R3)

- [ ] 3.1 `core/scripts/resume_state.py`:加 `--run-root <name>`(默认 `.mgh-init`);运行目录解析
      优先级 `--init-dir` > `--run-root` → `<target>/<name>` > 默认 `<target>/.mgh-init`;更新 `--help`
      docstring(CLI 契约,R5.1)。tier 逻辑/产物名/**`--check`** 全部不动。
- [ ] 3.2 `core/scripts/write_runconfig.py`:同上加 `--run-root` + 优先级解析 + `--help` docstring;
      `run_config.json` 写入路径随之解析。
- [ ] 3.3 验证默认行为字节级一致:`--target <t>` ≡ `--target <t> --run-root .mgh-init`(stdout / 退出码 /
      产物路径逐字相同)。

## 4. 测试扩展(满足 R3 + R4)

- [ ] 4.1 `tests/test_resume_state.py` 加用例:① 默认 = 旧行为;② `--run-root .mgh-ut-init` 读命名目录;
      ③ `--init-dir` 优先于 `--run-root`。
- [ ] 4.2 `tests/test_write_runconfig.py` 加同三类用例(`run_config.json` 落对应目录)。
- [ ] 4.3 确认 `tools/check_contracts.py` 覆盖新 flag(双壳中 `resume_state.py`/`write_runconfig.py`
      调用的 `--run-root` 在各自 `--help` 中存在);若 lint 规则需扩扫描集则扩之。

## 5. 版本号 + 全量验收(满足 R4)

- [ ] 5.1 bump 涉事产物版本号(两壳 `description`/版本标记、两脚本版本常量、新 fragment 无版本字段但
      入镜像;承 R5.8)。
- [ ] 5.2 跑既有回归全套(`tests/test_resume_state.py` / `test_write_runconfig.py` / `test_init_runtime.py` /
      `test_init_ack_contract.py` / `test_distributed_md_purity.py` / `test_opencode_hook_parity.py` /
      `test_deterministic.py` 等)全绿。
- [ ] 5.3 跑三项 lint:`tools/check_contracts.py`、`tools/check_distributed_purity.py`(含新 fragment)、
      零依赖 AST 扫描(`test_zero_deps.py`);`install.sh` 自检 fail-soft 通过。
- [ ] 5.4 人工评审:`REQUIRED SUB-SKILL` 标记措辞能指引宿主 agent 找到并加载
      `.claude/mgh-core/prompts/fragments/orchestrator-discipline.md`;确认 sast 与 resume tier 逻辑未被动。
