# fix-mgh-fanout-dispatcher-hygiene — Tasks

> 实施纪律:先红后绿(每组测试先写、跑出失败、再实现);harness 调
> `fanout_runner.main()` 一律显式 `--cooldown-s 0`(R5.8);本机 `py` 坏,用 `python` 跑。
> 涉改面 = `core/scripts/fanout_runner.py` + `tests/test_fanout_runner.py` /
> `tests/test_fanout_stale.py`,此外零文件。

## 1. 测试先行(红)

- [x] 1.1 冷却忙等红测:`tests/test_fanout_runner.py` 新增用例——构造 drain 点熔断前退避
  武装态(队列空、在飞零、`--cooldown-s` 极小值如 1),monkeypatch `time.sleep` 计数,断言
  冷却生效期间 sleep 被调用(现状零调用 → 红;勿用默认 300s 冷却值)
- [x] 1.2 杀失败处置红测:mock `_kill_tree` 返回 False 的 stall/timeout 路径,断言 ① uid 进
  stdout `kill_failed` ② 单元不回队且 drain re-list 不再收 ③ `_terminal_children_rm` 未被
  调用(pid 留 liveness children[])(现状三项全红)
- [x] 1.3 POSIX 升级红测:monkeypatch `os` 信号层,断言 `_kill_tree` POSIX 分支信号序列为
  SIGTERM → 短宽限复查仍存活 → SIGKILL(现状无 SIGKILL 路径 → 红)
- [x] 1.4 越树 marker 红测:pending 清单注入 `failed_marker` 指向 repo 锚外临时目录,跑至
  path-drift 拦截,断言该目录 NEVER 被创建、无 marker 文件、stderr 含处置 recipe、stdout
  `failed` 计数不虚增(现状会 mkdir+写盘 → 红);并保留/补一条树内 marker 照旧写的对照用例
- [x] 1.5 PWD 剥离红测:monkeypatch `subprocess.Popen` 捕获 env,断言 opencode/claude/dsh
  三 host 形子进程 env 均无 `PWD` 且 dsh 形仍携带 `MGH_TASK_TEXT`(现状 opencode/claude
  env=None 全继承 → 红)
- [x] 1.6 kill-stale 锚定红测:`tests/test_fanout_stale.py` 新增用例——children cmdline 喂
  「宿主名仅在参数」(`notepad C:\notes\claude-meeting.txt`)与「绝对路径形」
  (`C:\npm\opencode.cmd run --agent x`)两组,断言前者 NEVER 进 kill 目标、后者正确分类
  连树杀(现状前者被子串析取项误杀 → 红)
- [x] 1.7 文件名编码红测:>200 stem 的单元 id 断言 `.task.md`/`.run.log` 落盘成功且路径
  ≤255 字符,与 `init_tier.safe_unit_filename` 样本集(含 `::`/超长/中段相似对)parity;
  短 id 文件名与既有形态逐字节一致(现状超长 id 写失败仅 warn → 红)

## 2. 实现(绿)

- [x] 2.1 冷却 gate(D1):主循环冷却等待条件改 `monotonic() < cooldown_until and not
      inflight`,去掉队列非空前置;跑 1.1 转绿
- [x] 2.2 树杀升级与处置(D2):`_kill_tree` POSIX 侧 SIGTERM→短宽限复查→SIGKILL、Windows
      侧失败重试一次;stall/timeout 调用点检查返回值,确认失败 → uid 记入本 run
      `kill_failed` 集合、不回队、drain re-list 排除、跳过 `_terminal_children_rm`、
      stderr fail-loud recipe(指 `--kill-stale --dry-run`)+ stdout 摘要可选键
      `kill_failed:[unit…]`;跑 1.2/1.3 转绿
- [x] 2.3 marker 锚定守卫(D3):`_write_failed_marker` 增加 repo 参数,写盘前 resolve 校验
      在锚树内;树外 → NEVER mkdir/写盘 + stderr recipe + 不进 `failed_written`;两调用点
      (path-drift 拦截、failed ack)同判;跑 1.4 转绿
- [x] 2.4 PWD 剥离(D5):`_run_unit` env 构造改全 host 统一
      `{k: v for k, v in os.environ.items() if k != "PWD"}`(dsh 形附加 `MGH_TASK_TEXT`);
      跑 1.5 转绿
- [x] 2.5 kill-stale 锚定(D4):`_classify_targets` 子进程匹配改「argv[0] 基名(统一分隔符、
      小写、剥 .exe/.cmd/.bat)∈ {opencode, claude, dsh}」,删除 `cl.find(h) >= 0` 析取项;
      runner 侧匹配不动;跑 1.6 转绿
- [x] 2.6 编码归一(D6):`_safe_name` 改 `init_tier.safe_unit_filename` 别名(镜像
      list_scout_batches 的 import + 别名形态);跑 1.7 转绿

## 3. 回归与共用面确认

- [x] 3.1 `python tests/test_fanout_runner.py` 全绿(~50s 真子进程/计时器面),确认其中
      sdr tier 用例(`TestDshHost`/sdr 相关组)零回归
      (注:174 测中 173 绿 + 1 skip;唯一失败 `TestRateLimitStorm.
      test_all_rate_limit_storm_truncates_fast`(waves_run 3!=2)经 HEAD worktree
      对照为**存量失败**(HEAD 同样 5/5 失败,同断言同 3!=2),与本批六项零关联,
      不在本批修复)
- [x] 3.2 `python tests/test_fanout_stale.py` 全绿
- [x] 3.3 `python tests/test_zero_deps.py` + `python tests/test_no_compile_warnings.py`
      全绿(新增 init_tier import 属兄弟标准库导入,零依赖不变)
- [x] 3.4 `git diff --stat` 确认涉改面仅 `core/scripts/fanout_runner.py` + 两个测试文件
      (+ VERSION/CHANGELOG);守卫三镜像、壳、agent、枚举器零触碰
      (维护者私有文档区里的战役交接文档在本 change 提议会话之前已有未提交改动,非本批产物)

## 4. 收尾

- [x] 4.1 VERSION bump 0.1.69 → 0.1.70 + CHANGELOG 条目(六缺陷收口,一项一句)
- [x] 4.2 `openspec validate "fix-mgh-fanout-dispatcher-hygiene" --strict` 过 +
      `python tools/check_distributed_purity.py` 零违例 +
      `python tools/check_plain_language.py`(exit 2 = 既有噪音,与本批无关)
- [x] 4.3 实机冒烟(可选但建议):`fanout_runner.py --tier <t> --dry-run` 一次 + 手动
      `--kill-stale --dry-run` 一次,确认正常路径无行为变化
      (dispatch --dry-run exit 0 + 摘要契约键齐 + audit 副本落盘;kill-stale --dry-run
      exit 0 `none:true`;均无 spawn)
- [x] 4.4 `/opsx:archive`(归档会话执行;specs 增量回写主规格 fanout-dispatch 5 MODIFIED)
      (已归档 archive/2026-10-13-fix-mgh-fanout-dispatcher-hygiene;5 MODIFIED 增量回写
      主规格验证:5 requirement + 38 scenario + 6 段落全在)
