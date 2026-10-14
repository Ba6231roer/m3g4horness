## 1. 红测先行(全部先红)

- [x] 1.1 `tests/test_mgh_sdr_launch.py` 新增 `TestInlineBranchList` 组:纯函数直测 `_split_branch_list`——正常切分、逐项去空白、保序去重、空项退出 2 且 stderr 报序号(`a,,b` / 结尾逗号)、全空白退出 2
- [x] 1.2 同组集成测(临时仓 `_two_branch_repo` + `_FakeHostMixin`):`--branch-list "feature-pay, feature-b2"` 串行两轮完整流程、退出码 0、两份报告、两个 run 目录;`--multi-branch` 与 `--branch-list` 同给 → 退出码 2、stderr 含 recipe、零 spawn 零 run 目录;`--branch feature-pay --branch-list "feature-b2"` → 内联清单优先(只跑 feature-b2)
- [x] 1.3 `--help` 真子进程断言含 `--branch-list`(镜像 `test_help_documents_model_flag` 形态);跑 `py tests/test_mgh_sdr_launch.py` 确认新测全红、既有测全绿

## 2. launcher 实现(单文件)

- [x] 2.1 `core/scripts/mgh_sdr_launch.py` 新增纯函数 `_split_branch_list(value: str) -> list[str]`(D2:切分/strip/空项 `sys.exit(2)` 报序号/保序去重/全空白退出 2;docstring 注明无注释语法与理由)
- [x] 2.2 argparse 新增 `--branch-list`(metavar `<b1,b2,...>`,help 写明逗号分隔内联清单、与 `--multi-branch` 互斥);`main()` 互斥检查(同给退出码 2 + recipe,先于任何 gate)与清单选择三分支表达式(D3:内联 > 文件 > 单分支/当前分支)
- [x] 2.3 文档对齐:launcher 头注 usage 行补 `[--branch-list <b1,b2,...>]` + 一句互斥/拒识说明;README `/mgh-sdr` 多分支段补第三种喂法示例与格式/互斥说明(人类面,简练)

## 3. 转绿 + 定向回归

- [x] 3.1 `py tests/test_mgh_sdr_launch.py` 全绿(新组转绿 + 既有组零触碰)
- [x] 3.2 定向回归:`py tests/test_zero_deps.py` + `py tests/test_no_compile_warnings.py`;lint 四件套 `check_contracts` / `check_distributed_purity` / `check_distributed_prompt_budget` / `check_plain_language`(plain_language 既有 exit 2 存量噪音为准;purity 现存 sdr 三面壳 9 行 `core/scripts|prompts/` 违例属进行中的 `fix-mgh-sdr-report-human-readability` 未归档工作,**不属本 change、不代修**——本 change 判定标准 = 自身工件零违例 + 不新增违例行)

## 4. 收尾

- [x] 4.1 `openspec validate add-mgh-sdr-inline-branch-list --strict` 过
- [x] 4.2 VERSION bump + CHANGELOG 条目(单条)
- [x] 4.3 实机冒烟:临时清单仓或 `C:/DEV/springBootTemplate` 上 `--dry-run --branch-list "sdr-dryrun,sdr-mb-authz"`(零 AI 调用),核对两分支预检 + 互斥拒识 + 空项拒识三种形态;真跑归维护者按需执行
