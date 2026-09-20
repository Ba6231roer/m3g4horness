## 1. 测量下沉：判据与产物同源

- [x] 1.1 在 `core/scripts/diff_group.py` 新增模块内测量函数（渲染某单元 → 取 utf-8 编码字节数），实现体直接调用 `_render_slice`；注释写明"与物化同源，NEVER 另写估算"
- [x] 1.2 把打包期成员大小判据从估算改为实测：`_cluster_standalone._size`、`_cluster_standalone_sel._size`、`_con_bytes`、`_split_interface_budget` 内成分打包与"成分内按文件再切"两处；保持路由序排序与"不切文件中部"规则逐字不变；避免同一候选在一次比较中被重复渲染
- [x] 1.3 让 `pending[]` 每项的 `unit_bytes` 取自测量函数结果（而非落盘后的 `stat().st_size`），使判据与产物在代码上就是同一个数

## 2. 超预算三级处置

- [x] 2.1 一级（无损重切）：确认并固化"多文件单元实测超预算即由既有贪心规则拆为续单元"的行为——续单元沿用 `-partN` 命名、`chain[]` 随每份携带；断言不丢 hunk、不截内容
- [x] 2.2 二级（上下文瘦身）：新增确定性截断，只作用于 `ann_ctx` 与 `sym_ctx`（字符串与列表两种形态），上限为模块常量；截断在切片内写可见标记（形如 `… (截断:K 行 / 原 N 字节)`）；`fd.hunks` 正文、"Files in this unit" 清单、hunk 定位头、头部字段一律不碰
- [x] 2.3 三级（fail-loud 零派发）：把物化循环改为"先全量在内存渲染判定、再落盘"；收集瘦身后仍超预算的单元，`sys.exit(2)` 并打印 `unit_id`、适用上限、实测字节数、最大贡献文件与可操作 recipe（提高上限 / 收窄 diff 区间 / 单独复核该文件）；该路径**不得**写出任何切片或 `grouping.json`
- [x] 2.4 删除源码中 "one oversize file may still exceed it (merged-capped, never split mid-file, same case as standalone)" 一类的容忍性描述，替换为三级处置的准确说明

## 3. 披露与边界校验

- [x] 3.1 `grouping.json` 顶层新增本次生效的两个预算值，`pending[]` 每项新增 `slimmed`（`{字段名: 原始字节数}`，未截断为 `{}`）
- [x] 3.2 `diff_group.py --check` 在字段存在时断言"每项 `unit_bytes` ≤ 其适用上限"与 `slimmed` 结构合法；字段缺失（旧产物）跳过断言并保持退出码 0（与既有 `excluded`/`codegraph_stats`/`chain[]` 的向后兼容同例）
- [x] 3.3 `core/scripts/render_sdr_report.py` 的 `_boundaries(...)` 增加条件性边界项：仅本次确实发生瘦身时披露被瘦身单元及"上下文经截断、输入完整度低于常规单元"；确认不触碰该函数既有条目数下限断言
- [x] 3.4 双壳 `releases/claude-code/commands/mgh-sdr.md` 与 `releases/opencode/command/mgh-sdr.md`：更新 `--max-interface-bytes` / `--max-standalone-bytes` 的帮助文案（超预算三级处置与退出码 2），两壳措辞一致

## 4. 回归测试（`tests/test_diff_group.py` 为主，真建 git 仓、属慢测清单，定向跑）

- [x] 4.1 多文件单元实测超预算 → 切成多份续单元，每份实测 ≤ 上限，且 hunk 并集与切分前等价（无损）；同时把 `test_interface_budget_splits_parts` 里 `unit_bytes > cap + 1024` 的容差收紧为 `> cap`
- [x] 4.2 单文件原子残渣：瘦身可救的分支 → 切片含可见截断标记、diff 正文与定位头完整、`slimmed` 有记录、退出码 0
- [x] 4.3 单文件原子残渣：瘦身不可救的分支 → 退出码 2、零切片文件、零 `grouping.json`、stderr 含单元标识与字节数
- [x] 4.4 预算内路径逐字节不变：以改动前的切片文本与 `pending[]` 既有字段为基线对照（新增的预算记录与空 `slimmed` 是仅有增量）
- [x] 4.5 断言 `pending[].unit_bytes` 恰等于其落地切片文件字节数（测量与物化同源的可证伪线）
- [x] 4.6 `--check`：新产物断言生效（人为造超上限/坏 `slimmed` → 退出码 2）；旧产物（无新字段）→ 退出码 0
- [x] 4.7 `tests/test_fanout_runner.py`：`--tier sdr` 下枚举脚本退出码 2 时原样透传、零子代理被派出（沿用既有 harness 的 `--cooldown-s 0` 缺省，避免吃到真实等待）

## 5. 文档与发布

- [x] 5.1 维护者私有文档区里 `/mgh-sdr` 的命令人话说明补"切片超预算如何处理"一节：三级处置的取舍、退出码 2 时的三个出口、瘦身单元为何在报告里被单独披露
- [x] 5.2 `CHANGELOG.md` 记录本 change，`VERSION` bump
- [x] 5.3 定向回归：`py tests/test_diff_group.py`、`py tests/test_fanout_runner.py`、`py tests/test_render_sdr_report.py`，加 `py tests/test_zero_deps.py` 与 `py tools/check_contracts.py`（确认无新增 flag 后契约面不变）
