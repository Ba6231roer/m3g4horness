<!--
  mgh-init stage-flow — bootstrap (not-started 首 run). Install mirrors to <mgh-core>/prompts/fragments/init-stage/.
  可达性:本 fragment 由壳 fresh-run recipe **fixed-path Read** 加载(首 run,`.mgh-init/` 不存在 /
  resume_state exit 1),不走 resume_state 循环(resume_state 对 not-started 返回 `stage_flow_files[]` 为空)。
-->

## bootstrap (not-started 首 run)

```
0. parse + self-check (host agent/model available; else STOP with fix hint;发现脚本统计源文件数,超 `--large-repo-threshold` 则建议 `--scope`+`--merge`(**花 token 前**前置建议;波次进行中不再因规模打断,见 orchestrator-discipline fragment),扫描期向 stderr 打印进度)
   · **起步**:`Bash: export MGH_INIT_ACTIVE=1`(声明运行域,激活 PreToolUse hook,含子树外 Write/Edit 拦截)
   · **run_config(无状态 resume 意图源)**:起步后、花 token 前,**原子写** `<target>/.mgh-init/run_config.json`
     (起始态意图:记决定步骤图的本次 flag;与终态 `init_manifest.json` 边界清晰、互不替代):
     `py .claude/mgh-core/scripts/write_runconfig.py --target <abs target> [--format <fmt>] [--no-scout] [--no-codegraph] [--skip-consistency] [--merge <dir>] [--include-dotfiles] [--include-tests] [--scope ..] [--scope-mode ..] [--max-aggregate-bytes ..] [--max-unit-bytes ..] [--orch-budget-bytes ..] [--scout-* ..]`
     **`--format` 默认 opencode(省略即 opencode);仅当用户显式传 `--format claude` 时透传之。**该文件使 `/mgh-init --resume` **无需重输 flag**;`resume_state.py` 据它解析 optional/codepath 分支。
     `--resume` 复用既有 run_config(不覆盖);新 run(`.mgh-init/` 不存在或被清)重写。
   · **哨兵(磁盘激活信号,opencode 可靠激活兜底)**:`write_runconfig.py` stdout 的 `target` 即**绝对项目根**
     (Windows 原生、供守卫 `Path.resolve()` 判树;**NEVER** 用 bash `pwd`,其 MSYS `/c/...` 在 Windows pathlib 误解析)。
     据此写哨兵:
     `printf '%s' '{"domain":"mgh-init","target":"<write_runconfig stdout 的 target>","out_roots":[<非默认 --out/--rules-dir 解析后绝对根,默认产物根不列>],"v":1}' > <target>/.mgh-init/.active`
     守卫激活 = `MGH_INIT_ACTIVE=1` env **或** 该哨兵(opencode 插件进程不继承 mid-session env → 哨兵兜底,使
     脚本只读 / 受信子树守卫在 opencode 上整 run 可靠激活)。哨兵携 `target` 使 `MGH_TARGET` 在首 run 即就绪。
     完成态(done 步)/ 干净停止 `rm <target>/.mgh-init/.active`(避免残留锁死日常开发);`--resume` 重跑时重写覆盖。
   · **MGH_TARGET**(供 hook 判树):`controls_candidates.json::repo` 即**绝对项目根**(= 哨兵 `target`,二者一致)。该产物首次 discover 后落盘、**`--resume` 时 discover 跳过但产物仍在**——故编排器在 fan-out 前(无论本次是否实跑 discover)**逐字读**该字段并 `export MGH_TARGET=<repo>`。取值经 `describe_artifact.py --field repo`(合法瞄结构出口)。hook 在 `MGH_TARGET` 缺失时该条**降级放行**(不阻断)。
   · **codegraph 检测**(花 token 之前):`Bash: if test -d <target>/.codegraph && command -v codegraph >/dev/null 2>&1; then echo on; else echo off; fi`
     → `codegraph=on|off`。默认 `auto`(可用即启用);传 `--no-codegraph` 或检测不可用 → `codegraph=off`。该信号**逐字透传**进
     scout/induct/survey/resolve subagent task 输入(仅 `codegraph=on` 时这些 stage 启用 codegraph 外科式上下文 + 执行 `init-resolve` stage)。
```
