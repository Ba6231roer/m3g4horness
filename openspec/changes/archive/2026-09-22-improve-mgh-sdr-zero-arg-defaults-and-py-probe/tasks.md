# tasks — improve-mgh-sdr-zero-arg-defaults-and-py-probe

## 1. 基线测量与准备

- [x] 1.1 `py tools/measure_prompts.py` 实测两份 mgh-sdr 壳当前 `mid_tokens`,记录到
      本 change 目录备注(预算余量 = 5000 − 现值,决定是否需要裁剪位)
      → 备注:claude 壳 `mid_tokens=4146`(余量 854)/ opencode 壳 `4175`(余量 825),
      预估双壳各净增百余 token,无需预留裁剪位
- [x] 1.2 通读 `releases/claude-code/commands/mgh-sdr.md` 与
      `releases/opencode/command/mgh-sdr.md`,确认除既有超时标定/agent 派生注释外无其他
      分叉点(双壳同改清单核对)

## 2. 双壳 step 0:解释器探测(D1/D3)

- [x] 2.1 claude 壳 step 0 新增探测配方(design D1 的 `for c in py python python3`
      单条命令 + `PYPROBE` 标签输出),附选中规则:第一个 rc 0 且版本 ≥3.10 者;
      全部不可用 → 早停披露 + `rm <repo>/.mgh-sdr/.active`
- [x] 2.2 claude 壳 Orchestrator discipline 段加「`py` = 规范 token」全局替换纪律
      (示例文本不动;选中非 `py` 后所有调用逐字用探测选中的解释器,NEVER 逐命令试错)
- [x] 2.3 claude 壳「中断恢复」段补一句:选中解释器不确定 → 重跑探测命令重建事实
- [x] 2.4 opencode 壳镜像 2.1–2.3(逐字对等,仅宿主路径前缀差异)

## 3. 双壳零参默认执行(D2/D4)

- [x] 3.1 两份壳参数表逐项标注默认值(`--base` 默认 `master`、`--branch` 默认当前分支
      已有,补齐 `--dimensions` 不传 = 全 6 维、`--run-dir` 默认 `<ts>` 等其余条目)
- [x] 3.2 两份壳把「**无 actionable 参数 / `--help`** → 打印参数表后 STOP」改为
      design D2 的两分支句:`--help` → STOP;无参 → 按声明的默认集直接进入编排流
      (零参 = 显式传默认值的等价路径)
- [x] 3.3 两份壳编排流明示零参路径:`--base`/`--branch` 整体省略(脚本 argparse 兜底),
      run 目录命名只用 `<ts>` 不含分支,报告/后续步骤消费 step 1 stdout 已解析的
      `branch`/`base` 字段;NEVER 在壳里加 `git rev-parse`(D4)
- [x] 3.4 两份壳 Always disclose 补一行:零参默认执行口径(base=master / 当前分支 /
      全 6 维)+ `--dry-run` 低成本试跑出口指引

## 4. AGENTS.md R5.6 措辞修订

- [x] 4.1 按 design D2 修订 `AGENTS.md` R5.6 薄壳纪律句:`--help`/无参 STOP 放宽为
      「无参默认 STOP,仅当命令参数表逐项标注默认值并显式声明零参执行时按默认集执行
      (mgh-sdr 首用)」;`理由〔花 token 前先校验〕` 承重括号保留
- [x] 4.2 自查修订句与 R5 其余子规则无连锁引用失效(强制面索引表无需增行——仍由
      purity/contracts lint 兜底)

## 5. 验证与回归

- [x] 5.1 `py tools/check_contracts.py` 通过(双壳 flag 镜像未被探测/零参文本破坏)
- [x] 5.2 `py tools/measure_prompts.py` 复核两份 mgh-sdr 壳 `mid_tokens` ≤ 5000;
      超限则按保真度优先裁剪(删重复措辞,NEVER 删承重防线)后回到 5.1
- [x] 5.3 定向回归(design 改动面→测试映射「命令壳/提示词/分发产物」行):
      `py tests/test_distributed_md_purity.py` + `py tests/test_plain_language.py`
- [x] 5.4 手工干跑验证(至少一宿主):在无 `py` 语义等价环境模拟(临时 PATH 剔除
      `py`)调用 `/mgh-sdr --help` 确认 STOP、零参调用确认探测一次定型并进
      step 1(可用 `--dry-run` 截断),全程零逐命令试错
- [x] 5.5 bump 相关版本号(承 R5.8:任何 `.md` 改动 bump 版本号——按仓库现行版本
      标注位置执行)
