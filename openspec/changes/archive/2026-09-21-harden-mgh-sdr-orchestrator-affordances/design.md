## Context

真机失败链(四个违规动作与其成因)已在 `proposal.md - Why` 落定;本节只记录决策依赖的现状事实:

- 审批闭环现状:`sdr_context.py::_run` 检出未批仓 → stdout `pending_approval[]`;批准写入住在
  `read_roots_config.py`(原子写 `<target>/.mgh/read-roots.json`,schema `{"v":1,"read_roots":[…]}`)。
- 哨兵现状:宿主壳路径的哨兵是 `sdr_context.py` **跑完之后**的 co-write(失败退出码 2 在写之前);
  launcher 路径在 spawn 宿主 CLI 前自行写哨兵(`mgh_sdr_launch.py::_write_sentinel`)。step 1 之前的
  任何失败 = 宿主壳路径守卫休眠(opencode 不继承跨调用 env 是既有已证边界)。
- 守卫现状:`block_adhoc_scripts.py` 的内联代码判定 `_PYC_RX` 只匹配 `解释器 -c`;heredoc 形态
  (`python3 - <<'EOF'`)与 here-string 均不在拦截面。守卫 recipe 推荐 `describe_artifact.py`
  (`--keys/--count/--sample/--shape/--field`),该出口在 sra/srr 壳各有引用、`/mgh-sdr` 双壳 0 次。
- 纪律正文现状:`core/prompts/fragments/orchestrator-discipline.md` 持有宿主无关三条 `NEVER` 硬边界,
  其中内联代码边界措辞同样只写 `py -c|python -c`;`/mgh-sdr` 双壳当前**内联**了一份(未走
  REQUIRED SUB-SKILL 引用)。
- 契约 lint 现状:`tools/check_contracts.py` 从双壳提取 `*.py --flag` 并逐 flag 跑 `--help` 断言存在;
  另一 in-progress change 正在给同一检查器加「调用域断言 + 阈值标定口径」(本 change 的 recipe 可见性
  断言与之同面不同规则,落 tasks 时须协调文件冲突)。

## Goals / Non-Goals

**Goals:**

- 模型在失败/试错期的每一步都有**在册出口**:想审批 → 有 flag;猜错 flag → 报错给配方;想看字段 →
  有摘要视图与 `describe_artifact`;守卫在 step 1 失败时仍然醒着。
- 拦截面与指令面**同步演进**:hook 新增的每种被拦形态,fragment/壳先有对应措辞;hook recipe 推荐的
  每个脚本,壳内先有确切调用形态(且新增确定性检查兜底该对应关系)。
- 全部新增为**纯附加**:缺省输出逐字不变,既有幂等/契约零破坏。

**Non-Goals:**

- 不改 launcher 的 run 目录新建语义与 `--multi-branch` 行为(仅其打印的审批提示语可选更新为
  `--approve-external` 形态)。
- 不实现 `--dimensions` 下发;不做 `pending[]` 路径前缀瘦身(改字段形态风险大于收益,留待字节实测
  数据);不把 step 0 上膛做成 shell `printf`。
- 不重构 `/mgh-sdr` 壳接入共享 fragment 的既有内联纪律段(只在原地扩写措辞;fragment 与壳的正文
  去重归 substrate 的既有要求,后续 change 处理,本 change 仅保证**两处措辞同扩**)。
- 不引入任何 pip 依赖;不改 `sdr_context` 的检索逻辑与哨兵最小化原则。

## Decisions

**D1 — `--approve-external` 复用 `read_roots_config.py` 的写函数,而非子进程调用或复制实现。**
`sdr_context.py` 与 `read_roots_config.py` 同目录、同自定位导入机制(`sys.path.insert(0, dir-of-__file__)`),
直接 `from read_roots_config import <原子写/校验函数>`。否决项:子进程 `subprocess` 调用(多一层
退出码/编码翻译,错误配方难归因);复制实现(两处 schema 写逻辑必然漂移,违背「写路径单一来源」)。
校验语义(存在 ∧ 是目录,违者退出码 2)与幂等语义随被复用函数天然继承。

**D2 — 模糊 flag 报错在 `main()` 前置,不改 argparse 内部。**
用 `parse_known_args`:未知 `--*` token 命中词根集 `{approve, read, external, root}` → stderr 在
argparse 原生报错文本**之后**追加配方(脚本自身 `Path(__file__).resolve()` 拼绝对路径 + `args.repo`
填 `--target`),随后 `sys.exit(2)`。`--approve-external` 本体在册后不误伤自身;非命中词根的未知 flag
行为逐字不变。否决项:子类化 argparse 改写 `error()`(把配方逻辑埋进框架钩子,`--help` 契约面不变但
可读性差,且双 flag 前缀风格易误触)。

**D3 — `--arm-sentinel` 落在 `resume_sdr_state.py`,step-0-only 语义,与 `--rearm-sentinel` 互斥。**
候选:新脚本 `arm_sdr_guard.py` / `write_runconfig.py` 加 sdr 模式 / 挂进 `resume_sdr_state.py`。
选后者:`resume_sdr_state.py` 已是 sdr 域「运行态磁盘操作」的唯一脚本入口,满足「恢复指引域内可执行」
的既有要求;新脚本会多一个契约面与 install 镜像项。`--arm` 与 `--rearm` 的判据分工:
`--arm` 只认 `--repo`(run 起点,`context.json` 可以不存在),`--rearm` 只认 `context.json`(run 中途);
前者遇同 target 已存在哨兵 → no-op(NEVER 清空 `read_roots[]`),后者全量重写。互斥由 argparse
`add_mutually_exclusive_group` 机器保证。launcher 不加 `--arm`(其 spawn 前写哨兵已覆盖该入口)。

**D4 — `--summary` 是 stdout 投影视图,不是新产物。**
`sdr_context.py --summary`:同一执行流跑完后 stdout 打印投影(关键量 + 摘要级 `external_repos[]`,
剔除 `route_hits[]` 明细),`context.json`/哨兵/run_config 落盘内容与缺省形态逐字一致。
`diff_group.py --summary`:物化照常执行(幂等,已存在 slice/marker 不重复劳动),stdout 以
`summary{pending_total,done,failed,by_type{interface,standalone,partN},excluded_count,empty}` +
`pending[]`(保留绝对路径字段全量,`--offset/--limit` 语义不变)输出。否决项:摘要独立缓存文件
(多一份磁盘真相源);把缺省输出直接改小(破坏既有逐字消费方与回归基线)。
stderr 噪音收敛(真机 25KB)按「最小充分」处理:`sdr_context` 的逐文件检索进度行降为每仓一行汇总,
error/提醒行保留;不做 `--verbose` 分级(无在册消费方)。

**D5 — heredoc/here-string 判定用独立正则,不复用 `_INTRO_TOKENS` 词表。**
新增 `_PY_INLINE_RX ≈ (?:^|[\s;&|(])py(?:thon)?[0-9]*\s+(?:-c\b|- <<<|- <<)`(命令体按 `;`/`&&`/`|`
切段后逐段判定);命中即退出码 2 + 现行 `_recipe(domain)`,与 `-c` 的差异:**不**要求体内含内省 token
(heredoc 体在命令字符串里往往不可见/被截,词表判定不可靠;内联解释器按形态即违纪)。独占 `-` 但无
`<<`(如 `git log -` 误形、管道 stdin 喂给解释器的其它写法)不在本规则面——保持最小拦截面,后续按
真机新形态逐词净网(与 Bash 动词表的既有立场一致)。双端 hook 文件继续字节级 parity(判定在唯一
Python 守卫,`.ts` shim 零改动)。

**D6 — recipe 可见性检查并入 `tools/check_contracts.py`,域→壳映射复用守卫的 `_DOMAINS` 表。**
提取守卫 `_WORKLIST`/`_recipe` 文本中的 `*.py` 脚本名集合,断言 ⊆(该域双端壳 ∪ 共享 fragment)中
出现的脚本名集合。已知假阳性源:`describe_artifact.py` 在 fragment 以抽象词「artifact-inspect 脚本」
出现而非字面名 → 检查按字面名匹配时 fragment 需保留一处字面脚本名,或白名单豁免;倾向前者(字面名
出现一次即可,成本一个词)。与 in-progress 的域断言 change 同文件不同规则,实现顺序上本 change 的
规则以**独立函数**加入,冲突面收敛在注册行。

**D7 — 措辞同扩三处一份真相:fragment ②、sdr 双壳硬边界段、契约文档
`core/contracts/hooks/runtime-enforcement.md`。** 内联代码边界的形态枚举(三种喂入形态)在三处用
同一措辞(壳段可逐字复制 fragment 该句);分发纯净性 lint 不受影响(纯操作性措辞)。

## Risks / Trade-offs

- [step 0 预武装后用户放弃/step 1 反复失败,残哨锁死日常开发] → 壳的干净停止步 MUST 含 `rm
  <repo>/.mgh-sdr/.active`(写进 step 0 配方行而非只写收尾段);下次 launcher 启动的既有残哨检测/清理
  路径兜底硬杀;`resume_sdr_state.py --check` 在 `not-started` 保持 advisory 不 gate(既有语义)。
- [`--approve-external` 名义上把「写配置」能力给了产出脚本,可能被编排器跳过用户同意自批] → 审批
  语义不破靠三层:壳措辞「仅在宿主会话获用户明示同意后传入」;`--check` 对 `pending_approval` 非空的
  WARN 使「跳批」在产物层留痕;报告渲染对 `external_repos` 与批准来源如实披露。不设机器强制
  (用户同意发生在会话层,本就不可见于磁盘)。
- [D2 词根模糊匹配误报(如未来新增合法 `--read-only-something` flag 尚未注册)] → 判定仅对
  `parse_known_args` 的**未知** token 生效;在册 flag 永不进此路径;新增词根命中在册前缀时用
  argparse 原生 suggestion 而非配方(实现时以「在册集合」做排除)。
- [heredoc 拦截误伤目标项目自身的合法 `python3 -` 用法] → 仅在 mgh 运行域激活期生效、且要求解释器
  直接吃 `<<` 喂入;recipe 给出照抄出口;域外零变化(守卫休眠语义不变)。
- [D6 检查把 `_WORKLIST` 里的泛占位(非脚本名词)提成假项] → 提取正则只认 `\w+\.py` 形态;
  `_AGGREGATES`/描述文本不进提取面。
- [`diff_group --summary` 仍携带全量绝对路径 pending,单页超编排预算] → 既有 `--offset/--limit` 分页覆盖摘要
  形态(`effective_limit` 报本页实返条数)。注:`diff_group` 从未有 init `list_*` 家族的 `--orch-budget-bytes`
  按字节自动收页(`shrunk:true`),本 change 不为它新造该 flag(超「摘要视图」范畴且扩契约面);真单页超预算由编排器 `--limit` 分页消费。

## Migration Plan

纯附加发布:脚本新 flag(缺省行为逐字不变)→ hook 双端同步扩规则 → 壳/fragment/契约措辞 →
`tests/` 反例用例(本次真机四动作逐一固化)→ install 自检与契约 lint 接线 → 版本号 bump。
回滚 =  revert 各文件;无磁盘 schema 变更(`read-roots.json`/哨兵/`context.json` 结构均不变),
无跨 run 状态迁移。

## Open Questions

- step 0 预武装后 `sdr_context.py` 是否应容忍「哨兵 `read_roots:[]` 已存在」直接开始(co-write 覆盖)
  ——按现设计是,无需决策,实现时以测覆盖。
- 摘要形态的 `diff_group` 是否需要同时省略 `pending[].slice_path`(最大字段)——留实现时按真机
  stdout 字节实测再定,两种形态都在 `pending[]` 消费配方内,不改规格。
