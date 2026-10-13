# Tasks: fix-mgh-sdr-multibranch-findings

> 依据:`proposal.md`(问题与范围)+ `design.md`(D1–D5 决策)。定向回归优先(改哪面跑
> 哪面,映射见 AGENTS.md 快速命令节);全量留给发布闸门。launcher 的 `--help` docstring 是
> 唯一 CLI 契约面,任何 flag/行为改动同步它。

## 1. launcher 分支预检(P1 + P6)

- [x] 1.1 `core/scripts/mgh_sdr_launch.py` `_run_one` 最入口加分支 ref 预检(`git rev-parse --verify --quiet` 可解到 commit;在 run 目录创建 / sdr_context / 哨兵 / spawn 之前),解析失败返回 `(False, "branch not found: <branch>")` 走既有失败记录路径;验证:`tests/test_mgh_sdr_launch.py` 新用例——多分支清单含不存在分支时该分支 FAILED、零宿主 spawn、零 run 目录与哨兵副作用,其后分支照常,launcher 退出 1 且 stderr 汇总含该分支
- [x] 1.2 dry-run 与单分支模式覆盖同一预检:验证:新用例——`--dry-run` 同清单对不存在分支记 FAILED 且退出 1(有效分支照常产 dry-run 产物);显式 `--branch 不存在`(无 `--multi-branch`)退出 1 + FAILED 汇总

## 2. 报告认领以 run 目录 manifest 为准(P2)

- [x] 2.1 `_run_one` ok 路径改为读 `<run-dir>/sdr_manifest.json` 的 `report` 字段并断言文件在盘;manifest 缺失或文件不在盘 → `(False, "no report produced for <branch>")`;删除仓根 `repo.glob("mgh-sdr-*.html")` 认领;验证:新用例——宿主退出 0 + manifest 在盘 = 认领 manifest 路径;宿主退出 0 + 无 manifest + 仓根存在他人报告 = FAILED(no-report) 且 `reports[]` 不含他人路径;`--open` 对 FAILED 分支不触发
- [x] 2.2 stdout `reports[]` 与 `--open` 形状回归:验证:既有 `TestLauncherReportSurface` 用例全绿(必要处随认领来源适配),dry-run outcome 仍是提示词路径、不开浏览器

## 3. spawn 环境卫生(P3)

- [x] 3.1 `_spawn_host` 传 `env`(继承 `os.environ` 并剥离 `PWD`),`cwd` 不变,两宿主同路径;验证:新用例——捕获传给 `subprocess.run` 的 kwargs,断言 `"PWD" not in env` 且 `cwd` = 目标仓,claude/opencode 两分支都断言

## 4. opencode 可诊断性 + `--model` 透传(P4)

- [x] 4.1 opencode cmd 扩为 `[opencode, run, --print-logs, --log-level, ERROR]`(claude 不加);新增 `--model <provider/model>` argparse flag,两宿主透传同名 flag,未传不附加;同步 docstring usage 行与退出码/行为描述;验证:新用例——opencode cmd 含两 flag、claude cmd 不含;`--model m1` 时两宿主 cmd 末尾含 `--model m1`,缺省时不含;`py core/scripts/mgh_sdr_launch.py --help` 正常且 usage 含新 flag
- [x] 4.2 契约与纯净面 lint:验证:`py tools/check_contracts.py` 退出 0;`py tests/test_zero_deps.py`、`py tests/test_no_compile_warnings.py` 全绿

## 5. 守卫通配 token 归一(P5)

- [x] 5.1 `core/scripts/block_adhoc_scripts.py` Bash 分派入口单点归一:① 引号闭合绝对路径后紧邻的 glob 段剥引号拼为单 token;② 含 `*`/`?` 的 token 按首个元字符前的前缀 resolve 判属;文件搜索 / 目录列举 / 兜底净网三判定共用归一后 token 流;验证:`tests/test_block_adhoc_scripts.py` 新用例——证据形态 `ls -la "<target>" | grep -i x ; ls "<target>"/*.html` 在 mgh-sdr 运行域放行(搜索/列举/净网各至少一例放行)
- [x] 5.2 通配修复不放松 containment:验证:新用例——`ls "D:\other"/*.html`(树外前缀)照拦退出码 2;`type "<target>\..\..\secret.txt"`(前缀含 `..` 越树)照拦;非运行域(无哨兵无 env)同形命令不受影响
- [x] 5.3 守卫接线不漂移:验证:`py tests/test_opencode_hook_parity.py`、`py tests/test_dsh_hook_parity.py`、`py tests/test_install_hook.py` 全绿

## 6. 发布面收尾

- [x] 6.1 `install.sh` 版本号 bump(脚本改动,承安装自检约定);验证:`grep -n` 版本串已更新,`./install.sh --opencode` 到 scratch 目标自检无 fail(warn 可)
- [x] 6.2 AGENTS.md 诚实边界节补守卫通配残余一句(按去通配前缀判属、展开结果不判定、别名/变量间接既有立场不变);验证:AGENTS.md 该节含新句且与 D5 残余描述一致

## 7. 回归与验收

- [x] 7.1 定向回归:验证:`py tests/test_mgh_sdr_launch.py`、`py tests/test_block_adhoc_scripts.py`、`py tests/test_zero_deps.py`、`py tests/test_no_compile_warnings.py` 全绿;`py tools/check_contracts.py` 退出 0
- [x] 7.2 真仓回归(维护者执行,验收证据):测试床 `C:/DEV/springBootTemplate` 同清单(含 `sdr-mb-nonexistent` 探针)重跑 launcher——断言:探针 FAILED(branch-not-found)且零 LLM 轮次、后续分支报告照常、退出码 1 + stderr 汇总完整、`reports[]` 无跨分支认领;另从开发仓 cwd 启动一轮,opencode 会话 `directory` = 测试床、`ls "<床>"/*.html` 形态命令在运行域内放行
  - 2026-10-13 执行通过,证据与逐项断言结论:`openspec/changes/test-mgh-sdr-multibranch-rerun/findings.md`(测试床 cwd 轮:探针 `FAILED pre-check` 零 spawn、3 分支报告各归其名、exit 1 + FAILED BRANCHES(1);开发仓 cwd 轮:单分支完整收敛 exit 0,会话全程落测试床)。注:`ls "<床>"/*.html` 形态本轮无自然样本(P2 修复后宿主不再需要仓根 glob 找报告),以「全程零误拦 + 一次真阳性树外拦截」与单测覆盖代偿。遗留新问题 F1(`--print-logs --log-level ERROR` 对子会话 provider 错误无效)记录于同一 findings §4。
