## 1. 守卫 docstring 修复(stderr 纯净)

- [x] 1.1 `core/scripts/list_clusters.py` 模块 docstring 改 raw string(`r"""`),消除 :69 `` `\` `` 非法转义;正文内容零变更
- [x] 1.2 新增 `tests/test_no_compile_warnings.py`:全量 `py_compile.compile` `core/scripts/*.py`(`warnings.simplefilter("always")`),捕获任何 Warning → fail-loud 列出脚本名与消息;运行确认全绿

## 2. 守卫三规则(claude + opencode 双写 byte-identical)

- [x] 2.1 `block_adhoc_scripts.py`(先 `releases/claude-code/hooks/`)新增列目录动词集 `_LISTING_VERBS = ("ls","dir","get-childitem","gci")` + `_LISTING_VERB_RX`(首 token / `;|&` 分隔符后锚定),scope 判定镜像 `_out_of_tree_file_search`(显式绝对路径 token 任一树外 → hit;无显式路径 → cwd 判;target None → degrade)
- [x] 2.2 新增解释器执行规则:`_INTERPRETERS`(`py/py3/python/python3/python2`)首 token(排除 `-c`/`-m`)→ 第一个非 flag 值位置的脚本扩展名 token 树外 → hit;`--flag <path>` 对跳过(前置 token 以 `--` 开头则下一 token 为其值)
- [x] 2.3 新增 mgh-core 缺失安装规则:`mgh-core/scripts` 路径段 ∧ 脚本扩展名 token,解析路径不存在或树外 → exit 2 + stop-all recipe(停止全部任务/要求用户当前项目 install/NEVER 跨目录搜索);规则次序置于其他 Bash 规则之前(terminal 状态短路)
- [x] 2.4 同步整份文件到 `releases/opencode/hooks/block_adhoc_scripts.py`(byte-identical)
- [x] 2.5 `tests/test_block_adhoc_scripts.py` 增三规则 hit/pass 双面用例:`ls /home` 拦 / `ls src` 放 / bare `ls` cwd 树内放;`py /home/x/run.py` 拦 / `py .claude/mgh-core/scripts/resume_state.py --target .` 放 / `--flag <in-tree>` 值不判 / `py -c` 不进本规则;mgh-core 缺失引用拦(stop-all recipe 文案断言)/ 已装引用放 / 非 mgh-core 缺失路径不拦;既有各规则 hit 不受新规则短路影响(次序回归)
- [x] 2.6 `py tests/test_opencode_hook_parity.py` 全绿(byte-identical 兜底)

## 3. 任务模板 + stage 提示词硬钉

- [x] 3.1 `core/prompts/fragments/fanout/t1-task.md` 行为加载段追加:提示词路径是唯一位置;Read 失败 → 立即 `failed mgh-core prompts not installed at <path>` ack,NEVER 跨目录搜索提示词/脚本
- [x] 3.2 `t3-task.md` / `scout-task.md` 同位同句(t2-task.md 若含 stage 加载指令则同补,否则跳过)
- [x] 3.3 `core/prompts/stages/init-induct.md` 路径锚定纪律段追加:锚内预期路径(提示词/脚本)不存在 → 毒输入同款处理(failed ack,不漫游);核对 `init-scout.md`/t3 stage 提示词有同形锚定段则同补
- [x] 3.4 `py tools/check_distributed_purity.py` + `py tools/check_contracts.py` 全绿(无 dev-meta 引入、无新 flag 契约缺口)

## 4. 收尾验证

- [x] 4.1 全量回归:`py tests/test_block_adhoc_scripts.py` / `test_opencode_hook_parity.py` / `test_no_compile_warnings.py` / `test_list_clusters.py` / `test_resume_state.py` 全绿
- [x] 4.2 `py tools/measure_prompts.py` 确认模板增量后 fragment 预算无回归(R5.6 防漂移)
- [x] 4.3 CHANGELOG.md + VERSION bump(任何 .md/脚本改动 bump 版本号,承 R5.8)
