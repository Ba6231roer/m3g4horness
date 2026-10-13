# fix-mgh-init-distribution-links — Tasks

> 实施纪律:先红后绿(每组测试先写、跑出失败、再实现);本机解释器先探测(`py --version;
> python --version` 取可用者;AGENTS.md 快速命令写 `python` 是维护者本机 `py` 坏的历史原因)。
> 壳/agent/fragment 改动 → `check_distributed_prompt_budget.py` 必跑;涉 shipped md → VERSION
> bump。涉改面 = `core/prompts/**`(8 文件)+ `releases/**`(三面壳 + agents)+ `core/scripts/
> write_runconfig.py` + `install.sh` + 两 lint 工具;dispatcher 与守卫零触碰。

## 1. 测试先行(红)

- [ ] 1.1 第 10 类死链红测:`tests/test_distributed_md_purity.py` 新增用例——shipped md 含
  `core/prompts/…`/`core/contracts/…`/`core/scripts/…` 前缀引用 → lint 退出码 2(现网 init
  切片命中即红:`core/prompts/stages/init-*.md` ×6 codegraph-hint + `init-rulewriter.md`
  rules-format ×2 + 三面 init 壳 `core/contracts/init/unit-inputs.md`);基线外新增命中即红、
  allowlist 基线内放行两形态都断言(现状:lint 无此类别 → 红)
- [ ] 1.2 失实头注红测:codegraph-hint.md 头注含 `Inlined into the task message` 类机制陈述 →
  违例断言(或最小形态:断言头注不含 `Inlined`;现状含 → 红)
- [ ] 1.3 壳 flag 表对账红测:`tools/check_contracts.py` 扩展 + 对应测试——三面 mgh-init 壳
  参数表条目对账消费脚本 `--help` 并集(豁免清单显式);现网 `--out`/`--config` 无消费点 → 红;
  claude 面缺 `--rules-dir` 行 → 红(断言三面 flag 表同集)
- [ ] 1.4 分发完整性红测:壳 subagent inventory 点名的 agent 文件在对应 `releases/<platform>/`
  存在断言——claude 面点名 `init-scout-merge-rollup` 而文件缺失 → 红(挂
  `test_distributed_md_purity` 或新测试文件)
- [ ] 1.5 agent/stage 操作契约同形红测:fanout agent 的 ack 枚举形态词集 ⊆ 对应 stage
  Return-to-orchestrator 形态词集——`init-scout-fanout` 枚举 `oversize` 而 `init-scout.md`
  未定义 → 红;`init-scout-audit.md` frontmatter `bash: deny` 与 stage 授权 chunk_sources 调用
  冲突 → 红;audit Input 缺 `slice_dir` → 红
- [ ] 1.6 gitignore co-write 红测:`tests/test_write_runconfig.py` 新增——step 0 落盘后
  `<run-root>/.gitignore` 存在且内容 `*`;已存在时幂等不重写;目标根既有 .gitignore 零改动
  (现状无此行为 → 红)
- [ ] 1.7 dsh 披露实况红测(文本断言,挂 `test_dsh_command_surface` 或同类):SKILL.md 派发
  披露段含 scout-merge、停止清单含 `init-synthesis`/`init-synthesis-rollup`/
  `init-scout-merge-rollup`、含 mid-run 不可注入与非终态处置表述(现状缺 → 红)

## 2. 实现(绿)

- [ ] 2.1 H10:`core/prompts/stages/init-{scout,induct,survey,resolve}.md` +
      `sra-{clarify,augment}.md` 的 codegraph-hint 引用改兄弟相对表述(D1 形态,操作性正文
      逐字保留);`codegraph-hint.md` 头注「Inlined …」改述实况;跑 1.2 转绿
- [ ] 2.2 H14:claude/opencode 三 agent 定义引用改各宿主安装布局绝对路径;单源
      `init-rulewriter.md` 兄弟相对(D2);`init-rulewriter-fanout.md` 同修
- [ ] 2.3 同形态顺带修:三面 init 壳 Output 节 `core/contracts/init/unit-inputs.md` →
      `mgh-core/contracts/init/unit-inputs.md`(安装布局);init 切片命中全部移出第 10 类
      allowlist 基线;跑 1.1 转绿(基线外零命中)
- [ ] 2.4 H9:`releases/dsh/skills/mgh-init/SKILL.md` 派发披露段四处改实况(D3);跑 1.7 转绿
- [ ] 2.5 M1/M2/M3/M4/M6:三面壳 `--out`/`--config` 移除、claude 补 `--rules-dir` 行、缓存句
      三面统一、Output/表格单元对齐(D4);跑 1.3 转绿 + `check_distributed_prompt_budget.py`
      过
- [ ] 2.6 M5:`write_runconfig.py` co-write `<run-root>/.gitignore`(D5,幂等);`--check`
      增 warn 级存在性报告;跑 1.6 转绿
- [ ] 2.7 M7/M8:8 个 opencode fanout agent ack 枚举对形(D6,scout 面删 `oversize` 行);
      `init-scout-audit.md` bash 放开 + Input 补 `slice_dir`(D7);跑 1.5 转绿
- [ ] 2.8 M9/L1/L2:claude 补发 `init-scout-merge-rollup.md`(以 opencode 面为源镜像);install.sh
      prune `__pycache__` + 自检增分发完整性断言 + 成功消息核准(D9);跑 1.4 转绿
- [ ] 2.9 L3:`orchestrator-discipline.md` 头注「to come」清单改实况(ut-init 已发布)

## 3. 回归与共用面确认

- [ ] 3.1 定向面:`test_distributed_md_purity` `test_dsh_command_surface` `test_recipe_visibility`
      `test_write_runconfig` `test_zero_deps` `test_no_compile_warnings` 全绿
- [ ] 3.2 lint 三件套:`check_contracts.py`(含 flag 表对账)过、`check_distributed_purity.py`
      过(第 10 类基线:存量 209 − init 切片命中,只减不增)、
      `check_distributed_prompt_budget.py` 过、`check_plain_language.py`(exit 2 = 既有噪音)
- [ ] 3.3 实机冒烟:`./install.sh --opencode <scratch 目标>` 一次——目标树无 `__pycache__`、
      `.mgh-init/.gitignore` 由冒烟 run 落盘、自检消息与文件清单核对;`--dsh`/`--claude` 面
      至少各跑一次自检段
- [ ] 3.4 `git diff --stat` 核对涉改面与本批清单一致(守卫三镜像、dispatcher、枚举器零触碰)

## 4. 收尾

- [ ] 4.1 VERSION bump 0.1.70 → 0.1.71 + CHANGELOG 条目(死链/披露/对账/gitignore/install
      卫生,分组各一句)
- [ ] 4.2 `openspec validate "fix-mgh-init-distribution-links" --strict` 过 + purity 零违例
      (SDD 面不指私有文档区)
- [ ] 4.3 拍板项回执(不阻塞):A(edit: deny live 验证双分支,维护者参与)与 B(第 10 类
      全家族 209 行扫尾:独立小批 vs 并入批次 7)结果回填战役交接文档情报区
- [ ] 4.4 `/opsx:archive`(归档会话执行;specs 增量回写主规格 5 能力:distribution-purity
      3 MODIFIED、dsh-command-surface 1 ADDED、orchestration-substrate 1 MODIFIED、
      control-discovery 1 MODIFIED + 1 ADDED、fanout-dispatch 1 ADDED)
