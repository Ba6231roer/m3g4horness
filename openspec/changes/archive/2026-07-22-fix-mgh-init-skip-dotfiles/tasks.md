# Tasks — fix-mgh-init-skip-dotfiles

> 实现依设计 D1–D5。chokepoint = `core/scripts/expand_scope.py`;逃生口 = `discover_controls.py`。

## 1. 共享文件枚举层加点前缀跳过(expand_scope.py)

- [x] 1.1 `walk_sources` 增参数 `include_dotfiles: bool = False`;当为假时,在既有
      `any(part in EXCLUDE_DIR …)` 之外,**追加** `or any(part.startswith(".") for part in p.parts)`
      跳过(D1/D5)。`EXCLUDE_DIR` 集合**不改**(D3)。
- [x] 1.2 `collect_dir` 增同样参数与谓词(与 `walk_sources` 同一判定,保持 `--path` scope 与全仓
      扫描一致)。
- [x] 1.3 `build_call_graph` 透传 `include_dotfiles` 到其 `walk_sources(repo, …)` 调用(调用图与
      候选/skeleton 共用同一次遍历,承「Bounded single-pass scan」)。
- [x] 1.4 核验 `package_to_dirs` 的 `rglob` fallback 不受影响(它做包→目录映射,非源枚举;仅在
      点目录解析包路径时才触及,行为可接受,无需改)。

## 2. discover_controls.py 加 --include-dotfiles 逃生口

- [x] 2.1 argparse 增 `--include-dotfiles`(默认 `False`,`action="store_true"`);`--help` 文案
      说明「默认跳过点前缀路径,传此 flag 纳入」(R5.1:`--help` 即契约面)。
- [x] 2.2 把 `args.include_dotfiles` 透传进本脚本对 `walk_sources` / `build_call_graph` /
      `collect_dir` 的调用(确认 discover 既有 walk 调用点全部带上,含 skeleton 抽取与候选扫描两路)。
- [x] 2.3 stdout 摘要增 `dotfiles_skipped`(默认真时本次跳过的点前缀源文件计数,便于披露与排查);
      `--include-dotfiles` 时为 `0`/缺省(承「Derived counts exposed as script output」范式)。

## 3. 测试(tests/test_init_discover.py)

- [x] 3.1 默认跳过:在 `.opencode/plugins/`、`.claude/hooks/`、`.codegraph/` 下各造一个匹配控制特征的
      `.py`/`.ts`,断言默认运行下它们**不**出现在 candidates/skeleton/调用图(对标 spec 场景 1)。
- [x] 3.2 逃生口:`--include-dotfiles` 下上述文件**重新纳入**(对标 spec 场景 2)。
- [x] 3.3 一致性:断言 skeleton、调用图、scout 目标集**三者**均不含点前缀路径(对标 spec 场景 3)。
- [x] 3.4 回归:`node_modules/`、`target/`、`build/` 下源文件仍被 `EXCLUDE_DIR` 跳过(对标 spec 场景 4)。
- [x] 3.5 Windows 盘符根:断言 `C:\DEV\<repo>` 下正常源文件不被点前缀规则误排除(对标 spec 场景 5)。

## 4. 契约落定(core/contracts/init/)

- [x] 4.1 在记录文件枚举/`EXCLUDE_DIR` 的契约(`candidates.md` 与/或 `skeleton.md`,确认实际落点)
      增「点前缀路径默认跳过 + `--include-dotfiles` 覆盖」条款,并登记新增 stdout 字段 `dotfiles_skipped`。

## 5. 分发壳(releases/ 双端 + 边界披露)

- [x] 5.1 `releases/claude-code/commands/mgh-init.md` 与 `releases/opencode/command/mgh-init.md`
      镜像新增 `--include-dotfiles`(参数表 + 调用 `discover_controls.py` 示例逐字带上,R5.1)。
      若壳由 `tools/gen_*.py` 生成,改生成器源头再重生成,双端对等。
- [x] 5.2 两壳的边界/诚实段增列「点前缀路径默认不扫描,控制定义点在 `.xxx` 内须传
      `--include-dotfiles`」(对标 spec「Disclose honesty boundaries」第 4 条)。

## 6. R5 合规与回归

- [x] 6.1 `py tools/check_contracts.py`——断言新 flag `--include-dotfiles` 经双壳被 `discover_controls.py
      --help` 声明(R5.1 CLI lint)。
- [x] 6.2 `py tools/check_distributed_purity.py`——改后双壳不携带研发态悬空引用(R5.10)。
- [x] 6.3 改动的 `.md`/`.py` bump 版本号;`py tests/test_init_discover.py` + 既有 init 回归全绿;
      零依赖 AST 扫描无新增第三方 import(R5.2/R5.8)。

## 7. SAST 连带核验(Non-Goal 内的副作用确认)

- [x] 7.1 核验无 `/mgh-sast` spec/测试断言「扫描 `.claude`/`.opencode`」;确认 `expand_scope.py main()`
      未加新 flag(SAST CLI 契约稳定),SAST 仅静默继承「不再扫工具目录」的更正确默认(非回归)。
