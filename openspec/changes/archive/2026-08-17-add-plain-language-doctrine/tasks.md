## 1. R3 修订(受众声明制 + 人话序 convention + 人工闸门)

- [x] 1.1 在 `AGENTS.md` R3「文档输出规范」段加「受众声明制」子段:每份产物声明受众 ∈ {人类/agent/双受众};人类面走人话规范(现象→原因→改法、术语首现给解释、允许冗余);R5.5 措辞纪律只辖 agent 操作面;`proposal.md` 是唯一双受众文件
- [x] 1.2 附**受众分类表**:人类面(`docs/man/**`、`docs/glossary.md`、proposal 人话序、终端报告)/ agent 面(命令壳纪律段、stage 提示词、`core/contracts/**`、JSON schema、NEVER 链、flag 表)/ 双受众(`proposal.md`)
- [x] 1.3 写入 proposal 人话序 marker 约定:`> **人话序**` 起始的 blockquote(四要素:现象→根因→改什么→怎么验证,~200–300 字)+ **人工闸门**(维护者只读人话序 + tasks.md 能复述本 change,做不到 = 未就绪)
- [x] 1.4 校对:R3 措辞保持 AGENTS.md 简练风格(RFC-2119 动词),不新增 R 编号,不把「人话规范」误写成给 agent 的禁令

## 2. glossary 种子

- [x] 2.1 新建 `docs/glossary.md`:`术语 | 大白话释义` 两列表,提取 AGENTS.md 高频术语 + `docs/r5-plain-language.md`「术语表」,种子 ~30–50 条
- [x] 2.2 英文术语(`fan-out`/`recipe`/`mid-session`)保留英文、给中文释义;「人类面用词前词典必有、缺则先补」规则已随 R3 写入

## 3. man 文档 ×5

- [x] 3.1 新建 `docs/man/mgh-sast.md`(四段:做什么 / 会动哪些文件 / 产出什么 / 风险边界;人话,零研发态悬空引用)
- [x] 3.2 新建 `docs/man/mgh-init.md`(同上)
- [x] 3.3 新建 `docs/man/mgh-sra.md`(同上)
- [x] 3.4 新建 `docs/man/mgh-srr.md`(同上)
- [x] 3.5 新建 `docs/man/mgh-ut-init.md`(同上)

## 4. CI 代理 lint `tools/check_plain_language.py`

- [x] 4.1 新建 `tools/check_plain_language.py`(stdlib,承 R2/R5.3 契约:`--help` 即契约、stdout=JSON、stderr=诊断、退出码 `0/1/2`、任意 cwd、utf-8、零第三方 import)。三项:① proposal 人话序存在性(扫 `openspec/changes/*/proposal.md` 断言 `> **人话序**` marker,缺失 fail-loud exit 2);② 术语黑名单(完整词边界匹配,无编号压缩词表,命中 WARN exit 0);③ 英文原子密度超阈值 WARN(跳过 fenced code / inline code / `> ` 引用行 / 纯路径行)
- [x] 4.2 黑名单表初版:`物化`/`拒识`/`接线`/`治类`/`锚`/`哨兵`/`运行域`/`运行域` 等无编号压缩词(完整词边界;「承 R5.x/兑现 R5.x」dev-meta 不重复,已由 purity lint 覆盖)
- [x] 4.3 新建 `tests/test_plain_language.py`:缺失 marker → exit 2;黑名单命中 → warn exit 0;密度超阈值 → warn;仅扫人类面文件(agent 面 stage 提示词/契约 md 不误报)
- [x] 4.4 接线 CI(与 `check_contracts.py` / `check_distributed_purity.py` 并列)

## 5. 分发 + purity 不变量 + 壳指针

- [x] 5.1 `install.sh` 加 man 分发段:`cp -r docs/man/ → <target>/docs/man/`(幂等 `mkdir -p` + `cp`,平台中立,与 `docs/security-controls/` 同层)
- [x] 5.2 `tools/check_distributed_purity.py::SCAN_DIRS` 加 `ROOT / "docs" / "man"`(维持 shipped = install.sh globs = SCAN_DIRS 三同源);docstring 同步
- [x] 5.3 5 命令壳 ×2 平台 = 10 文件各加一行人类读者指针 `> 人类读者:通俗说明见 docs/man/<cmd>.md`(~20 tok);版本号 bump 涉及清单核对
- [x] 5.4 `tests/test_distributed_md_purity.py` 覆盖新增 `docs/man/` 扫描(断言 5 份 man 文档通过 purity)

## 6. 回归与收尾

- [x] 6.1 全量 lint:`py tools/check_contracts.py`(R5.1)+ `py tools/check_distributed_purity.py`(R5.10)+ `py tools/check_plain_language.py`(新)+ `py tools/measure_prompts.py`(R5.6:壳指针不破 5K 预算)
- [x] 6.2 install 自检演练:`./install.sh --claude <tmp-target>` 验证 `docs/man/` 落地 + purity 自检通过 + 壳指针就位;`--opencode` 同验
- [x] 6.3 `openspec validate add-plain-language-doctrine --strict` 通过
