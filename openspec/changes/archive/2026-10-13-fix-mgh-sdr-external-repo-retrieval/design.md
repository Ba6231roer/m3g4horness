# Design — fix-mgh-sdr-external-repo-retrieval

> 修复对象:2026-10-13 评审在 `sdr_context.py` 确认的 H6/M8/M9/M10/L4/L5 + `read_roots_config.py` L11。
> H6 + M8 + M10 集中在同一片外部仓物化/遍历代码,**同批重构**;M9/L4/L5/L11 为独立小修。

## D1 — H6 修法:结论目录键 = slug + 解析后路径短哈希

- `_external_slug` 从 `Path(decl["path"]).name` 改为 `f"{name}-{sha8(resolved)}"` 形态:
  `name` = basename(保人读性),`sha8` = `Path(decl["path"]).resolve()` 规范字符串的
  SHA-256 前 8 位十六进制(确定性、跨机器同路径同键)。
- **无迁移负担**:run 目录一次性、每次 run 重新检索,旧 run 的 `external/<basename>/` 不会被
  新代码读取——直接改键形态,不做兼容映射。
- **声明去重键**同改:`dict` 键 / 比较基准从字面路径串改为 resolved 字符串——同一仓的
  `..` 变体写法去重为一次检索(顺带修复双倍检索)。
- `out_dir` 的 `mkdir(exist_ok=True)` 保留(消歧后冲突在结构上不可能,exist_ok 无害)。
- 回归:两个同名 basename 仓 → 两个独立结论目录、记录各自指向自己的证据、`--check` 通过;
  含 `..` 双写法 → 单次检索。

## D2 — M8 修法:过滤判定改仓内相对组件

- `any(part in skip_dirs for part in p.parts)` 改为对 `p.relative_to(ext).parts` 判定
  (`rel` 变量既有代码已算出,直接复用)。祖先目录段不再参与判定,仓内规则目录照常跳过。
- 回归:外部仓位于 `.../build/front` 祖先下 → 计数为真实值;仓内真实 `build/` 目录 → 照常跳过。

## D3 — M10 修法:单遍 os.walk + 原位剪枝,一趟双用(与 D1 同批)

- 现状:每个声明配置文件名各一次 `ext.rglob(root_name)`(≤5 次,无过滤下钻)+ 一次
  `ext.rglob("*")` 出现计数(过滤在产出之后)= 每仓最多 6 遍全树 I/O。
- 重构为**单遍** `os.walk(ext, topdown=True)`:每层 `dirs[:] = [d for d in dirs if d not in
  skip_dirs]` 原位删除实现真剪枝(.git/node_modules 不再被读取);walk 内一次文件名判定
  同时完成「声明配置文件命中」与「参与出现计数的文本文件收集」。
- **确定性**:遍历顺序 `dirs.sort()` / `files.sort()`,保证同输入同产出(幂等重跑字节级一致,
  与现有产物对拍口径一致)。
- 路由出现计数逻辑(正则 + 类级 base 拼接)零变化——只改遍历与收集层。
- **与 D1 同批的原因**:同一函数域内的物化路径与遍历逻辑互相咬合,分两个 change 会同片
  代码动两次、回归面重叠。
- 回归:仓含 `.git`/`node_modules` → 剪枝生效(其内文件不进结果);结果集与重构前对拍一致。

## D4 — M9 修法:生效预算落盘,check 按记录值判定

- `sdr_context.py` 运行时把实际生效的 `--baseline-budget-bytes` 写进 `context.json`
  (新增字段,如 `effective_baseline_budget`)。
- `--check` 的基线尺寸断言:字段存在 → 按记录值判定;字段缺失(旧 run 产物)→ 按默认值
  (向后兼容,旧产物不因新校验误报——与既有 `excluded`/`slimmed` 增量字段先例同例)。
- **否决删除启发式**:尺寸校验保留有披露价值(捕获异常膨胀的基线),只是判定基准必须与
  运行时一致。
- 回归:预算 400000 → 162KB 产物 `--check` exit 0;旧产物(无字段)→ 按默认值判定不误报。

## D5 — L4 修法:回退归因改文案,不探测远端

- 「回退默认分支」文案改为如实描述(回退当前检出分支)。**否决探测 `origin/HEAD`**:
  依赖远端配置与网络/本地 ref 状态,增加失败面与不确定分支语义,收益(更"正确"的参照)
  不抵成本;诚实归因已消除误导。
- 回归:无同名分支仓 → 结论归因串与新文案一致。

## D6 — L5 修法:候选提取排除 URL token

- 外部路径候选提取处排除含 `://` 的 token(仓库守卫的路径 regex 已有同形先例)。
- 回归:存量设计文本含 GitHub URL → `external_skipped` 无 `s://github.com/...` 伪条目。

## D7 — L11 修法(read_roots_config.py):mkdir 入 try

- `mkdir(parents=True)` 挪进既有 try 块:`.mgh` 已作为文件存在 → stderr 人类诊断 + 契约
  退出码(裸 traceback → 合规失败形态)。零行为语义变化(方向本就无害:零写入)。

## 测试与验收口径

- 定向回归:`tests/test_sdr_context.py` + `tests/test_read_roots_config.py`;顺手
  `tests/test_zero_deps.py`、`tests/test_no_compile_warnings.py`。
- 关键回归(先红后绿):同名双仓独立性(D1)、祖先 build 不误伤(D2)、剪枝(D3)、
  大预算 check(D4)、URL 候选(D6)。
- 授权/fail-closed 面回归零改动全绿 = 检索/授权语义未漂移的最低证据(该面为已验证健康面,
  修复 MUST NOT 触碰授权判定与降级语义)。
