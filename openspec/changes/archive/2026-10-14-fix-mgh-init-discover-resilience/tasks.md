# fix-mgh-init-discover-resilience — Tasks

> 实施纪律:先红后绿,红测全部 CLI 级(真跑脚本 + 真产物树);本机 `py` 坏用 `python`。
> 实现顺序按组号(design D11:单脚本项 1-3 先,expand_scope 三连 4-6,discover 侧 7-8 最后)。
> `expand_scope` 是 mgh-sast 共用面——组 4-6 每组绿后顺带跑 `test_focus_scope`。

## 1. 单脚本小项(M5/M7 / design D8/D10)

- [x] 1.1 红测:`test_scout_plan` 增——写盘途中模拟(kill 不可测则断言写路径形态:写后盘上
      无 `.tmp` 残留 + helper 存在性源断言);或 CLI 级:正常跑后 plan 完整 + 二次跑幂等覆盖
- [x] 1.2 实现:`plan_scout` 写 `scout_plan.json` 改 `.tmp` + `os.replace`(自写三行 helper,
      零新 import 耦合);跑 1.1 转绿
- [x] 1.3 红测:`test_describe_artifact` 增——`--field <大数组>` 单独使用断言 stdout 含
      `truncated:true` + 容器计数 + 回显 ≤ 上限(现状整份倾倒 → 红);`--field a.b --count`
      组合输出不变(兼容锚)
- [x] 1.4 实现:`--field` 单独使用时有界回显(`VALUE_ECHO_CAP` 常量截断 + 容器
      `{type,count}` + sample ≤4 条);跑 1.3 转绿

## 2. step 0 持久性(M6 / design D9)

- [x] 2.1 红测:`test_write_runconfig` 增两组——①fsync 源形态断言(mock `os.fsync` 记录调用,
      run_config/哨兵/gitignore 三写均先 flush+fsync 再 replace;现状零 fsync 调用 → 红);
      ②错组拒识:`--init-dir <t>/.mgh-init --run-root .mgh-ut-init` → 退出码 2(现状静默写出
      错域哨兵 → 红);默认组合 stdout/落盘逐字节不变(兼容锚)
- [x] 2.2 实现:原子写 helper 补 flush+fsync;main 增 init_dir == target/run_root 显式校验
      (缺省派生恒满足);跑 2.1 转绿
- [x] 2.3 `test_write_runconfig` 全量绿(批次 4 加的 --check/gitignore 面零回归)

## 3. `--check` 形状错收口(M1 / design D4)

- [x] 3.1 红测:`test_init_discover` 增——`controls_candidates.json` 为 `[1,2,3]`(合法 JSON
      顶层 list)运行 `--check` → 断言退出码 2 + violations 含 wrapper issue、NEVER traceback
      (现状 `TypeError: 'NoneType' object is not iterable` 裸崩 → 红,实机复现形态固化);
      clusters 侧同形一组
- [x] 3.2 实现:not-list 分支补 `cands = []` / `clusters = []` 归一;跑 3.1 转绿;
      `--check` 既有用例零回归

## 4. 调用图两遍化(H5 / design D1)

- [x] 4.1 红测:`test_focus_scope`(sast 共用面)或 `test_init_runtime` 增——两 Java 文件
      互相调用,交换文件名双跑,断言两次调用图逐边一致(现状单向边随枚举序漂移 → 红);
      单向大仓样本断言跨文件边数量不回退
- [x] 4.2 实现:`expand_scope.build_call_graph` 改两遍(一次 walk 物化缓存文本 → pass 1 全量
      def 索引 + 框架标记 → pass 2 解析调用);输出 shape 零变化;跑 4.1 转绿 +
      `python tests/test_focus_scope.py` 全绿
- [x] 4.3 `test_init_discover` / `test_discover_resilience` / `test_init_runtime` 既有调用图
      用例零回归

## 5. 配额只数源文件 + 截断上浮(H6 / design D2)

- [x] 5.1 红测:`test_init_discover`(或 `test_focus_scope`,walk_sources 所在面)增两组——
      ①2 万 .txt + 2 .java → 两源文件均被 yield(现状配额被 .txt 吃完 → 红);②真超配额源
      文件仓 → stderr 告警 + accumulator 截断信号 + discover stdout `truncated:true`
      (现状静默 → 红)
- [x] 5.2 实现:`limit_files` 计数移进 `if lang:` 分支 + 触顶 stderr 告警 + `limit_hit`
      accumulator 形参;discover `_collect_files` 接 accumulator;跑 5.1 转绿 + sast 面复跑

## 6. scope 歧义与剪枝(H7/M8 / design D3)

- [x] 6.1 红测:`test_focus_scope` 增——`--path <不存在>` → 退出码 2(现状空集 exit 0 → 红);
      `--package <零匹配>` → 退出码 2;目录存在无源文件 → exit 0 + note(兼容锚);
      repo 置于 `<tmp>/build/<repo>` 与 `<tmp>/.cache/<repo>` 祖先下 → 源文件照常发现
      (现状整仓扫空 → 红)
- [x] 6.2 实现:`--path`/`--package` 存在性 fail-loud;EXCLUDE_DIR 与点前缀剪枝改
      `p.relative_to(repo).parts` 判定;跑 6.1 转绿 + `test_focus_scope` 全量绿
- [x] 6.3 `test_init_discover` 的剪枝/dotfile/test-tree 用例零回归(仓内剪枝语义不变)

## 7. 续点参数指纹与增量日志(M2/M4 / design D5/D7)

- [x] 7.1 红测:`test_discover_resilience` 增三组——①换参 resume(scope A 中途 → scope B
      resume)→ stderr 披露 + 全量按 B 重扫、候选集纯 B(现状混合集合 → 红);②写放大:
      大候选数扫描统计 cache/ 写入字节,journal 总量 O(n)(现状每窗口全量重写 → 红,可断言
      `scan_progress.json` 恒小于阈值 + journal 行数 == 候选数);③journal 损坏/计数不符 →
      弃续点重扫自愈;完成态 resume 幂等 no-op(兼容锚)
- [x] 7.2 实现:`scan_params` 指纹入 progress + resume 比对弃续;`scan_journal.jsonl` 增量
      追加 + progress 瘦身 + 完成清理;跑 7.1 转绿
- [x] 7.3 存量续点(无指纹字段)兼容:视作相符续扫,既有 resume 用例零回归

## 8. 调用图软时限(M3 / design D6)

- [x] 8.1 红测:`test_discover_resilience` 增——小 `--time-budget-ms` 构造 pass 1 完成后
      pass 2 中途超限 → 退出码 0 + `partial:true` + `cache/callgraph_defs.json` 在盘
      (现状 pass 中途被硬杀零留存,红测以「budget 耗尽于 pass 2 时进程仍干净退出且 defs
      落盘」断言;现状无 pass 内检查 → 超预算继续跑满 → 红);重派 `--resume` 复用 defs
      跳过 pass 1
- [x] 8.2 实现:两 pass 循环 progress 边界 deadline 检查 + pass 1 完成原子写 defs 缓存 +
      resume 载入(全量图缓存优先级不变);跑 8.1 转绿;软时限既有用例(scan 边界形态)零回归

## 9. 回归与收尾

- [x] 9.1 定向面全绿:`test_init_discover` / `test_discover_resilience` / `test_init_runtime` /
      `test_write_runconfig` / `test_describe_artifact` / `test_scout_plan` /
      `test_focus_scope`(sast 共用面)+ `test_zero_deps` + `test_no_compile_warnings`
- [x] 9.2 `git diff --stat` 确认涉改面 = 5 脚本 + 测试文件(+ VERSION/CHANGELOG);提示词/
      分发面/守卫/枚举器零触碰(与批次 5 工件零冲突)
- [x] 9.3 VERSION bump + CHANGELOG(按 11 项一句一条;基线版本号以批次 5 归档后的 VERSION
      为准顺延)
- [x] 9.4 `openspec validate "fix-mgh-init-discover-resilience" --strict` 过 + purity 零违例
      + plain_language(exit 2 = 既有噪音)
- [x] 9.5 实机冒烟(建议):小仓跑 `discover_controls.py --check` 与 `expand_scope.py
      --path <真目录>`;祖先排除名目录下放一个 mini 仓跑 discover 确认非空
- [x] 9.6 `/opsx:archive`(归档会话执行;specs 增量回写 control-discovery 10 MODIFIED——
      与批次 5 回写的 5 条按名不冲突,先后归档互不覆盖)
