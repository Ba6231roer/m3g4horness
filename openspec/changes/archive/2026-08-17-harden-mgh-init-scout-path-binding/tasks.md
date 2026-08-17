## 1. 守卫:哨兵锚点最优 + 向上发现(激活层,design D1)

- [x] 1.1 `releases/claude-code/hooks/block_adhoc_scripts.py` `_resolve_domain` 改为「最优锚点起有界
       向上 walk」:锚 = hook stdin payload `cwd` 字段(claude)?? 守卫进程 cwd(opencode 兜底);
       ≤16 级/盘根,每级查 5 域 `<dir>/<run-root>/.active`;域名优先序不变;docstring 同步 + 版本 bump
- [x] 1.2 `tests/test_block_adhoc_scripts.py` 新增用例组:锚=target 子目录(向上命中→激活→越树 Read
       拦 exit 2)、payload `cwd` 优先于进程 cwd、锚=temp/树外(不命中→休眠 exit 0)、锚=target 子目录
       时树内 Read 放行、16 级上限不越界、多域哨兵按 `_DOMAINS` 序取第一命中
- [x] 1.3 `..` 链/幻觉前缀用例:激活态(哨兵携 target)`Read D:\…\aa\bb\cc\..\..\..\..\xxxx`(折叠后
       落盘根)→ exit 2 + read-side recipe;`Read D:\acme\wing\…`(target=`D:\acme_wing\…`)→
       exit 2(同 out-of-tree 判定,无目录名语义)
- [x] 1.4 把改后 claude 侧 `.py` 逐字节复制到 `releases/opencode/hooks/block_adhoc_scripts.py`;
       跑 `tests/test_opencode_hook_parity.py`(byte parity + shim glue-only 断言,shim 逻辑不动)

## 2. install 面 + 接线不变量(咨询层,design D2)

- [x] 2.1 `tools/install_hook.py` `_DEFAULT_MATCHER` 扩为
       `Bash|Write|Edit|MultiEdit|NotebookEdit|Read|Glob|Grep`;`present` 分支加「matcher 子集则演进」
       (按 `|` split 集合比较;子集→原地更新 matcher,非子集→不动 + stderr 提示;`--matcher`
       显式传值时跳过演进)
- [x] 2.2 matcher 单测(扩 `tests/test_install_hook.py`):fresh install 得全工具面;旧
       `Bash|Write|Edit` 条目重跑后演进;用户自定义非子集 matcher 不动;二次重跑幂等;用户自定义
       command 字段保留
- [x] 2.3 **接线覆盖回归测**(双宿主一个不变量):从守卫源码静态提取 `main()` 分派工具名集合,断言
       ①每个 ∈ `_DEFAULT_MATCHER` split、②每个有 opencode shim `HANDLED`/`normalize` 映射;新增守卫
       分支忘扩接线面 → CI fail(可挂 `tests/test_opencode_hook_parity.py` 或新文件)
- [x] 2.4 `install.sh` 自检面核对(hook 注入路径不变,吃新默认值;若自检有 matcher 断言则同步)

## 3. 来源层:producer `repo` 锚 + reader 拒识 recipe(design D3)

- [x] 3.1 `core/scripts/list_scout_batches.py` `_write_batch_input` 核对/补写 input.json 顶层 `repo`
       (绝对,wrapper `repo` 透传);`--check`/契约 docstring 同步;单测补 input.json 顶层 `repo` 断言
- [x] 3.2 `list_clusters.py` / `list_test_groups.py`(T1/ut-init 同形 producer)同步统一「fan-out
       input 必携顶层绝对 `repo` 锚」契约;各自单测补断言
- [x] 3.3 `core/prompts/stages/init-scout.md` 加两段:①锚定段(工作锚 = 输入绝对 repo 根;自建路径
       SHALL 以锚为前缀或相对锚;NEVER 凭记忆手拼盘符绝对路径——已观察失败形态:下划线目录名被概率
       重生成分隔符、NEVER `..` 链);②毒输入拒识段(输入路径字段解析后不在锚树内 → 回
       `failed <suspected path drift>` ack,不 Read 不 Write)
- [x] 3.4 同形 reader stage 顺带核查(`init-scout-audit.md` 等与扇出路径字段直接交互者)同款锚定 +
       拒识段补齐(最小集)
- [x] 3.5 `core/prompts/fragments/init-stage/scout.md` 派发段(3b spawn 行)加「逐字节复制」recipe:
       `checkpoint_path`/`input_path`/`done_marker`/`slice_dir` 逐字节从 stdout `pending[]` 复制,
       NEVER 手拼/NEVER 记忆路径/NEVER「简化」前缀
- [x] 3.6 提示词预算 lint:改后 stage prompt / fragment 过 `tools/measure_prompts.py` +
       `tools/check_distributed_prompt_budget.py`(R5.6 上限不破)

## 4. 契约与文档同步(design D4)

- [x] 4.1 `core/contracts/hooks/runtime-enforcement.md`:激活段改「锚点最优 + 向上 walk(有界)」;
       **opencode 残余边界运行要求**(「在 target 根或其子目录启动 opencode」)显式写入;读侧表补
       `..` 链折叠/幻觉前缀场景行;新增接线覆盖小节(matcher/HANDLED ⊇ 守卫分支集,CI 强制)
- [x] 4.2 AGENTS.md R5.7 段 B「当前兑现」句扩:matcher 全工具面(claude install 面)+ 哨兵锚点最优
       向上发现 + 接线覆盖 CI 不变量;版本号 bump 涉及清单核对(守卫/install_hook/提示词/脚本)
- [x] 4.3 `openspec validate harden-mgh-init-scout-path-binding --strict` 通过

## 5. 回归与收尾

- [x] 5.1 全量回归:`py tests/test_block_adhoc_scripts.py` + `py tests/test_opencode_hook_parity.py`
       (含新接线覆盖测)+ `py tests/test_install_hook.py` + `py tools/check_contracts.py`(R5.1)+
       分发纯净性 lint(R5.10,提示词改动涉及)
- [x] 5.2 install 自检演练:`./install.sh --claude <tmp-target>` 验证 fresh matcher;模拟旧 matcher
       settings.json 重跑验证演进;`--no-enforce-hook` 路径不受影响
- [ ] 5.3 真机冒烟(双宿主,若目标项目可用):claude——subagent 锚=子目录场景越树 Read 被 recipe 拦
       (不再弹权限询问);opencode——从 target 根启动,验证插件进程哨兵发现 + 越树 Read 被
       `tool.execute.before` throw 拦(先于宿主权限询问);正常批次全绿
