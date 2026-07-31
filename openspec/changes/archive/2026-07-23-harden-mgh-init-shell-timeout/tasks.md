# Tasks — harden-mgh-init-shell-timeout

> 依赖顺序:discover 韧性核心(L1/FD2,最低风险、全 additive)→ 契约 → 命令壳 recipe(FD1/FD6)
> → 文档 → AGENTS.md 措辞 → 契约 lint + 回归单测 → 端到端。每条可独立验收。遵守 AGENTS.md R1–R5
> (零依赖、文档简练、复用导入、R5.1 CLI lint、R5.8 回归 + bump 版本号)。改 `discover_controls.py`
> 后 MUST 经 `tools/check_contracts.py` 断言双壳镜像的所有 flag 仍存在 + 新 flag 双壳一致。

## 1. discover 韧性核心(改 `core/scripts/discover_controls.py`;FD2/FD3/FD5,全 additive)

- [x] 1.1 **稳定排序物化文件清单**(FD-OQ1):`collect_sources` 返回前对 `files` 按 `rel`(repo 相对
      posix 路径)字典序稳定排序,使 `scanned_index` 跨运行可复现。零行为漂移(候选集与排序无关)。
- [x] 1.2 **原子写工具**:`_atomic_write_json(path, obj)` = 写 `<path>.tmp` + `os.replace`;所有产物
      JSON(`controls_candidates.json`/`clusters.json`/`skeleton.json`/`cache/*`)改经之(FD5)。仅 py stdlib。
- [x] 1.3 **callgraph 缓存**(FD2/FD3):`build_call_graph` 后原子写 `<out>/cache/callgraph.json`
      (`forward`/`reverse`/`framework_files`)+ `<out>/cache/manifest.json`(每源
      `(rel,mtime,size)`)。`run_discover` 入口:缓存存在且 manifest 与当前源 mtime/size 全匹配且未传
      `--rebuild-cache` → 加载缓存跳过两遍重建;否则重建并刷新缓存。stdout 摘要增 `cache_hit`(bool)。
- [x] 1.4 **真实化 `--rebuild-cache`**(关闭悬空契约):argparse 增 `--rebuild-cache`(store_true,
      help 进 `--help`);置位则强制重建+刷新缓存。默认无缓存=重建(向后兼容)。
- [x] 1.5 **scan 续点**(FD2):scan 阶段每 `--progress-every` 文件原子写
      `<out>/cache/scan_progress.json`(`scanned_index` + 累积候选 list)。`--resume` argparse flag:
      置位 + callgraph 缓存命中 → 跳过前 `scanned_index` 文件、从续点续扫、追加候选(确定性合并,
      单测断言幂等)。scan 完整完成后写最终候选并清理续点(或保留,不破坏产物)。
- [x] 1.6 **软时限 `--time-budget-ms`**(FD4):argparse 增 `--time-budget-ms`(int,默认 0=关);
      用 `time.monotonic()` 在安全边界(callgraph 建成后、scan 每 `--progress-every`)判超预算 →
      落缓存+续点 + stdout `partial:true` + `resume_hint` + 退出码 0。未置位/未超 → 一次性跑完、
      `partial:false`。stdout 摘要增 `partial`(bool)/`resume_hint`(str)。
- [x] 1.7 **`--check` 不触韧性逻辑**:`--check` 路径行为/退出码不变(只读校验既有产物);确认 atomic
      写使被强杀的 out-dir 不留截断 JSON(`--check` 不会误判破损)。
- [x] 1.8 模块 docstring + `--help` 同步新 flag(`--time-budget-ms`/`--rebuild-cache`/`--resume` 的
      discover 语义)与 stdout 新字段(`partial`/`resume_hint`/`cache_hit`)(`--help` 即契约)。

## 2. 契约同步(`core/contracts/init/`;L1 产出者 stdout/cache 契约)

- [x] 2.1 新增(或并入既有)`core/contracts/init/discover-cache.md`:`<out>/cache/` 布局
      (`callgraph.json`/`scan_progress.json`/`manifest.json`)+ 缓存新鲜度规则(mtime/size manifest
      比对)+ `--rebuild-cache` 语义 + stdout `cache_hit`。
- [x] 2.2 discover stdout 契约文档(既有 candidates/clusters 摘要说明处)补 `partial`/`resume_hint`
      字段 + `--time-budget-ms` 早退语义(退出码 0、编排器 Bash 重派 `--resume`)。

## 3. 命令壳 recipe + opencode 超时披露(L2/FD1/FD6;横切,4 壳 × 双端 = 8 份)

- [x] 3.1 两份 `mgh-init.md`(claude + opencode):编排纪律段/调用示例区增 recipe——长跑确定性 Bash
      (`discover_controls.py`/`plan_scout.py`/`merge_scout.py`)SHALL 传 per-call `timeout`;对带
      `--time-budget-ms` 的 discover,`timeout` 略大于 budget;见 stdout `partial:true` 即 **Bash 重派**
      `--resume`(**NEVER** 写 wrapper `.py`),带 sane 重派上界(OQ3)超限则建议 `--scope`+`--merge`。
- [x] 3.2 两份 `mgh-init.md`:边界/披露段 + 「Always disclose」补 opencode 超时配置项
      `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS`(默认 120000;**须 opencode 启动前就绪**,
      mid-session `export` 不生效)与 per-call `timeout` 为会话内即时替代。
- [x] 3.3 两份 `mgh-sast.md`:长跑确定性 Bash(prefilter/dedup/emit_sarif)SHALL 传 per-call `timeout` +
      opencode 超时配置披露(同 3.2 文案)。
- [x] 3.4 两份 `mgh-sra.md`:长跑确定性 Bash(prepare_augment/merge_augment/merge_memory)同 3.3。
- [x] 3.5 两份 `mgh-srr.md`:长跑确定性 Bash(ingest_requirements/render_report)同 3.3。
- [x] 3.6 **分发纯净性**(R5.10):4 壳新增的 recipe/披露为操作性内容(per-call timeout / env 变量 /
      `partial`/`--resume`),不含 dev-only provenance(R5.x/FDn/变更夹名);`tools/check_distributed_purity.py`
      通过。

## 4. 文档(README;cross-command opencode 超时段)

- [x] 4.1 README 增 opencode 超时段:`OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS`(默认 120000、
      pre-launch 设置、mid-session 不生效)与 per-call `timeout` 的关系;claude Bash `timeout` 上限
      (600000ms)。简练、面向 AI/使用者(R3)。

## 5. AGENTS.md 措辞 sharpen(R5.3 / R5.4)

- [x] 5.1 R5.4「大仓可观测 + 无静默截断」补:长跑确定性 Bash SHALL 传 per-call `timeout`;discover
      软时限早退由编排器 **Bash 重派 `--resume`** 推进(NEVER wrapper `.py`);理由〔跨宿主 + 零全损 +
      不依赖单次调用跑完〕随规保留。
- [x] 5.2 R5.3(b) 顺带补一句:确定性长跑脚本的可恢复性(callgraph 缓存 + 续点 + 软时限)属稳定性契约
      一部分,承既有 `--check`/退出码 0/1/2。

## 6. 契约 lint + 回归单测(R5.1 / R5.8)

- [x] 6.1 `tools/check_contracts.py`:断言 `discover_controls.py --help` 含 `--time-budget-ms`/
      `--rebuild-cache`;双壳 `mgh-init.md` 镜像这些 flag 的调用一致(若有 fenced 调用引用)。
- [x] 6.2 `tests/test_init_discover.py`(或新增 `test_discover_resilience.py`):断言
      (a) 二次运行 cache_hit=true 且候选集等价;(b) 改一源 mtime → 缓存失效重建;
      (c) `--rebuild-cache` 强制重建;(d) scan 续点:模拟中途停 + `--resume` 产等价候选集且幂等;
      (e) `--time-budget-ms` 小值 → `partial:true` + 退出码 0 + 缓存/续点落盘;
      (f) atomic 写:杀点不留截断 JSON(`--check` 通过)。
- [x] 6.3 `tests/test_zero_deps.py`:AST 扫描 `discover_controls.py` 仍无第三方 import(新增 `time`/
      `os` 均为 stdlib)。
- [x] 6.4 `tests/test_distributed_md_purity.py`:4 壳新增内容通过纯净性 lint(R5.10)。
- [x] 6.5 既有 R5.8 回归扩面:`discover_controls.py` 在**非脚本目录 cwd** 子进程跑(导入鲁棒)、
      `--help` 即契约、性能不退化(缓存命中路径快于重建);install 自检:脚本就位 + 共定位。

## 7. 端到端验证

- [x] 7.1 `py -m unittest discover -s tests` 全绿(含新/改测试);`tools/check_contracts.py` 0 违例;
      `tools/check_distributed_purity.py` 0 违例;零依赖 AST 扫描无输出。
- [x] 7.2 双壳 install 自检(`./install.sh --claude <tmp>` / `--opencode <tmp>`):脚本就位、hook 注入
      幂等不变、4 壳分发纯净 **(本机)**。
- [x] 7.3 合成大仓跑 `/mgh-init --format claude`:discover 在「单次调用必然超时」设定下(小
      `--time-budget-ms`)经多次 Bash 重派 `--resume` 收敛至 `partial:false`,产物完整、无 `(no output)`
      全损;缓存命中使后续重派提速 **(确定性核)**。
- [ ] 7.4 真机大仓(用户曾复现 60s 强杀的仓,如 bemproot)复跑 `/mgh-init`:opencode 下 discover
      不再全损(缓存+续点存活、或经 per-call timeout/重派完成);若 opencode per-call `timeout` 有硬顶
      < 600000ms(OQ2),确认软时限+resume 独立生效 **(待用户真机;确定性核已由 7.3 + 单测覆盖)**。
- [x] 7.5 回滚演练:改动面清单(脚本改 1、契约新增/扩、4 壳 ×2 recipe、README、AGENTS.md、测试新增/扩);
      无 schema/数据迁移;`--time-budget-ms` 默认 0=关、缓存缺失=重建(均向后兼容);`git revert` + 版本号
      回退即整体回退;VERSION bump + CHANGELOG 条目(R5.8)。
