# fix-mgh-init-discover-resilience — Design

> 范围:发现层 5 个脚本(`expand_scope` / `discover_controls` / `plan_scout` /
> `write_runconfig` / `describe_artifact`),零提示词零分发面。`expand_scope` 被 mgh-sast
> 共用(scope resolver CLI 直调),其改动的回归面 MUST 含 sast 侧 `test_focus_scope`。
> 基态说明:批次 5 归档进行中,本批按工作树现态验证(涉改文件与批次 5 零重叠);
> control-discovery 主规格将由批次 5 归档回写 5 条 requirement,与本批 10 条按名不冲突。

## D1 — 调用图两遍化(H5)

`expand_scope.build_call_graph` 现为单遍:同循环内 `name_to_files[d].add(rel)`(建索引)与
`for tgt in name_to_files.get(name, ())`(解析调用)并发推进——文件 A 的调用只能命中枚举顺序中
先于 A 的定义。修法镜像 `discover_controls` 内部两遍实现的结构:pass 1 全量遍历建**完整** def
索引 + 框架标记;pass 2 再遍历解析调用边。实现形态:单次 `walk_sources` 物化
`(path, lang, text)` 列表(两 pass 共用缓存文本,保持「每文件至多读一次磁盘」的既有承诺——
规格「Bounded single-pass」的「walk 一次」语义按 rglob 遍历次数理解,读盘次数不变),或 walk
两次但 pass 2 复用 pass 1 缓存的文本 dict——取前者(与 discover 形态一致,一次 walk)。
输出 shape(forward/reverse/name_to_files/framework_files)零变化;mgh-sast CLI 消费面无感。
**被否的替代**:把 discover 的实现 import 过来——两函数输入面不同(缓存文本列表 vs repo 路径
walk),强行合并引入参数适配层;两处各自两遍、语义由本批规格钉死,漂移由回归测试锚住
(同名双实现已有先例:fanout/_safe_name 别名化在批次 3 处理过,此处文本不同构不适用别名)。

## D2 — 配额只数源文件 + 截断上浮(H6)

`walk_sources` 的 `limit_files -= 1` 从「每个存活文件」改「仅 `SOURCE_EXT` 命中的源文件」
(移进 `if lang:` 分支后、yield 前后皆可,取 yield 同分支);触顶时:stderr 一行告警(含配额值
与已 yield 源文件数)+ 可选 `limit_hit: list | None = None` accumulator 形参置位(镜像
`dot_skipped`/`tests_skipped` 家族——generator 无法 return 值,家族既有通道就是 accumulator)。
discover 侧 `_collect_files` 传 accumulator,其 `max_files+1` 哨兵语义随之真正生效(多 yield
一个源文件 → `scanned > max_files` → truncated)。**兼容性**:混合仓下修复后会扫描到更多源文件
(此前配额被资产吃掉)——这是缺陷修复本身;纯源文件仓行为逐字节不变。

## D3 — scope 歧义输入 fail-loud(H7)

`--path`:`d.is_dir()` 为假 → 退出码 2 + stderr recipe(指认路径 + 提示检查 typo);
目录存在但 `collect_dir` 为空 → 保持 exit 0 + note(合法空集,与规格场景一致)。
`--package`:`package_to_dirs` 零匹配 → 退出码 2 + recipe。判据二分:**路径/包不存在 = 输入
歧义**(fail-loud);**存在但无源 = 真空集**(如实空)。`--seed-file` 路径与 `--file` glob 形
不在本缺陷面(seed-file 的 JSON 解析失败已有处理),不动。

## D4 — `--check` 形状错收口(M1)

崩点:`cands = cd.get("candidates") if isinstance(cd, dict) else None` 后 not-list 分支只
append violation 未归一,随后 `enumerate(cands)` 对 None 裸崩(实机复现 TypeError)。
修法:两处(wrapper/candidates 与 clusters)在 not-list 分支补 `cands = []` /
`clusters = []` 归一(violation 照报,逐条循环安全走过);str 子项既有「not an object」
violation 路径不变。退出码路径 `0 if ok else 2` 已对,零改动。

## D5 — 续点参数指纹(M2)

`scan_progress.json` 增 `scan_params` 字段:`{"scope": "<规范化种子描述或 null>",
"language": "<lang 或 null>"}`(指纹取生效语义:scope 模式 + 规范化路径/包串,language 原值)。
resume 时:当前参数规范化后与指纹比对——不符 → 弃 `scan_progress.json` + `scan_journal.jsonl`
从头扫 + stderr 一行披露(「checkpoint params mismatch: discarding stale scan progress」);
相符/缺指纹(存量续点)→ 续扫(存量兼容:无指纹字段视作相符,避免旧 run 无谓重扫)。
**被否的替代**:把指纹并进 manifest 新鲜度判定——manifest 管文件集新鲜度,参数是另一维
(文件未变但参数变了照样要重扫),混进一个键会让「源文件变了」的失效语义含混。

## D6 — 调用图软时限 + pass 1 缓存(M3)

两 pass 循环体内按 `--progress-every` 节奏检查 deadline(pass 1 完成 → 原子写
`cache/callgraph_defs.json`:`{name_to_files, framework_files, manifest}`);pass 2 超限 →
干净 partial(exit 0 + `partial:true` + resume_hint)。resume 时 defs 缓存存在且 manifest
新鲜(既有 mtime/size 判定)→ 载入跳过 pass 1。完成态的 `callgraph.json` 全量缓存逻辑不变
(defs 是中途产物,完成后仍写全量图缓存;resume 优先用全量图缓存,defs 只在中途断点场景生效)。
顺序:deadline 检查点在 progress 边界(与 scan 一致的安全边界节奏),NEVER 逐文件检查
(计时代价集中在边界,与家族形态一致)。

## D7 — 续点增量日志(M4)

`scan_journal.jsonl`:每检查点窗口把**新增**候选逐行 append(JSONL,每行一条;窗口内先
缓冲,边界处一次性 append + flush);`scan_progress.json` 瘦身为
`{scanned_index, candidate_count, cid, scan_params, manifest_digest}`(恒小体积,原子写)。
resume:读 journal 重放累积候选(与 `candidate_count` 校验,不一致 → 视续点损坏,弃之重扫
——防御外部篡改/手工编辑,镜像 write_runconfig 缺失即 fail-loud 的家族姿态但此处可自愈:
重扫即重建)。完成时:删除 journal(保留 progress 完成态,幂等 resume no-op 语义不变)。
写放大从每窗口 O(累积) 降 O(窗口增量),总 O(n)。JSONL 选型:append 天然 O(增量)、
逐行解析零依赖;**被否**:二进制分块/长度前缀帧——std 库下无收益徒增解析面。

## D8 — plan_scout 原子写(M5)

单点改 `.tmp` + `os.replace`(仓内 `_atomic_write_json` 家族形态照搬,plan_scout 自己写一个
三行 helper 或 import——`plan_scout` 无兄弟 import 依赖,自写 helper 三行,避免为零依赖纪律
引入新耦合)。批次 5 刚给该文件加了预算记录/`--check` 退出码面,零冲突。

## D9 — step 0 持久性(M6)

- **fsync**:`write_runconfig` 的 `_atomic_write` 改 `with open(tmp, "w", encoding="utf-8")` →
  write → `f.flush()` + `os.fsync(f.fileno())` → close → `os.replace`。三处 co-write
  (run_config/哨兵/gitignore)同治(gitignore 是单行小文件,同 helper 顺治,零额外分支)。
  discover 的同形 helper 理论同病,但 review 只点名恢复锚点(run_config)——**不顺手扩面**,
  留观察(规格条款只钉 write_runconfig)。
- **哨兵单一来源(apply 期收窄)**:实现在既有测试 `test_init_dir_overrides_run_root` 上发现
  碰撞——「custom 位置 `--init-dir` 覆盖 `--run-root`」是文档钉死的合法旗标语义,全域
  `init_dir == target/run_root` 校验会破坏它。收窄为:**仅当 init_dir 的基名是规范运行目录名**
  (`.mgh-init`/`.mgh-ut-init`)且与 `--run-root` 派生的域冲突时 exit 2 + recipe(规范名目录里写
  错域 = 评审点名的危险形态,规格场景原样通过);custom 名目录保留既有覆盖语义(既有测试零
  破坏)。domain 派生与哨兵位置逻辑不变。

## D10 — `--field` 有界(M7)

单独使用(无其它模式)时:导航成功后构造有界回显——标量:字符串截断到实现常量(4096 字节,
`VALUE_ECHO_CAP`)+ `truncated`;容器:`{type, count}` + 首元素 sample(≤4 条/键,每条同
截断)。组合形态(`--field a.b --count` 等)输出不变。选 4096:对齐 describe 家族「瞄结构」
用途,大于单字段合理值、远小于任何聚合倾倒。

## D11 — 测试策略与批次边界

- 先红后绿,红测全部 CLI 级真跑脚本(M1 已有实机复现形态可直接固化);H5 红测用「交换文件名
  双跑比对」实验形态(评审同款);M3 红测用小 `--time-budget-ms` 构造 pass 中途超限;
  M6 fsync 红测断言源形态(mock `os.fsync` 调用序列)而非模拟掉电;M8 红测用 tmp 目录拼
  `build/` 祖先(Windows 真目录,零 mock)。
- `expand_scope` 改动 → sast 共用面 `test_focus_scope` 必跑;discover 改动 → 五件套定向面。
- **批次边界**:批次 5 归档回写 control-discovery 5 条 requirement 与本批 10 条按名不冲突
  (归档按 requirement 名合并);批次 7(提示词/契约批量 + H11)不涉;`test_fanout_runner`
  存量失败(TestRateLimitStorm)与本批无关,不追查。
- 实现顺序建议:单脚本项(plan_scout/describe_artifact/write_runconfig = M5/M7/M6)先,
  `--check`(M4 一行归一)次之,`expand_scope` 三连(H5/H6/H7/M8)再次,discover 侧
  (M2/M3/M4 哨兵消费)最后——expand_scope 与 discover 的耦合点只在 limit accumulator 消费。
