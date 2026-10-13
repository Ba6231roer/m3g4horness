# Tasks — fix-mgh-sdr-external-repo-retrieval

> 收口面:`core/scripts/sdr_context.py`(H6/M8/M9/M10/L4/L5)+ `core/scripts/read_roots_config.py`(L11)。
> H6/M8/M10 同批重构(D1–D3 咬合);每组先红后绿。

## 1. H6 — 结论物化唯一性(sdr_context.py)

- [x] 1.1 `_external_slug` 改 `basename + "-" + sha8(resolved 路径)` 消歧形态;声明去重键改 resolved 字符串
- [x] 1.2 回归:两个同名 basename 的已批准仓 → 独立结论目录、各自 `summary_path` 指向自己的证据、内容与各仓命中一致、`--check` exit 0(修复前:单目录覆盖、错配、`--check` 放行)
- [x] 1.3 回归:同一仓含 `..` 双写法声明 → 去重为一次检索一份结论(修复前:双倍检索 + 同目录错配)

## 2. M8 — 目录过滤相对性(sdr_context.py)

- [x] 2.1 skip_dirs 判定改用 `relative_to(ext).parts`(复用既有 rel 变量)
- [x] 2.2 回归:祖先目录名含 `build` 的外部仓 → 计数为真实值;仓内真实 `build/` 目录照常跳过(修复前:整仓假零、零披露)

## 3. M10 — 单遍剪枝遍历(sdr_context.py,与 1/2 同批)

- [x] 3.1 每仓遍历改单遍 `os.walk(topdown=True)`,`dirs[:]` 原位删除 skip_dirs;配置命中 + 文本收集一趟完成;dirs/files 排序保证确定性
- [x] 3.2 回归:`.git`/`node_modules` 内文件不进结果;结果集与重构前对拍一致;幂等重跑产物字节一致
- [x] 3.3 确认路由出现计数逻辑(正则 + 类级 base 拼接)零变化

## 4. M9 — check 按生效预算判定(sdr_context.py)

- [x] 4.1 实际生效的 `--baseline-budget-bytes` 写入 `context.json` 新增字段
- [x] 4.2 `--check` 尺寸断言:字段存在按记录值;缺失按默认值(旧产物向后兼容)
- [x] 4.3 回归:预算 400000 + 162KB 产物 → exit 0(修复前被硬编码 4× 默认值误否决);旧产物不误报

## 5. L4/L5 — 归因与提取卫生(sdr_context.py)

- [x] 5.1 回退归因文案改「回退当前检出分支」;回归断言结论归因串
- [x] 5.2 候选提取排除含 `://` 的 token;回归:含 GitHub URL 的存量文本 → 无伪路径条目

## 6. L11 — mkdir 入 try(read_roots_config.py)

- [x] 6.1 `mkdir(parents=True)` 挪进既有 try;回归:`.mgh` 已作为文件存在 → stderr 诊断 + 契约退出码(非裸 traceback)

## 7. 收口

- [x] 7.1 定向回归:`python tests/test_sdr_context.py`、`python tests/test_read_roots_config.py`;顺手 `python tests/test_zero_deps.py`、`python tests/test_no_compile_warnings.py`
- [x] 7.2 授权/fail-closed 面既有用例零改动全绿(语义未漂移的证据)
- [x] 7.3 `python tools/check_contracts.py`、`python tools/check_distributed_purity.py`
- [x] 7.4 `CHANGELOG.md` + `VERSION` bump
