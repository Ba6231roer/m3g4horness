## MODIFIED Requirements

### Requirement: Runtime enforcement hook for the sast run-domain

`/mgh-sast` SHALL 复用既有 `releases/claude-code/hooks/block_adhoc_scripts.py`。守卫的**激活模型 + 运行域
写入纪律**由共享契约 [`runtime-hook-enforcement`](../runtime-hook-enforcement/spec.md) 单一规定:激活 =
`MGH_SAST_ACTIVE=1`(或 init 域 `MGH_INIT_ACTIVE=1`)env **或** `<cwd>/security-scan/.active` 哨兵(编排器
step 0 经 `Bash` 写、run 完成/干净停止移除;哨兵绕开 opencode 插件不继承 mid-session env 的可靠性边界)。
运行域内一切脚本扩展名(`.py`/`.ps1`/`.sh`/`.ts`/…)写入均 fail-loud——**取消**既有
`core/scripts`/`tests`/`tools`/`releases/*/hooks` 白名单豁免(叶脚本 read-only)。既有 `py -c`/`python -c`
内省拦截 + recipe(指向 `list_chunks`/`list_verify_jobs`/`describe_artifact`/脚本 stdout 字段)+ 多单元聚合
(`s3_chunks.json`/`s5_filtered.json`/`scope_manifest.json`)整读拦截 **不变**。sast 域保留**树外**写入拦截
(`MGH_TARGET` 取值优先级 env > 哨兵.`target` > cwd),不加正向受信子表。命中 SHALL fail-loud(退出码 2)+
stderr recipe。非运行域 SHALL 直接放行(零日常噪声)。`install.sh` 的 hook 注入与 `--no-enforce-hook`
opt-out 行为不变(hook 已由 mgh-init 注入、幂等)。

#### Scenario: Hook blocks introspection py -c during a sast run
- **WHEN** `MGH_SAST_ACTIVE=1` 下编排器运行 `py -c "import json; json.load(open('security-scan/checkpoints/s5_filtered.json'))"`
- **THEN** hook 以退出码 2 拦截,stderr 给出「用 list_verify_jobs.py / describe_artifact.py」recipe

#### Scenario: Hook passes legitimate leaf-script invocation
- **WHEN** `MGH_SAST_ACTIVE=1` 下运行 `py .claude/mgh-core/scripts/prefilter.py --in … --out …`
- **THEN** hook 放行,不误伤合法叶子调用

#### Scenario: Hook blocks editing a leaf script during a sast run
- **WHEN** `MGH_SAST_ACTIVE=1` 下编排器 `Edit`/`Write` `.claude/mgh-core/scripts/prefilter.py`
- **THEN** hook 以退出码 2 拦截(叶脚本 read-only,取消 `core/scripts` 白名单豁免)

#### Scenario: opencode activates the sast guard via the disk sentinel
- **WHEN** opencode 下 `MGH_SAST_ACTIVE` env 未设,但 step 0 已写 `<cwd>/security-scan/.active` 哨兵
- **THEN** 守卫经哨兵激活,等效 env 已设;内省/越权脚本写/越树写均 fail-loud

#### Scenario: Non-run-domain is silent
- **WHEN** 既无 `MGH_INIT_ACTIVE` 也无 `MGH_SAST_ACTIVE`、且哨兵不存在时运行任意 Bash
- **THEN** hook 退出码 0 放行,零噪声

#### Scenario: Shell sets the run-domain flag and writes the sentinel
- **WHEN** 审阅两份 `mgh-sast.md` 编排流起步与完成态
- **THEN** 两壳均含 `export MGH_SAST_ACTIVE=1` + 写 `<target>/security-scan/.active` 哨兵步骤 + hook 存在/opt-out 声明;完成态移除哨兵
